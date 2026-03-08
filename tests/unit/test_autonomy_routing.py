from __future__ import annotations

import pytest

from pylon.autonomy.routing import CacheStrategy, ModelRouter, ModelRouteRequest, ModelTier


def test_simple_request_routes_to_lightweight_tier() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="classification",
            input_tokens_estimate=500,
            latency_sensitive=True,
        )
    )

    assert decision.tier == ModelTier.LIGHTWEIGHT


def test_quality_sensitive_request_routes_to_premium_tier() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="final answer",
            input_tokens_estimate=2000,
            quality_sensitive=True,
        )
    )

    assert decision.tier == ModelTier.PREMIUM


def test_budget_pressure_downgrades_premium_request() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="final answer",
            input_tokens_estimate=2000,
            quality_sensitive=True,
            remaining_budget_usd=0.05,
        )
    )

    assert decision.tier == ModelTier.STANDARD


def test_severe_budget_pressure_downgrades_to_lightweight() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="final answer",
            input_tokens_estimate=2000,
            quality_sensitive=True,
            remaining_budget_usd=0.02,
        )
    )

    assert decision.tier == ModelTier.LIGHTWEIGHT


def test_standard_request_can_downgrade_to_lightweight_under_budget_pressure() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="tooling",
            input_tokens_estimate=9000,
            remaining_budget_usd=0.02,
        )
    )

    assert decision.tier == ModelTier.LIGHTWEIGHT


def test_batch_cache_strategy_selected_when_eligible() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="offline eval",
            input_tokens_estimate=6000,
            cacheable_prefix=True,
            batch_eligible=True,
            latency_sensitive=False,
        )
    )

    assert decision.cache_strategy == CacheStrategy.BATCH
    assert decision.batch_eligible is True


def test_cacheable_prefix_selects_explicit_cache_for_anthropic() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="review",
            input_tokens_estimate=2000,
            cacheable_prefix=True,
        )
    )

    assert decision.cache_strategy == CacheStrategy.EXPLICIT


def test_requires_tools_filters_profiles() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="tool-use",
            input_tokens_estimate=1000,
            requires_tools=True,
        )
    )

    assert decision.tier in {ModelTier.LIGHTWEIGHT, ModelTier.STANDARD}


def test_empty_profiles_raise_value_error() -> None:
    with pytest.raises(ValueError):
        ModelRouter(profiles=())


def test_latency_sensitive_mid_range_request_routes_to_standard_tier() -> None:
    router = ModelRouter()
    decision = router.route(
        ModelRouteRequest(
            purpose="chat",
            input_tokens_estimate=4000,
            latency_sensitive=True,
        )
    )

    assert decision.tier == ModelTier.STANDARD
