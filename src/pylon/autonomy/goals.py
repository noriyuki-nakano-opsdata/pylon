"""Goal specification types for bounded autonomous execution."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.termination import (
    AnyTermination,
    CostBudget,
    MaxIterations,
    TerminationCondition,
    Timeout,
    TokenBudget,
)


class FailurePolicy(enum.StrEnum):
    """Fallback behavior when a goal cannot be satisfied."""

    FAIL = "fail"
    ESCALATE = "escalate"
    REQUEST_APPROVAL = "request_approval"


class RunCompletionPolicy(enum.StrEnum):
    """When goal satisfaction is allowed to complete the run."""

    REQUIRE_WORKFLOW_END = "require_workflow_end"
    COMPLETE_ON_GOAL = "complete_on_goal"


@dataclass(frozen=True)
class RefinementPolicy:
    """Explicit policy for bounded refinement and refinement exhaustion."""

    max_replans: int | None = None
    exhaustion_policy: FailurePolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_replans": self.max_replans,
            "exhaustion_policy": (
                self.exhaustion_policy.value if self.exhaustion_policy is not None else None
            ),
        }


@dataclass(frozen=True)
class SuccessCriterion:
    """Declarative success criterion for a goal."""

    type: str
    threshold: float | None = None
    rubric: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "threshold": self.threshold,
            "rubric": self.rubric,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GoalConstraints:
    """Resource and retry ceilings for a goal-directed run."""

    max_iterations: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    timeout_seconds: float | None = None
    max_replans: int | None = None

    def to_termination_condition(self) -> TerminationCondition | None:
        conditions: list[TerminationCondition] = []
        if self.max_iterations is not None:
            conditions.append(MaxIterations(self.max_iterations))
        if self.max_tokens is not None:
            conditions.append(TokenBudget(max_total_tokens=self.max_tokens))
        if self.max_cost_usd is not None:
            conditions.append(CostBudget(self.max_cost_usd))
        if self.timeout_seconds is not None:
            conditions.append(Timeout(self.timeout_seconds))
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return AnyTermination(tuple(conditions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "timeout_seconds": self.timeout_seconds,
            "max_replans": self.max_replans,
        }


@dataclass(frozen=True)
class GoalSpec:
    """Declared objective and success conditions for an autonomous run."""

    objective: str
    success_criteria: tuple[SuccessCriterion, ...] = ()
    constraints: GoalConstraints = field(default_factory=GoalConstraints)
    failure_policy: FailurePolicy = FailurePolicy.ESCALATE
    completion_policy: RunCompletionPolicy = RunCompletionPolicy.REQUIRE_WORKFLOW_END
    refinement_policy: RefinementPolicy = field(default_factory=RefinementPolicy)
    allowed_effect_scopes: frozenset[str] = field(default_factory=frozenset)
    allowed_secret_scopes: frozenset[str] = field(default_factory=frozenset)

    def resolved_max_replans(self) -> int | None:
        if self.refinement_policy.max_replans is not None:
            return self.refinement_policy.max_replans
        return self.constraints.max_replans

    def resolved_refinement_failure_policy(self) -> FailurePolicy:
        return self.refinement_policy.exhaustion_policy or self.failure_policy

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "success_criteria": [criterion.to_dict() for criterion in self.success_criteria],
            "constraints": self.constraints.to_dict(),
            "failure_policy": self.failure_policy.value,
            "completion_policy": self.completion_policy.value,
            "refinement_policy": self.refinement_policy.to_dict(),
            "allowed_effect_scopes": sorted(self.allowed_effect_scopes),
            "allowed_secret_scopes": sorted(self.allowed_secret_scopes),
        }
