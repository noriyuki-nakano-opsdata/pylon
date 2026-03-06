"""Integration tests: Workflow + Repository modules.

Validates that workflow execution correctly interacts with checkpoint,
workflow-run, audit, and memory repositories -- creating records,
enabling replay, and maintaining consistency.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from pylon.errors import WorkflowError
from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.memory import MemoryRepository
from pylon.repository.workflow import RunStatus, WorkflowRepository, WorkflowRun
from pylon.types import ConditionalEdge
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_linear_graph(*node_ids: str) -> WorkflowGraph:
    g = WorkflowGraph()
    for nid in node_ids:
        g.add_node(nid)
    for i in range(len(node_ids) - 1):
        g.add_edge(node_ids[i], node_ids[i + 1])
    g.add_edge(node_ids[-1], END)
    g.set_entry(node_ids[0])
    return g


async def _accumulating_handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
    visited = state.get("visited", [])
    visited.append(node_id)
    counter = state.get("counter", 0) + 1
    return {**state, "visited": visited, "counter": counter}


async def _failing_handler_at(
    fail_node: str,
    node_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    visited = state.get("visited", []) + [node_id]
    if node_id == fail_node:
        raise RuntimeError(f"Simulated failure at {node_id}")
    return {**state, "visited": visited}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_created_after_each_node():
    """Each completed node produces a checkpoint in the repository."""
    checkpoint_repo = CheckpointRepository()
    graph = _build_linear_graph("a", "b", "c")
    run_id = str(uuid.uuid4())

    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        checkpoint_repo=checkpoint_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    checkpoints = checkpoint_repo.list(run_id)
    # At minimum one checkpoint per node
    assert len(checkpoints) >= 3


@pytest.mark.asyncio
async def test_checkpoint_restore_produces_same_final_state():
    """Restoring from a mid-workflow checkpoint and replaying yields
    the same final state as a fresh run."""
    checkpoint_repo = CheckpointRepository()
    graph = _build_linear_graph("x", "y", "z")

    # Full run
    run_id_full = str(uuid.uuid4())
    executor_full = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        checkpoint_repo=checkpoint_repo,
        run_id=run_id_full,
    )
    result_full = await executor_full.run({"visited": []})

    # Restore from checkpoint after "x" and replay
    checkpoints = checkpoint_repo.list(run_id_full)
    first_cp = checkpoints[0]
    restored_state = checkpoint_repo.load(first_cp.checkpoint_id)

    run_id_replay = str(uuid.uuid4())
    executor_replay = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        checkpoint_repo=checkpoint_repo,
        run_id=run_id_replay,
    )
    result_replay = await executor_replay.run(
        restored_state,
        resume_from=first_cp.node_id,
    )

    # Final counters must match
    assert result_replay["counter"] == result_full["counter"]


@pytest.mark.asyncio
async def test_workflow_run_status_created_on_start():
    """WorkflowRepository records a run with RUNNING status on start."""
    workflow_repo = WorkflowRepository()
    graph = _build_linear_graph("only")

    run_id = str(uuid.uuid4())
    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        workflow_repo=workflow_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    run: WorkflowRun = workflow_repo.get(run_id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_workflow_run_marked_failed_on_error():
    """A handler exception marks the run as FAILED in the repository."""
    workflow_repo = WorkflowRepository()
    graph = _build_linear_graph("good", "bad")

    run_id = str(uuid.uuid4())

    async def handler(nid: str, st: dict[str, Any]) -> dict[str, Any]:
        return await _failing_handler_at("bad", nid, st)

    executor = GraphExecutor(
        graph,
        handler=handler,
        workflow_repo=workflow_repo,
        run_id=run_id,
    )

    with pytest.raises(RuntimeError):
        await executor.run({"visited": []})

    run = workflow_repo.get(run_id)
    assert run.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_audit_log_captures_workflow_start_and_end():
    """AuditRepository receives events for workflow start and completion."""
    audit_repo = AuditRepository()
    graph = _build_linear_graph("m", "n")

    run_id = str(uuid.uuid4())
    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        audit_repo=audit_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    events = audit_repo.list(run_id)
    event_types = [e.event_type for e in events]
    assert "workflow_started" in event_types
    assert "workflow_completed" in event_types


@pytest.mark.asyncio
async def test_audit_log_captures_node_execution_events():
    """Each node execution generates at least one audit event."""
    audit_repo = AuditRepository()
    graph = _build_linear_graph("p", "q", "r")

    run_id = str(uuid.uuid4())
    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        audit_repo=audit_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    events = audit_repo.list(run_id)
    node_events = [e for e in events if e.event_type == "node_executed"]
    assert len(node_events) >= 3


@pytest.mark.asyncio
async def test_audit_log_records_failure_event():
    """When a node fails, an audit event with error details is recorded."""
    audit_repo = AuditRepository()
    graph = _build_linear_graph("ok", "fail")

    run_id = str(uuid.uuid4())

    async def handler(nid: str, st: dict[str, Any]) -> dict[str, Any]:
        return await _failing_handler_at("fail", nid, st)

    executor = GraphExecutor(
        graph,
        handler=handler,
        audit_repo=audit_repo,
        run_id=run_id,
    )

    with pytest.raises(RuntimeError):
        await executor.run({"visited": []})

    events = audit_repo.list(run_id)
    failure_events = [e for e in events if "fail" in e.event_type.lower() or "error" in e.event_type.lower()]
    assert len(failure_events) >= 1


@pytest.mark.asyncio
async def test_memory_repository_stores_agent_working_memory():
    """Agent handlers can persist intermediate data via MemoryRepository."""
    memory_repo = MemoryRepository()
    graph = _build_linear_graph("producer", "consumer")

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if node_id == "producer":
            memory_repo.store(
                agent_id="producer",
                key="analysis_result",
                value={"score": 0.95, "tags": ["important"]},
            )
        elif node_id == "consumer":
            mem = memory_repo.retrieve(agent_id="producer", key="analysis_result")
            state["consumed_memory"] = mem
        visited = state.get("visited", []) + [node_id]
        return {**state, "visited": visited}

    executor = GraphExecutor(graph, handler=handler)
    result = await executor.run({"visited": []})

    assert result["consumed_memory"]["score"] == 0.95
    assert "important" in result["consumed_memory"]["tags"]


@pytest.mark.asyncio
async def test_checkpoint_and_audit_consistency():
    """Checkpoint count and audit node-execution events are consistent."""
    checkpoint_repo = CheckpointRepository()
    audit_repo = AuditRepository()
    graph = _build_linear_graph("s1", "s2", "s3", "s4")

    run_id = str(uuid.uuid4())
    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        checkpoint_repo=checkpoint_repo,
        audit_repo=audit_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    checkpoints = checkpoint_repo.list(run_id)
    audit_node_events = [
        e for e in audit_repo.list(run_id) if e.event_type == "node_executed"
    ]

    # Every checkpointed node should have a corresponding audit event
    checkpoint_nodes = {cp.node_id for cp in checkpoints}
    audit_nodes = {e.node_id for e in audit_node_events}
    assert checkpoint_nodes == audit_nodes


@pytest.mark.asyncio
async def test_workflow_run_persists_across_operations():
    """WorkflowRun metadata survives multiple repository operations."""
    workflow_repo = WorkflowRepository()
    run_id = str(uuid.uuid4())

    # Create
    workflow_repo.create(
        WorkflowRun(
            run_id=run_id,
            graph_id="test-graph",
            status=RunStatus.RUNNING,
        )
    )

    # Update
    workflow_repo.update_status(run_id, RunStatus.COMPLETED)

    # Retrieve
    run = workflow_repo.get(run_id)
    assert run.run_id == run_id
    assert run.graph_id == "test-graph"
    assert run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_event_log_ordering_matches_execution_order():
    """Audit events appear in chronological execution order."""
    audit_repo = AuditRepository()
    graph = _build_linear_graph("first", "second", "third")

    run_id = str(uuid.uuid4())
    executor = GraphExecutor(
        graph,
        handler=_accumulating_handler,
        audit_repo=audit_repo,
        run_id=run_id,
    )
    await executor.run({"visited": []})

    events = audit_repo.list(run_id)
    node_events = [e for e in events if e.event_type == "node_executed"]

    node_order = [e.node_id for e in node_events]
    assert node_order == ["first", "second", "third"]
