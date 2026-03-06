"""End-to-end integration tests for the Pylon platform.

These tests exercise the complete pipeline: DSL definition, graph
construction, safety validation, execution, checkpointing, audit
logging, and replay.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from pylon.dsl.parser import PylonProject, load_project
from pylon.errors import PolicyViolationError, WorkflowError
from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.memory import MemoryRepository
from pylon.repository.workflow import RunStatus, WorkflowRepository, WorkflowRun
from pylon.safety.autonomy import AutonomyEnforcer
from pylon.safety.capability import CapabilityValidator
from pylon.safety.kill_switch import KillSwitch
from pylon.safety.policy import PolicyEngine
from pylon.types import AgentCapability, AgentState, AutonomyLevel, ConditionalEdge
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repos() -> dict[str, Any]:
    return {
        "checkpoint_repo": CheckpointRepository(),
        "workflow_repo": WorkflowRepository(),
        "audit_repo": AuditRepository(),
        "memory_repo": MemoryRepository(),
    }


async def _counting_handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
    visited = state.get("visited", []) + [node_id]
    counter = state.get("counter", 0) + 1
    return {**state, "visited": visited, "counter": counter}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_define_validate_execute_checkpoint_replay():
    """Complete lifecycle: build graph, execute, checkpoint, restore, replay."""
    repos = _make_repos()
    graph = WorkflowGraph()
    graph.add_node("plan")
    graph.add_node("code")
    graph.add_node("test")
    graph.add_edge("plan", "code")
    graph.add_edge("code", "test")
    graph.add_edge("test", END)
    graph.set_entry("plan")

    run_id = str(uuid.uuid4())

    executor = GraphExecutor(
        graph,
        handler=_counting_handler,
        run_id=run_id,
        **repos,
    )
    result = await executor.run({"visited": []})

    assert result["visited"] == ["plan", "code", "test"]
    assert result["counter"] == 3

    # Verify checkpoint exists
    checkpoints = repos["checkpoint_repo"].list(run_id)
    assert len(checkpoints) >= 3

    # Verify audit trail
    events = repos["audit_repo"].list(run_id)
    event_types = {e.event_type for e in events}
    assert "workflow_started" in event_types
    assert "workflow_completed" in event_types

    # Replay from the first checkpoint
    first_cp = checkpoints[0]
    restored = repos["checkpoint_repo"].load(first_cp.checkpoint_id)

    replay_id = str(uuid.uuid4())
    executor_replay = GraphExecutor(
        graph,
        handler=_counting_handler,
        run_id=replay_id,
        **repos,
    )
    replay_result = await executor_replay.run(
        restored, resume_from=first_cp.node_id,
    )
    assert replay_result["counter"] == result["counter"]


@pytest.mark.asyncio
async def test_fan_out_fan_in_multi_agent():
    """Multiple parallel branches (fan-out) merge into a single node (fan-in)."""
    graph = WorkflowGraph()
    graph.add_node("split")
    graph.add_node("worker_a")
    graph.add_node("worker_b")
    graph.add_node("worker_c")
    graph.add_node("merge")

    graph.add_edge("split", "worker_a")
    graph.add_edge("split", "worker_b")
    graph.add_edge("split", "worker_c")
    graph.add_edge("worker_a", "merge")
    graph.add_edge("worker_b", "merge")
    graph.add_edge("worker_c", "merge")
    graph.add_edge("merge", END)
    graph.set_entry("split")

    results_by_worker: dict[str, str] = {}

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        visited = state.get("visited", []) + [node_id]
        if node_id.startswith("worker_"):
            results_by_worker[node_id] = f"output_{node_id}"
        if node_id == "merge":
            state["merged"] = dict(results_by_worker)
        return {**state, "visited": visited}

    executor = GraphExecutor(graph, handler=handler)
    result = await executor.run({"visited": []})

    assert "split" in result["visited"]
    assert "merge" in result["visited"]
    # All workers must have executed
    for w in ("worker_a", "worker_b", "worker_c"):
        assert w in result["visited"]
    assert len(result["merged"]) == 3


@pytest.mark.asyncio
async def test_conditional_branching_based_on_agent_output():
    """A conditional edge routes execution based on runtime state."""
    graph = WorkflowGraph()
    graph.add_node("evaluate")
    graph.add_node("approve")
    graph.add_node("reject")

    graph.add_conditional_edge(
        "evaluate",
        condition=lambda state: "approve" if state.get("score", 0) >= 0.8 else "reject",
    )
    graph.add_edge("approve", END)
    graph.add_edge("reject", END)
    graph.set_entry("evaluate")

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        visited = state.get("visited", []) + [node_id]
        return {**state, "visited": visited}

    executor = GraphExecutor(graph, handler=handler)

    # High score -> approve
    result_high = await executor.run({"visited": [], "score": 0.9})
    assert "approve" in result_high["visited"]
    assert "reject" not in result_high["visited"]

    # Low score -> reject
    result_low = await executor.run({"visited": [], "score": 0.3})
    assert "reject" in result_low["visited"]
    assert "approve" not in result_low["visited"]


@pytest.mark.asyncio
async def test_error_handling_run_marked_failed_audit_logged():
    """Agent failure marks the run as FAILED and creates an audit entry."""
    repos = _make_repos()
    graph = WorkflowGraph()
    graph.add_node("setup")
    graph.add_node("crash")
    graph.add_edge("setup", "crash")
    graph.add_edge("crash", END)
    graph.set_entry("setup")

    run_id = str(uuid.uuid4())

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if node_id == "crash":
            raise RuntimeError("Agent exploded")
        visited = state.get("visited", []) + [node_id]
        return {**state, "visited": visited}

    executor = GraphExecutor(
        graph, handler=handler, run_id=run_id, **repos,
    )

    with pytest.raises(RuntimeError, match="exploded"):
        await executor.run({"visited": []})

    # Run status
    run = repos["workflow_repo"].get(run_id)
    assert run.status == RunStatus.FAILED

    # Audit trail includes failure
    events = repos["audit_repo"].list(run_id)
    has_failure = any(
        "fail" in e.event_type.lower() or "error" in e.event_type.lower()
        for e in events
    )
    assert has_failure


@pytest.mark.asyncio
async def test_max_steps_prevents_infinite_loop():
    """A cycle with no termination condition is stopped by max_steps."""
    graph = WorkflowGraph()
    graph.add_node("loop_body")
    # Intentional cycle: loop_body -> loop_body
    graph.add_conditional_edge(
        "loop_body",
        condition=lambda state: "loop_body" if state.get("counter", 0) < 1000 else END,
    )
    graph.add_edge("loop_body", END)  # fallback edge for graph validity
    graph.set_entry("loop_body")

    repos = _make_repos()
    run_id = str(uuid.uuid4())

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        counter = state.get("counter", 0) + 1
        return {**state, "counter": counter}

    executor = GraphExecutor(
        graph,
        handler=handler,
        run_id=run_id,
        max_steps=10,
        **repos,
    )

    with pytest.raises((WorkflowError, RuntimeError)):
        await executor.run({"counter": 0})

    # Run should be marked failed or stopped
    run = repos["workflow_repo"].get(run_id)
    assert run.status in (RunStatus.FAILED, RunStatus.STOPPED)


@pytest.mark.asyncio
async def test_dsl_definition_to_workflow_execution(tmp_path):
    """Load a workflow definition from YAML DSL, build a graph, and execute."""
    yaml_content = """
name: review-pipeline
version: "1.0"
nodes:
  - id: lint
    type: agent
    capabilities: [READ]
  - id: review
    type: agent
    capabilities: [READ, WRITE]
  - id: report
    type: agent
    capabilities: [READ]
edges:
  - from: lint
    to: review
  - from: review
    to: report
entry: lint
"""
    yaml_file = tmp_path / "pipeline.yaml"
    yaml_file.write_text(yaml_content)

    project: PylonProject = load_project(str(yaml_file))

    # Build graph from DSL
    graph = WorkflowGraph()
    for node_def in project.nodes:
        graph.add_node(node_def.id)
    for edge_def in project.edges:
        graph.add_edge(edge_def.source, edge_def.target)
    graph.add_edge(project.nodes[-1].id, END)
    graph.set_entry(project.entry)

    executor = GraphExecutor(graph, handler=_counting_handler)
    result = await executor.run({"visited": []})

    assert result["visited"] == ["lint", "review", "report"]


@pytest.mark.asyncio
async def test_safety_gates_in_full_pipeline():
    """End-to-end pipeline with safety gates at each stage:
    capability validation + autonomy enforcement + kill switch check."""
    validator = CapabilityValidator()
    enforcer = AutonomyEnforcer(max_level=AutonomyLevel.A3)
    kill_switch = KillSwitch()

    node_config = {
        "scan": {
            "caps": [AgentCapability.READ],
            "autonomy": AutonomyLevel.A1,
        },
        "analyze": {
            "caps": [AgentCapability.READ, AgentCapability.WRITE],
            "autonomy": AutonomyLevel.A2,
        },
        "remediate": {
            "caps": [AgentCapability.READ, AgentCapability.WRITE],
            "autonomy": AutonomyLevel.A3,
        },
    }

    graph = WorkflowGraph()
    for nid in node_config:
        graph.add_node(nid)
    graph.add_edge("scan", "analyze")
    graph.add_edge("analyze", "remediate")
    graph.add_edge("remediate", END)
    graph.set_entry("scan")

    repos = _make_repos()
    run_id = str(uuid.uuid4())

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        kill_switch.check()
        cfg = node_config[node_id]
        for cap in cfg["caps"]:
            validator.validate(cap)
        enforcer.enforce(node_id, cfg["autonomy"])
        visited = state.get("visited", []) + [node_id]
        return {**state, "visited": visited}

    executor = GraphExecutor(
        graph, handler=handler, run_id=run_id, **repos,
    )
    result = await executor.run({"visited": []})

    assert result["visited"] == ["scan", "analyze", "remediate"]

    run = repos["workflow_repo"].get(run_id)
    assert run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_memory_shared_across_agents_in_workflow():
    """Agents in different workflow nodes share data through MemoryRepository."""
    memory_repo = MemoryRepository()

    graph = WorkflowGraph()
    graph.add_node("researcher")
    graph.add_node("writer")
    graph.add_node("reviewer")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_edge("reviewer", END)
    graph.set_entry("researcher")

    async def handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if node_id == "researcher":
            memory_repo.store(
                agent_id="researcher",
                key="findings",
                value={"topics": ["security", "performance"], "confidence": 0.92},
            )
        elif node_id == "writer":
            findings = memory_repo.retrieve(agent_id="researcher", key="findings")
            memory_repo.store(
                agent_id="writer",
                key="draft",
                value={"based_on": findings["topics"], "word_count": 1500},
            )
        elif node_id == "reviewer":
            draft = memory_repo.retrieve(agent_id="writer", key="draft")
            state["review_result"] = {
                "approved": draft["word_count"] > 1000,
                "topics_covered": draft["based_on"],
            }

        visited = state.get("visited", []) + [node_id]
        return {**state, "visited": visited}

    executor = GraphExecutor(graph, handler=handler)
    result = await executor.run({"visited": []})

    assert result["visited"] == ["researcher", "writer", "reviewer"]
    assert result["review_result"]["approved"] is True
    assert "security" in result["review_result"]["topics_covered"]
