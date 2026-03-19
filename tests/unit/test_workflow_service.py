from __future__ import annotations

from pathlib import Path

import pytest

from pylon.control_plane import JsonFileWorkflowControlPlaneStore, WorkflowRunService
from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError
from pylon.lifecycle import build_lifecycle_workflow_definition
from pylon.observability.tracing import Tracer
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


def _store(path: Path) -> JsonFileWorkflowControlPlaneStore:
    return JsonFileWorkflowControlPlaneStore(path)


def test_json_file_store_persists_completed_run(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    stored_run = service.start_run(
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


def test_json_file_store_persists_approval_resume(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("review", _approval_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    waiting_run = service.start_run(workflow_id="review", tenant_id="tenant-a")
    assert waiting_run["status"] == RunStatus.WAITING_APPROVAL.value
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


def test_json_file_store_replays_checkpoint_after_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    stored_run = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
    )
    checkpoints = store.list_run_checkpoints(str(stored_run["id"]))
    assert checkpoints

    replay_payload = WorkflowRunService(_store(state_path)).replay_checkpoint(
        str(checkpoints[0]["id"])
    )

    assert replay_payload["view_kind"] == "replay"
    assert replay_payload["replay"]["checkpoint_id"] == str(checkpoints[0]["id"])


def test_start_run_is_idempotent_for_same_workflow_and_tenant(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
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


def test_put_run_record_enforces_expected_record_version(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    stored = service.start_run(
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


def test_json_file_store_persists_surface_records_and_sequences(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    first = store.allocate_sequence_value("memories")
    second = store.allocate_sequence_value("memories")
    store.put_surface_record(
        "tasks",
        "task-1",
        {
            "id": "task-1",
            "tenant_id": "tenant-a",
            "title": "Investigate funnel leak",
            "updated_at": "2026-03-11T00:00:00Z",
        },
    )

    reopened = _store(state_path)
    assert first == 1
    assert second == 2
    assert reopened.allocate_sequence_value("memories") == 3
    assert reopened.get_surface_record("tasks", "task-1") == {
        "id": "task-1",
        "record_version": 1,
        "tenant_id": "tenant-a",
        "title": "Investigate funnel leak",
        "updated_at": "2026-03-11T00:00:00Z",
    }


def test_start_run_supports_queued_execution_mode(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    stored = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        execution_mode="queued",
    )

    assert stored["execution_mode"] == "queued"
    assert stored["status"] == RunStatus.COMPLETED.value
    assert len(stored["queue_task_ids"]) == 2
    assert len(store.list_run_checkpoints(str(stored["id"]))) == 2
    queue_state = stored["state"]["queue"]
    assert queue_state["completed_task_ids"] == list(stored["queue_task_ids"])
    assert queue_state["failed_task_ids"] == []


def test_start_run_rehydrates_lifecycle_handlers_after_store_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    workflow_id = "lifecycle-research-demo-project"
    store = _store(state_path)
    store.register_workflow_project(
        workflow_id,
        build_lifecycle_workflow_definition("demo-project", "research")["project"],
        tenant_id="tenant-a",
    )

    reopened = _store(state_path)
    assert reopened.get_node_handlers(workflow_id) in (None, {})

    stored = WorkflowRunService(reopened).start_run(
        workflow_id=workflow_id,
        tenant_id="tenant-a",
        input_data={"spec": "Operator-led lifecycle workspace"},
    )

    assert stored["status"] == RunStatus.COMPLETED.value
    assert reopened.get_node_handlers(workflow_id)
    research = stored["state"].get("research")
    assert isinstance(research, dict)
    assert research


def test_start_run_uses_active_trace_context_when_not_explicit(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")
    tracer = Tracer()
    service = WorkflowRunService(store, tracer=tracer)

    with tracer.start_as_current_span("api.request") as request_span:
        stored = service.start_run(
            workflow_id="echo",
            tenant_id="tenant-a",
            input_data={"msg": "hi"},
        )

    assert stored["trace_id"] == request_span.trace_id


def test_start_run_rejects_queued_execution_for_approval_workflow(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("review", _approval_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)

    with pytest.raises(ValueError, match="queued execution mode currently supports only"):
        service.start_run(
            workflow_id="review",
            tenant_id="tenant-a",
            execution_mode="queued",
        )


def test_start_run_queued_retry_policy_allows_recovery(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")
    attempts = {"researcher": 0}

    def _researcher(_node_id: str, state: dict[str, object]) -> dict[str, object]:
        attempts["researcher"] += 1
        if attempts["researcher"] == 1:
            raise RuntimeError("transient")
        return {"msg": state.get("msg"), "retried": True}

    store.set_handlers("echo", agent_handlers={"researcher": _researcher})
    service = WorkflowRunService(store)

    stored = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        execution_mode="queued",
        parameters={
            "queued": {
                "retry": {"policy": "fixed", "max_retries": 1, "delay_seconds": 0.0}
            }
        },
    )

    assert stored["status"] == RunStatus.COMPLETED.value
    assert stored["state"]["retried"] is True
    assert attempts["researcher"] == 2
    queue_state = stored["state"]["queue"]
    assert queue_state["retry_policy"]["policy"] == "fixed"
    assert queue_state["retrying_task_ids"] == []
    assert queue_state["dead_letter_task_ids"] == []
    assert any(event.get("retry_scheduled") for event in stored["event_log"])


def test_start_run_queued_retry_policy_dead_letters_exhausted_task(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    def _researcher(_node_id: str, _state: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("hard failure")

    store.set_handlers("echo", agent_handlers={"researcher": _researcher})
    service = WorkflowRunService(store)

    stored = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        execution_mode="queued",
        parameters={
            "queued": {
                "retry": {"policy": "fixed", "max_retries": 1, "delay_seconds": 0.0}
            }
        },
    )

    assert stored["status"] == RunStatus.FAILED.value
    queue_state = stored["state"]["queue"]
    assert len(queue_state["dead_letter_task_ids"]) == 1
    assert len(queue_state["failed_task_ids"]) == 1
    assert len(queue_state["blocked_task_ids"]) == 1
    assert stored["runtime_metrics"]["queue"]["dead_letter_task_ids"] == queue_state[
        "dead_letter_task_ids"
    ]
    assert any(event.get("dead_lettered") for event in stored["event_log"])


def test_start_run_queued_heartbeat_configuration_is_reflected(tmp_path: Path) -> None:
    state_path = tmp_path / "control-plane.json"
    store = _store(state_path)
    store.register_workflow_project("echo", _workflow_project(), tenant_id="tenant-a")

    service = WorkflowRunService(store)
    stored = service.start_run(
        workflow_id="echo",
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        execution_mode="queued",
        parameters={
            "queued": {
                "lease_timeout_seconds": 2.0,
                "heartbeat_interval_seconds": 0.5,
            }
        },
    )

    queue_state = stored["state"]["queue"]
    assert queue_state["lease_timeout_seconds"] == 2.0
    assert queue_state["heartbeat_interval_seconds"] == 0.5
    assert stored["runtime_metrics"]["queue"]["lease_timeout_seconds"] == 2.0
    assert stored["runtime_metrics"]["queue"]["heartbeat_interval_seconds"] == 0.5
    assert "heartbeat_total" in queue_state
