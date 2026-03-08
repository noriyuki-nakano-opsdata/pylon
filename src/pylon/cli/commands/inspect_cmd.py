"""pylon inspect command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_workflow_service
from pylon.errors import ExitCode


@click.command("inspect")
@click.argument("run_id")
@click.pass_context
def inspect(ctx: click.Context, run_id: str) -> None:
    """Inspect a workflow run by its ID."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    workflow_service = load_workflow_service()
    try:
        payload = workflow_service.get_run_payload(run_id)
    except KeyError:
        fail_command(ctx, f"Run not found: {run_id}", exit_code=ExitCode.WORKFLOW_ERROR)
    click.echo(cli_ctx.formatter.render(payload))
