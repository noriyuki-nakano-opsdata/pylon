"""Fallback chain engine for cross-provider failover.

Implements configurable fallback chains with same-tier cross-provider
fallback followed by tier downgrade. Only triggers on retryable errors
(429/5xx), never on client errors (400-428).

Preserves request context across fallback attempts and converts message
formats between providers during failover.

Integration point: wraps LLMRuntime.chat() to intercept ProviderError
and transparently retry with alternate providers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.routing import ModelTier
from pylon.cost.rate_limiter import RateLimitManager
from pylon.providers.base import Message, Response

# Status codes that trigger fallback.
_FALLBACK_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FallbackTarget:
    """A single fallback target: provider + model at a specific tier."""

    provider: str
    model_id: str
    tier: ModelTier


@dataclass(frozen=True)
class FallbackChainConfig:
    """Configurable fallback chain per tier.

    same_tier: cross-provider fallbacks at the same quality level.
    downgrade: fallback targets at lower tiers (ordered by preference).
    max_attempts: total attempts including the primary (1 = no fallback).
    """

    primary_provider: str
    primary_model: str
    primary_tier: ModelTier
    same_tier: tuple[FallbackTarget, ...] = ()
    downgrade: tuple[FallbackTarget, ...] = ()
    max_attempts: int = 3

    def chain(self) -> list[FallbackTarget]:
        """Return the full fallback chain in priority order."""
        targets: list[FallbackTarget] = [
            FallbackTarget(
                provider=self.primary_provider,
                model_id=self.primary_model,
                tier=self.primary_tier,
            ),
        ]
        targets.extend(self.same_tier)
        targets.extend(self.downgrade)
        return targets[:self.max_attempts]


@dataclass
class FallbackEvent:
    """Record of a single fallback attempt for observability.

    These events are emitted to the EventBus as "llm.fallback" events
    and stored for audit logging.
    """

    timestamp: float
    from_provider: str
    from_model: str
    to_provider: str
    to_model: str
    reason: str
    status_code: int = 0
    attempt: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "from_provider": self.from_provider,
            "from_model": self.from_model,
            "to_provider": self.to_provider,
            "to_model": self.to_model,
            "reason": self.reason,
            "status_code": self.status_code,
            "attempt": self.attempt,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class FallbackResult:
    """Result of a fallback chain execution."""

    response: Response
    provider: str
    model_id: str
    tier: ModelTier
    attempt: int
    events: list[FallbackEvent] = field(default_factory=list)
    total_latency_ms: float = 0.0

    @property
    def was_fallback(self) -> bool:
        """True if the response came from a fallback provider."""
        return self.attempt > 1


class ProviderCallError(Exception):
    """Wraps a provider error with status code for fallback decisions."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        provider: str = "",
        model_id: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.model_id = model_id


# Default fallback chains per tier.
# Model IDs MUST match DEFAULT_MODEL_PROFILES in pylon.autonomy.routing.
DEFAULT_FALLBACK_CHAINS: dict[ModelTier, FallbackChainConfig] = {
    ModelTier.PREMIUM: FallbackChainConfig(
        primary_provider="anthropic",
        primary_model="claude-opus",
        primary_tier=ModelTier.PREMIUM,
        same_tier=(
            FallbackTarget("openai", "o3", ModelTier.PREMIUM),
        ),
        downgrade=(
            FallbackTarget("anthropic", "claude-sonnet", ModelTier.STANDARD),
            FallbackTarget("openai", "gpt-4o-mini", ModelTier.LIGHTWEIGHT),
        ),
        max_attempts=3,
    ),
    ModelTier.STANDARD: FallbackChainConfig(
        primary_provider="anthropic",
        primary_model="claude-sonnet",
        primary_tier=ModelTier.STANDARD,
        same_tier=(
            FallbackTarget("openai", "gpt-4o", ModelTier.STANDARD),
        ),
        downgrade=(
            FallbackTarget("deepseek", "deepseek-chat", ModelTier.LIGHTWEIGHT),
            FallbackTarget("openai", "gpt-4o-mini", ModelTier.LIGHTWEIGHT),
        ),
        max_attempts=3,
    ),
    ModelTier.LIGHTWEIGHT: FallbackChainConfig(
        primary_provider="deepseek",
        primary_model="deepseek-chat",
        primary_tier=ModelTier.LIGHTWEIGHT,
        same_tier=(
            FallbackTarget("openai", "gpt-4o-mini", ModelTier.LIGHTWEIGHT),
            FallbackTarget("groq", "llama-3.3-70b-versatile", ModelTier.LIGHTWEIGHT),
            FallbackTarget("mistral", "mistral-small-3.2", ModelTier.LIGHTWEIGHT),
        ),
        max_attempts=3,
    ),
}


class FallbackEngine:
    """Executes LLM calls with automatic cross-provider fallback.

    Usage:
        engine = FallbackEngine(
            rate_limiter=rate_limit_manager,
            chains={ModelTier.STANDARD: my_chain_config},
        )

        async def call_provider(provider, model, messages, **kwargs):
            return await registry.resolve(provider, model).chat(messages, **kwargs)

        result = await engine.execute(
            tier=ModelTier.STANDARD,
            messages=messages,
            call_fn=call_provider,
        )

    Integration with LLMRuntime:
        The LLMRuntime.chat() method should delegate to FallbackEngine.execute()
        instead of calling provider.chat() directly. The engine handles retries,
        circuit breaker checks, and message format conversion transparently.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        chains: dict[ModelTier, FallbackChainConfig] | None = None,
        on_fallback: Any = None,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._chains = chains or dict(DEFAULT_FALLBACK_CHAINS)
        self._on_fallback = on_fallback
        self._events: list[FallbackEvent] = []
        self._events_max = 10000

    def set_chain(self, tier: ModelTier, config: FallbackChainConfig) -> None:
        """Override the fallback chain for a tier."""
        self._chains[tier] = config

    async def execute(
        self,
        *,
        tier: ModelTier,
        messages: list[Message],
        call_fn: Any,
        primary_override: FallbackTarget | None = None,
        tools: list[dict[str, Any]] | None = None,
        cache_strategy: str = "none",
        **kwargs: Any,
    ) -> FallbackResult:
        """Execute an LLM call with fallback chain.

        Args:
            tier: The model tier to use (determines fallback chain).
            messages: Pylon messages to send.
            call_fn: Async callable(provider, model_id, messages, **kw) -> Response.
            primary_override: Optional primary target to use for the first
                attempt while preserving the configured same-tier and downgrade
                fallbacks for the selected tier.
            tools: Tool definitions to pass through.
            cache_strategy: Cache strategy value string.
            **kwargs: Additional arguments passed to call_fn.

        Returns:
            FallbackResult with the response and fallback metadata.

        Raises:
            ProviderCallError: If all fallback attempts fail. The error
                contains the last failure's status code.
        """
        chain_config = self._chains.get(tier)
        if chain_config is None:
            raise ValueError(f"No fallback chain configured for tier {tier.value}")

        if primary_override is not None:
            filtered_same_tier = tuple(
                target
                for target in chain_config.same_tier
                if (target.provider, target.model_id)
                != (primary_override.provider, primary_override.model_id)
            )
            filtered_downgrade = tuple(
                target
                for target in chain_config.downgrade
                if (target.provider, target.model_id)
                != (primary_override.provider, primary_override.model_id)
            )
            chain_config = FallbackChainConfig(
                primary_provider=primary_override.provider,
                primary_model=primary_override.model_id,
                primary_tier=primary_override.tier,
                same_tier=filtered_same_tier,
                downgrade=filtered_downgrade,
                max_attempts=chain_config.max_attempts,
            )

        chain = chain_config.chain()
        events: list[FallbackEvent] = []
        last_error: ProviderCallError | None = None
        start_time = time.monotonic()

        for attempt, target in enumerate(chain, 1):
            # Index of the next target in the chain (0-indexed).
            next_idx = attempt  # enumerate starts at 1, so attempt == next 0-index
            next_target = chain[next_idx] if next_idx < len(chain) else None

            # Rate limiter pre-flight check.
            if self._rate_limiter and not self._rate_limiter.can_send(
                target.provider,
            ):
                events.append(FallbackEvent(
                    timestamp=time.time(),
                    from_provider=target.provider,
                    from_model=target.model_id,
                    to_provider=next_target.provider if next_target else "",
                    to_model=next_target.model_id if next_target else "",
                    reason="rate_limited",
                    attempt=attempt,
                ))
                continue

            acquired = False
            if self._rate_limiter:
                self._rate_limiter.acquire(target.provider)
                acquired = True

            call_start = time.monotonic()
            try:
                # Convert messages if switching providers.
                effective_messages = messages
                if last_error and last_error.provider != target.provider:
                    effective_messages = self._convert_messages(
                        messages, target.provider,
                    )

                response = await call_fn(
                    target.provider,
                    target.model_id,
                    effective_messages,
                    tools=tools,
                    cache_strategy=cache_strategy,
                    **kwargs,
                )
                latency = (time.monotonic() - call_start) * 1000

                if self._rate_limiter:
                    self._rate_limiter.record_success(
                        target.provider, latency_ms=latency,
                    )

                total_latency = (time.monotonic() - start_time) * 1000
                return FallbackResult(
                    response=response,
                    provider=target.provider,
                    model_id=target.model_id,
                    tier=target.tier,
                    attempt=attempt,
                    events=events,
                    total_latency_ms=total_latency,
                )

            except Exception as exc:
                latency = (time.monotonic() - call_start) * 1000

                status_code = _extract_status_code(exc)

                # Do NOT fallback on client errors (except 429).
                if 400 <= status_code < 429:
                    raise ProviderCallError(
                        str(exc),
                        status_code=status_code,
                        provider=target.provider,
                        model_id=target.model_id,
                    ) from exc

                if self._rate_limiter:
                    self._rate_limiter.record_failure(
                        target.provider,
                        status_code=status_code,
                        latency_ms=latency,
                    )

                last_error = ProviderCallError(
                    str(exc),
                    status_code=status_code,
                    provider=target.provider,
                    model_id=target.model_id,
                )

                event = FallbackEvent(
                    timestamp=time.time(),
                    from_provider=target.provider,
                    from_model=target.model_id,
                    to_provider=next_target.provider if next_target else "",
                    to_model=next_target.model_id if next_target else "",
                    reason=f"error_{status_code}",
                    status_code=status_code,
                    attempt=attempt,
                    latency_ms=latency,
                )
                events.append(event)
                self._record_event(event)

                if self._on_fallback:
                    try:
                        self._on_fallback(event)
                    except Exception:
                        pass

            finally:
                # Guarantee release only if we actually acquired.
                if acquired and self._rate_limiter:
                    self._rate_limiter.release(target.provider)

        # All attempts exhausted.
        if last_error:
            raise last_error
        raise ProviderCallError(
            "All fallback targets exhausted",
            status_code=503,
        )

    def get_recent_events(self, limit: int = 100) -> list[FallbackEvent]:
        """Retrieve recent fallback events for observability."""
        return list(self._events[-limit:])

    def _convert_messages(
        self,
        messages: list[Message],
        target_provider: str,
    ) -> list[Message]:
        """Convert messages between provider formats during fallback.

        Most conversions are handled by the provider implementations, but
        some structural differences need pre-processing:
        - Anthropic uses separate system parameter; OpenAI uses system role
        - Tool result format differs between providers
        """
        # Messages are in Pylon's provider-agnostic format, so no
        # structural conversion is needed at this level. Provider-specific
        # adapters handle the final translation.
        return messages

    def _record_event(self, event: FallbackEvent) -> None:
        """Store a fallback event for observability."""
        if len(self._events) >= self._events_max:
            self._events = self._events[-(self._events_max // 2):]
        self._events.append(event)


def _extract_status_code(exc: Exception) -> int:
    """Extract HTTP status code from a provider exception."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    details = getattr(exc, "details", {})
    if isinstance(details, dict):
        code = details.get("status_code")
        if isinstance(code, int):
            return code
    return 500
