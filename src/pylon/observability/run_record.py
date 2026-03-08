"""Command-side builders for persisted workflow run records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pylon.types import RunStatus, RunStopReason


def build_run_record(
    *,
    run_id: str,
    workflow_id: str,
    status: RunStatus,
    stop_reason: RunStopReason,
    suspension_reason: RunStopReason,
    state: dict[str, Any],
    event_log: list[dict[str, Any]],
    project_name: str | None = None,
    workflow_name: str | None = None,
    input_data: Any = None,
    goal: dict[str, Any] | None = None,
    autonomy: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    runtime_metrics: dict[str, Any] | None = None,
    policy_resolution: dict[str, Any] | None = None,
    refinement_context: str | None = None,
    approval_context: str | None = None,
    termination_reason: str | None = None,
    active_approval: dict[str, Any] | None = None,
    approvals: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    approval_request_id: str | None = None,
    state_version: int = 0,
    state_hash: str = "",
    checkpoint_ids: list[str] | tuple[str, ...] = (),
    logs: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    view_kind: str = "run",
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical stored run record."""
    payload = {
        "id": run_id,
        "view_kind": view_kind,
        "project": project_name or workflow_id,
        "workflow": workflow_name or workflow_id,
        "workflow_id": workflow_id,
        "status": status.value,
        "stop_reason": stop_reason.value,
        "suspension_reason": suspension_reason.value,
        "approval_request_id": approval_request_id,
        "input": input_data,
        "state": dict(state),
        "goal": goal,
        "autonomy": autonomy,
        "verification": verification,
        "runtime_metrics": runtime_metrics,
        "policy_resolution": policy_resolution,
        "refinement_context": refinement_context,
        "approval_context": approval_context,
        "termination_reason": termination_reason,
        "active_approval": (
            dict(active_approval) if isinstance(active_approval, dict) else None
        ),
        "approvals": [dict(approval) for approval in approvals],
        "state_version": state_version,
        "state_hash": state_hash,
        "event_log": list(event_log),
        "checkpoint_ids": list(checkpoint_ids),
        "logs": list(logs),
        "created_at": created_at,
        "started_at": started_at,
    }
    if replay is not None:
        payload["replay"] = dict(replay)
    return payload


def rebuild_run_record(
    run_record: Mapping[str, Any],
    *,
    status: RunStatus,
    stop_reason: RunStopReason,
    suspension_reason: RunStopReason,
    active_approval: Mapping[str, Any] | None,
    approval_request_id: str | None,
    approvals: Sequence[Mapping[str, Any]] = (),
    logs: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Rebuild a stored run record after a control-plane state transition."""
    payload = build_run_record(
        run_id=str(run_record["id"]),
        workflow_id=str(run_record.get("workflow_id", run_record.get("workflow", ""))),
        project_name=run_record.get("project"),
        workflow_name=run_record.get("workflow"),
        status=status,
        stop_reason=stop_reason,
        suspension_reason=suspension_reason,
        input_data=run_record.get("input"),
        state=dict(run_record.get("state", {})),
        goal=run_record.get("goal"),
        autonomy=run_record.get("autonomy"),
        verification=run_record.get("verification"),
        runtime_metrics=run_record.get("runtime_metrics"),
        policy_resolution=run_record.get("policy_resolution"),
        refinement_context=run_record.get("refinement_context"),
        approval_context=run_record.get("approval_context"),
        termination_reason=run_record.get("termination_reason"),
        active_approval=(
            dict(active_approval) if active_approval is not None else None
        ),
        approvals=[dict(approval) for approval in approvals],
        approval_request_id=approval_request_id,
        state_version=int(run_record.get("state_version", 0)),
        state_hash=str(run_record.get("state_hash", "")),
        event_log=list(run_record.get("event_log", [])),
        checkpoint_ids=list(run_record.get("checkpoint_ids", [])),
        logs=list(logs) if logs is not None else list(run_record.get("logs", [])),
        created_at=run_record.get("created_at"),
        started_at=run_record.get("started_at"),
        completed_at=run_record.get("completed_at"),
        view_kind=str(run_record.get("view_kind", "run")),
        replay=run_record.get("replay"),
    )
    for key, value in run_record.items():
        if key not in payload:
            payload[key] = value
    return payload
