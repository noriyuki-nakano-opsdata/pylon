"""pylon logs command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_state
from pylon.errors import ExitCode


@click.command()
@click.argument("run_id")
@click.option("--follow", is_flag=True, help="Follow logs until run completion.")
@click.pass_context
def logs(ctx: click.Context, run_id: str, follow: bool) -> None:
    """Show logs for a workflow run."""
    state = load_state()
    run = state["runs"].get(run_id)
    if run is None:
        fail_command(ctx, f"Run not found: {run_id}", exit_code=ExitCode.WORKFLOW_ERROR)

    for line in run.get("logs", []):
        click.echo(line)

    if follow:
        click.echo("-- end of buffered logs --")
