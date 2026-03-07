"""Tests for workflow graph executor."""

import pytest

from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.workflow import RunStatus, WorkflowRun
from pylon.types import ConditionalEdge
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph


async def mock_handler(node_id: str, state: dict) -> dict:
    """Simple mock handler that returns node-specific state."""
    if node_id == "analyze":
        return {"issues_found": 3, "analyzed": True}
    elif node_id == "review":
        return {"reviewed": True, "comments": 5}
    elif node_id == "approve":
        return {"approved": True}
    elif node_id == "worker1":
        return {"worker1_done": True}
    elif node_id == "worker2":
        return {"worker2_done": True}
    return {f"{node_id}_done": True}


class TestGraphExecutor:
    @pytest.fixture
    def executor(self):
        return GraphExecutor()

    @pytest.mark.asyncio
    async def test_linear_execution(self, executor):
        g = WorkflowGraph(name="linear")
        g.add_node("analyze", "planner", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("analyzed") is True
        assert len(result.event_log) == 1

    @pytest.mark.asyncio
    async def test_multi_step_execution(self, executor):
        g = WorkflowGraph(name="multi")
        g.add_node("analyze", "planner", next_nodes=[ConditionalEdge(target="review")])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("analyzed") is True
        assert result.state.get("reviewed") is True
        assert len(result.event_log) == 2

    @pytest.mark.asyncio
    async def test_conditional_branching(self, executor):
        g = WorkflowGraph(name="conditional")
        g.add_node("analyze", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="state.issues_found > 0"),
            ConditionalEdge(target=END, condition="state.issues_found == 0"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        # mock_handler returns issues_found=3, so review should execute
        assert result.state.get("reviewed") is True
        assert len(result.event_log) == 2

    @pytest.mark.asyncio
    async def test_fan_out(self, executor):
        g = WorkflowGraph(name="fanout")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="worker1"),
            ConditionalEdge(target="worker2"),
        ])
        g.add_node("worker1", "agent1", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("worker2", "agent2", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")

        async def fanout_handler(node_id: str, state: dict) -> dict:
            return {f"{node_id}_done": True}

        result = await executor.execute(g, run, fanout_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("worker1_done") is True
        assert result.state.get("worker2_done") is True

    @pytest.mark.asyncio
    async def test_checkpoints_created(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="cp-test")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        await executor.execute(g, run, mock_handler)

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert len(checkpoints) == 2  # One per superstep

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, executor):
        """Verify max_steps prevents infinite loops and marks run as FAILED."""
        g = WorkflowGraph(name="limited")
        # Create a long chain
        for i in range(10):
            next_target = f"step{i+1}" if i < 9 else END
            g.add_node(f"step{i}", "agent", next_nodes=[ConditionalEdge(target=next_target)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler, max_steps=5)

        # Should stop after 5 steps even though graph has 10
        assert len(result.event_log) == 5
        # Run should be FAILED, not COMPLETED, since work remains
        assert result.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_handler_error_fails_run(self, executor):
        g = WorkflowGraph(name="error")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def failing_handler(node_id: str, state: dict) -> dict:
            raise RuntimeError("handler failed")

        run = WorkflowRun(workflow_id="wf-1")
        with pytest.raises(Exception):
            await executor.execute(g, run, failing_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_replay(self, executor):
        """Replay should reconstruct state from event log."""
        g = WorkflowGraph(name="replay")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        run.event_log = [
            {"step": 1, "node_id": "step1", "agent": "agent", "output": {"key": "value"}},
        ]

        replayed = await executor.replay(g, run, mock_handler)
        assert replayed.state.get("key") == "value"

    @pytest.mark.asyncio
    async def test_condition_error_propagates(self, executor):
        """Condition evaluation errors must raise, not be silently swallowed."""
        from pylon.errors import WorkflowError

        g = WorkflowGraph(name="bad-cond")
        g.add_node("step1", "agent", next_nodes=[
            ConditionalEdge(target="step2", condition="state.nonexistent_attr.foo"),
        ])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        with pytest.raises(WorkflowError, match="Condition evaluation failed"):
            await executor.execute(g, run, mock_handler)
