"""Tests for cost estimation and spend tracking."""

from __future__ import annotations

import pytest

from pylon.cost.estimator import (
    CostEstimator,
    Currency,
    ModelPricingTable,
    ProviderPricing,
    SpendRecord,
)
from pylon.providers.base import TokenUsage


@pytest.fixture
def pricing_table() -> ModelPricingTable:
    return ModelPricingTable(pricing=(
        ProviderPricing(
            provider="anthropic",
            model_id="claude-haiku",
            input_per_million=1.00,
            output_per_million=5.00,
            cached_input_per_million=0.10,
            cache_write_per_million=1.25,
            batch_discount=0.50,
        ),
        ProviderPricing(
            provider="deepseek",
            model_id="deepseek-chat",
            input_per_million=0.28,
            output_per_million=0.42,
            cached_input_per_million=0.028,
        ),
    ))


@pytest.fixture
def estimator(pricing_table: ModelPricingTable) -> CostEstimator:
    return CostEstimator(pricing_table=pricing_table)


class TestCostEstimator:
    def test_estimate_basic(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = estimator.estimate("anthropic", "claude-haiku", usage)
        expected = (1000 * 1.00 + 500 * 5.00) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_estimate_with_cache(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(
            input_tokens=500,
            output_tokens=200,
            cache_read_tokens=500,
            cache_write_tokens=500,
        )
        cost = estimator.estimate("anthropic", "claude-haiku", usage)
        expected = (
            500 * 1.00 + 200 * 5.00 + 500 * 0.10 + 500 * 1.25
        ) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_estimate_batch_discount(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost_normal = estimator.estimate("anthropic", "claude-haiku", usage)
        cost_batch = estimator.estimate(
            "anthropic", "claude-haiku", usage, is_batch=True,
        )
        assert cost_batch == pytest.approx(cost_normal * 0.50)

    def test_estimate_unknown_model(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = estimator.estimate("unknown", "model", usage)
        assert cost == 0.0

    def test_estimate_and_record(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = estimator.estimate_and_record(
            "anthropic", "claude-haiku", usage,
            session_id="s1", workflow_id="w1",
        )
        assert cost > 0

        session_spend = estimator.get_spend("session", "s1")
        assert session_spend.total_usd == pytest.approx(cost)
        assert session_spend.request_count == 1

        workflow_spend = estimator.get_spend("workflow", "w1")
        assert workflow_spend.total_usd == pytest.approx(cost)

    def test_remaining_budget(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        estimator.estimate_and_record(
            "anthropic", "claude-haiku", usage, session_id="s1",
        )
        cost = estimator.get_spend("session", "s1").total_usd
        remaining = estimator.remaining_budget("session", "s1", 1.0)
        assert remaining == pytest.approx(1.0 - cost)

    def test_currency_conversion(self, estimator: CostEstimator) -> None:
        usd_amount = 10.0
        cny = estimator.convert_currency(usd_amount, Currency.CNY)
        assert cny == pytest.approx(72.4)

        eur = estimator.convert_currency(usd_amount, Currency.EUR)
        assert eur == pytest.approx(9.2)

        same = estimator.convert_currency(usd_amount, Currency.USD)
        assert same == usd_amount

    def test_reasoning_tokens(self, estimator: CostEstimator) -> None:
        usage = TokenUsage(input_tokens=100, output_tokens=1000)
        cost_no_reason = estimator.estimate("anthropic", "claude-haiku", usage)
        # With reasoning_tokens, output is split: 500 standard + 500 reasoning.
        # Since reasoning_per_million is None for haiku, both charge at output rate.
        cost_with_reason = estimator.estimate(
            "anthropic", "claude-haiku", usage, reasoning_tokens=500,
        )
        assert cost_with_reason == pytest.approx(cost_no_reason)


class TestModelPricingTable:
    def test_cheapest_for_tier(self, pricing_table: ModelPricingTable) -> None:
        ranked = pricing_table.cheapest_for_tier()
        assert len(ranked) == 2
        # DeepSeek should be cheapest (0.28 + 0.42 = 0.70 vs 1.00 + 5.00 = 6.00).
        assert ranked[0].provider == "deepseek"

    def test_filter_by_providers(self, pricing_table: ModelPricingTable) -> None:
        ranked = pricing_table.cheapest_for_tier(providers={"anthropic"})
        assert len(ranked) == 1
        assert ranked[0].provider == "anthropic"


class TestSpendRecord:
    def test_burn_rate(self) -> None:
        record = SpendRecord(
            total_usd=1.0,
            request_count=10,
            first_request_at=100.0,
            last_request_at=160.0,  # 60 seconds = 1 minute
        )
        assert record.burn_rate_usd_per_minute == pytest.approx(1.0)

    def test_burn_rate_single_request(self) -> None:
        record = SpendRecord(
            total_usd=0.5,
            request_count=1,
            first_request_at=100.0,
            last_request_at=100.0,
        )
        assert record.burn_rate_usd_per_minute == 0.0
