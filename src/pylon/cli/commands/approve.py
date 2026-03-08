"""pylon approve command."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

logger = logging.getLogger(__name__)

from pylon.approval import ApprovalManager, ApprovalRequest, ApprovalStore
from pylon.cli.state import load_state, now_ts, save_state
from pylon.dsl.parser import load_project
from pylon.observability.run_payload import build_public_run_payload
from pylon.repository.audit import AuditRepository, default_hmac_key
from pylon.runtime import resume_project_sync, serialize_run
from pylon.types import RunStatus, RunStopReason


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@click.command()
@click.argument("approval_id")
@click.option("--deny", is_flag=True, help="Deny the approval request.")
@click.option("--reason", default=None, help="Reason for approval/denial.")
@click.pass_context
def approve(ctx: click.Context, approval_id: str, deny: bool, reason: str | None) -> None:
    """Approve or deny a pending approval request."""
    state = load_state()
    request = state["approvals"].get(approval_id)
    if request is None:
        click.echo(f"Approval request not found: {approval_id}")
        raise SystemExit(1)

    if request.get("status") != "pending":
        click.echo(f"Approval request already decided: {approval_id}")
        raise SystemExit(1)

    run_id = request.get("run_id", "")
    run = state["runs"].get(run_id)

    store = ApprovalStore()
    for payload in state["approvals"].values():
        try:
            approval = ApprovalRequest.from_dict(payload)
        except Exception as exc:
            logger.debug("Skipping malformed approval payload %s: %s", payload.get("id", "?"), exc)
            continue
        _run_sync(store.create(approval))
    manager = ApprovalManager(
        store,
        AuditRepository(hmac_key=default_hmac_key()),
    )

    if deny:
        _run_sync(manager.reject(approval_id, "cli", reason or ""))
        request["status"] = "rejected"
        if run is not None:
            run["status"] = RunStatus.CANCELLED.value
            run["stop_reason"] = RunStopReason.APPROVAL_DENIED.value
            run["suspension_reason"] = RunStopReason.NONE.value
            run.setdefault("logs", []).append(f"approval_rejected:{approval_id}")
            run["updated_at"] = now_ts()
        action = "Denied"
    else:
        _run_sync(manager.approve(approval_id, "cli", comment=reason or ""))
        binding_plan = request.get("context", {}).get("binding_plan")
        binding_effects = request.get("context", {}).get("binding_effect_envelope")
        try:
            _run_sync(
                manager.validate_binding(
                    approval_id,
                    plan=binding_plan,
                    effect_envelope=binding_effects,
                )
            )
        except Exception as exc:
            logger.warning("Binding validation failed for %s: %s", approval_id, exc)
        request["status"] = "approved"
        if run is not None:
            project_path = run.get("project_path")
            if not project_path:
                click.echo(f"Run is missing project path metadata: {run_id}")
                raise SystemExit(1)
            project = load_project(Path(project_path))
            checkpoint_payloads = [
                checkpoint
                for checkpoint in state["checkpoints"].values()
                if checkpoint.get("run_id") == run_id
            ]
            resume_input = run.get("input")
            if resume_input is not None and not isinstance(resume_input, dict):
                resume_input = {"input": resume_input}
            artifacts = resume_project_sync(
                project,
                run,
                input_data=resume_input,
                checkpoints=checkpoint_payloads,
                approvals=list(state["approvals"].values()),
            )
            resumed_run = serialize_run(
                artifacts,
                project_name=run.get("project"),
                workflow_name=run.get("workflow"),
                input_data=run.get("input"),
            )
            resumed_run["project_path"] = project_path
            resumed_run["sandbox_id"] = run.get("sandbox_id")
            resumed_run["agents"] = run.get("agents", [])
            resumed_run["nodes"] = run.get("nodes", [])
            resumed_run["updated_at"] = now_ts()
            resumed_run["logs"] = [
                *run.get("logs", []),
                f"approval_approved:{approval_id}",
                *[
                    line
                    for line in resumed_run.get("logs", [])
                    if line not in run.get("logs", [])
                ],
            ]
            state["runs"][run_id] = resumed_run
            for checkpoint in artifacts.checkpoints:
                checkpoint_payload = checkpoint.to_dict()
                checkpoint_payload["run_id"] = run_id
                state["checkpoints"][checkpoint.id] = checkpoint_payload
            for approval in artifacts.approvals:
                approval_payload = dict(approval)
                approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
                    "context", {}
                ).get("run_id", run_id)
                state["approvals"][approval_payload["id"]] = approval_payload
        action = "Approved"

    for stored_request in _run_sync(store.list()):
        payload = stored_request.to_dict()
        existing = state["approvals"].get(payload["id"], {})
        state["approvals"][payload["id"]] = {**existing, **payload}

    persisted_request = state["approvals"].get(approval_id, request)
    persisted_request["decided_at"] = now_ts()
    if reason:
        persisted_request["reason"] = reason

    if deny and run is not None:
        updated_approvals = list(state["approvals"].values())
        updated_run = build_public_run_payload(
            run_id=str(run["id"]),
            workflow_id=str(run.get("workflow_id", run.get("workflow", "default"))),
            project_name=run.get("project"),
            workflow_name=run.get("workflow"),
            status=RunStatus(str(run["status"])),
            stop_reason=RunStopReason(str(run.get("stop_reason", RunStopReason.NONE.value))),
            suspension_reason=RunStopReason(
                str(run.get("suspension_reason", RunStopReason.NONE.value))
            ),
            input_data=run.get("input"),
            state=dict(run.get("state", {})),
            goal=run.get("goal"),
            autonomy=run.get("autonomy"),
            verification=run.get("verification"),
            runtime_metrics=run.get("runtime_metrics"),
            policy_resolution=run.get("policy_resolution"),
            refinement_context=run.get("refinement_context"),
            approval_context=run.get("approval_context"),
            termination_reason=run.get("termination_reason"),
            active_approval=None,
            approvals=updated_approvals,
            approval_request_id=None,
            state_version=int(run.get("state_version", 0)),
            state_hash=str(run.get("state_hash", "")),
            event_log=list(run.get("event_log", [])),
            checkpoint_ids=list(run.get("checkpoint_ids", [])),
            logs=list(run.get("logs", [])),
            created_at=run.get("created_at"),
            started_at=run.get("started_at"),
            completed_at=run.get("completed_at"),
        )
        for key in ("project_path", "sandbox_id", "agents", "nodes", "updated_at"):
            if key in run:
                updated_run[key] = run[key]
        state["runs"][run_id] = updated_run

    save_state(state)

    click.echo(f"{action} approval request '{approval_id}'.")
    if reason:
        click.echo(f"Reason: {reason}")
