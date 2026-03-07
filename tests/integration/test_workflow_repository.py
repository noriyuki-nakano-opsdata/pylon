"""Integration tests: Workflow and checkpoint repositories."""

from __future__ import annotations

from typing import Any

import pytest

from pylon.repository.audit import AuditEntry, AuditRepository
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.memory import (
    EpisodicEntry,
    MemoryRepository,
    ProceduralEntry,
    SemanticEntry,
)
from pylon.repository.workflow import (
    RunStatus,
    WorkflowDefinition,
    WorkflowRepository,
    WorkflowRun,
)


# ---------- CheckpointRepository ----------


async def test_checkpoint_create_and_get():
    repo = CheckpointRepository()
    cp = Checkpoint(workflow_run_id="run-1", node_id="step-a")
    cp.add_event(input_data={"x": 1}, output_data={"y": 2})

    created = await repo.create(cp)
    assert created.id == cp.id

    fetched = await repo.get(cp.id)
    assert fetched is not None
    assert fetched.workflow_run_id == "run-1"
    assert len(fetched.event_log) == 1


async def test_checkpoint_list_by_workflow_run():
    repo = CheckpointRepository()
    cp1 = Checkpoint(workflow_run_id="run-1", node_id="a")
    cp2 = Checkpoint(workflow_run_id="run-1", node_id="b")
    cp3 = Checkpoint(workflow_run_id="run-2", node_id="c")

    await repo.create(cp1)
    await repo.create(cp2)
    await repo.create(cp3)

    results = await repo.list(workflow_run_id="run-1")
    assert len(results) == 2
    assert all(c.workflow_run_id == "run-1" for c in results)


async def test_checkpoint_delete():
    repo = CheckpointRepository()
    cp = Checkpoint(workflow_run_id="run-1", node_id="x")
    await repo.create(cp)

    deleted = await repo.delete(cp.id)
    assert deleted is True

    fetched = await repo.get(cp.id)
    assert fetched is None

    deleted_again = await repo.delete(cp.id)
    assert deleted_again is False


async def test_checkpoint_get_latest():
    repo = CheckpointRepository()
    cp1 = Checkpoint(workflow_run_id="run-1", node_id="a")
    cp2 = Checkpoint(workflow_run_id="run-1", node_id="b")

    await repo.create(cp1)
    await repo.create(cp2)

    latest = await repo.get_latest("run-1")
    assert latest is not None


# ---------- WorkflowRepository ----------


async def test_workflow_run_lifecycle():
    repo = WorkflowRepository()
    run = WorkflowRun(workflow_id="wf-1")

    created = await repo.create_run(run)
    assert created.status == RunStatus.PENDING

    run.start()
    assert run.status == RunStatus.RUNNING
    assert run.started_at is not None

    run.complete()
    assert run.status == RunStatus.COMPLETED
    assert run.completed_at is not None

    fetched = await repo.get_run(run.id)
    assert fetched is not None
    assert fetched.status == RunStatus.COMPLETED


async def test_workflow_run_fail():
    run = WorkflowRun(workflow_id="wf-1")
    run.start()
    run.fail("something broke")

    assert run.status == RunStatus.FAILED
    assert run.state["error"] == "something broke"


async def test_workflow_definition_crud():
    repo = WorkflowRepository()
    defn = WorkflowDefinition(name="my-workflow", graph={"nodes": {}})

    created = await repo.create_definition(defn)
    assert created.id == defn.id

    fetched = await repo.get_definition(defn.id)
    assert fetched is not None
    assert fetched.name == "my-workflow"

    definitions = await repo.list_definitions()
    assert len(definitions) == 1


async def test_workflow_run_list_with_filters():
    repo = WorkflowRepository()
    run1 = WorkflowRun(workflow_id="wf-1")
    run2 = WorkflowRun(workflow_id="wf-1")
    run3 = WorkflowRun(workflow_id="wf-2")

    run1.start()
    run1.complete()

    await repo.create_run(run1)
    await repo.create_run(run2)
    await repo.create_run(run3)

    all_runs = await repo.list_runs()
    assert len(all_runs) == 3

    wf1_runs = await repo.list_runs(workflow_id="wf-1")
    assert len(wf1_runs) == 2

    completed = await repo.list_runs(status=RunStatus.COMPLETED)
    assert len(completed) == 1


# ---------- AuditRepository ----------


async def test_audit_append_and_chain():
    repo = AuditRepository(hmac_key=b"test-key-at-least-16-bytes")

    e1 = await repo.append(
        event_type="agent.start", actor="system", action="start"
    )
    e2 = await repo.append(
        event_type="agent.stop", actor="system", action="stop"
    )

    assert e1.id == 1
    assert e2.id == 2
    assert e2.prev_hash == e1.entry_hash
    assert repo.count == 2

    valid, msg = await repo.verify_chain()
    assert valid


async def test_audit_list_by_event_type():
    repo = AuditRepository(hmac_key=b"test-key-at-least-16-bytes")

    await repo.append(event_type="workflow.start", actor="sys", action="start")
    await repo.append(event_type="workflow.end", actor="sys", action="end")
    await repo.append(event_type="workflow.start", actor="sys", action="start")

    starts = await repo.list(event_type="workflow.start")
    assert len(starts) == 2


async def test_audit_get_by_id():
    repo = AuditRepository(hmac_key=b"test-key-at-least-16-bytes")

    await repo.append(event_type="test", actor="admin", action="do")
    entry = await repo.get(1)
    assert entry is not None
    assert entry.actor == "admin"

    missing = await repo.get(999)
    assert missing is None


# ---------- MemoryRepository ----------


async def test_memory_episodic_store_and_get():
    repo = MemoryRepository()
    entry = EpisodicEntry(agent_id="agent-1", content="saw error X")

    stored = await repo.store_episodic(entry)
    assert stored.id == entry.id

    fetched = await repo.get_episodic(entry.id)
    assert fetched is not None
    assert fetched.content == "saw error X"


async def test_memory_episodic_list_by_agent():
    repo = MemoryRepository()
    await repo.store_episodic(EpisodicEntry(agent_id="a1", content="one"))
    await repo.store_episodic(EpisodicEntry(agent_id="a1", content="two"))
    await repo.store_episodic(EpisodicEntry(agent_id="a2", content="three"))

    a1_entries = await repo.list_episodic("a1")
    assert len(a1_entries) == 2


async def test_memory_semantic_store_and_lookup():
    repo = MemoryRepository()
    entry = SemanticEntry(key="auth-pattern", content="use JWT refresh tokens")

    await repo.store_semantic(entry)

    by_key = await repo.get_semantic_by_key("auth-pattern")
    assert by_key is not None
    assert by_key.content == "use JWT refresh tokens"


async def test_memory_procedural_stats_update():
    repo = MemoryRepository()
    entry = ProceduralEntry(pattern="retry-on-503", action="retry with backoff")

    await repo.store_procedural(entry)

    updated = await repo.update_procedural_stats(entry.id, success=True)
    assert updated is not None
    assert updated.execution_count == 1
    assert updated.success_rate == 1.0

    updated2 = await repo.update_procedural_stats(entry.id, success=False)
    assert updated2 is not None
    assert updated2.execution_count == 2
    assert updated2.success_rate == 0.5
