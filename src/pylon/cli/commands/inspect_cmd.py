"""pylon inspect command."""

from __future__ import annotations

import click

from pylon.cli.state import load_state


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
        click.echo(f"Run not found: {run_id}")
        raise SystemExit(1)
    click.echo(cli_ctx.formatter.render(run))
