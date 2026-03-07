"""Tests for workflow graph executor."""

import pytest

from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.workflow import RunStatus, WorkflowRun
from pylon.types import ConditionalEdge, WorkflowJoinPolicy, WorkflowNodeType
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph
from pylon.workflow.result import NodeResult
from pylon.workflow.state import compute_state_hash


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
        assert result.state_version == 1
        assert result.state_hash != ""

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
        assert [cp.node_id for cp in checkpoints] == ["step1", "step2"]
        assert [cp.event_log[0]["node_id"] for cp in checkpoints] == ["step1", "step2"]
        assert all(cp.state_version > 0 for cp in checkpoints)
        assert all(cp.state_hash for cp in checkpoints)

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, executor):
        """Verify max_steps prevents infinite loops."""
        g = WorkflowGraph(name="limited")
        # Create a long chain
        for i in range(10):
            next_target = f"step{i+1}" if i < 9 else END
            g.add_node(f"step{i}", "agent", next_nodes=[ConditionalEdge(target=next_target)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler, max_steps=5)

        # Should pause after 5 steps even though graph has 10
        assert result.status == RunStatus.PAUSED
        assert len(result.event_log) == 5
        assert "pause_reason" in result.state

    @pytest.mark.asyncio
    async def test_join_node_executes_once_after_all_inbound_edges_resolve(self, executor):
        g = WorkflowGraph(name="join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="fast"),
            ConditionalEdge(target="slow"),
        ])
        g.add_node("fast", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("slow", "agent2", next_nodes=[ConditionalEdge(target="mid")])
        g.add_node("mid", "agent3", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("join", "agent4", next_nodes=[ConditionalEdge(target=END)])

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order == ["start", "fast", "slow", "mid", "join"]
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_parallel_conflicting_writes_fail(self, executor):
        g = WorkflowGraph(name="conflict")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="worker1"),
            ConditionalEdge(target="worker2"),
        ])
        g.add_node("worker1", "agent1", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("worker2", "agent2", next_nodes=[ConditionalEdge(target=END)])

        async def conflicting_handler(node_id: str, state: dict) -> dict:
            if node_id == "start":
                return {"started": True}
            return {"shared": node_id}

        run = WorkflowRun(workflow_id="wf-conflict")
        with pytest.raises(Exception, match="State conflict"):
            await executor.execute(g, run, conflicting_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_condition_fails_run(self, executor):
        g = WorkflowGraph(name="bad-condition")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="next", condition="state.missing > 0"),
        ])
        g.add_node("next", "agent1", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-bad-condition")
        with pytest.raises(Exception, match="missing"):
            await executor.execute(g, run, mock_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_any_join_router_executes_before_all_inbound_edges_resolve(self, executor):
        g = WorkflowGraph(name="any-join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="fast"),
            ConditionalEdge(target="slow"),
        ])
        g.add_node("fast", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("slow", "agent2", next_nodes=[ConditionalEdge(target="mid")])
        g.add_node("mid", "agent3", next_nodes=[ConditionalEdge(target="late")])
        g.add_node("late", "agent4", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "router",
            node_type=WorkflowNodeType.ROUTER,
            join_policy=WorkflowJoinPolicy.ANY,
            next_nodes=[ConditionalEdge(target=END)],
        )

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-any-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order.index("join") < execution_order.index("late")
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_first_join_router_selects_deterministic_winner(self, executor):
        g = WorkflowGraph(name="first-join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="left"),
            ConditionalEdge(target="right"),
        ])
        g.add_node("left", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("right", "agent2", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "router",
            node_type=WorkflowNodeType.ROUTER,
            join_policy=WorkflowJoinPolicy.FIRST,
            next_nodes=[ConditionalEdge(target=END)],
        )

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-first-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order == ["start", "left", "right", "join"]
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_structured_node_result_persists_rich_event_data(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="structured")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="next", condition="state.should_route"),
            ConditionalEdge(target=END, condition="not state.should_route"),
        ])
        g.add_node("next", "agent1", next_nodes=[ConditionalEdge(target=END)])

        async def structured_handler(node_id: str, state: dict) -> dict | NodeResult:
            if node_id == "start":
                return NodeResult(
                    state_patch={"should_route": False, "started": True},
                    artifacts=[{"kind": "report", "name": "analysis.json"}],
                    edge_decisions={"next": True, "END": False},
                    llm_events=[{"model": "test-model", "tokens": 42}],
                    tool_events=[{"tool": "search", "status": "ok"}],
                    metrics={"latency_ms": 12},
                )
            return NodeResult(state_patch={"finished": True})

        run = WorkflowRun(workflow_id="wf-structured")
        result = await executor.execute(g, run, structured_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state["finished"] is True
        assert len(result.event_log) == 2
        start_event = result.event_log[0]
        assert start_event["state_patch"] == {"should_route": False, "started": True}
        assert start_event["output"] == {"should_route": False, "started": True}
        assert start_event["edge_decisions"] == {"next": True, "END": False}
        assert start_event["artifacts"] == [{"kind": "report", "name": "analysis.json"}]
        assert start_event["tool_events"] == [{"tool": "search", "status": "ok"}]
        assert start_event["llm_events"] == [{"model": "test-model", "tokens": 42}]
        assert start_event["metrics"] == {"latency_ms": 12}
        assert start_event["input_state_version"] == 0

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert checkpoints[0].event_log[0]["state_patch"] == {
            "should_route": False,
            "started": True,
        }
        assert checkpoints[0].event_log[0]["tool_events"] == [{"tool": "search", "status": "ok"}]
        assert checkpoints[0].event_log[0]["artifacts"] == [
            {"kind": "report", "name": "analysis.json"}
        ]

    @pytest.mark.asyncio
    async def test_unknown_edge_decision_fails_run(self, executor):
        g = WorkflowGraph(name="bad-decision")
        g.add_node("start", "planner", next_nodes=[ConditionalEdge(target=END)])

        async def bad_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(state_patch={"started": True}, edge_decisions={"missing": True})

        run = WorkflowRun(workflow_id="wf-bad-decision")
        with pytest.raises(Exception, match="unknown outbound edge decisions"):
            await executor.execute(g, run, bad_handler)

        assert run.status == RunStatus.FAILED

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
            {
                "step": 1,
                "node_id": "step1",
                "agent": "agent",
                "state_patch": {"key": "value"},
                "state_version": 1,
                "state_hash": compute_state_hash({"key": "value"}),
            },
        ]

        replayed = await executor.replay(g, run, mock_handler)
        assert replayed.state.get("key") == "value"
        assert replayed.state_version == 1
        assert replayed.state_hash != ""

    @pytest.mark.asyncio
    async def test_replay_hash_mismatch_fails(self, executor):
        g = WorkflowGraph(name="replay")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        run.event_log = [
            {
                "step": 1,
                "node_id": "step1",
                "agent": "agent",
                "state_patch": {"key": "value"},
                "state_version": 1,
                "state_hash": "invalid",
            },
        ]

        with pytest.raises(Exception, match="hash mismatch"):
            await executor.replay(g, run, mock_handler)
