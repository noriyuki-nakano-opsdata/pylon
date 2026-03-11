"""Human feedback collection and online learning.

Collects approval/rejection/scoring feedback from human operators and
uses it to improve agent behavior over time. Integrates with the
AdaptiveAutonomyManager for autonomy level adjustments.

Uses a lightweight Context Bandit implementation for online learning
without requiring a full RL infrastructure.
"""

from __future__ import annotations

import enum
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


class FeedbackType(enum.Enum):
    APPROVAL = "approval"
    REJECTION = "rejection"
    RATING = "rating"  # 1-5 scale
    CORRECTION = "correction"  # Human corrected the output
    PREFERENCE = "preference"  # A/B choice between options


@dataclass
class HumanFeedback:
    """A single feedback signal from a human operator."""

    run_id: str
    agent_id: str
    feedback_type: FeedbackType
    value: float  # 1.0 for approval, 0.0 for rejection, or rating
    context: dict[str, Any] = field(default_factory=dict)
    correction: str | None = None
    timestamp: float = field(default_factory=time.time)

    @property
    def is_positive(self) -> bool:
        return self.value > 0.5


@dataclass
class FeedbackSummary:
    """Aggregated feedback statistics for an agent."""

    agent_id: str
    total_feedback: int = 0
    positive_count: int = 0
    negative_count: int = 0
    average_rating: float = 0.0
    correction_count: int = 0
    recent_trend: str = "neutral"  # "improving", "declining", "neutral"
    by_action: dict[str, float] = field(default_factory=dict)


class FeedbackCollector:
    """Collects and aggregates human feedback.

    Usage:
        collector = FeedbackCollector()
        collector.record(HumanFeedback(
            run_id="run-123",
            agent_id="coder",
            feedback_type=FeedbackType.APPROVAL,
            value=1.0,
            context={"action": "write_file"},
        ))
        summary = collector.aggregate("coder")
    """

    def __init__(self, max_history: int = 10000) -> None:
        self._history: dict[str, list[HumanFeedback]] = defaultdict(list)
        self._max_history = max_history

    def record(self, feedback: HumanFeedback) -> None:
        """Record a feedback signal."""
        history = self._history[feedback.agent_id]
        history.append(feedback)
        if len(history) > self._max_history:
            self._history[feedback.agent_id] = history[-self._max_history :]

    def aggregate(self, agent_id: str) -> FeedbackSummary:
        """Aggregate feedback for an agent."""
        history = self._history.get(agent_id, [])
        if not history:
            return FeedbackSummary(agent_id=agent_id)

        positive = sum(1 for f in history if f.is_positive)
        negative = len(history) - positive
        ratings = [f.value for f in history if f.feedback_type == FeedbackType.RATING]
        corrections = sum(
            1 for f in history if f.feedback_type == FeedbackType.CORRECTION
        )

        # Compute per-action success rates
        action_counts: dict[str, list[float]] = defaultdict(list)
        for f in history:
            action = f.context.get("action", "unknown")
            action_counts[action].append(f.value)
        by_action = {
            action: sum(values) / len(values)
            for action, values in action_counts.items()
        }

        # Trend detection (compare last 20% vs first 20%)
        if len(history) >= 10:
            window = max(len(history) // 5, 2)
            early = sum(f.value for f in history[:window]) / window
            recent = sum(f.value for f in history[-window:]) / window
            if recent > early + 0.1:
                trend = "improving"
            elif recent < early - 0.1:
                trend = "declining"
            else:
                trend = "neutral"
        else:
            trend = "neutral"

        return FeedbackSummary(
            agent_id=agent_id,
            total_feedback=len(history),
            positive_count=positive,
            negative_count=negative,
            average_rating=sum(ratings) / len(ratings) if ratings else 0.0,
            correction_count=corrections,
            recent_trend=trend,
            by_action=by_action,
        )

    def get_history(
        self,
        agent_id: str,
        *,
        limit: int = 50,
        feedback_type: FeedbackType | None = None,
    ) -> list[HumanFeedback]:
        """Get feedback history for an agent."""
        history = self._history.get(agent_id, [])
        if feedback_type is not None:
            history = [f for f in history if f.feedback_type == feedback_type]
        return history[-limit:]


class ContextBandit:
    """Contextual bandit for online decision learning.

    Uses Thompson Sampling to learn which actions work best in
    which contexts. Much simpler than full RL—requires only
    (context, action, reward) tuples.

    Usage:
        bandit = ContextBandit(actions=["model_a", "model_b", "model_c"])
        action = bandit.select_action({"task_type": "coding", "complexity": "high"})
        # ... execute action, observe reward ...
        bandit.update({"task_type": "coding", "complexity": "high"}, action, reward=0.9)
    """

    def __init__(self, actions: list[str]) -> None:
        self._actions = actions
        # Simple: per-action (alpha, beta) for Thompson Sampling
        self._alpha: dict[str, float] = {a: 1.0 for a in actions}
        self._beta: dict[str, float] = {a: 1.0 for a in actions}
        # Per-context success tracking
        self._context_stats: dict[str, dict[str, tuple[float, float]]] = {}

    def select_action(self, context: dict[str, Any] | None = None) -> str:
        """Select an action using Thompson Sampling."""
        context_key = self._context_key(context) if context else ""

        # Get per-context stats if available
        if context_key and context_key in self._context_stats:
            stats = self._context_stats[context_key]
            samples = {
                action: random.betavariate(
                    stats.get(action, (1.0, 1.0))[0],
                    stats.get(action, (1.0, 1.0))[1],
                )
                for action in self._actions
            }
        else:
            samples = {
                action: random.betavariate(self._alpha[action], self._beta[action])
                for action in self._actions
            }

        return max(samples, key=samples.get)  # type: ignore[arg-type]

    def update(
        self, context: dict[str, Any] | None, action: str, reward: float
    ) -> None:
        """Update beliefs based on observed reward."""
        if action not in self._alpha:
            return

        # Update global
        self._alpha[action] += reward
        self._beta[action] += (1.0 - reward)

        # Update per-context
        if context:
            ctx_key = self._context_key(context)
            if ctx_key not in self._context_stats:
                self._context_stats[ctx_key] = {}
            stats = self._context_stats[ctx_key]
            current = stats.get(action, (1.0, 1.0))
            stats[action] = (current[0] + reward, current[1] + (1.0 - reward))

    def get_action_values(self) -> dict[str, float]:
        """Get expected reward for each action."""
        return {
            action: self._alpha[action] / (self._alpha[action] + self._beta[action])
            for action in self._actions
        }

    @staticmethod
    def _context_key(context: dict[str, Any]) -> str:
        """Create a hashable key from context dict."""
        sorted_items = sorted(
            (str(k), str(v)) for k, v in context.items()
        )
        return "|".join(f"{k}={v}" for k, v in sorted_items)
