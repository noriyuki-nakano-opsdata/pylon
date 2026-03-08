"""Tests for context projection by autonomy level."""

from pylon.runtime.context import project_context
from pylon.types import AutonomyLevel


def _full_context() -> dict:
    return {
        "input": "do something",
        "task": "build feature",
        "node_id": "node-1",
        "memory": {"key": "value"},
        "history": [{"step": i} for i in range(10)],
        "sibling_results": {"node-0": "ok"},
        "goal": "ship it",
    }


class TestProjectContext:
    def test_a0_strips_non_essential_keys(self) -> None:
        result = project_context(_full_context(), AutonomyLevel.A0)
        assert set(result.keys()) == {"input", "task", "node_id"}
        assert result["input"] == "do something"

    def test_a1_same_as_a0(self) -> None:
        result = project_context(_full_context(), AutonomyLevel.A1)
        assert set(result.keys()) == {"input", "task", "node_id"}

    def test_a2_includes_memory_and_trimmed_history(self) -> None:
        result = project_context(_full_context(), AutonomyLevel.A2)
        assert "memory" in result
        assert "history" in result
        assert len(result["history"]) == 5
        assert result["history"][0] == {"step": 5}
        assert "sibling_results" not in result

    def test_a3_returns_full_context(self) -> None:
        ctx = _full_context()
        result = project_context(ctx, AutonomyLevel.A3)
        assert result is ctx

    def test_a4_returns_full_context(self) -> None:
        ctx = _full_context()
        result = project_context(ctx, AutonomyLevel.A4)
        assert result is ctx

    def test_missing_keys_no_error(self) -> None:
        result = project_context({}, AutonomyLevel.A0)
        assert result == {}

        result = project_context({"input": "x"}, AutonomyLevel.A2)
        assert result == {"input": "x"}

    def test_a2_short_history_not_truncated(self) -> None:
        ctx = {"history": [{"step": 0}, {"step": 1}]}
        result = project_context(ctx, AutonomyLevel.A2)
        assert len(result["history"]) == 2
