"""Composable termination policies for bounded autonomous execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pylon.providers.base import TokenUsage
from pylon.types import RunStatus, RunStopReason


@dataclass(frozen=True)
class TerminationState:
    """Observed runtime state used to evaluate termination policies."""

    iterations: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    external_stop_requested: bool = False
    quality_score: float | None = None
    recent_step_signatures: tuple[str, ...] = ()


@dataclass(frozen=True)
class TerminationDecision:
    """Result of evaluating a termination condition."""

    matched: bool
    reason: str = ""
    stop_reason: RunStopReason = RunStopReason.NONE
    target_status: RunStatus = RunStatus.PAUSED


class TerminationCondition(Protocol):
    """Protocol implemented by all termination conditions."""

    def evaluate(self, state: TerminationState) -> TerminationDecision: ...

    def __or__(self, other: TerminationCondition) -> TerminationCondition: ...

    def __and__(self, other: TerminationCondition) -> TerminationCondition: ...


class BaseTermination:
    """Common composition helpers for termination conditions."""

    def __or__(self, other: TerminationCondition) -> TerminationCondition:
        return AnyTermination((self, other))

    def __and__(self, other: TerminationCondition) -> TerminationCondition:
        return AllTermination((self, other))


def describe_termination_condition(
    condition: TerminationCondition | None,
) -> dict[str, object] | None:
    """Return a stable, inspectable representation of a termination condition tree."""
    if condition is None:
        return None
    if isinstance(condition, MaxIterations):
        return {"kind": "max_iterations", "max_iterations": condition.max_iterations}
    if isinstance(condition, Timeout):
        return {"kind": "timeout", "seconds": condition.seconds}
    if isinstance(condition, TokenBudget):
        return {
            "kind": "token_budget",
            "max_total_tokens": condition.max_total_tokens,
            "max_prompt_tokens": condition.max_prompt_tokens,
            "max_completion_tokens": condition.max_completion_tokens,
        }
    if isinstance(condition, CostBudget):
        return {"kind": "cost_budget", "max_usd": condition.max_usd}
    if isinstance(condition, ExternalStop):
        return {"kind": "external_stop"}
    if isinstance(condition, QualityThreshold):
        return {"kind": "quality_threshold", "min_score": condition.min_score}
    if isinstance(condition, StuckDetector):
        return {"kind": "stuck_detector", "window": condition.window}
    if isinstance(condition, AnyTermination):
        return {
            "kind": "any",
            "conditions": [
                describe_termination_condition(child) for child in condition.conditions
            ],
        }
    if isinstance(condition, AllTermination):
        return {
            "kind": "all",
            "conditions": [
                describe_termination_condition(child) for child in condition.conditions
            ],
        }
    return {"kind": condition.__class__.__name__.lower()}


@dataclass(frozen=True)
class MaxIterations(BaseTermination):
    """Stop after the configured number of iterations has been consumed."""

    max_iterations: int

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("MaxIterations must be greater than 0")

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        if state.iterations >= self.max_iterations:
            return TerminationDecision(
                matched=True,
                reason=f"Iteration limit exceeded: {state.iterations} >= {self.max_iterations}",
                stop_reason=RunStopReason.LIMIT_EXCEEDED,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class Timeout(BaseTermination):
    """Stop after the configured elapsed time has been consumed."""

    seconds: float

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("Timeout must be greater than 0")

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        if state.elapsed_seconds >= self.seconds:
            return TerminationDecision(
                matched=True,
                reason=f"Timeout exceeded: {state.elapsed_seconds:.3f}s >= {self.seconds:.3f}s",
                stop_reason=RunStopReason.TIMEOUT_EXCEEDED,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class TokenBudget(BaseTermination):
    """Stop when token usage exceeds the configured budget."""

    max_total_tokens: int | None = None
    max_prompt_tokens: int | None = None
    max_completion_tokens: int | None = None

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        usage = state.token_usage
        if self.max_total_tokens is not None and usage.total_tokens >= self.max_total_tokens:
            return TerminationDecision(
                matched=True,
                reason=(
                    "Token budget exceeded: "
                    f"{usage.total_tokens} >= {self.max_total_tokens}"
                ),
                stop_reason=RunStopReason.TOKEN_BUDGET_EXCEEDED,
            )
        if self.max_prompt_tokens is not None and usage.input_tokens >= self.max_prompt_tokens:
            return TerminationDecision(
                matched=True,
                reason=(
                    "Prompt token budget exceeded: "
                    f"{usage.input_tokens} >= {self.max_prompt_tokens}"
                ),
                stop_reason=RunStopReason.TOKEN_BUDGET_EXCEEDED,
            )
        if (
            self.max_completion_tokens is not None
            and usage.output_tokens >= self.max_completion_tokens
        ):
            return TerminationDecision(
                matched=True,
                reason=(
                    "Completion token budget exceeded: "
                    f"{usage.output_tokens} >= {self.max_completion_tokens}"
                ),
                stop_reason=RunStopReason.TOKEN_BUDGET_EXCEEDED,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class CostBudget(BaseTermination):
    """Stop when estimated cost exceeds the configured budget."""

    max_usd: float

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        if state.estimated_cost_usd >= self.max_usd:
            return TerminationDecision(
                matched=True,
                reason=(
                    "Cost budget exceeded: "
                    f"${state.estimated_cost_usd:.4f} >= ${self.max_usd:.4f}"
                ),
                stop_reason=RunStopReason.COST_BUDGET_EXCEEDED,
            )
        return TerminationDecision(matched=False)


class ExternalStop(BaseTermination):
    """Stop when a cooperative external stop has been requested."""

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        if state.external_stop_requested:
            return TerminationDecision(
                matched=True,
                reason="External stop requested",
                stop_reason=RunStopReason.EXTERNAL_STOP,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class QualityThreshold(BaseTermination):
    """Complete when the observed quality score reaches the target threshold."""

    min_score: float

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        if state.quality_score is None:
            return TerminationDecision(matched=False)
        if state.quality_score >= self.min_score:
            return TerminationDecision(
                matched=True,
                reason=(
                    "Quality threshold reached: "
                    f"{state.quality_score:.3f} >= {self.min_score:.3f}"
                ),
                stop_reason=RunStopReason.QUALITY_REACHED,
                target_status=RunStatus.COMPLETED,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class StuckDetector(BaseTermination):
    """Pause when recent step signatures show no progress."""

    window: int = 3

    def __post_init__(self) -> None:
        if self.window <= 1:
            raise ValueError("StuckDetector window must be greater than 1")

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        signatures = state.recent_step_signatures
        if len(signatures) < self.window:
            return TerminationDecision(matched=False)
        recent = signatures[-self.window :]
        if len(set(recent)) == 1:
            return TerminationDecision(
                matched=True,
                reason=f"Stuck detected across {self.window} identical step signatures",
                stop_reason=RunStopReason.STUCK_DETECTED,
                target_status=RunStatus.PAUSED,
            )
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class AnyTermination(BaseTermination):
    """Match when any child condition matches."""

    conditions: tuple[TerminationCondition, ...]

    def __init__(self, conditions: tuple[TerminationCondition, ...]) -> None:
        flattened = _flatten_any(conditions)
        if not flattened:
            raise ValueError("AnyTermination requires at least one condition")
        object.__setattr__(self, "conditions", flattened)

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        for condition in self.conditions:
            decision = condition.evaluate(state)
            if decision.matched:
                return decision
        return TerminationDecision(matched=False)


@dataclass(frozen=True)
class AllTermination(BaseTermination):
    """Match only when all child conditions match."""

    conditions: tuple[TerminationCondition, ...]

    def __init__(self, conditions: tuple[TerminationCondition, ...]) -> None:
        flattened = _flatten_all(conditions)
        if not flattened:
            raise ValueError("AllTermination requires at least one condition")
        object.__setattr__(self, "conditions", flattened)

    def evaluate(self, state: TerminationState) -> TerminationDecision:
        decisions = [condition.evaluate(state) for condition in self.conditions]
        if not decisions or not all(decision.matched for decision in decisions):
            return TerminationDecision(matched=False)
        reasons = [decision.reason for decision in decisions if decision.reason]
        # Pick the most severe target status: FAILED > PAUSED > COMPLETED
        status_priority = {
            RunStatus.FAILED: 0,
            RunStatus.PAUSED: 1,
            RunStatus.COMPLETED: 2,
        }
        most_severe = min(
            decisions,
            key=lambda d: status_priority.get(d.target_status, 1),
        )
        return TerminationDecision(
            matched=True,
            reason="; ".join(reasons),
            stop_reason=most_severe.stop_reason,
            target_status=most_severe.target_status,
        )


def _flatten_any(
    conditions: tuple[TerminationCondition, ...],
) -> tuple[TerminationCondition, ...]:
    flattened: list[TerminationCondition] = []
    for condition in conditions:
        if isinstance(condition, AnyTermination):
            flattened.extend(condition.conditions)
        else:
            flattened.append(condition)
    return tuple(flattened)


def _flatten_all(
    conditions: tuple[TerminationCondition, ...],
) -> tuple[TerminationCondition, ...]:
    flattened: list[TerminationCondition] = []
    for condition in conditions:
        if isinstance(condition, AllTermination):
            flattened.extend(condition.conditions)
        else:
            flattened.append(condition)
    return tuple(flattened)
