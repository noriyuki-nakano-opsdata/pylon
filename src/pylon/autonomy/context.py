"""Autonomy runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.goals import GoalSpec
from pylon.autonomy.routing import ModelRouteDecision
from pylon.providers.base import TokenUsage


@dataclass
class AutonomyContext:
    """Runtime-scoped autonomy state layered above workflow execution."""

    run_id: str
    workflow_id: str
    goal: GoalSpec
    current_iteration: int = 0
    replan_count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    model_routes: list[ModelRouteDecision] = field(default_factory=list)
    evaluation_history: list[dict[str, Any]] = field(default_factory=list)
    last_verification: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "goal": self.goal.to_dict(),
            "current_iteration": self.current_iteration,
            "replan_count": self.replan_count,
            "token_usage": {
                "input_tokens": self.token_usage.input_tokens,
                "output_tokens": self.token_usage.output_tokens,
                "cache_read_tokens": self.token_usage.cache_read_tokens,
                "cache_write_tokens": self.token_usage.cache_write_tokens,
                "total_tokens": self.token_usage.total_tokens,
            },
            "estimated_cost_usd": self.estimated_cost_usd,
            "model_routes": [decision.to_dict() for decision in self.model_routes],
            "evaluation_history": list(self.evaluation_history),
            "last_verification": self.last_verification,
        }
