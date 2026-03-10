from __future__ import annotations

from pathlib import Path

import pytest

from pylon.control_plane import SQLiteWorkflowControlPlaneStore, WorkflowRunService
from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError
from pylon.types import RunStatus


def _workflow_project(name: str = "demo-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
        }
    )


def _approval_project(name: str = "approval-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "reviewer": {"role": "review", "autonomy": "A4"},
            },
            "workflow": {
                "nodes": {
                    "review": {"agent": "reviewer", "next": "END"},
                }
            },
        }
    )


def _store(path: Path) -> SQLiteWorkflowControlPlaneStore:
    return SQLiteWorkflowControlPlaneStore(path)


def test_sqlite_store_persists_completed_run(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.db"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    stored_run = WorkflowRunService(store).start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
    )

    reopened = _store(state_path)
    persisted = reopened.get_run_record(str(stored_run["id"]))
    assert persisted is not None
    assert persisted["status"] == RunStatus.COMPLETED.value
    assert reopened.get_workflow_project("echo", tenant_id="tenant-a") is not None
    assert len(reopened.list_run_checkpoints(str(stored_run["id"]))) == 2


def test_sqlite_store_persists_approval_resume(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.db"
    store = _store(state_path)
    store.register_workflow_project("review", _approval_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    waiting_run = service.start_run(workflow_id="review", tenant_id="tenant-a")
    approval_id = str(waiting_run["approval_request_id"])

    reopened = _store(state_path)
    resumed = WorkflowRunService(reopened).approve_request(
        approval_id,
        tenant_id="tenant-a",
        actor="test",
        reason="approved",
    )

    assert resumed["status"] == RunStatus.COMPLETED.value
    approval = reopened.get_approval_record(approval_id)
    assert approval is not None
    assert approval["status"] == "approved"
    audit_entries = reopened.list_audit_records(limit=None)
    assert [entry["event_type"] for entry in audit_entries] == [
        "approval.submitted",
        "approval.approved",
    ]
    assert audit_entries[0]["details"]["request_id"] == approval_id
    assert audit_entries[1]["details"]["request_id"] == approval_id


def test_sqlite_store_honors_idempotency_key(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.db"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    first = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        idempotency_key="req-1",
    )
    second = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        idempotency_key="req-1",
    )

    assert second["id"] == first["id"]
    assert len(store.list_all_run_records()) == 1


def test_sqlite_store_enforces_expected_record_version(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.db"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    stored = WorkflowRunService(store).start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
    )
    assert stored["record_version"] == 1

    with pytest.raises(ConcurrencyError):
        store.put_run_record(
            dict(stored),
            workflow_id="echo",
            tenant_id="tenant-a",
            expected_record_version=0,
        )


def test_sqlite_store_persists_surface_records_and_sequences(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.db"
    store = _store(state_path)
    first = store.allocate_sequence_value("memories")
    second = store.allocate_sequence_value("memories")
    store.put_surface_record(
        "tasks",
        "task-1",
        {
            "id": "task-1",
            "tenant_id": "tenant-a",
            "title": "Audit ads pipeline",
            "updated_at": "2026-03-11T00:00:00Z",
        },
    )

    reopened = _store(state_path)
    assert first == 1
    assert second == 2
    assert reopened.allocate_sequence_value("memories") == 3
    assert reopened.get_surface_record("tasks", "task-1") == {
        "id": "task-1",
        "tenant_id": "tenant-a",
        "title": "Audit ads pipeline",
        "updated_at": "2026-03-11T00:00:00Z",
    }
