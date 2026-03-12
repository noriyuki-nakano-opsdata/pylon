from __future__ import annotations

import time

from pylon.api.async_runs import (
    AsyncWorkflowRunManager,
    reconcile_lifecycle_projects_for_terminal_runs,
    sync_lifecycle_project_for_run,
)
from pylon.control_plane import InMemoryWorkflowControlPlaneStore
from pylon.dsl.parser import PylonProject
from pylon.lifecycle import default_lifecycle_project_record
from pylon.observability.run_payload import build_public_run_payload
from pylon.types import RunStatus, RunStopReason


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


def _wait_for_terminal(
    manager: AsyncWorkflowRunManager,
    run_id: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = manager.get_run(run_id)
        if payload is not None and payload.get("status") in {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
        }:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Run {run_id} did not reach a terminal state in time")


def test_async_workflow_run_manager_completes_and_persists_checkpoints() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "echo"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")
    store.set_handlers(
        workflow_id,
        agent_handlers={
            "researcher": lambda _node_id, state: {"msg": state.get("msg"), "researched": True},
            "writer": lambda _node_id, state: {"output": f"done:{state.get('msg')}"},
        },
    )
    manager = AsyncWorkflowRunManager(store)

    started = manager.start_run(
        workflow_id=workflow_id,
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
    )

    finished = _wait_for_terminal(manager, str(started["id"]))
    assert finished["status"] == RunStatus.COMPLETED.value
    assert finished["execution_mode"] == "async"
    assert len(store.list_run_checkpoints(str(started["id"]))) == 2


def test_async_workflow_run_manager_persists_failures() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "echo"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")

    def _boom(_node_id: str, _state: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    store.set_handlers(workflow_id, agent_handlers={"researcher": _boom})
    manager = AsyncWorkflowRunManager(store)

    started = manager.start_run(
        workflow_id=workflow_id,
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
    )

    finished = _wait_for_terminal(manager, str(started["id"]))
    assert finished["status"] == RunStatus.FAILED.value
    assert "Async workflow execution failed:" in str(finished.get("error"))
    assert "boom" in str(finished.get("error"))


def test_async_workflow_run_manager_preserves_idempotency_and_trace_context() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "echo"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")
    store.set_handlers(
        workflow_id,
        agent_handlers={
            "researcher": lambda _node_id, state: {"msg": state.get("msg"), "researched": True},
            "writer": lambda _node_id, state: {"output": f"done:{state.get('msg')}"},
        },
    )
    manager = AsyncWorkflowRunManager(store)

    started = manager.start_run(
        workflow_id=workflow_id,
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        idempotency_key="same-request",
        correlation_id="corr-123",
        trace_id="trace-456",
    )
    reused = manager.start_run(
        workflow_id=workflow_id,
        tenant_id="tenant-a",
        input_data={"msg": "hi"},
        idempotency_key="same-request",
    )

    finished = _wait_for_terminal(manager, str(started["id"]))
    assert reused["id"] == started["id"]
    assert len(store.list_all_run_records()) == 1
    assert finished["correlation_id"] == "corr-123"
    assert finished["trace_id"] == "trace-456"


def test_async_workflow_run_manager_reconciles_orphaned_running_runs() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "echo"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")
    running = build_public_run_payload(
        run_id="run_async_orphaned",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.RUNNING,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"msg": "hi"},
        state={"msg": "hi"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
    )
    store.put_run_record(running, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    manager = AsyncWorkflowRunManager(store)

    recovered = manager.reconcile_orphaned_runs()
    assert recovered == 1

    payload = manager.get_run("run_async_orphaned", tenant_id="tenant-a")
    assert payload is not None
    assert payload["status"] == RunStatus.FAILED.value
    assert "worker is no longer running" in str(payload.get("error"))


def test_async_workflow_run_manager_list_runs_reconciles_orphans() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "echo"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")
    running = build_public_run_payload(
        run_id="run_async_orphaned_list",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.RUNNING,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"msg": "hi"},
        state={"msg": "hi"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
    )
    store.put_run_record(running, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    manager = AsyncWorkflowRunManager(store)

    payloads = manager.list_runs(tenant_id="tenant-a", workflow_id=workflow_id)

    assert len(payloads) == 1
    assert payloads[0]["id"] == "run_async_orphaned_list"
    assert payloads[0]["status"] == RunStatus.FAILED.value
    assert "worker is no longer running" in str(payloads[0].get("error"))


def test_sync_lifecycle_project_for_run_persists_phase_status_and_runs() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    run_record = build_public_run_payload(
        run_id="run_async_research_complete",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={
            "research": {
                "claims": [
                    {
                        "statement": "Demand exists",
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "winning_theses": ["SMB teams need simpler intake"],
                "source_links": ["https://example.com/report"],
                "evidence": [
                    {
                        "id": "ev-1",
                        "source_type": "url",
                        "source_ref": "https://example.com/report",
                        "claim": "Demand exists",
                    }
                ],
                "dissent": [
                    {
                        "statement": "Switching cost is high",
                        "severity": "medium",
                        "resolved": True,
                    }
                ],
                "confidence_summary": {"average": 0.82, "floor": 0.71, "accepted": 1},
            }
        },
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(run_record, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    lifecycle_key = "tenant-a:demo-project"
    store.put_surface_record(
        "lifecycle_projects",
        lifecycle_key,
        default_lifecycle_project_record("demo-project", tenant_id="tenant-a"),
    )

    synced = sync_lifecycle_project_for_run(
        store,
        run_record=run_record,
        workflow_id=workflow_id,
        tenant_id="tenant-a",
    )

    project = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced is True
    assert project is not None
    research_status = next(
        item for item in project["phaseStatuses"] if item["phase"] == "research"
    )
    assert research_status["status"] == "completed"
    assert any(item["runId"] == "run_async_research_complete" for item in project["phaseRuns"])


def test_sync_lifecycle_project_for_run_does_not_overwrite_existing_research_with_empty_payload() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    existing_project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    existing_project["research"] = {
        "claims": [{"statement": "Demand exists", "evidence_ids": ["ev-1"], "status": "accepted"}],
        "winning_theses": ["SMB teams need simpler intake"],
        "source_links": ["https://example.com/report"],
        "evidence": [
            {
                "id": "ev-1",
                "source_type": "url",
                "source_ref": "https://example.com/report",
                "claim": "Demand exists",
            }
        ],
        "confidence_summary": {"average": 0.82, "floor": 0.71, "accepted": 1},
    }
    existing_project["phaseStatuses"][0]["status"] = "completed"
    store.put_surface_record("lifecycle_projects", lifecycle_key, existing_project)
    run_record = build_public_run_payload(
        run_id="run_async_research_empty",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(run_record, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = sync_lifecycle_project_for_run(
        store,
        run_record=run_record,
        workflow_id=workflow_id,
        tenant_id="tenant-a",
    )

    project = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced is True
    assert project is not None
    assert project["research"]["winning_theses"] == ["SMB teams need simpler intake"]
    research_status = next(
        item for item in project["phaseStatuses"] if item["phase"] == "research"
    )
    assert research_status["status"] == "completed"


def test_sync_lifecycle_project_for_run_marks_empty_research_run_as_available_without_existing_artifact() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    store.put_surface_record(
        "lifecycle_projects",
        lifecycle_key,
        default_lifecycle_project_record("demo-project", tenant_id="tenant-a"),
    )
    run_record = build_public_run_payload(
        run_id="run_async_research_empty_fresh",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(run_record, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = sync_lifecycle_project_for_run(
        store,
        run_record=run_record,
        workflow_id=workflow_id,
        tenant_id="tenant-a",
    )

    project = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced is True
    assert project is not None
    assert project.get("research") in ({}, None)
    research_status = next(
        item for item in project["phaseStatuses"] if item["phase"] == "research"
    )
    assert research_status["status"] == "available"


def test_async_workflow_run_manager_syncs_lifecycle_project_when_orphan_is_reconciled() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    store.register_workflow_project(workflow_id, _workflow_project(), tenant_id="tenant-a")
    lifecycle_key = "tenant-a:demo-project"
    store.put_surface_record(
        "lifecycle_projects",
        lifecycle_key,
        default_lifecycle_project_record("demo-project", tenant_id="tenant-a"),
    )
    running = build_public_run_payload(
        run_id="run_async_orphaned_lifecycle",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.RUNNING,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
    )
    store.put_run_record(running, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    manager = AsyncWorkflowRunManager(
        store,
        on_terminal_run=lambda run, wf_id, tenant_id: sync_lifecycle_project_for_run(
            store,
            run_record=run,
            workflow_id=wf_id,
            tenant_id=tenant_id,
        ),
    )

    recovered = manager.reconcile_orphaned_runs()

    project = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert recovered == 1
    assert project is not None
    research_status = next(
        item for item in project["phaseStatuses"] if item["phase"] == "research"
    )
    assert research_status["status"] == "available"
    phase_run = next(
        item
        for item in project["phaseRuns"]
        if item["runId"] == "run_async_orphaned_lifecycle"
    )
    assert phase_run["status"] == RunStatus.FAILED.value


def test_reconcile_lifecycle_projects_for_terminal_runs_backfills_stale_project() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    run_record = build_public_run_payload(
        run_id="run_async_backfill",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.FAILED,
        stop_reason=RunStopReason.WORKFLOW_ERROR,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief", "error": "worker exited"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(run_record, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    lifecycle_key = "tenant-a:demo-project"
    project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    project["phaseStatuses"][0]["status"] = "in_progress"
    store.put_surface_record("lifecycle_projects", lifecycle_key, project)

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 1
    assert updated is not None
    research_status = next(
        item for item in updated["phaseStatuses"] if item["phase"] == "research"
    )
    assert research_status["status"] == "available"
    assert any(item["runId"] == "run_async_backfill" for item in updated["phaseRuns"])


def test_reconcile_lifecycle_projects_for_terminal_runs_replays_valid_research_before_empty_rerun() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    store.put_surface_record(
        "lifecycle_projects",
        lifecycle_key,
        default_lifecycle_project_record("demo-project", tenant_id="tenant-a"),
    )
    valid_run = build_public_run_payload(
        run_id="run_async_research_valid",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={
            "research": {
                "claims": [
                    {
                        "statement": "Demand exists",
                        "evidence_ids": ["ev-1"],
                        "status": "accepted",
                    }
                ],
                "winning_theses": ["SMB teams need simpler intake"],
                "source_links": ["https://example.com/report"],
                "evidence": [
                    {
                        "id": "ev-1",
                        "source_type": "url",
                        "source_ref": "https://example.com/report",
                        "claim": "Demand exists",
                    }
                ],
                "confidence_summary": {"average": 0.82, "floor": 0.71, "accepted": 1},
            }
        },
        event_log=[],
        created_at="2026-03-12T00:10:25Z",
        started_at="2026-03-12T00:10:25Z",
        completed_at="2026-03-12T00:11:10Z",
    )
    empty_rerun = build_public_run_payload(
        run_id="run_async_research_empty_latest",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(valid_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    store.put_run_record(empty_rerun, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 2
    assert updated is not None
    assert updated["research"]["winning_theses"] == ["SMB teams need simpler intake"]
    run_ids = [item["runId"] for item in updated["phaseRuns"] if item["phase"] == "research"]
    assert "run_async_research_valid" in run_ids
    assert "run_async_research_empty_latest" in run_ids


def test_reconcile_lifecycle_projects_for_terminal_runs_skips_already_synced_historical_runs() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    existing_project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    existing_project["research"] = {
        "winning_theses": ["SMB teams need simpler intake"],
        "claims": [{"statement": "Demand exists", "status": "accepted"}],
    }
    existing_project["phaseRuns"] = [
        {
            "id": "run_async_research_valid",
            "runId": "run_async_research_valid",
            "phase": "research",
            "status": "completed",
            "createdAt": "2026-03-12T00:11:10Z",
        }
    ]
    store.put_surface_record("lifecycle_projects", lifecycle_key, existing_project)
    valid_run = build_public_run_payload(
        run_id="run_async_research_valid",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"research": {"winning_theses": ["SMB teams need simpler intake"]}},
        event_log=[],
        created_at="2026-03-12T00:10:25Z",
        started_at="2026-03-12T00:10:25Z",
        completed_at="2026-03-12T00:11:10Z",
    )
    store.put_run_record(valid_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 1
    assert updated is not None
    refreshed_run = next(item for item in updated["phaseRuns"] if item["runId"] == "run_async_research_valid")
    assert "totalTokens" in refreshed_run


def test_reconcile_lifecycle_projects_for_terminal_runs_keeps_current_research_when_only_older_runs_are_missing() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    existing_project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    existing_project["research"] = {
        "winning_theses": ["Newest thesis"],
        "claims": [{"statement": "Newest demand thesis", "status": "accepted"}],
    }
    existing_project["phaseRuns"] = [
        {
            "id": "run_async_research_latest",
            "runId": "run_async_research_latest",
            "phase": "research",
            "status": "completed",
            "createdAt": "2026-03-12T00:20:10Z",
        }
    ]
    store.put_surface_record("lifecycle_projects", lifecycle_key, existing_project)
    older_run = build_public_run_payload(
        run_id="run_async_research_older",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"research": {"winning_theses": ["Older thesis"]}},
        event_log=[],
        created_at="2026-03-12T00:10:25Z",
        started_at="2026-03-12T00:10:25Z",
        completed_at="2026-03-12T00:11:10Z",
    )
    latest_run = build_public_run_payload(
        run_id="run_async_research_latest",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:19:25Z",
        started_at="2026-03-12T00:19:25Z",
        completed_at="2026-03-12T00:20:10Z",
    )
    store.put_run_record(older_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    store.put_run_record(latest_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 1
    assert updated is not None
    assert updated["research"]["winning_theses"] == ["Newest thesis"]


def test_reconcile_lifecycle_projects_for_terminal_runs_rebuilds_empty_research_even_if_phase_runs_exist() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    existing_project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    existing_project["phaseRuns"] = [
        {
            "id": "run_async_research_valid",
            "runId": "run_async_research_valid",
            "phase": "research",
            "status": "completed",
            "createdAt": "2026-03-12T00:11:10Z",
        },
        {
            "id": "run_async_research_empty_latest",
            "runId": "run_async_research_empty_latest",
            "phase": "research",
            "status": "completed",
            "createdAt": "2026-03-12T00:16:10Z",
        },
    ]
    store.put_surface_record("lifecycle_projects", lifecycle_key, existing_project)
    valid_run = build_public_run_payload(
        run_id="run_async_research_valid",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={
            "research": {
                "winning_theses": ["Recovered thesis"],
                "claims": [{"statement": "Recovered demand thesis", "status": "accepted"}],
            }
        },
        event_log=[],
        created_at="2026-03-12T00:10:25Z",
        started_at="2026-03-12T00:10:25Z",
        completed_at="2026-03-12T00:11:10Z",
    )
    latest_run = build_public_run_payload(
        run_id="run_async_research_empty_latest",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={"spec": "brief"},
        event_log=[],
        created_at="2026-03-12T00:15:25Z",
        started_at="2026-03-12T00:15:25Z",
        completed_at="2026-03-12T00:16:10Z",
    )
    store.put_run_record(valid_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    store.put_run_record(latest_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 2
    assert updated is not None
    assert updated["research"]["winning_theses"] == ["Recovered thesis"]


def test_reconcile_lifecycle_projects_for_terminal_runs_refreshes_existing_phase_run_without_cost_metrics() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    workflow_id = "lifecycle-research-demo-project"
    lifecycle_key = "tenant-a:demo-project"
    existing_project = default_lifecycle_project_record("demo-project", tenant_id="tenant-a")
    existing_project["research"] = {
        "winning_theses": ["Existing thesis"],
        "claims": [{"statement": "Demand exists", "status": "accepted"}],
    }
    existing_project["phaseRuns"] = [
        {
            "id": "run_async_research_valid",
            "runId": "run_async_research_valid",
            "phase": "research",
            "status": "completed",
            "createdAt": "2026-03-12T00:11:10Z",
            "costUsd": 0.0,
        }
    ]
    store.put_surface_record("lifecycle_projects", lifecycle_key, existing_project)
    valid_run = build_public_run_payload(
        run_id="run_async_research_valid",
        workflow_id=workflow_id,
        project_name="demo-project",
        workflow_name=workflow_id,
        execution_mode="async",
        status=RunStatus.COMPLETED,
        stop_reason=RunStopReason.NONE,
        suspension_reason=RunStopReason.NONE,
        input_data={"spec": "brief"},
        state={
            "research": {
                "winning_theses": ["Existing thesis"],
                "claims": [{"statement": "Demand exists", "status": "accepted"}],
            }
        },
        event_log=[],
        created_at="2026-03-12T00:10:25Z",
        started_at="2026-03-12T00:10:25Z",
        completed_at="2026-03-12T00:11:10Z",
    )
    store.put_run_record(valid_run, workflow_id=workflow_id, tenant_id="tenant-a", parameters={})
    store.put_checkpoint_record(
        {
            "id": "cp-1",
            "run_id": "run_async_research_valid",
            "node_id": "research-judge",
            "created_at": "2026-03-12T00:11:10Z",
            "state_hash": "hash",
            "state_version": 1,
            "state_ref": None,
            "workflow_run_id": "run_async_research_valid",
            "event_log": [
                {
                    "node_id": "research-judge",
                    "llm_events": [
                        {
                            "provider": "anthropic",
                            "model": "claude-sonnet-4-6",
                            "estimated_cost_usd": 0.0,
                            "usage": {
                                "input_tokens": 3000,
                                "output_tokens": 1500,
                                "cache_read_tokens": 0,
                                "cache_write_tokens": 0,
                            },
                        }
                    ],
                }
            ],
        }
    )

    synced = reconcile_lifecycle_projects_for_terminal_runs(store)

    updated = store.get_surface_record("lifecycle_projects", lifecycle_key)
    assert synced == 1
    assert updated is not None
    refreshed_run = next(item for item in updated["phaseRuns"] if item["runId"] == "run_async_research_valid")
    assert refreshed_run["totalTokens"] == 4500
    assert refreshed_run["costMeasured"] is True
    assert refreshed_run["costUsd"] > 0
