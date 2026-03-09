"""Tests for pylon.intelligence.adaptive_router."""

from unittest.mock import patch

from pylon.autonomy.routing import ModelTier
from pylon.intelligence.adaptive_router import AdaptiveRouter, RoutingOutcome


def _make_outcome(
    purpose: str = "code",
    provider: str = "anthropic",
    quality: float = 0.9,
    cost: float = 0.01,
    tier: ModelTier = ModelTier.STANDARD,
) -> RoutingOutcome:
    return RoutingOutcome(
        purpose=purpose,
        provider=provider,
        model_id="model-1",
        tier=tier,
        quality_score=quality,
        cost_usd=cost,
        latency_ms=100.0,
    )


class TestAdaptiveRouter:
    def test_record_outcome(self) -> None:
        router = AdaptiveRouter()
        outcome = _make_outcome()
        router.record_outcome(outcome)
        assert len(router._outcomes) == 1
        assert router._outcomes[0] is outcome

    def test_suggest_provider_insufficient_samples(self) -> None:
        router = AdaptiveRouter(min_samples=5)
        # Only 3 samples for anthropic
        for _ in range(3):
            router.record_outcome(_make_outcome(provider="anthropic"))
        for _ in range(5):
            router.record_outcome(_make_outcome(provider="openai"))

        result = router.suggest_provider("code", ModelTier.STANDARD, ["anthropic", "openai"])
        assert result is None

    def test_suggest_provider_best_quality_cost(self) -> None:
        router = AdaptiveRouter(exploration_rate=0.0, min_samples=2)
        # anthropic: quality 0.9, cost 0.10 -> ratio 9.0
        for _ in range(3):
            router.record_outcome(_make_outcome(provider="anthropic", quality=0.9, cost=0.10))
        # openai: quality 0.8, cost 0.05 -> ratio 16.0
        for _ in range(3):
            router.record_outcome(_make_outcome(provider="openai", quality=0.8, cost=0.05))

        with patch("pylon.intelligence.adaptive_router.random") as mock_random:
            mock_random.random.return_value = 0.5  # above exploration_rate=0.0
            result = router.suggest_provider("code", ModelTier.STANDARD, ["anthropic", "openai"])

        assert result == "openai"

    def test_get_stats(self) -> None:
        router = AdaptiveRouter()
        router.record_outcome(_make_outcome(provider="anthropic", quality=0.8, cost=0.02))
        router.record_outcome(_make_outcome(provider="anthropic", quality=1.0, cost=0.04))
        router.record_outcome(_make_outcome(provider="openai", quality=0.7, cost=0.01))

        stats = router.get_stats(purpose="code")
        assert stats["anthropic"]["count"] == 2
        assert abs(stats["anthropic"]["avg_quality"] - 0.9) < 1e-9
        assert abs(stats["anthropic"]["avg_cost"] - 0.03) < 1e-9
        assert stats["openai"]["count"] == 1
