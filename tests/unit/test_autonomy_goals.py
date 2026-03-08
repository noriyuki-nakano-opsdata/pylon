from __future__ import annotations

from pylon.autonomy.goals import (
    FailurePolicy,
    GoalConstraints,
    GoalSpec,
    RefinementPolicy,
    RunCompletionPolicy,
    SuccessCriterion,
)
from pylon.autonomy.termination import TerminationState
from pylon.types import RunStopReason


def test_goal_constraints_build_termination_policy() -> None:
    constraints = GoalConstraints(
        max_iterations=3,
        max_tokens=100,
        max_cost_usd=0.5,
        timeout_seconds=30,
    )

    policy = constraints.to_termination_condition()
    assert policy is not None

    decision = policy.evaluate(TerminationState(iterations=3))
    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.LIMIT_EXCEEDED


def test_goal_spec_serializes_for_runtime_state() -> None:
    goal = GoalSpec(
        objective="answer accurately",
        success_criteria=(
            SuccessCriterion(type="rubric", threshold=0.8, rubric="be precise"),
        ),
        constraints=GoalConstraints(max_iterations=5),
        failure_policy=FailurePolicy.REQUEST_APPROVAL,
        completion_policy=RunCompletionPolicy.COMPLETE_ON_GOAL,
        refinement_policy=RefinementPolicy(
            max_replans=2,
            exhaustion_policy=FailurePolicy.FAIL,
        ),
        allowed_effect_scopes=frozenset({"github.pr.comment"}),
        allowed_secret_scopes=frozenset({"vault"}),
    )

    payload = goal.to_dict()

    assert payload["objective"] == "answer accurately"
    assert payload["constraints"]["max_iterations"] == 5
    assert payload["failure_policy"] == "request_approval"
    assert payload["completion_policy"] == "complete_on_goal"
    assert payload["refinement_policy"]["max_replans"] == 2
    assert payload["refinement_policy"]["exhaustion_policy"] == "fail"
    assert payload["allowed_effect_scopes"] == ["github.pr.comment"]
    assert payload["allowed_secret_scopes"] == ["vault"]


def test_goal_spec_refinement_policy_falls_back_to_legacy_max_replans() -> None:
    goal = GoalSpec(
        objective="answer accurately",
        constraints=GoalConstraints(max_replans=3),
    )

    assert goal.resolved_max_replans() == 3
    assert goal.resolved_refinement_failure_policy() == FailurePolicy.ESCALATE
