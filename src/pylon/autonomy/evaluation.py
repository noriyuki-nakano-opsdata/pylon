"""Evaluation-native runtime helpers."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.goals import GoalSpec, SuccessCriterion


class EvaluationKind(enum.StrEnum):
    RESPONSE_QUALITY = "response_quality"
    TOOL_TRAJECTORY = "tool_trajectory"
    HALLUCINATION = "hallucination"
    SAFETY = "safety"
    STATE_VALUE = "state_value"


@dataclass(frozen=True)
class EvaluationResult:
    """Single criterion evaluation outcome."""

    kind: EvaluationKind
    score: float
    passed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "score": self.score,
            "passed": self.passed,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


class VerificationDisposition(enum.StrEnum):
    SUCCESS = "success"
    REFINE = "refine"
    FAIL = "fail"


@dataclass(frozen=True)
class VerificationDecision:
    """Aggregated decision from a set of evaluation results."""

    disposition: VerificationDisposition
    reason: str
    results: tuple[EvaluationResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "reason": self.reason,
            "results": [result.to_dict() for result in self.results],
        }


class Critic:
    """Evaluates a goal's success criteria against runtime outputs."""

    def evaluate(
        self,
        goal: GoalSpec,
        *,
        state: dict[str, Any],
        event_log: list[dict[str, Any]],
        results: dict[str, Any],
    ) -> tuple[EvaluationResult, ...]:
        evaluations: list[EvaluationResult] = []
        for criterion in goal.success_criteria:
            try:
                kind = EvaluationKind(criterion.type)
            except ValueError:
                evaluations.append(
                    EvaluationResult(
                        kind=EvaluationKind.STATE_VALUE,
                        score=0.0,
                        passed=False,
                        reason=f"unsupported criterion type: {criterion.type}",
                    )
                )
                continue
            evaluations.append(
                self._evaluate_criterion(
                    criterion,
                    kind=kind,
                    state=state,
                    event_log=event_log,
                    results=results,
                )
            )
        return tuple(evaluations)

    def _evaluate_criterion(
        self,
        criterion: SuccessCriterion,
        *,
        kind: EvaluationKind,
        state: dict[str, Any],
        event_log: list[dict[str, Any]],
        results: dict[str, Any],
    ) -> EvaluationResult:
        threshold = criterion.threshold if criterion.threshold is not None else 1.0

        if kind == EvaluationKind.RESPONSE_QUALITY:
            score = _latest_metric_score(event_log, results, "response_quality_score")
            return _score_result(kind, score, threshold, "response quality")

        if kind == EvaluationKind.HALLUCINATION:
            score = _latest_metric_score(event_log, results, "hallucination_score")
            return _score_result(kind, score, threshold, "hallucination")

        if kind == EvaluationKind.SAFETY:
            score = _latest_metric_score(event_log, results, "safety_score")
            return _score_result(kind, score, threshold, "safety")

        if kind == EvaluationKind.TOOL_TRAJECTORY:
            expected = tuple(criterion.metadata.get("expected", ()))
            match_type = str(criterion.metadata.get("match", "exact"))
            observed = _observed_tool_names(event_log, results)
            passed = _match_tool_trajectory(expected, observed, match_type)
            score = 1.0 if passed else 0.0
            return EvaluationResult(
                kind=kind,
                score=score,
                passed=passed,
                reason=f"tool trajectory {match_type} match",
                metadata={"expected": list(expected), "observed": observed, "match": match_type},
            )

        if kind == EvaluationKind.STATE_VALUE:
            key = str(criterion.metadata.get("key", ""))
            if key == "":
                return EvaluationResult(
                    kind=kind,
                    score=0.0,
                    passed=False,
                    reason="state_value criterion missing 'key'",
                )
            expected = criterion.metadata.get("expected", _MISSING)
            if expected is _MISSING:
                passed = key in state
            else:
                passed = state.get(key) == expected
            return EvaluationResult(
                kind=kind,
                score=1.0 if passed else 0.0,
                passed=passed,
                reason=f"state value check for '{key}'",
                metadata={"key": key, "expected": None if expected is _MISSING else expected},
            )

        raise ValueError(f"Unsupported evaluation kind: {kind.value}")


class Verifier:
    """Converts evaluation results into an execution decision."""

    def verify(
        self,
        goal: GoalSpec,
        evaluations: tuple[EvaluationResult, ...],
    ) -> VerificationDecision | None:
        if not evaluations:
            return VerificationDecision(
                disposition=VerificationDisposition.SUCCESS,
                reason="no success criteria defined",
                results=(),
            )
        if len(evaluations) != len(goal.success_criteria):
            raise ValueError("Verification criteria and evaluations length mismatch")

        all_passed = all(result.passed for result in evaluations)
        if all_passed:
            return VerificationDecision(
                disposition=VerificationDisposition.SUCCESS,
                reason="all success criteria satisfied",
                results=evaluations,
            )

        for criterion, result in zip(goal.success_criteria, evaluations, strict=True):
            if not result.passed and criterion.metadata.get("terminal_on_failure"):
                return VerificationDecision(
                    disposition=VerificationDisposition.FAIL,
                    reason=f"terminal criterion failed: {criterion.type}",
                    results=evaluations,
                )

        return VerificationDecision(
            disposition=VerificationDisposition.REFINE,
            reason="one or more success criteria not yet satisfied",
            results=evaluations,
        )


def _score_result(
    kind: EvaluationKind,
    score: float,
    threshold: float,
    label: str,
) -> EvaluationResult:
    passed = score >= threshold
    return EvaluationResult(
        kind=kind,
        score=score,
        passed=passed,
        reason=f"{label} score {score:.3f} against threshold {threshold:.3f}",
    )


def _latest_metric_score(
    event_log: list[dict[str, Any]],
    results: dict[str, Any],
    metric_name: str,
) -> float:
    for node_id in reversed(list(results.keys())):
        metrics = _result_attr(results[node_id], "metrics", {})
        if metric_name in metrics:
            return float(metrics[metric_name])
    for event in reversed(event_log):
        metrics = event.get("metrics", {})
        if isinstance(metrics, dict) and metric_name in metrics:
            return float(metrics[metric_name])
    return 0.0


def _observed_tool_names(event_log: list[dict[str, Any]], results: dict[str, Any]) -> list[str]:
    observed: list[str] = []
    for event in event_log:
        for tool_event in event.get("tool_events", []):
            tool_name = tool_event.get("tool")
            if isinstance(tool_name, str):
                observed.append(tool_name)
    for result in results.values():
        for tool_event in _result_attr(result, "tool_events", []):
            tool_name = tool_event.get("tool")
            if isinstance(tool_name, str):
                observed.append(tool_name)
    return observed


def _result_attr(result: Any, field_name: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(field_name, default)
    return getattr(result, field_name, default)


def _match_tool_trajectory(
    expected: tuple[str, ...],
    observed: list[str],
    match_type: str,
) -> bool:
    if not expected:
        return True
    if match_type == "exact":
        return list(expected) == observed
    if match_type == "in_order":
        idx = 0
        for tool_name in observed:
            if idx < len(expected) and tool_name == expected[idx]:
                idx += 1
        return idx == len(expected)
    if match_type == "any_order":
        return all(tool in observed for tool in expected)
    return False


_MISSING = object()
