"""Tests for evaluation-native autonomy helpers."""

import pytest

from pylon.autonomy.evaluation import Critic, VerificationDisposition, Verifier
from pylon.autonomy.goals import GoalSpec, SuccessCriterion
from pylon.workflow.result import NodeResult


class TestCritic:
    def test_response_quality_threshold_passes(self):
        goal = GoalSpec(
            objective="answer well",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
        )

        critic = Critic()
        evaluations = critic.evaluate(
            goal,
            state={"answer": "ok"},
            event_log=[],
            results={
                "draft": NodeResult(
                    state_patch={"answer": "ok"},
                    metrics={"response_quality_score": 0.91},
                )
            },
        )

        assert len(evaluations) == 1
        assert evaluations[0].passed is True
        assert evaluations[0].score == 0.91

    def test_tool_trajectory_in_order_match(self):
        goal = GoalSpec(
            objective="use tools in sequence",
            success_criteria=(
                SuccessCriterion(
                    type="tool_trajectory",
                    metadata={"expected": ["search", "fetch"], "match": "in_order"},
                ),
            ),
        )

        critic = Critic()
        evaluations = critic.evaluate(
            goal,
            state={},
            event_log=[],
            results={
                "step": NodeResult(
                    tool_events=[{"tool": "search"}, {"tool": "other"}, {"tool": "fetch"}]
                )
            },
        )

        assert evaluations[0].passed is True
        assert evaluations[0].metadata["observed"] == ["search", "other", "fetch"]

    def test_hallucination_and_safety_scores_are_evaluated(self):
        goal = GoalSpec(
            objective="safe and grounded",
            success_criteria=(
                SuccessCriterion(type="hallucination", threshold=0.7),
                SuccessCriterion(type="safety", threshold=0.8),
            ),
        )

        evaluations = Critic().evaluate(
            goal,
            state={},
            event_log=[],
            results={
                "step": NodeResult(
                    metrics={"hallucination_score": 0.8, "safety_score": 0.9}
                )
            },
        )

        assert [evaluation.passed for evaluation in evaluations] == [True, True]

    def test_response_quality_reads_metrics_from_dict_results(self):
        goal = GoalSpec(
            objective="answer well",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
        )

        evaluations = Critic().evaluate(
            goal,
            state={},
            event_log=[],
            results={"draft": {"metrics": {"response_quality_score": 0.85}}},
        )

        assert evaluations[0].passed is True
        assert evaluations[0].score == 0.85

    def test_state_value_without_key_fails_cleanly(self):
        goal = GoalSpec(
            objective="need a state key",
            success_criteria=(SuccessCriterion(type="state_value", metadata={}),),
        )

        evaluations = Critic().evaluate(goal, state={}, event_log=[], results={})

        assert evaluations[0].passed is False
        assert "missing 'key'" in evaluations[0].reason


class TestVerifier:
    def test_success_when_all_criteria_pass(self):
        goal = GoalSpec(
            objective="done",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.5),),
        )
        evaluations = Critic().evaluate(
            goal,
            state={},
            event_log=[],
            results={"step": NodeResult(metrics={"response_quality_score": 0.9})},
        )

        decision = Verifier().verify(goal, evaluations)

        assert decision is not None
        assert decision.disposition == VerificationDisposition.SUCCESS

    def test_verify_returns_success_for_empty_evaluations(self):
        goal = GoalSpec(objective="noop")
        decision = Verifier().verify(goal, ())
        assert decision is not None
        assert decision.disposition == VerificationDisposition.SUCCESS
        assert decision.reason == "no success criteria defined"
        assert decision.results == ()

    def test_refine_when_non_terminal_criterion_is_not_yet_satisfied(self):
        goal = GoalSpec(
            objective="keep improving",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.9),),
        )
        evaluations = Critic().evaluate(
            goal,
            state={},
            event_log=[],
            results={"step": NodeResult(metrics={"response_quality_score": 0.4})},
        )

        decision = Verifier().verify(goal, evaluations)

        assert decision is not None
        assert decision.disposition == VerificationDisposition.REFINE

    def test_fail_when_terminal_criterion_fails(self):
        goal = GoalSpec(
            objective="must populate final answer",
            success_criteria=(
                SuccessCriterion(
                    type="state_value",
                    metadata={"key": "final_answer", "terminal_on_failure": True},
                ),
            ),
        )
        evaluations = Critic().evaluate(
            goal,
            state={},
            event_log=[],
            results={"step": NodeResult(state_patch={"draft": "missing final"})},
        )

        decision = Verifier().verify(goal, evaluations)

        assert decision is not None
        assert decision.disposition == VerificationDisposition.FAIL

    def test_verify_raises_on_length_mismatch(self):
        goal = GoalSpec(
            objective="mismatch",
            success_criteria=(
                SuccessCriterion(type="response_quality", threshold=0.9),
                SuccessCriterion(type="safety", threshold=0.9),
            ),
        )

        with pytest.raises(ValueError):
            Verifier().verify(goal, Critic().evaluate(
                GoalSpec(
                    objective="partial",
                    success_criteria=(SuccessCriterion(type="response_quality", threshold=0.9),),
                ),
                state={},
                event_log=[],
                results={"step": NodeResult(metrics={"response_quality_score": 0.95})},
            ))
