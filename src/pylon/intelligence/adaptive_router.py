"""Adaptive routing with learning from past outcomes."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from pylon.autonomy.routing import ModelTier


@dataclass
class RoutingOutcome:
    """Recorded outcome of a routing decision for adaptive learning."""

    purpose: str
    provider: str
    model_id: str
    tier: ModelTier
    quality_score: float  # 0.0-1.0
    cost_usd: float
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


class AdaptiveRouter:
    """Epsilon-greedy adaptive router that learns from past routing outcomes.

    Tracks quality/cost ratios per provider and suggests the best candidate
    once enough samples have been collected. Falls back to None (letting the
    default router decide) when data is insufficient.
    """

    def __init__(
        self,
        exploration_rate: float = 0.1,
        min_samples: int = 5,
    ) -> None:
        if not 0.0 <= exploration_rate <= 1.0:
            raise ValueError("exploration_rate must be between 0.0 and 1.0")
        if min_samples < 1:
            raise ValueError("min_samples must be at least 1")
        self._exploration_rate = exploration_rate
        self._min_samples = min_samples
        self._outcomes: list[RoutingOutcome] = []
        self._outcomes_max: int = 10000

    def suggest_provider(
        self,
        purpose: str,
        tier: ModelTier,
        candidates: list[str],
    ) -> str | None:
        """Suggest the best provider from candidates based on past outcomes.

        Returns None when insufficient data is available, signaling that
        the caller should fall back to default routing logic.
        """
        if not candidates:
            return None

        # Filter outcomes matching purpose and tier
        relevant: dict[str, list[RoutingOutcome]] = {}
        for outcome in self._outcomes:
            if outcome.purpose == purpose and outcome.tier == tier and outcome.provider in candidates:
                relevant.setdefault(outcome.provider, []).append(outcome)

        # Check if all candidates have enough samples
        for candidate in candidates:
            if len(relevant.get(candidate, [])) < self._min_samples:
                return None

        # Epsilon-greedy exploration
        if random.random() < self._exploration_rate:
            return random.choice(candidates)

        # Exploit: pick provider with best quality/cost score
        scored = [
            (candidate, self._score_provider(candidate, purpose, tier))
            for candidate in candidates
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[0][0]

    def record_outcome(self, outcome: RoutingOutcome) -> None:
        """Record a routing outcome for future adaptive decisions."""
        self._outcomes.append(outcome)
        self._trim_outcomes()

    def get_stats(self, purpose: str = "") -> dict:
        """Return per-provider statistics, optionally filtered by purpose.

        Returns a dict keyed by provider name, each containing count,
        avg_quality, avg_cost, and avg_latency.
        """
        stats: dict[str, dict] = {}
        for outcome in self._outcomes:
            if purpose and outcome.purpose != purpose:
                continue
            provider = outcome.provider
            if provider not in stats:
                stats[provider] = {
                    "count": 0,
                    "total_quality": 0.0,
                    "total_cost": 0.0,
                    "total_latency": 0.0,
                }
            entry = stats[provider]
            entry["count"] += 1
            entry["total_quality"] += outcome.quality_score
            entry["total_cost"] += outcome.cost_usd
            entry["total_latency"] += outcome.latency_ms

        result: dict[str, dict] = {}
        for provider, entry in stats.items():
            count = entry["count"]
            result[provider] = {
                "count": count,
                "avg_quality": entry["total_quality"] / count,
                "avg_cost": entry["total_cost"] / count,
                "avg_latency": entry["total_latency"] / count,
            }
        return result

    def _score_provider(self, provider: str, purpose: str, tier: ModelTier | None = None) -> float:
        """Score a provider by quality/cost ratio for a given purpose and tier.

        Higher is better. If cost is zero, uses quality alone.
        When tier is provided, only outcomes matching that tier are considered.
        """
        outcomes = [
            o for o in self._outcomes
            if o.provider == provider and o.purpose == purpose
            and (tier is None or o.tier == tier)
        ]
        if not outcomes:
            return 0.0

        avg_quality = sum(o.quality_score for o in outcomes) / len(outcomes)
        avg_cost = sum(o.cost_usd for o in outcomes) / len(outcomes)

        if avg_cost <= 0.0:
            return avg_quality
        return avg_quality / avg_cost

    def _trim_outcomes(self) -> None:
        """Remove oldest outcomes when exceeding max capacity."""
        if len(self._outcomes) > self._outcomes_max:
            excess = len(self._outcomes) - self._outcomes_max
            self._outcomes = self._outcomes[excess:]
