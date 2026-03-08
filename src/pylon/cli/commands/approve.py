"""pylon approve command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_control_plane_store, load_workflow_service
from pylon.errors import ExitCode


@click.command()
@click.argument("approval_id")
@click.option("--deny", is_flag=True, help="Deny the approval request.")
@click.option("--reason", default=None, help="Reason for approval/denial.")
@click.pass_context
def approve(ctx: click.Context, approval_id: str, deny: bool, reason: str | None) -> None:
    """Approve or deny a pending approval request."""
    store = load_control_plane_store()
    workflow_service = load_workflow_service()
    request = store.get_approval_record(approval_id)
    if request is None:
        fail_command(
            ctx,
            f"Approval request not found: {approval_id}",
            exit_code=ExitCode.WORKFLOW_ERROR,
        )
    if request.get("status") != "pending":
        fail_command(
            ctx,
            f"Approval request already decided: {approval_id}",
            exit_code=ExitCode.WORKFLOW_ERROR,
        )

    try:
        if deny:
            workflow_service.reject_request(
                approval_id,
                actor="cli",
                reason=reason,
            )
            action = "Denied"
        else:
            workflow_service.approve_request(
                approval_id,
                actor="cli",
                reason=reason,
            )
            action = "Approved"
    except KeyError as exc:
        fail_command(ctx, str(exc), exit_code=ExitCode.WORKFLOW_ERROR)
    except ValueError as exc:
        fail_command(ctx, str(exc), exit_code=ExitCode.WORKFLOW_ERROR)

    click.echo(f"{action} approval request '{approval_id}'.")
    if reason:
        click.echo(f"Reason: {reason}")
