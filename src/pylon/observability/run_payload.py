"""Shared public payload builders for run-oriented operator views."""

from __future__ import annotations

from typing import Any

from pylon.observability.execution_summary import build_execution_summary
from pylon.types import RunStatus, RunStopReason


def build_approval_summary(
    *,
    active_approval: dict[str, Any] | None = None,
    approvals: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Build a normalized approval summary for public operator surfaces."""
    approval_payloads = [dict(approval) for approval in approvals]
    active = dict(active_approval) if isinstance(active_approval, dict) else None
    context = active.get("context", {}) if isinstance(active, dict) else {}
    pending_request_ids = [
        approval.get("id")
        for approval in approval_payloads
        if approval.get("status") == "pending"
    ]

    return {
        "pending": bool(pending_request_ids),
        "active_request_id": active.get("id") if active is not None else None,
        "active_status": active.get("status") if active is not None else None,
        "action": active.get("action") if active is not None else None,
        "autonomy_level": active.get("autonomy_level") if active is not None else None,
        "context_kind": context.get("kind") if isinstance(context, dict) else None,
        "context_reason": context.get("reason") if isinstance(context, dict) else None,
        "binding_plan": context.get("binding_plan") if isinstance(context, dict) else None,
        "binding_effect_envelope": (
            context.get("binding_effect_envelope") if isinstance(context, dict) else None
        ),
        "plan_hash": active.get("plan_hash") if active is not None else None,
        "effect_hash": active.get("effect_hash") if active is not None else None,
        "pending_request_ids": pending_request_ids,
        "approved_request_ids": [
            approval.get("id")
            for approval in approval_payloads
            if approval.get("status") == "approved"
        ],
        "rejected_request_ids": [
            approval.get("id")
            for approval in approval_payloads
            if approval.get("status") == "rejected"
        ],
    }


def build_public_run_payload(
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
    """Build a normalized public run payload shared by CLI, API, and replay."""
    approval_payloads = [dict(approval) for approval in approvals]
    active = dict(active_approval) if isinstance(active_approval, dict) else None
    approval_id = (
        active.get("id") if active is not None else approval_request_id
    )
    execution_summary = build_execution_summary(
        status=status,
        stop_reason=stop_reason,
        suspension_reason=suspension_reason,
        state=dict(state),
        event_log=list(event_log),
        active_approval=active,
    )
    payload: dict[str, Any] = {
        "id": run_id,
        "view_kind": view_kind,
        "project": project_name or workflow_id,
        "workflow": workflow_name or workflow_id,
        "workflow_id": workflow_id,
        "status": status.value,
        "stop_reason": stop_reason.value,
        "suspension_reason": suspension_reason.value,
        "approval_id": approval_id,
        "approval_request_id": approval_id,
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
        "active_approval": active,
        "approvals": approval_payloads,
        "approval_summary": build_approval_summary(
            active_approval=active,
            approvals=approval_payloads,
        ),
        "execution_summary": execution_summary,
        "state_version": state_version,
        "state_hash": state_hash,
        "event_log": list(event_log),
        "checkpoint_ids": list(checkpoint_ids),
        "logs": list(logs),
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    if replay is not None:
        payload["replay"] = dict(replay)
        payload["source_run"] = replay.get("source_run")
        payload["source_status"] = replay.get("source_status")
        payload["source_stop_reason"] = replay.get("source_stop_reason")
        payload["source_suspension_reason"] = replay.get("source_suspension_reason")
        payload["checkpoint_id"] = replay.get("checkpoint_id")
    return payload
