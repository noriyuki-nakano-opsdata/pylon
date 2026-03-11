"""Cost estimation and cumulative spend tracking across providers.

Tracks per-session, per-workflow, and per-agent spend with real-time
burn rate calculation and currency conversion support.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pylon.providers.base import TokenUsage


class Currency(StrEnum):
    """Supported currencies for cost reporting."""

    USD = "USD"
    CNY = "CNY"
    EUR = "EUR"


# Static exchange rates (updated at deployment; override via config).
_DEFAULT_EXCHANGE_RATES: dict[tuple[Currency, Currency], float] = {
    (Currency.USD, Currency.CNY): 7.24,
    (Currency.USD, Currency.EUR): 0.92,
    (Currency.CNY, Currency.USD): 0.138,
    (Currency.CNY, Currency.EUR): 0.127,
    (Currency.EUR, Currency.USD): 1.087,
    (Currency.EUR, Currency.CNY): 7.87,
}


@dataclass(frozen=True)
class ProviderPricing:
    """Per-million token pricing for a single provider/model combination.

    All rates are in USD per million tokens.
    """

    provider: str
    model_id: str
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0
    cache_write_per_million: float = 0.0
    reasoning_per_million: float | None = None  # Some providers charge separately
    batch_discount: float = 0.0  # Fractional discount (0.5 = 50% off)
    min_cacheable_tokens: int = 0  # Minimum prefix length for cache eligibility


# 2026 provider pricing landscape.
# Model IDs MUST match DEFAULT_MODEL_PROFILES in pylon.autonomy.routing.
DEFAULT_PRICING: tuple[ProviderPricing, ...] = (
    # DeepSeek
    ProviderPricing(
        provider="deepseek", model_id="deepseek-chat",
        input_per_million=0.28, output_per_million=0.42,
        cached_input_per_million=0.028, cache_write_per_million=0.28,
        min_cacheable_tokens=0,
    ),
    # Groq
    ProviderPricing(
        provider="groq", model_id="llama-3.3-70b-versatile",
        input_per_million=0.05, output_per_million=0.08,
    ),
    # Gemini
    ProviderPricing(
        provider="google", model_id="gemini-2.0-flash",
        input_per_million=0.15, output_per_million=0.60,
        cached_input_per_million=0.0375, cache_write_per_million=0.15,
        min_cacheable_tokens=0,
    ),
    # Mistral
    ProviderPricing(
        provider="mistral", model_id="mistral-small-3.2",
        input_per_million=0.06, output_per_million=0.18,
    ),
    # OpenAI
    ProviderPricing(
        provider="openai", model_id="gpt-4o-mini",
        input_per_million=0.15, output_per_million=0.60,
        cached_input_per_million=0.025, cache_write_per_million=0.05,
        min_cacheable_tokens=1024,
    ),
    ProviderPricing(
        provider="openai", model_id="gpt-4o",
        input_per_million=2.50, output_per_million=10.00,
        cached_input_per_million=0.50, cache_write_per_million=2.00,
        min_cacheable_tokens=1024,
        batch_discount=0.50,
    ),
    # Anthropic
    ProviderPricing(
        provider="anthropic", model_id="claude-haiku",
        input_per_million=1.00, output_per_million=5.00,
        cached_input_per_million=0.10, cache_write_per_million=1.25,
        batch_discount=0.50,
    ),
    ProviderPricing(
        provider="anthropic", model_id="claude-sonnet",
        input_per_million=3.00, output_per_million=15.00,
        cached_input_per_million=0.30, cache_write_per_million=3.75,
        batch_discount=0.50,
    ),
    ProviderPricing(
        provider="anthropic", model_id="claude-opus",
        input_per_million=5.00, output_per_million=25.00,
        cached_input_per_million=0.50, cache_write_per_million=6.25,
        batch_discount=0.50,
    ),
)


@dataclass
class SpendRecord:
    """Cumulative spend tracking for a single scope (session/workflow/agent)."""

    total_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    request_count: int = 0
    first_request_at: float = 0.0
    last_request_at: float = 0.0

    @property
    def burn_rate_usd_per_minute(self) -> float:
        """Real-time burn rate in USD/minute based on elapsed time."""
        if self.request_count < 2 or self.first_request_at == self.last_request_at:
            return 0.0
        elapsed_minutes = (self.last_request_at - self.first_request_at) / 60.0
        if elapsed_minutes <= 0:
            return 0.0
        return self.total_usd / elapsed_minutes

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_usd": round(self.total_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "request_count": self.request_count,
            "burn_rate_usd_per_minute": round(self.burn_rate_usd_per_minute, 6),
        }


class ModelPricingTable:
    """Registry of provider pricing, keyed by (provider, model_id).

    Thread-safe. Supports runtime updates for custom or private models.
    """

    def __init__(
        self,
        pricing: tuple[ProviderPricing, ...] = DEFAULT_PRICING,
    ) -> None:
        self._lock = threading.Lock()
        self._table: dict[tuple[str, str], ProviderPricing] = {}
        for entry in pricing:
            self._table[(entry.provider, entry.model_id)] = entry

    def register(self, pricing: ProviderPricing) -> None:
        """Register or update pricing for a provider/model pair."""
        with self._lock:
            self._table[(pricing.provider, pricing.model_id)] = pricing

    def lookup(self, provider: str, model_id: str) -> ProviderPricing | None:
        """Look up pricing. Returns None if unknown model."""
        with self._lock:
            return self._table.get((provider, model_id))

    def cheapest_for_tier(
        self,
        providers: set[str] | None = None,
    ) -> list[ProviderPricing]:
        """Return all known pricings sorted by blended cost (input+output)."""
        with self._lock:
            candidates = list(self._table.values())
        if providers is not None:
            candidates = [p for p in candidates if p.provider in providers]
        candidates.sort(
            key=lambda p: p.input_per_million + p.output_per_million,
        )
        return candidates


class CostEstimator:
    """Estimates and tracks LLM costs with per-scope spend accumulation.

    Integration point: replaces LLMRuntime._estimate_cost with richer tracking.
    The LLMRuntime should call estimate_and_record() after each provider call
    and pass the returned cost into RoutedChatResult.estimated_cost_usd.

    Usage:
        estimator = CostEstimator()
        cost = estimator.estimate(provider, model, usage)
        estimator.record(session_id, cost, usage)
        report = estimator.get_spend("session", session_id)
    """

    def __init__(
        self,
        pricing_table: ModelPricingTable | None = None,
        exchange_rates: dict[tuple[Currency, Currency], float] | None = None,
    ) -> None:
        self._pricing = pricing_table or ModelPricingTable()
        self._exchange_rates = exchange_rates or dict(_DEFAULT_EXCHANGE_RATES)
        self._lock = threading.Lock()
        # Scope -> scope_id -> SpendRecord
        self._spend: dict[str, dict[str, SpendRecord]] = {
            "session": {},
            "workflow": {},
            "agent": {},
        }

    @property
    def pricing_table(self) -> ModelPricingTable:
        return self._pricing

    def estimate(
        self,
        provider: str,
        model_id: str,
        usage: TokenUsage,
        *,
        is_batch: bool = False,
        reasoning_tokens: int = 0,
    ) -> float:
        """Estimate cost in USD for a single request.

        Args:
            provider: Provider name (e.g., "anthropic").
            model_id: Model identifier (e.g., "claude-haiku").
            usage: Token counts from the provider response.
            is_batch: Whether this used the batch API (applies discount).
            reasoning_tokens: Tokens consumed by chain-of-thought/thinking.
                              Deducted from output_tokens if reasoning pricing
                              is set, otherwise charged at output rate.

        Returns:
            Estimated cost in USD.
        """
        pricing = self._pricing.lookup(provider, model_id)
        if pricing is None:
            return 0.0

        standard_output = usage.output_tokens - reasoning_tokens
        if standard_output < 0:
            standard_output = 0
            reasoning_tokens = usage.output_tokens

        cost = (
            usage.input_tokens * pricing.input_per_million
            + standard_output * pricing.output_per_million
            + usage.cache_read_tokens * pricing.cached_input_per_million
            + usage.cache_write_tokens * pricing.cache_write_per_million
        ) / 1_000_000

        if reasoning_tokens > 0:
            rate = pricing.reasoning_per_million or pricing.output_per_million
            cost += (reasoning_tokens * rate) / 1_000_000

        if is_batch and pricing.batch_discount > 0:
            cost *= 1.0 - pricing.batch_discount

        return cost

    def estimate_and_record(
        self,
        provider: str,
        model_id: str,
        usage: TokenUsage,
        *,
        session_id: str = "",
        workflow_id: str = "",
        agent_id: str = "",
        is_batch: bool = False,
        reasoning_tokens: int = 0,
    ) -> float:
        """Estimate cost and record it against all provided scopes.

        Convenience method combining estimate() + record().
        Returns the estimated cost in USD.
        """
        cost = self.estimate(
            provider, model_id, usage,
            is_batch=is_batch, reasoning_tokens=reasoning_tokens,
        )
        now = time.monotonic()
        with self._lock:
            for scope, scope_id in [
                ("session", session_id),
                ("workflow", workflow_id),
                ("agent", agent_id),
            ]:
                if not scope_id:
                    continue
                record = self._spend[scope].setdefault(scope_id, SpendRecord())
                record.total_usd += cost
                record.input_tokens += usage.input_tokens
                record.output_tokens += usage.output_tokens
                record.cached_tokens += usage.cache_read_tokens
                record.request_count += 1
                if record.first_request_at == 0.0:
                    record.first_request_at = now
                record.last_request_at = now
        return cost

    def get_spend(self, scope: str, scope_id: str) -> SpendRecord:
        """Retrieve cumulative spend for a scope.

        Args:
            scope: One of "session", "workflow", "agent".
            scope_id: The identifier within that scope.

        Returns:
            SpendRecord (default empty if not found).
        """
        with self._lock:
            return self._spend.get(scope, {}).get(scope_id, SpendRecord())

    def remaining_budget(
        self,
        scope: str,
        scope_id: str,
        budget_usd: float,
    ) -> float:
        """Calculate remaining budget for a scope."""
        spent = self.get_spend(scope, scope_id).total_usd
        return max(0.0, budget_usd - spent)

    def convert_currency(
        self,
        amount_usd: float,
        target: Currency,
    ) -> float:
        """Convert a USD amount to target currency."""
        if target == Currency.USD:
            return amount_usd
        rate = self._exchange_rates.get((Currency.USD, target))
        if rate is None:
            raise ValueError(f"No exchange rate from USD to {target}")
        return amount_usd * rate

    def reset_scope(self, scope: str, scope_id: str) -> None:
        """Clear spend records for a scope."""
        with self._lock:
            if scope in self._spend:
                self._spend[scope].pop(scope_id, None)
