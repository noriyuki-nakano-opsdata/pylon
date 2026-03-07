from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .committer import CommitPlan, FileContent, GitCommitter
from .planner import Plan, TaskPlanner
from .reviewer import CodeChange, CodeReviewer, ReviewResult


class LoopState(enum.Enum):
    IDLE = "idle"
    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMMITTING = "committing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid state transitions: source -> set of allowed targets
_TRANSITIONS: dict[LoopState, set[LoopState]] = {
    LoopState.IDLE: {LoopState.PLANNING, LoopState.FAILED},
    LoopState.PLANNING: {LoopState.CODING, LoopState.FAILED},
    LoopState.CODING: {
        LoopState.TESTING,
        LoopState.REVIEWING,
        LoopState.COMPLETED,
        LoopState.FAILED,
    },
    LoopState.TESTING: {
        LoopState.REVIEWING,
        LoopState.CODING,
        LoopState.COMPLETED,
        LoopState.FAILED,
    },
    LoopState.REVIEWING: {
        LoopState.COMMITTING,
        LoopState.CODING,
        LoopState.AWAITING_APPROVAL,
        LoopState.COMPLETED,
        LoopState.FAILED,
    },
    LoopState.AWAITING_APPROVAL: {
        LoopState.COMMITTING,
        LoopState.CODING,
        LoopState.FAILED,
    },
    LoopState.COMMITTING: {LoopState.COMPLETED, LoopState.FAILED},
    LoopState.COMPLETED: set(),
    LoopState.FAILED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


@dataclass
class CodingLoopConfig:
    max_iterations: int = 10
    auto_commit: bool = False
    require_review: bool = True
    require_tests: bool = True


@dataclass
class LoopResult:
    status: LoopState
    plan: Plan | None = None
    code_changes: list[dict[str, Any]] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    review_comments: list[str] = field(default_factory=list)
    iterations: int = 0


# Callback type aliases
StateChangeCallback = Callable[[LoopState, LoopState], Awaitable[None]]
IterationCallback = Callable[[int, LoopState], Awaitable[None]]

# Handler type aliases
CodeHandler = Callable[[Plan], Awaitable[list[dict[str, Any]]]]
TestHandler = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]
ApprovalHandler = Callable[[ReviewResult], Awaitable[bool]]


class CodingLoop:
    """Core coding loop state machine: Plan -> Code -> Test -> Review -> Commit."""

    def __init__(
        self,
        *,
        config: CodingLoopConfig | None = None,
        planner: TaskPlanner | None = None,
        reviewer: CodeReviewer | None = None,
        committer: GitCommitter | None = None,
        code_handler: CodeHandler | None = None,
        test_handler: TestHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
        on_state_change: StateChangeCallback | None = None,
        on_iteration_complete: IterationCallback | None = None,
    ) -> None:
        self.config = config or CodingLoopConfig()
        self.planner = planner or TaskPlanner()
        self.reviewer = reviewer or CodeReviewer()
        self.committer = committer or GitCommitter()

        self._code_handler = code_handler
        self._test_handler = test_handler
        self._approval_handler = approval_handler
        self._on_state_change = on_state_change
        self._on_iteration_complete = on_iteration_complete

        self._state = LoopState.IDLE

    @property
    def state(self) -> LoopState:
        return self._state

    async def _transition(self, target: LoopState) -> None:
        if target not in _TRANSITIONS.get(self._state, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {target.value}"
            )
        old = self._state
        self._state = target
        if self._on_state_change is not None:
            await self._on_state_change(old, target)

    # ---- Individual phase methods ------------------------------------

    async def plan(self, task: str) -> Plan:
        await self._transition(LoopState.PLANNING)
        return await self.planner.plan(task)

    async def code(self, plan: Plan) -> list[dict[str, Any]]:
        await self._transition(LoopState.CODING)
        if self._code_handler is None:
            return []
        return await self._code_handler(plan)

    async def test(self, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        await self._transition(LoopState.TESTING)
        if self._test_handler is None:
            return [{"status": "skipped"}]
        return await self._test_handler(changes)

    async def review(self, changes: list[dict[str, Any]]) -> ReviewResult:
        await self._transition(LoopState.REVIEWING)
        code_changes = [
            CodeChange(
                file_path=c.get("file_path", "unknown"),
                content=c.get("content", ""),
                line_count=c.get("line_count", 0),
                has_tests=c.get("has_tests", False),
            )
            for c in changes
        ]
        return await self.reviewer.review(code_changes)

    async def commit(self, changes: list[dict[str, Any]], message: str) -> CommitPlan:
        await self._transition(LoopState.COMMITTING)
        file_contents = [
            FileContent(
                path=c.get("file_path", "unknown"),
                content=c.get("content", ""),
            )
            for c in changes
        ]
        plan = await self.committer.prepare_commit(file_contents, message)
        valid, issues = await self.committer.validate_commit(plan, file_contents)
        if not valid:
            await self._transition(LoopState.FAILED)
            raise ValueError(f"Commit validation failed: {'; '.join(issues)}")
        return plan

    # ---- Full loop execution -----------------------------------------

    async def run(self, task: str) -> LoopResult:
        result = LoopResult(status=LoopState.IDLE)

        try:
            # Plan
            plan = await self.plan(task)
            result.plan = plan

            for iteration in range(1, self.config.max_iterations + 1):
                result.iterations = iteration

                # Code
                code_changes = await self.code(plan)
                result.code_changes = code_changes

                # Test (optional)
                if self.config.require_tests:
                    test_results = await self.test(code_changes)
                    result.test_results = test_results

                    all_passed = all(
                        r.get("status") in ("passed", "skipped") for r in test_results
                    )
                    if not all_passed:
                        if self._on_iteration_complete:
                            await self._on_iteration_complete(iteration, self._state)
                        # Retry from coding
                        continue

                # Review (optional)
                if self.config.require_review:
                    review_result = await self.review(code_changes)
                    result.review_comments = [c.message for c in review_result.comments]

                    if not review_result.approved:
                        if self._on_iteration_complete:
                            await self._on_iteration_complete(iteration, self._state)
                        # Retry from coding
                        continue

                    # Approval gate
                    if self._approval_handler is not None:
                        await self._transition(LoopState.AWAITING_APPROVAL)
                        approved = await self._approval_handler(review_result)
                        if not approved:
                            if self._on_iteration_complete:
                                await self._on_iteration_complete(iteration, self._state)
                            continue

                # Commit
                if self.config.auto_commit:
                    await self.commit(code_changes, f"feat: {task}")
                    await self._transition(LoopState.COMPLETED)
                else:
                    await self._transition(LoopState.COMPLETED)

                result.status = self._state
                if self._on_iteration_complete:
                    await self._on_iteration_complete(iteration, self._state)
                return result

            # Exhausted iterations
            await self._fail()
            result.status = LoopState.FAILED
            return result

        except InvalidTransitionError:
            raise
        except Exception:
            try:
                await self._fail()
            except InvalidTransitionError:
                self._state = LoopState.FAILED
            result.status = LoopState.FAILED
            return result

    async def _fail(self) -> None:
        if self._state in (LoopState.COMPLETED, LoopState.FAILED):
            return
        await self._transition(LoopState.FAILED)
