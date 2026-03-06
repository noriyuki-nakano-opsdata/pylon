"""pylon approve command."""

from __future__ import annotations

import click


@click.command()
@click.argument("approval_id")
@click.option("--deny", is_flag=True, help="Deny the approval request.")
@click.option("--reason", default=None, help="Reason for approval/denial.")
@click.pass_context
def approve(ctx: click.Context, approval_id: str, deny: bool, reason: str | None) -> None:
    """Approve or deny a pending approval request."""
    action = "Denied" if deny else "Approved"
    click.echo(f"{action} approval request '{approval_id}'.")
    if reason:
        click.echo(f"Reason: {reason}")
    click.echo("(Stub: AutonomyEnforcer integration pending)")
