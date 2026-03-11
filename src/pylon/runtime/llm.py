"""Provider-backed LLM runtime with model routing, cost telemetry, and fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from pylon.autonomy.routing import (
    CacheStrategy,
    ModelRouteDecision,
    ModelRouter,
    ModelRouteRequest,
    ModelTier,
)
from pylon.cost.fallback_engine import FallbackEngine, FallbackResult, FallbackTarget
from pylon.observability.metrics import MetricsCollector
from pylon.providers.base import Chunk, LLMProvider, Message, Response, TokenUsage
from pylon.providers.health import ProviderHealthTracker
from pylon.runtime.context import ContextManager


@dataclass(frozen=True)
class ModelPricing:
    """Per-million token pricing used for estimated cost telemetry."""

    input_per_million: float
    output_per_million: float
    cache_read_per_million: float = 0.0
    cache_write_per_million: float = 0.0


@dataclass(frozen=True)
class RoutedChatResult:
    """Standardized LLM call result for workflow nodes."""

    response: Response
    route: ModelRouteDecision
    estimated_cost_usd: float
    context: dict[str, Any] = field(default_factory=dict)


class ProviderRegistry:
    """Minimal provider registry keyed by provider name."""

    def __init__(
        self,
        factories: dict[str, Callable[[str], LLMProvider]] | None = None,
    ) -> None:
        self._factories = factories or {}

    def register(self, provider_name: str, factory: Callable[[str], LLMProvider]) -> None:
        self._factories[provider_name] = factory

    def has_provider(self, provider_name: str) -> bool:
        return provider_name in self._factories

    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._factories.keys())

    def resolve(self, provider_name: str, model_id: str) -> LLMProvider:
        factory = self._factories.get(provider_name)
        if factory is None:
            raise ValueError(f"No provider factory registered for {provider_name}")
        return factory(model_id)


def parse_model_ref(model_ref: str) -> tuple[str | None, str]:
    """Split a provider/model reference into provider and model id."""
    if "/" not in model_ref:
        return None, model_ref
    provider_name, model_id = model_ref.split("/", 1)
    return provider_name, model_id


@dataclass
class LLMRuntime:
    """Routes provider-backed chat calls and standardizes telemetry.

    Integrates FallbackEngine for automatic cross-provider failover
    and ProviderHealthTracker for health-aware routing.
    """

    router: ModelRouter = field(default_factory=ModelRouter)
    pricing: dict[tuple[str, str], ModelPricing] = field(default_factory=dict)
    metrics: MetricsCollector | None = None
    context_manager: ContextManager = field(default_factory=ContextManager)
    fallback_engine: FallbackEngine | None = None
    health_tracker: ProviderHealthTracker | None = None

    async def chat(
        self,
        *,
        registry: ProviderRegistry,
        request: ModelRouteRequest,
        messages: list[Message],
        preferred_model: str = "",
        tools: list[dict[str, Any]] | None = None,
        static_instruction: str = "",
        use_fallback: bool = True,
    ) -> RoutedChatResult:
        prepared_context = self.context_manager.prepare(
            messages,
            static_instruction=static_instruction,
        )
        effective_request = replace(
            request,
            input_tokens_estimate=prepared_context.prepared_input_tokens,
            cacheable_prefix=request.cacheable_prefix or prepared_context.cacheable_prefix,
        )
        route = self._select_route(
            registry=registry,
            request=effective_request,
            preferred_model=preferred_model,
        )

        # Use FallbackEngine if available and enabled
        if use_fallback and self.fallback_engine is not None:
            response, fallback_result = await self._chat_with_fallback(
                registry=registry,
                route=route,
                messages=prepared_context.messages,
                tools=tools,
            )
        else:
            provider = registry.resolve(route.provider_name, route.model_id)
            response = await provider.chat(
                prepared_context.messages,
                model=route.model_id,
                tools=tools or None,
                cache_strategy=route.cache_strategy.value,
                batch_eligible=route.batch_eligible,
                context_compacted=prepared_context.was_compacted,
                original_input_tokens=prepared_context.original_input_tokens,
                prepared_input_tokens=prepared_context.prepared_input_tokens,
            )
            fallback_result = None

        effective_route = route
        if fallback_result is not None:
            effective_route = ModelRouteDecision(
                provider_name=fallback_result.provider,
                model_id=fallback_result.model_id,
                tier=fallback_result.tier,
                reasoning=(
                    f"{route.reasoning}; fallback chain attempt {fallback_result.attempt}"
                    if fallback_result.was_fallback
                    else route.reasoning
                ),
                cache_strategy=route.cache_strategy,
                batch_eligible=route.batch_eligible,
            )

        # Track health
        if self.health_tracker is not None:
            self.health_tracker.record_success(
                effective_route.provider_name, effective_route.model_id,
            )

        usage = response.usage or TokenUsage()
        estimated_cost = self._estimate_cost(
            effective_route.provider_name,
            effective_route.model_id,
            usage,
        )
        self._record_metrics(effective_route, usage, estimated_cost)

        context: dict[str, Any] = {
            "compacted": prepared_context.was_compacted,
            "original_input_tokens": prepared_context.original_input_tokens,
            "prepared_input_tokens": prepared_context.prepared_input_tokens,
            "cacheable_prefix": prepared_context.cacheable_prefix,
            "summary": prepared_context.summary,
            "requested_route": route.to_dict(),
        }
        if fallback_result is not None and fallback_result.was_fallback:
            context["fallback"] = {
                "was_fallback": True,
                "attempts": fallback_result.attempt,
                "final_provider": fallback_result.provider,
                "final_model": fallback_result.model_id,
                "events": [e.to_dict() for e in fallback_result.events],
            }

        return RoutedChatResult(
            response=response,
            route=effective_route,
            estimated_cost_usd=estimated_cost,
            context=context,
        )

    async def stream(
        self,
        *,
        registry: ProviderRegistry,
        request: ModelRouteRequest,
        messages: list[Message],
        preferred_model: str = "",
        tools: list[dict[str, Any]] | None = None,
        static_instruction: str = "",
    ) -> AsyncIterator[Chunk]:
        """Stream a chat completion through the routed provider."""
        prepared_context = self.context_manager.prepare(
            messages,
            static_instruction=static_instruction,
        )
        effective_request = replace(
            request,
            input_tokens_estimate=prepared_context.prepared_input_tokens,
            cacheable_prefix=request.cacheable_prefix or prepared_context.cacheable_prefix,
        )
        route = self._select_route(
            registry=registry,
            request=effective_request,
            preferred_model=preferred_model,
        )
        provider = registry.resolve(route.provider_name, route.model_id)
        async for chunk in provider.stream(
            prepared_context.messages,
            model=route.model_id,
            tools=tools or None,
            cache_strategy=route.cache_strategy.value,
        ):
            yield chunk

    async def _chat_with_fallback(
        self,
        *,
        registry: ProviderRegistry,
        route: ModelRouteDecision,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Response, FallbackResult]:
        """Execute chat with automatic cross-provider fallback."""
        assert self.fallback_engine is not None

        async def call_fn(
            provider_name: str,
            model_id: str,
            msgs: list[Message],
            **kwargs: Any,
        ) -> Response:
            provider = registry.resolve(provider_name, model_id)
            return await provider.chat(msgs, model=model_id, **kwargs)

        result = await self.fallback_engine.execute(
            tier=route.tier,
            messages=messages,
            call_fn=call_fn,
            primary_override=FallbackTarget(
                provider=route.provider_name,
                model_id=route.model_id,
                tier=route.tier,
            ),
            tools=tools,
            cache_strategy=route.cache_strategy.value,
        )
        return result.response, result

    def _select_route(
        self,
        *,
        registry: ProviderRegistry,
        request: ModelRouteRequest,
        preferred_model: str,
    ) -> ModelRouteDecision:
        preferred_provider, preferred_model_id = parse_model_ref(preferred_model)
        if preferred_provider and preferred_model_id and registry.has_provider(preferred_provider):
            return ModelRouteDecision(
                provider_name=preferred_provider,
                model_id=preferred_model_id,
                tier=ModelTier.STANDARD,
                reasoning="agent model override",
                cache_strategy=self._cache_strategy_for_provider(preferred_provider, request),
                batch_eligible=request.batch_eligible and not request.latency_sensitive,
            )

        try:
            routed = self.router.route(request)
        except ValueError:
            routed = None
        if routed is None:
            available_providers = set(registry.provider_names())
            if preferred_provider is None and preferred_model and len(available_providers) == 1:
                provider_name = next(iter(available_providers))
                return ModelRouteDecision(
                    provider_name=provider_name,
                    model_id=preferred_model,
                    tier=ModelTier.STANDARD,
                    reasoning="fallback to preferred model id on sole available provider",
                    cache_strategy=self._cache_strategy_for_provider(
                        provider_name,
                        request,
                    ),
                    batch_eligible=request.batch_eligible
                    and not request.latency_sensitive,
                )
            if available_providers:
                return self.router.route_for_available_providers(request, available_providers)
            raise ValueError("No available provider for routed model request")
        if registry.has_provider(routed.provider_name):
            return routed

        available_providers = set(registry.provider_names())
        if preferred_provider is None and preferred_model and len(available_providers) == 1:
            provider_name = next(iter(available_providers))
            return ModelRouteDecision(
                provider_name=provider_name,
                model_id=preferred_model,
                tier=ModelTier.STANDARD,
                reasoning="fallback to preferred model id on sole available provider",
                cache_strategy=self._cache_strategy_for_provider(provider_name, request),
                batch_eligible=request.batch_eligible and not request.latency_sensitive,
            )
        if available_providers:
            return self.router.route_for_available_providers(request, available_providers)
        raise ValueError("No available provider for routed model request")

    def _cache_strategy_for_provider(
        self,
        provider_name: str,
        request: ModelRouteRequest,
    ) -> CacheStrategy:
        if request.batch_eligible and not request.latency_sensitive:
            return CacheStrategy.BATCH
        if not request.cacheable_prefix:
            return CacheStrategy.NONE
        if provider_name in {"openai", "google"}:
            return CacheStrategy.PREFIX
        return CacheStrategy.EXPLICIT

    def _estimate_cost(
        self,
        provider_name: str,
        model_id: str,
        usage: TokenUsage,
    ) -> float:
        pricing = self.pricing.get((provider_name, model_id))
        if pricing is None:
            return 0.0
        return (
            usage.input_tokens * pricing.input_per_million
            + usage.output_tokens * pricing.output_per_million
            + usage.cache_read_tokens * pricing.cache_read_per_million
            + usage.cache_write_tokens * pricing.cache_write_per_million
        ) / 1_000_000

    def _record_metrics(
        self,
        route: ModelRouteDecision,
        usage: TokenUsage,
        estimated_cost_usd: float,
    ) -> None:
        if self.metrics is None:
            return
        labels = {
            "provider": route.provider_name,
            "model": route.model_id,
            "tier": route.tier.value,
        }
        self.metrics.counter("llm_token_usage", usage.total_tokens, labels=labels)
        self.metrics.counter("llm_cost_usd", estimated_cost_usd, labels=labels)
        self.metrics.counter("model_route_count", 1, labels=labels)


def messages_from_input(value: Any) -> list[Message]:
    """Normalize a raw input payload into provider messages."""
    if isinstance(value, list):
        messages: list[Message] = []
        for item in value:
            if isinstance(item, Message):
                messages.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError("Message payload items must be dict or Message")
            messages.append(
                Message(
                    role=str(item.get("role", "user")),
                    content=str(item.get("content", "")),
                    tool_calls=list(item.get("tool_calls", [])),
                    tool_call_id=item.get("tool_call_id"),
                )
            )
        return messages
    if isinstance(value, str):
        return [Message(role="user", content=value)]
    raise ValueError("Expected prompt string or message list")


def estimate_message_tokens(messages: list[Message]) -> int:
    """Cheap token estimate for routing heuristics."""
    from pylon.runtime.context import _estimate_message_tokens

    return _estimate_message_tokens(messages)
