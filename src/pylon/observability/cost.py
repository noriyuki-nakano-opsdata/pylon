"""LLM cost tracking with budget alerts."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date


@dataclass
class ModelPricing:
    input_price_per_1k: float  # USD per 1K input tokens
    output_price_per_1k: float  # USD per 1K output tokens

    def calculate(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1000 * self.input_price_per_1k
            + output_tokens / 1000 * self.output_price_per_1k
        )

    def estimate(self, max_tokens: int) -> float:
        return max_tokens / 1000 * self.output_price_per_1k


@dataclass
class CostReport:
    tenant_id: str
    date: str
    total_cost_usd: float
    by_model: dict[str, float]
    by_provider: dict[str, float]
    budget_limit_usd: float
    utilization_pct: float
    alerts: list[str]


class LLMPriceTable:
    """Provider-specific pricing."""

    _DEFAULT_PRICES: dict[str, ModelPricing] = {
        "openai/gpt-4o": ModelPricing(0.005, 0.015),
        "openai/gpt-4o-mini": ModelPricing(0.00015, 0.0006),
        "openai/gpt-4-turbo": ModelPricing(0.01, 0.03),
        "anthropic/claude-sonnet-4-6": ModelPricing(0.003, 0.015),
        "anthropic/claude-opus-4-6": ModelPricing(0.015, 0.075),
        "anthropic/claude-haiku-4-5": ModelPricing(0.0008, 0.004),
        "google/gemini-2.0-flash": ModelPricing(0.00015, 0.0006),
    }

    def __init__(self) -> None:
        self._prices: dict[str, ModelPricing] = dict(self._DEFAULT_PRICES)

    def set_price(self, model: str, pricing: ModelPricing) -> None:
        self._prices[model] = pricing

    def get_price(self, model: str) -> ModelPricing | None:
        return self._prices.get(model)

    def list_models(self) -> list[str]:
        return list(self._prices.keys())


@dataclass
class _UsageRecord:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostTracker:
    """Per-tenant cost tracking with budget alerts."""

    def __init__(self, price_table: LLMPriceTable | None = None) -> None:
        self._lock = threading.Lock()
        self._price_table = price_table or LLMPriceTable()
        # {(tenant_id, date_str): [_UsageRecord, ...]}
        self._records: dict[tuple[str, str], list[_UsageRecord]] = {}
        # {tenant_id: budget_usd}
        self._budgets: dict[str, float] = {}

    def set_budget(self, tenant_id: str, daily_budget_usd: float) -> None:
        with self._lock:
            self._budgets[tenant_id] = daily_budget_usd

    def pre_estimate(self, model: str, max_tokens: int) -> float:
        pricing = self._price_table.get_price(model)
        if pricing is None:
            return 0.0
        return pricing.estimate(max_tokens)

    def record_actual(
        self,
        tenant_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        pricing = self._price_table.get_price(model)
        if pricing is None:
            cost = 0.0
        else:
            cost = pricing.calculate(input_tokens, output_tokens)

        provider = model.split("/")[0] if "/" in model else model

        record = _UsageRecord(
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

        today = date.today().isoformat()
        key = (tenant_id, today)
        with self._lock:
            self._records.setdefault(key, []).append(record)

        return cost

    def get_daily_summary(
        self, tenant_id: str, day: str | None = None
    ) -> CostReport:
        day = day or date.today().isoformat()
        key = (tenant_id, day)

        with self._lock:
            records = list(self._records.get(key, []))
            budget = self._budgets.get(tenant_id, 0.0)

        total = sum(r.cost_usd for r in records)
        by_model: dict[str, float] = {}
        by_provider: dict[str, float] = {}
        for r in records:
            by_model[r.model] = by_model.get(r.model, 0.0) + r.cost_usd
            by_provider[r.provider] = by_provider.get(r.provider, 0.0) + r.cost_usd

        utilization = (total / budget * 100) if budget > 0 else 0.0
        alerts = self._generate_alerts(tenant_id, total, budget)

        return CostReport(
            tenant_id=tenant_id,
            date=day,
            total_cost_usd=total,
            by_model=by_model,
            by_provider=by_provider,
            budget_limit_usd=budget,
            utilization_pct=utilization,
            alerts=alerts,
        )

    def check_budget(self, tenant_id: str) -> list[str]:
        report = self.get_daily_summary(tenant_id)
        return report.alerts

    def _generate_alerts(
        self, tenant_id: str, total: float, budget: float
    ) -> list[str]:
        if budget <= 0:
            return []
        alerts: list[str] = []
        pct = total / budget * 100
        if pct >= 100:
            alerts.append(
                f"CRITICAL: Tenant {tenant_id} has exceeded daily budget "
                f"({pct:.1f}% of ${budget:.2f})"
            )
        elif pct >= 80:
            alerts.append(
                f"WARNING: Tenant {tenant_id} at {pct:.1f}% of daily budget "
                f"(${budget:.2f})"
            )
        return alerts
