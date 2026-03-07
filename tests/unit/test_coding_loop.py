from __future__ import annotations

import pytest

from pylon.coding.committer import (
    CommitPlan,
    FileContent,
    GitCommitter,
)
from pylon.coding.loop import (
    CodingLoop,
    CodingLoopConfig,
    InvalidTransitionError,
    LoopResult,
    LoopState,
)
from pylon.coding.planner import (
    CodingComplexity,
    FileAction,
    Plan,
    PlanStep,
    TaskPlanner,
)
from pylon.coding.reviewer import (
    CodeChange,
    CodeReviewer,
    QualityGateConfig,
    ReviewResult,
    Severity,
)

# ======================================================================
# Helpers
# ======================================================================


def _make_plan(steps: int = 1) -> Plan:
    return Plan(
        steps=[
            PlanStep(f"step {i}", f"file_{i}.py", FileAction.MODIFY)
            for i in range(steps)
        ],
        estimated_files=[f"file_{i}.py" for i in range(steps)],
        estimated_complexity=CodingComplexity.LOW,
    )


def _make_changes(*, has_tests: bool = True, line_count: int = 50) -> list[dict]:
    return [
        {
            "file_path": "src/app.py",
            "content": "x = 1\n" * line_count,
            "line_count": line_count,
            "has_tests": has_tests,
        }
    ]


async def _noop_state_change(old: LoopState, new: LoopState) -> None:
    pass


async def _noop_iter(iteration: int, state: LoopState) -> None:
    pass


# ======================================================================
# 1-5: State machine transitions
# ======================================================================


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_idle_to_planning(self) -> None:
        loop = CodingLoop()
        assert loop.state == LoopState.IDLE
        await loop.plan("do something")
        assert loop.state == LoopState.PLANNING

    @pytest.mark.asyncio
    async def test_planning_to_coding(self) -> None:
        loop = CodingLoop()
        plan = await loop.plan("task")
        await loop.code(plan)
        assert loop.state == LoopState.CODING

    @pytest.mark.asyncio
    async def test_coding_to_testing(self) -> None:
        loop = CodingLoop()
        plan = await loop.plan("task")
        changes = await loop.code(plan)
        await loop.test(changes)
        assert loop.state == LoopState.TESTING

    @pytest.mark.asyncio
    async def test_invalid_idle_to_committing(self) -> None:
        loop = CodingLoop()
        with pytest.raises(InvalidTransitionError):
            await loop.commit([], "msg")

    @pytest.mark.asyncio
    async def test_invalid_idle_to_reviewing(self) -> None:
        loop = CodingLoop()
        with pytest.raises(InvalidTransitionError):
            await loop.review([])

    @pytest.mark.asyncio
    async def test_completed_is_terminal(self) -> None:
        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
        )
        result = await loop.run("task")
        assert result.status == LoopState.COMPLETED
        with pytest.raises(InvalidTransitionError):
            await loop.plan("another")


# ======================================================================
# 6-10: Full loop execution
# ======================================================================


class TestFullLoop:
    @pytest.mark.asyncio
    async def test_simple_loop_no_review_no_tests(self) -> None:
        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes()

        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
            code_handler=code_handler,
        )
        result = await loop.run("implement feature")
        assert result.status == LoopState.COMPLETED
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_loop_with_tests_passing(self) -> None:
        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes(has_tests=True)

        async def test_handler(changes: list[dict]) -> list[dict]:
            return [{"status": "passed"}]

        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=True),
            code_handler=code_handler,
            test_handler=test_handler,
        )
        result = await loop.run("task")
        assert result.status == LoopState.COMPLETED

    @pytest.mark.asyncio
    async def test_loop_with_review_approved(self) -> None:
        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes(has_tests=True)

        async def test_handler(changes: list[dict]) -> list[dict]:
            return [{"status": "passed"}]

        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(required_tests=False),
        )
        loop = CodingLoop(
            config=CodingLoopConfig(require_review=True, require_tests=True),
            code_handler=code_handler,
            test_handler=test_handler,
            reviewer=reviewer,
        )
        result = await loop.run("task")
        assert result.status == LoopState.COMPLETED

    @pytest.mark.asyncio
    async def test_loop_auto_commit(self) -> None:
        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes(has_tests=True)

        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(required_tests=False),
        )
        loop = CodingLoop(
            config=CodingLoopConfig(
                auto_commit=True, require_review=True, require_tests=False,
            ),
            code_handler=code_handler,
            reviewer=reviewer,
        )
        result = await loop.run("task")
        assert result.status == LoopState.COMPLETED

    @pytest.mark.asyncio
    async def test_loop_result_has_plan(self) -> None:
        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
        )
        result = await loop.run("my task")
        assert result.plan is not None
        assert len(result.plan.steps) >= 1


# ======================================================================
# 11-15: Planning and task decomposition
# ======================================================================


class TestPlanner:
    @pytest.mark.asyncio
    async def test_default_plan(self) -> None:
        planner = TaskPlanner()
        plan = await planner.plan("build login page")
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "build login page"

    @pytest.mark.asyncio
    async def test_custom_planner_fn(self) -> None:
        expected = _make_plan(3)

        async def custom_fn(desc: str) -> Plan:
            return expected

        planner = TaskPlanner(planner_fn=custom_fn)
        result = await planner.plan("anything")
        assert result is expected

    @pytest.mark.asyncio
    async def test_decompose_default(self) -> None:
        planner = TaskPlanner()
        subtasks = await planner.decompose("single task")
        assert subtasks == ["single task"]

    @pytest.mark.asyncio
    async def test_decompose_custom(self) -> None:
        async def decompose_fn(task: str) -> list[str]:
            return ["sub1", "sub2", "sub3"]

        planner = TaskPlanner(decompose_fn=decompose_fn)
        result = await planner.decompose("big task")
        assert len(result) == 3

    def test_complexity_low(self) -> None:
        planner = TaskPlanner()
        assert planner.estimate_complexity("fix typo") == CodingComplexity.LOW

    def test_complexity_medium(self) -> None:
        planner = TaskPlanner()
        desc = "refactor the authentication module to support OAuth2 with multiple providers"
        assert planner.estimate_complexity(desc) == CodingComplexity.MEDIUM

    def test_complexity_high(self) -> None:
        planner = TaskPlanner()
        desc = " ".join([f"modify file_{i}.py to handle case {i}" for i in range(20)])
        assert planner.estimate_complexity(desc) == CodingComplexity.HIGH

    @pytest.mark.asyncio
    async def test_plan_empty_raises(self) -> None:
        planner = TaskPlanner()
        with pytest.raises(ValueError):
            await planner.plan("")


# ======================================================================
# 16-19: Review with quality gates
# ======================================================================


class TestReviewer:
    @pytest.mark.asyncio
    async def test_review_approved_no_issues(self) -> None:
        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(required_tests=False),
        )
        changes = [CodeChange("app.py", "code", line_count=10, has_tests=False)]
        result = await reviewer.review(changes)
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_review_rejected_missing_tests(self) -> None:
        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(required_tests=True),
        )
        changes = [CodeChange("app.py", "code", line_count=10, has_tests=False)]
        result = await reviewer.review(changes)
        assert result.approved is False
        assert result.severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_review_warning_file_size(self) -> None:
        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(max_file_size=100, required_tests=False),
        )
        changes = [CodeChange("big.py", "x\n" * 200, line_count=200, has_tests=True)]
        result = await reviewer.review(changes)
        assert result.approved is True  # warning, not error
        assert result.severity == Severity.WARNING

    @pytest.mark.asyncio
    async def test_review_custom_fn(self) -> None:
        expected = ReviewResult(approved=True, comments=[], severity=Severity.INFO)

        async def custom_review(changes: list[CodeChange]) -> ReviewResult:
            return expected

        reviewer = CodeReviewer(review_fn=custom_review)
        result = await reviewer.review([])
        assert result is expected


# ======================================================================
# 20-23: Commit validation and secret detection
# ======================================================================


class TestCommitter:
    @pytest.mark.asyncio
    async def test_prepare_commit(self) -> None:
        committer = GitCommitter()
        changes = [FileContent("src/app.py", "content")]
        plan = await committer.prepare_commit(changes, "feat: add feature")
        assert plan.message == "feat: add feature"
        assert "src/app.py" in plan.files_to_modify

    @pytest.mark.asyncio
    async def test_validate_detects_api_key(self) -> None:
        committer = GitCommitter()
        plan = CommitPlan([], ["config.py"], [], "add config")
        contents = [FileContent("config.py", 'api_key = "abcdefghij1234567890"')]
        valid, issues = await committer.validate_commit(plan, contents)
        assert valid is False
        assert any("API Key" in i for i in issues)

    @pytest.mark.asyncio
    async def test_validate_detects_private_key(self) -> None:
        committer = GitCommitter()
        plan = CommitPlan([], ["key.pem"], [], "add key")
        contents = [FileContent("key.pem", "-----BEGIN RSA PRIVATE KEY-----\ndata")]
        valid, issues = await committer.validate_commit(plan, contents)
        assert valid is False
        assert any("Private Key" in i for i in issues)

    @pytest.mark.asyncio
    async def test_validate_clean_commit(self) -> None:
        committer = GitCommitter()
        plan = CommitPlan([], ["app.py"], [], "update app")
        contents = [FileContent("app.py", "print('hello')")]
        valid, issues = await committer.validate_commit(plan, contents)
        assert valid is True
        assert issues == []

    @pytest.mark.asyncio
    async def test_validate_large_file(self) -> None:
        committer = GitCommitter(max_file_size=100)
        plan = CommitPlan([], ["big.bin"], [], "add binary")
        contents = [FileContent("big.bin", "x" * 200, size_bytes=200)]
        valid, issues = await committer.validate_commit(plan, contents)
        assert valid is False
        assert any("max size" in i for i in issues)

    @pytest.mark.asyncio
    async def test_prepare_commit_empty_message_raises(self) -> None:
        committer = GitCommitter()
        with pytest.raises(ValueError):
            await committer.prepare_commit([], "")


# ======================================================================
# 24-25: Config defaults and event hooks
# ======================================================================


class TestConfigAndHooks:
    def test_config_defaults(self) -> None:
        cfg = CodingLoopConfig()
        assert cfg.max_iterations == 10
        assert cfg.auto_commit is False
        assert cfg.require_review is True
        assert cfg.require_tests is True

    def test_config_overrides(self) -> None:
        cfg = CodingLoopConfig(max_iterations=5, auto_commit=True)
        assert cfg.max_iterations == 5
        assert cfg.auto_commit is True

    @pytest.mark.asyncio
    async def test_on_state_change_called(self) -> None:
        transitions: list[tuple[LoopState, LoopState]] = []

        async def on_change(old: LoopState, new: LoopState) -> None:
            transitions.append((old, new))

        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
            on_state_change=on_change,
        )
        await loop.run("task")
        assert len(transitions) >= 2
        assert transitions[0] == (LoopState.IDLE, LoopState.PLANNING)

    @pytest.mark.asyncio
    async def test_on_iteration_complete_called(self) -> None:
        iterations_seen: list[int] = []

        async def on_iter(iteration: int, state: LoopState) -> None:
            iterations_seen.append(iteration)

        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
            on_iteration_complete=on_iter,
        )
        await loop.run("task")
        assert 1 in iterations_seen


# ======================================================================
# 26-28: Iteration limits and error handling
# ======================================================================


class TestIterationAndErrors:
    @pytest.mark.asyncio
    async def test_max_iterations_exhausted(self) -> None:
        call_count = 0

        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes(has_tests=False)

        async def test_handler(changes: list[dict]) -> list[dict]:
            nonlocal call_count
            call_count += 1
            return [{"status": "failed"}]

        loop = CodingLoop(
            config=CodingLoopConfig(
                max_iterations=3, require_tests=True, require_review=False,
            ),
            code_handler=code_handler,
            test_handler=test_handler,
        )
        result = await loop.run("task")
        assert result.status == LoopState.FAILED
        assert result.iterations == 3

    @pytest.mark.asyncio
    async def test_code_handler_exception_fails(self) -> None:
        async def bad_code_handler(plan: Plan) -> list[dict]:
            raise RuntimeError("compile error")

        loop = CodingLoop(
            config=CodingLoopConfig(require_review=False, require_tests=False),
            code_handler=bad_code_handler,
        )
        result = await loop.run("task")
        assert result.status == LoopState.FAILED

    @pytest.mark.asyncio
    async def test_approval_handler_rejects(self) -> None:
        reject_count = 0

        async def code_handler(plan: Plan) -> list[dict]:
            return _make_changes(has_tests=True)

        async def test_handler(changes: list[dict]) -> list[dict]:
            return [{"status": "passed"}]

        async def reject_approval(review: ReviewResult) -> bool:
            nonlocal reject_count
            reject_count += 1
            return False

        reviewer = CodeReviewer(
            quality_gates=QualityGateConfig(required_tests=False),
        )
        loop = CodingLoop(
            config=CodingLoopConfig(
                max_iterations=2, require_review=True, require_tests=True,
            ),
            code_handler=code_handler,
            test_handler=test_handler,
            reviewer=reviewer,
            approval_handler=reject_approval,
        )
        result = await loop.run("task")
        assert result.status == LoopState.FAILED
        assert reject_count == 2

    @pytest.mark.asyncio
    async def test_loop_result_dataclass_fields(self) -> None:
        result = LoopResult(status=LoopState.IDLE)
        assert result.plan is None
        assert result.code_changes == []
        assert result.test_results == []
        assert result.review_comments == []
        assert result.iterations == 0


# ======================================================================
# 29-30: PlanStep and FileAction enums
# ======================================================================


class TestDataclassesAndEnums:
    def test_plan_step_frozen(self) -> None:
        step = PlanStep("desc", "file.py", FileAction.CREATE)
        with pytest.raises(AttributeError):
            step.description = "new"  # type: ignore[misc]

    def test_file_action_values(self) -> None:
        assert FileAction.CREATE.value == "create"
        assert FileAction.MODIFY.value == "modify"
        assert FileAction.DELETE.value == "delete"
