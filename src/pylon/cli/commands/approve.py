"""pylon approve command."""

from __future__ import annotations

import click

from pylon.cli.state import load_state, now_ts, save_state


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

    if deny:
        request["status"] = "rejected"
        if run is not None:
            run["status"] = "cancelled"
            run.setdefault("logs", []).append(f"approval_rejected:{approval_id}")
            run["updated_at"] = now_ts()
        action = "Denied"
    else:
        request["status"] = "approved"
        if run is not None:
            run["status"] = "completed"
            run.setdefault("logs", []).append(f"approval_approved:{approval_id}")
            run["updated_at"] = now_ts()
        action = "Approved"

    request["decided_at"] = now_ts()
    if reason:
        request["reason"] = reason

    save_state(state)

    click.echo(f"{action} approval request '{approval_id}'.")
    if reason:
        click.echo(f"Reason: {reason}")
