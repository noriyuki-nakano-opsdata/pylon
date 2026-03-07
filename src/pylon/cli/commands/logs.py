"""pylon logs command."""

from __future__ import annotations

import click

from pylon.cli.state import load_state


@click.command()
@click.argument("run_id")
@click.option("--follow", is_flag=True, help="Follow logs until run completion.")
@click.pass_context
def logs(ctx: click.Context, run_id: str, follow: bool) -> None:
    """Show logs for a workflow run."""
    state = load_state()
    run = state["runs"].get(run_id)
    if run is None:
        click.echo(f"Run not found: {run_id}")
        raise SystemExit(1)

    for line in run.get("logs", []):
        click.echo(line)

    if follow:
        click.echo("-- end of buffered logs --")

