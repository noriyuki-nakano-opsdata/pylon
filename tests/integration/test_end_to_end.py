"""Integration tests: End-to-end workflows combining DSL, execution, safety, and persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pylon.dsl.parser import PylonProject, load_project
from pylon.errors import (
    ApprovalRequiredError,
    PolicyViolationError,
    PromptInjectionError,
    WorkflowError,
)
from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.memory import EpisodicEntry, MemoryRepository, SemanticEntry
from pylon.repository.workflow import RunStatus, WorkflowRepository, WorkflowRun
from pylon.safety.autonomy import AutonomyEnforcer
from pylon.safety.kill_switch import KillSwitch
from pylon.safety.policy import ActionState, PolicyEngine
from pylon.safety.prompt_guard import PromptGuard
from pylon.types import (
    AgentCapability,
    AgentConfig,
    AutonomyLevel,
    ConditionalEdge,
    PolicyConfig,
    TrustLevel,
)
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph


_MINIMAL_YAML = """\
version: "1"
name: e2e-test
agents:
  planner:
    role: "plans tasks"
    autonomy: A2
    sandbox: gvisor
  coder:
    role: "writes code"
    autonomy: A2
    sandbox: docker
workflow:
  type: graph
  nodes:
    plan:
      agent: planner
      next:
        - target: code
    code:
      agent: coder
      next:
        - target: END
policy:
  max_cost_usd: 5.0
  max_duration: 30m
  require_approval_above: A3
  safety:
    blocked_actions:
      - rm-rf
"""


async def _echo_handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return {f"{node_id}_output": f"completed-{node_id}"}


# ---------- DSL -> Workflow Execution ----------


async def test_dsl_to_execution(tmp_path: Path):
    """Load pylon.yaml, build WorkflowGraph, execute, verify completion."""
    yaml_file = tmp_path / "pylon.yaml"
    yaml_file.write_text(_MINIMAL_YAML)

    project = load_project(tmp_path)
    assert project.name == "e2e-test"
    assert "planner" in project.agents
    assert "coder" in project.agents

    g = WorkflowGraph(name=project.name)
    for node_id, node_def in project.workflow.nodes.items():
        edges: list[ConditionalEdge] = []
        if node_def.next is not None:
            if isinstance(node_def.next, str):
                edges.append(ConditionalEdge(target=node_def.next))
            else:
                for edge in node_def.next:
                    if isinstance(edge, str):
                        edges.append(ConditionalEdge(target=edge))
                    else:
                        edges.append(ConditionalEdge(target=edge.target, condition=edge.condition))
        g.add_node(node_id, node_def.agent, next_nodes=edges)

    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="e2e-wf-1")
    result = await executor.execute(g, run, _echo_handler)

    assert result.status == RunStatus.COMPLETED
    assert "plan_output" in result.state
    assert "code_output" in result.state


# ---------- End-to-end with Safety Checks ----------


async def test_e2e_safety_pipeline():
    """Full pipeline: prompt guard -> capability check -> policy -> execute."""
    guard = PromptGuard()
    safe_input = guard.check("analyze this code", TrustLevel.UNTRUSTED)
    assert safe_input == "analyze this code"

    cap = AgentCapability(can_write_external=True)
    assert not cap.can_read_untrusted
    assert cap.can_write_external

    policy = PolicyConfig(max_cost_usd=10.0, blocked_actions=["rm-rf"])
    engine = PolicyEngine(policy=policy)
    agent_cfg = AgentConfig(name="coder", autonomy=AutonomyLevel.A2)
    state = ActionState(current_cost_usd=2.0)
    decision = engine.evaluate_action(agent_cfg, "write-file", state)
    assert decision.allowed

    g = WorkflowGraph(name="safe-pipeline")
    g.add_node("run", "coder", next_nodes=[ConditionalEdge(target=END)])

    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="safe-wf")
    result = await executor.execute(g, run, _echo_handler)
    assert result.status == RunStatus.COMPLETED


# ---------- End-to-end with Persistence ----------


async def test_e2e_full_persistence():
    """Workflow execution with checkpoint, audit, and memory persistence."""
    cp_repo = CheckpointRepository()
    audit_repo = AuditRepository(hmac_key=b"test-key-at-least-16-bytes")
    wf_repo = WorkflowRepository()
    mem_repo = MemoryRepository()

    g = WorkflowGraph(name="persist-test")
    g.add_node("analyze", "agent-a", next_nodes=[ConditionalEdge(target="fix")])
    g.add_node("fix", "agent-b", next_nodes=[ConditionalEdge(target=END)])

    run = WorkflowRun(workflow_id="wf-persist")
    await wf_repo.create_run(run)

    await audit_repo.append(
        event_type="workflow.start", actor="system", action="start",
        details={"run_id": run.id},
    )

    executor = GraphExecutor(checkpoint_repo=cp_repo)
    result = await executor.execute(g, run, _echo_handler)

    await audit_repo.append(
        event_type="workflow.complete", actor="system", action="complete",
        details={"run_id": run.id},
    )

    assert result.status == RunStatus.COMPLETED

    checkpoints = await cp_repo.list(workflow_run_id=run.id)
    assert len(checkpoints) >= 2

    audit_entries = await audit_repo.list()
    assert len(audit_entries) == 2

    valid, _ = await audit_repo.verify_chain()
    assert valid

    await mem_repo.store_episodic(
        EpisodicEntry(agent_id="agent-a", content="found bug in auth module")
    )
    await mem_repo.store_semantic(
        SemanticEntry(key="auth-fix", content="patched JWT validation")
    )

    episodes = await mem_repo.list_episodic("agent-a")
    assert len(episodes) == 1

    semantic = await mem_repo.get_semantic_by_key("auth-fix")
    assert semantic is not None


# ---------- Replay ----------


async def test_e2e_replay():
    """Execute workflow then replay from event log."""
    g = WorkflowGraph(name="replay-test")
    g.add_node("step1", "agent-a", next_nodes=[ConditionalEdge(target=END)])

    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="wf-replay")
    result = await executor.execute(g, run, _echo_handler)
    assert result.status == RunStatus.COMPLETED

    replayed = await executor.replay(g, run, _echo_handler)
    assert replayed.state == result.state


# ---------- Conditional Routing ----------


async def test_e2e_conditional_routing():
    """Conditional edges route based on state."""
    g = WorkflowGraph(name="routing-test")
    g.add_node("check", "router-agent", next_nodes=[
        ConditionalEdge(target="fix", condition="state.needs_fix == True"),
        ConditionalEdge(target="done", condition="state.needs_fix == False"),
    ])
    g.add_node("fix", "fixer-agent", next_nodes=[ConditionalEdge(target=END)])
    g.add_node("done", "reporter-agent", next_nodes=[ConditionalEdge(target=END)])

    async def routing_handler(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if node_id == "check":
            return {"needs_fix": True}
        return {f"{node_id}_done": True}

    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="wf-route")
    result = await executor.execute(g, run, routing_handler)

    assert result.status == RunStatus.COMPLETED
    assert "fix_done" in result.state
    assert "done_done" not in result.state


# ---------- Workflow Validation Errors ----------


async def test_e2e_empty_graph_raises():
    g = WorkflowGraph(name="empty")
    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="wf-empty")

    with pytest.raises(WorkflowError, match="no nodes"):
        await executor.execute(g, run, _echo_handler)


async def test_e2e_cycle_detection():
    g = WorkflowGraph(name="cycle")
    g.add_node("a", "agent-a", next_nodes=[ConditionalEdge(target="b")])
    g.add_node("b", "agent-b", next_nodes=[ConditionalEdge(target="a")])

    executor = GraphExecutor()
    run = WorkflowRun(workflow_id="wf-cycle")

    with pytest.raises(WorkflowError, match="Cycle"):
        await executor.execute(g, run, _echo_handler)


# ---------- DSL Validation ----------


async def test_dsl_rejects_invalid_agent_ref(tmp_path: Path):
    """pylon.yaml with workflow referencing undefined agent should fail."""
    bad_yaml = """\
version: "1"
name: bad-project
agents:
  planner:
    role: plans
workflow:
  type: graph
  nodes:
    step1:
      agent: nonexistent
      next: END
"""
    yaml_file = tmp_path / "pylon.yaml"
    yaml_file.write_text(bad_yaml)

    with pytest.raises(Exception, match="undefined agent"):
        load_project(tmp_path)
