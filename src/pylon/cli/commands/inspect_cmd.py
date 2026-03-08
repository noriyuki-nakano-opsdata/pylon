"""pylon inspect command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_state
from pylon.errors import ExitCode
from pylon.observability.query_service import build_run_query_payload


@click.command("inspect")
@click.argument("run_id")
@click.pass_context
def inspect(ctx: click.Context, run_id: str) -> None:
    """Inspect a workflow run by its ID."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    state = load_state()
    run = state["runs"].get(run_id)
    if run is None:
        fail_command(ctx, f"Run not found: {run_id}", exit_code=ExitCode.WORKFLOW_ERROR)
    click.echo(cli_ctx.formatter.render(build_run_query_payload(run)))
