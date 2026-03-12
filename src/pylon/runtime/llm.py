"""Provider-backed LLM runtime with model routing, cost telemetry, and fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from typing import Any

from pylon.autonomy.explainability import DecisionExplainer
from pylon.autonomy.routing import (
    CacheStrategy,
    ModelRouteDecision,
    ModelRouter,
    ModelRouteRequest,
    ModelTier,
)
from pylon.cost.estimator import CostEstimator
from pylon.cost.fallback_engine import FallbackEngine, FallbackResult, FallbackTarget
from pylon.observability.metrics import MetricsCollector
from pylon.observability.tracing import Span, Tracer
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


def _span_payload(span: Span | None) -> dict[str, str] | None:
    if span is None:
        return None
    payload = {"trace_id": span.trace_id, "span_id": span.span_id}
    if span.parent_id:
        payload["parent_id"] = span.parent_id
    return payload


def _normalize_pricing_provider(provider_name: str) -> str:
    normalized = provider_name.strip().lower()
    aliases = {
        "gemini": "google",
        "google": "google",
        "vertex": "google",
        "vertexai": "google",
    }
    return aliases.get(normalized, normalized)


def _default_pricing() -> dict[tuple[str, str], ModelPricing]:
    pricing: dict[tuple[str, str], ModelPricing] = {
        ("openai", "gpt-5-mini"): ModelPricing(
            input_per_million=0.25,
            output_per_million=2.0,
            cache_read_per_million=0.025,
            cache_write_per_million=0.25,
        ),
        ("anthropic", "claude-sonnet-4-6"): ModelPricing(
            input_per_million=3.0,
            output_per_million=15.0,
            cache_read_per_million=0.30,
            cache_write_per_million=3.75,
        ),
        ("anthropic", "claude-sonnet-4-5"): ModelPricing(
            input_per_million=3.0,
            output_per_million=15.0,
            cache_read_per_million=0.30,
            cache_write_per_million=3.75,
        ),
        # Inference from the closest official Vertex AI pro-tier pricing table.
        ("google", "gemini-3-pro-preview"): ModelPricing(
            input_per_million=1.25,
            output_per_million=10.0,
            cache_read_per_million=0.3125,
            cache_write_per_million=1.25,
        ),
        # Official Moonshot K2 pricing chart published on 2026-02-11.
        ("moonshot", "kimi-k2.5"): ModelPricing(
            input_per_million=1.15,
            output_per_million=8.0,
            cache_read_per_million=0.15,
            cache_write_per_million=1.15,
        ),
        # Official GLM-4-Plus docs publish a flat 5 CNY / 1M tokens.
        # We split evenly across input/output to preserve the total-token bill.
        ("zhipu", "glm-4-plus"): ModelPricing(
            input_per_million=0.3453,
            output_per_million=0.3453,
        ),
    }
    return pricing


def estimate_cost_from_usage(
    provider_name: str,
    model_id: str,
    usage: TokenUsage,
    *,
    pricing: dict[tuple[str, str], ModelPricing] | None = None,
) -> float:
    active_pricing = pricing or _default_pricing()
    normalized_provider = _normalize_pricing_provider(provider_name)
    selected = active_pricing.get((provider_name, model_id))
    if selected is None:
        selected = active_pricing.get((normalized_provider, model_id))
    if selected is not None:
        return (
            usage.input_tokens * selected.input_per_million
            + usage.output_tokens * selected.output_per_million
            + usage.cache_read_tokens * selected.cache_read_per_million
            + usage.cache_write_tokens * selected.cache_write_per_million
            + usage.reasoning_tokens * selected.output_per_million
        ) / 1_000_000
    return CostEstimator().estimate(
        normalized_provider,
        model_id,
        usage,
        reasoning_tokens=usage.reasoning_tokens,
    )


@dataclass
class LLMRuntime:
    """Routes provider-backed chat calls and standardizes telemetry.

    Integrates FallbackEngine for automatic cross-provider failover
    and ProviderHealthTracker for health-aware routing.
    """

    router: ModelRouter = field(default_factory=ModelRouter)
    pricing: dict[tuple[str, str], ModelPricing] = field(default_factory=_default_pricing)
    metrics: MetricsCollector | None = None
    context_manager: ContextManager = field(default_factory=ContextManager)
    fallback_engine: FallbackEngine | None = None
    health_tracker: ProviderHealthTracker | None = None
    tracer: Tracer | None = None
    decision_explainer: DecisionExplainer | None = field(default_factory=DecisionExplainer)

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
        scope = (
            self.tracer.start_as_current_span(
                "llm.chat",
                attributes={
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": preferred_model,
                    "pylon.llm.message_count": len(messages),
                },
            )
            if self.tracer is not None
            else nullcontext(None)
        )
        with scope as span:
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
            explanation = (
                self.decision_explainer.explain_route(route)
                if self.decision_explainer is not None
                else None
            )
            if span is not None and explanation is not None:
                for key, value in explanation.to_otel_attributes().items():
                    span.set_attribute(key, value)

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
                if span is not None and fallback_result.was_fallback:
                    span.add_event(
                        "provider.fallback",
                        {
                            "provider": fallback_result.provider,
                            "model": fallback_result.model_id,
                            "attempts": fallback_result.attempt,
                        },
                    )

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
            if span is not None:
                span.set_attribute("gen_ai.system", effective_route.provider_name)
                span.set_attribute("gen_ai.response.model", response.model)
                span.set_attribute("pylon.llm.estimated_cost_usd", estimated_cost)
                span.set_attribute("pylon.llm.input_tokens", usage.input_tokens)
                span.set_attribute("pylon.llm.output_tokens", usage.output_tokens)

            context: dict[str, Any] = {
                "compacted": prepared_context.was_compacted,
                "original_input_tokens": prepared_context.original_input_tokens,
                "prepared_input_tokens": prepared_context.prepared_input_tokens,
                "cacheable_prefix": prepared_context.cacheable_prefix,
                "summary": prepared_context.summary,
                "requested_route": route.to_dict(),
            }
            if explanation is not None:
                context["decision"] = {
                    "summary": explanation.summary,
                    "confidence": explanation.confidence,
                    "risk_level": explanation.risk_level,
                }
            if fallback_result is not None and fallback_result.was_fallback:
                context["fallback"] = {
                    "was_fallback": True,
                    "attempts": fallback_result.attempt,
                    "final_provider": fallback_result.provider,
                    "final_model": fallback_result.model_id,
                    "events": [e.to_dict() for e in fallback_result.events],
                }
            trace_payload = _span_payload(span)
            if trace_payload is not None:
                context["trace"] = trace_payload

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
        scope = (
            self.tracer.start_as_current_span(
                "llm.stream",
                attributes={
                    "gen_ai.operation.name": "stream",
                    "gen_ai.request.model": preferred_model,
                },
            )
            if self.tracer is not None
            else nullcontext(None)
        )
        with scope as span:
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
            explanation = (
                self.decision_explainer.explain_route(route)
                if self.decision_explainer is not None
                else None
            )
            if span is not None and explanation is not None:
                for key, value in explanation.to_otel_attributes().items():
                    span.set_attribute(key, value)
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
        return estimate_cost_from_usage(
            provider_name,
            model_id,
            usage,
            pricing=self.pricing,
        )

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
        self.metrics.counter("llm_token_usage", usage.metered_tokens, labels=labels)
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
