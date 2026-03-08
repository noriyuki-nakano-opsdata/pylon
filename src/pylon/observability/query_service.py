"""Read-model builders for operator-facing workflow query surfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pylon.observability.run_payload import build_public_run_payload
from pylon.observability.run_record import rebuild_run_record
from pylon.types import RunStatus, RunStopReason

if TYPE_CHECKING:
    from pylon.workflow.replay import ReplayResult


def _base_run_kwargs(run_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(run_payload["id"]),
        "workflow_id": str(run_payload.get("workflow_id", run_payload.get("workflow", ""))),
        "project_name": run_payload.get("project"),
        "workflow_name": run_payload.get("workflow"),
        "execution_mode": str(run_payload.get("execution_mode", "inline")),
        "status": RunStatus(str(run_payload.get("status", RunStatus.PENDING.value))),
        "stop_reason": RunStopReason(
            str(run_payload.get("stop_reason", RunStopReason.NONE.value))
        ),
        "suspension_reason": RunStopReason(
            str(run_payload.get("suspension_reason", RunStopReason.NONE.value))
        ),
        "input_data": run_payload.get("input"),
        "state": dict(run_payload.get("state", {})),
        "goal": run_payload.get("goal"),
        "autonomy": run_payload.get("autonomy"),
        "verification": run_payload.get("verification"),
        "runtime_metrics": run_payload.get("runtime_metrics"),
        "policy_resolution": run_payload.get("policy_resolution"),
        "refinement_context": run_payload.get("refinement_context"),
        "approval_context": run_payload.get("approval_context"),
        "termination_reason": run_payload.get("termination_reason"),
        "active_approval": run_payload.get("active_approval"),
        "approvals": list(run_payload.get("approvals", [])),
        "approval_request_id": run_payload.get("approval_request_id"),
        "state_version": int(run_payload.get("state_version", 0)),
        "state_hash": str(run_payload.get("state_hash", "")),
        "event_log": list(run_payload.get("event_log", [])),
        "checkpoint_ids": list(run_payload.get("checkpoint_ids", [])),
        "queue_task_ids": list(run_payload.get("queue_task_ids", [])),
        "logs": list(run_payload.get("logs", [])),
        "created_at": run_payload.get("created_at"),
        "started_at": run_payload.get("started_at"),
        "completed_at": run_payload.get("completed_at"),
    }


def _merge_passthrough_fields(
    payload: dict[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(payload)
    for key, value in source.items():
        if key not in merged:
            merged[key] = value
    return merged


def build_run_query_payload(run_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a stored run payload into the canonical operator-facing shape."""
    payload = build_public_run_payload(
        **_base_run_kwargs(run_payload),
        view_kind=str(run_payload.get("view_kind", "run")),
        replay=run_payload.get("replay"),
    )
    return _merge_passthrough_fields(payload, run_payload)


def build_replay_query_payload(
    *,
    source_run: Mapping[str, Any],
    checkpoint_id: str,
    replayed: ReplayResult,
    replay_view: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Project replay state into the canonical operator-facing shape."""
    payload = build_public_run_payload(
        run_id=str(source_run["id"]),
        workflow_id=str(source_run.get("workflow_id", source_run.get("workflow", ""))),
        project_name=source_run.get("project"),
        workflow_name=source_run.get("workflow"),
        status=RunStatus(str(replay_view["status"])),
        stop_reason=RunStopReason(str(replay_view["stop_reason"])),
        suspension_reason=RunStopReason(str(replay_view["suspension_reason"])),
        input_data=source_run.get("input"),
        state=replayed.state,
        goal=source_run.get("goal"),
        autonomy=source_run.get("autonomy"),
        verification=source_run.get("verification"),
        runtime_metrics=source_run.get("runtime_metrics"),
        policy_resolution=source_run.get("policy_resolution"),
        refinement_context=source_run.get("refinement_context"),
        approval_context=source_run.get("approval_context"),
        termination_reason=source_run.get("termination_reason"),
        active_approval=replay_view.get("active_approval"),
        approvals=[dict(approval) for approval in approvals],
        approval_request_id=replay_view.get("approval_request_id"),
        state_version=replayed.state_version,
        state_hash=replayed.state_hash,
        event_log=replayed.event_log,
        checkpoint_ids=[checkpoint_id],
        logs=list(source_run.get("logs", [])),
        created_at=source_run.get("created_at"),
        started_at=source_run.get("started_at"),
        completed_at=source_run.get("completed_at"),
        view_kind="replay",
        replay={
            "checkpoint_id": checkpoint_id,
            "source_run": source_run["id"],
            "source_status": source_run.get("status"),
            "source_stop_reason": source_run.get("stop_reason"),
            "source_suspension_reason": source_run.get("suspension_reason"),
            "state_hash_verified": replayed.state_hash_verified,
        },
    )
    return _merge_passthrough_fields(payload, source_run)


def rebuild_run_query_payload(
    run_payload: Mapping[str, Any],
    *,
    status: RunStatus,
    stop_reason: RunStopReason,
    suspension_reason: RunStopReason,
    active_approval: Mapping[str, Any] | None,
    approval_request_id: str | None,
    approvals: Sequence[Mapping[str, Any]] = (),
    logs: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Rebuild a stored run payload after a control-plane transition."""
    updated_record = rebuild_run_record(
        run_payload,
        status=status,
        stop_reason=stop_reason,
        suspension_reason=suspension_reason,
        active_approval=active_approval,
        approvals=approvals,
        approval_request_id=approval_request_id,
        logs=logs,
    )
    payload = build_public_run_payload(**_base_run_kwargs(updated_record))
    return _merge_passthrough_fields(payload, updated_record)
