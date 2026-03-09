"""Tests for adaptive cost optimizer."""

from __future__ import annotations

import pytest

from pylon.autonomy.routing import CacheStrategy, ModelTier
from pylon.cost.estimator import CostEstimator, ModelPricingTable, ProviderPricing
from pylon.cost.optimizer import (
    CostCeiling,
    CostOptimizer,
    QualityFloor,
    TaskComplexity,
)


@pytest.fixture
def pricing_table() -> ModelPricingTable:
    return ModelPricingTable(pricing=(
        ProviderPricing(
            provider="deepseek", model_id="deepseek-chat",
            input_per_million=0.28, output_per_million=0.42,
            cached_input_per_million=0.028,
        ),
        ProviderPricing(
            provider="openai", model_id="gpt-4o-mini",
            input_per_million=0.05, output_per_million=0.40,
            cached_input_per_million=0.025,
            min_cacheable_tokens=1024,
        ),
        ProviderPricing(
            provider="anthropic", model_id="claude-haiku",
            input_per_million=1.00, output_per_million=5.00,
            cached_input_per_million=0.10,
            cache_write_per_million=1.25,
        ),
        ProviderPricing(
            provider="anthropic", model_id="claude-opus",
            input_per_million=5.00, output_per_million=25.00,
            cached_input_per_million=0.50,
        ),
    ))


@pytest.fixture
def optimizer(pricing_table: ModelPricingTable) -> CostOptimizer:
    estimator = CostEstimator(pricing_table=pricing_table)
    return CostOptimizer(
        estimator=estimator,
        pricing_table=pricing_table,
    )


class TestComplexityClassification:
    def test_trivial_tasks(self, optimizer: CostOptimizer) -> None:
        c = optimizer.classify_complexity(purpose="classify sentiment")
        assert c == TaskComplexity.TRIVIAL

    def test_high_tasks(self, optimizer: CostOptimizer) -> None:
        c = optimizer.classify_complexity(purpose="analyze codebase architecture")
        assert c == TaskComplexity.HIGH

    def test_quality_sensitive(self, optimizer: CostOptimizer) -> None:
        c = optimizer.classify_complexity(quality_sensitive=True)
        assert c == TaskComplexity.CRITICAL

    def test_medium_with_tools(self, optimizer: CostOptimizer) -> None:
        c = optimizer.classify_complexity(
            requires_tools=True, input_tokens_estimate=5000,
        )
        assert c == TaskComplexity.MEDIUM


class TestRecommendation:
    def test_cheapest_for_trivial(self, optimizer: CostOptimizer) -> None:
        rec = optimizer.recommend(
            complexity=TaskComplexity.TRIVIAL,
            input_tokens_estimate=500,
            output_tokens_estimate=100,
        )
        # Should pick one of the lightweight models (gpt-4o-mini or deepseek).
        assert rec.provider in {"deepseek", "openai", "groq", "mistral"}
        assert rec.estimated_cost_usd > 0

    def test_quality_floor_enforced(self, pricing_table: ModelPricingTable) -> None:
        estimator = CostEstimator(pricing_table=pricing_table)
        optimizer = CostOptimizer(
            estimator=estimator,
            pricing_table=pricing_table,
            floor=QualityFloor(min_tier=ModelTier.STANDARD),
        )
        rec = optimizer.recommend(
            complexity=TaskComplexity.LOW,
            input_tokens_estimate=500,
            output_tokens_estimate=100,
        )
        # Even for LOW complexity, should not pick lightweight due to floor.
        assert rec.tier in {ModelTier.STANDARD, ModelTier.PREMIUM}

    def test_cost_ceiling_rejects(self, pricing_table: ModelPricingTable) -> None:
        estimator = CostEstimator(pricing_table=pricing_table)
        optimizer = CostOptimizer(
            estimator=estimator,
            pricing_table=pricing_table,
            ceiling=CostCeiling(per_request_usd=0.00001),
        )
        with pytest.raises(ValueError, match="exceed per-request ceiling"):
            optimizer.recommend(
                complexity=TaskComplexity.LOW,
                input_tokens_estimate=10000,
                output_tokens_estimate=5000,
            )

    def test_cache_savings_estimated(self, optimizer: CostOptimizer) -> None:
        rec = optimizer.recommend(
            complexity=TaskComplexity.LOW,
            input_tokens_estimate=2000,
            output_tokens_estimate=500,
            cacheable_prefix_tokens=1500,
        )
        if rec.cache_savings:
            assert rec.cache_savings.estimated_saving_usd > 0
            assert rec.cache_savings.saving_percentage > 0

    def test_provider_filter(self, optimizer: CostOptimizer) -> None:
        rec = optimizer.recommend(
            complexity=TaskComplexity.LOW,
            input_tokens_estimate=500,
            output_tokens_estimate=100,
            available_providers={"anthropic"},
        )
        assert rec.provider == "anthropic"

    def test_budget_pacing(self, pricing_table: ModelPricingTable) -> None:
        estimator = CostEstimator(pricing_table=pricing_table)
        optimizer = CostOptimizer(
            estimator=estimator,
            pricing_table=pricing_table,
        )
        rec = optimizer.recommend(
            complexity=TaskComplexity.LOW,
            input_tokens_estimate=500,
            output_tokens_estimate=100,
            workflow_id="w1",
            workflow_budget_usd=1.0,
            workflow_total_steps=10,
            workflow_completed_steps=0,
        )
        assert rec.budget_pacing is not None
        assert rec.budget_pacing.per_step_budget_usd == pytest.approx(0.10)
        assert rec.budget_pacing.on_pace is True
