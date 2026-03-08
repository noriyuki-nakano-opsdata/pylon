from __future__ import annotations

import pytest

from pylon.autonomy.termination import (
    AllTermination,
    AnyTermination,
    CostBudget,
    ExternalStop,
    MaxIterations,
    QualityThreshold,
    StuckDetector,
    TerminationState,
    Timeout,
    TokenBudget,
    describe_termination_condition,
)
from pylon.providers.base import TokenUsage
from pylon.types import RunStopReason


def test_max_iterations_matches_when_limit_reached() -> None:
    condition = MaxIterations(3)
    decision = condition.evaluate(TerminationState(iterations=3))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.LIMIT_EXCEEDED


def test_timeout_matches_when_elapsed_reaches_limit() -> None:
    condition = Timeout(2.5)
    decision = condition.evaluate(TerminationState(elapsed_seconds=2.5))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.TIMEOUT_EXCEEDED


def test_token_budget_matches_total_tokens() -> None:
    condition = TokenBudget(max_total_tokens=12)
    decision = condition.evaluate(
        TerminationState(token_usage=TokenUsage(input_tokens=7, output_tokens=5))
    )

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.TOKEN_BUDGET_EXCEEDED


def test_token_budget_matches_prompt_tokens() -> None:
    decision = TokenBudget(max_prompt_tokens=7).evaluate(
        TerminationState(token_usage=TokenUsage(input_tokens=7, output_tokens=1))
    )

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.TOKEN_BUDGET_EXCEEDED


def test_token_budget_matches_completion_tokens() -> None:
    decision = TokenBudget(max_completion_tokens=5).evaluate(
        TerminationState(token_usage=TokenUsage(input_tokens=1, output_tokens=5))
    )

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.TOKEN_BUDGET_EXCEEDED


def test_cost_budget_matches_estimated_cost() -> None:
    condition = CostBudget(max_usd=0.25)
    decision = condition.evaluate(TerminationState(estimated_cost_usd=0.25))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.COST_BUDGET_EXCEEDED


def test_external_stop_matches_requested_flag() -> None:
    decision = ExternalStop().evaluate(TerminationState(external_stop_requested=True))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.EXTERNAL_STOP


def test_any_composition_matches_if_one_condition_matches() -> None:
    condition = MaxIterations(10) | Timeout(1.0)
    decision = condition.evaluate(TerminationState(iterations=3, elapsed_seconds=1.5))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.TIMEOUT_EXCEEDED


def test_all_composition_requires_all_conditions() -> None:
    condition = MaxIterations(3) & TokenBudget(max_total_tokens=20)
    matched = condition.evaluate(
        TerminationState(
            iterations=3,
            token_usage=TokenUsage(input_tokens=10, output_tokens=10),
        )
    )
    not_matched = condition.evaluate(
        TerminationState(
            iterations=3,
            token_usage=TokenUsage(input_tokens=5, output_tokens=5),
        )
    )

    assert matched.matched is True
    assert matched.stop_reason == RunStopReason.LIMIT_EXCEEDED
    assert not_matched.matched is False


def test_quality_threshold_completes_when_score_reached() -> None:
    decision = QualityThreshold(0.8).evaluate(TerminationState(quality_score=0.9))

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.QUALITY_REACHED


def test_stuck_detector_matches_repeated_step_signature() -> None:
    decision = StuckDetector(window=3).evaluate(
        TerminationState(
            recent_step_signatures=(
                "hash|draft|draft",
                "hash|draft|draft",
                "hash|draft|draft",
            )
        )
    )

    assert decision.matched is True
    assert decision.stop_reason == RunStopReason.STUCK_DETECTED


def test_invalid_iteration_and_timeout_values_raise() -> None:
    with pytest.raises(ValueError):
        MaxIterations(0)
    with pytest.raises(ValueError):
        Timeout(0)


def test_stuck_detector_validates_window_on_construction() -> None:
    with pytest.raises(ValueError):
        StuckDetector(window=1)


def test_empty_compositions_raise() -> None:
    with pytest.raises(ValueError):
        AnyTermination(())
    with pytest.raises(ValueError):
        AllTermination(())


def test_describe_termination_condition_handles_all_supported_variants() -> None:
    condition = (
        MaxIterations(3)
        & TokenBudget(max_total_tokens=10)
        | Timeout(5)
        | CostBudget(1.0)
        | ExternalStop()
        | QualityThreshold(0.8)
        | StuckDetector(window=3)
    )

    description = describe_termination_condition(condition)

    assert description is not None
    assert description["kind"] == "any"
