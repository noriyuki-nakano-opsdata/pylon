"""Dynamic autonomy level adjustment via Thompson Sampling.

Monitors human approval patterns and adjusts agent autonomy levels
based on demonstrated trustworthiness.  Uses Thompson Sampling to
balance exploration (trying higher autonomy) with exploitation
(staying at proven safe levels).

Integrates with Pylon's AutonomyLevel enum (A0-A4) and the approval
system in runtime/execution.py.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass


@dataclass
class TrustRecord:
    """Track record of an agent's approval history."""

    agent_id: str
    total_actions: int = 0
    approved: int = 0
    rejected: int = 0
    last_approved: float | None = None
    last_rejected: float | None = None
    consecutive_approvals: int = 0
    consecutive_rejections: int = 0

    @property
    def approval_rate(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.approved / self.total_actions

    @property
    def has_sufficient_data(self) -> bool:
        return self.total_actions >= 10


@dataclass(frozen=True)
class LevelRecommendation:
    """Recommendation for autonomy level adjustment."""

    current_level: int  # 0-4
    recommended_level: int  # 0-4
    confidence: float  # 0.0 - 1.0
    reason: str
    should_change: bool = False

    @property
    def direction(self) -> str:
        if self.recommended_level > self.current_level:
            return "upgrade"
        elif self.recommended_level < self.current_level:
            return "downgrade"
        return "maintain"


class ThompsonSampler:
    """Thompson Sampling for autonomy level exploration.

    Models each autonomy level as a Beta distribution:
    - Alpha: successful outcomes (approved actions)
    - Beta: failed outcomes (rejected actions)

    Samples from each level's Beta distribution and selects the
    one with the highest sampled value, naturally balancing
    exploration and exploitation.
    """

    def __init__(self, num_levels: int = 5) -> None:
        # Beta(alpha, beta) for each autonomy level
        self._alpha = [1.0] * num_levels  # prior: 1 success
        self._beta = [1.0] * num_levels  # prior: 1 failure
        self._pulls = [0] * num_levels

    def select_level(self) -> int:
        """Sample from Beta distributions and return the best level."""
        samples = []
        for i in range(len(self._alpha)):
            sample = random.betavariate(self._alpha[i], self._beta[i])
            samples.append(sample)
        return max(range(len(samples)), key=lambda i: samples[i])

    def update(self, level: int, reward: float) -> None:
        """Update the Beta distribution for a level.

        Args:
            level: The autonomy level that was tested (0-4).
            reward: 1.0 for success (approved), 0.0 for failure (rejected).
        """
        if 0 <= level < len(self._alpha):
            self._alpha[level] += reward
            self._beta[level] += (1.0 - reward)
            self._pulls[level] += 1

    def expected_values(self) -> list[float]:
        """Return expected value (mean) for each level."""
        return [
            a / (a + b) for a, b in zip(self._alpha, self._beta)
        ]

    def confidence_intervals(self) -> list[tuple[float, float]]:
        """Return 95% confidence intervals for each level."""
        intervals = []
        for a, b in zip(self._alpha, self._beta):
            total = a + b
            mean = a / total
            std = math.sqrt(a * b / (total ** 2 * (total + 1)))
            intervals.append((
                max(0.0, mean - 1.96 * std),
                min(1.0, mean + 1.96 * std),
            ))
        return intervals


class AdaptiveAutonomyManager:
    """Dynamically adjusts agent autonomy levels based on approval history.

    Usage:
        manager = AdaptiveAutonomyManager()

        # Record approval/rejection events
        manager.update_trust("agent-1", approved=True)

        # Get level recommendation
        rec = manager.recommend_level("agent-1", current_level=1)
        if rec.should_change:
            print(f"Recommend: {rec.direction} to level {rec.recommended_level}")
    """

    def __init__(
        self,
        *,
        promotion_threshold: int = 5,
        demotion_threshold: int = 2,
        min_data_points: int = 10,
        max_level: int = 4,
    ) -> None:
        self._records: dict[str, TrustRecord] = {}
        self._samplers: dict[str, ThompsonSampler] = {}
        self._promotion_threshold = promotion_threshold
        self._demotion_threshold = demotion_threshold
        self._min_data = min_data_points
        self._max_level = max_level

    def update_trust(self, agent_id: str, *, approved: bool) -> None:
        """Record an approval or rejection event."""
        record = self._get_or_create(agent_id)
        record.total_actions += 1

        if approved:
            record.approved += 1
            record.consecutive_approvals += 1
            record.consecutive_rejections = 0
            record.last_approved = time.time()
        else:
            record.rejected += 1
            record.consecutive_rejections += 1
            record.consecutive_approvals = 0
            record.last_rejected = time.time()

    def recommend_level(
        self,
        agent_id: str,
        current_level: int,
    ) -> LevelRecommendation:
        """Recommend an autonomy level change."""
        record = self._get_or_create(agent_id)

        if not record.has_sufficient_data:
            return LevelRecommendation(
                current_level=current_level,
                recommended_level=current_level,
                confidence=0.0,
                reason=f"insufficient data ({record.total_actions}/{self._min_data} actions)",
            )

        # Rule-based promotion/demotion
        if record.consecutive_approvals >= self._promotion_threshold:
            if current_level < self._max_level:
                return LevelRecommendation(
                    current_level=current_level,
                    recommended_level=current_level + 1,
                    confidence=min(record.approval_rate, 0.95),
                    reason=f"{record.consecutive_approvals} consecutive approvals",
                    should_change=True,
                )

        if record.consecutive_rejections >= self._demotion_threshold:
            if current_level > 0:
                return LevelRecommendation(
                    current_level=current_level,
                    recommended_level=current_level - 1,
                    confidence=0.9,
                    reason=f"{record.consecutive_rejections} consecutive rejections",
                    should_change=True,
                )

        # Thompson Sampling exploration
        sampler = self._get_sampler(agent_id)
        sampler.update(current_level, 1.0 if record.approval_rate > 0.8 else 0.0)
        suggested = sampler.select_level()

        if suggested != current_level:
            expected = sampler.expected_values()
            confidence = expected[suggested]
            return LevelRecommendation(
                current_level=current_level,
                recommended_level=min(suggested, self._max_level),
                confidence=confidence,
                reason=f"Thompson Sampling exploration (expected value: {confidence:.2f})",
                should_change=confidence > 0.7,
            )

        return LevelRecommendation(
            current_level=current_level,
            recommended_level=current_level,
            confidence=record.approval_rate,
            reason=f"maintaining level (approval rate: {record.approval_rate:.1%})",
        )

    def get_trust_record(self, agent_id: str) -> TrustRecord:
        return self._get_or_create(agent_id)

    def get_all_records(self) -> dict[str, TrustRecord]:
        return dict(self._records)

    def _get_or_create(self, agent_id: str) -> TrustRecord:
        if agent_id not in self._records:
            self._records[agent_id] = TrustRecord(agent_id=agent_id)
        return self._records[agent_id]

    def _get_sampler(self, agent_id: str) -> ThompsonSampler:
        if agent_id not in self._samplers:
            self._samplers[agent_id] = ThompsonSampler(
                num_levels=self._max_level + 1
            )
        return self._samplers[agent_id]
