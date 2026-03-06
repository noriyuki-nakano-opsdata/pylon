"""pylon inspect command."""

from __future__ import annotations

import click


@click.command("inspect")
@click.argument("run_id")
@click.pass_context
def inspect(ctx: click.Context, run_id: str) -> None:
    """Inspect a workflow run by its ID."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    data = {
        "run_id": run_id,
        "status": "unknown",
        "message": "Run inspection not yet implemented (stub).",
    }
    click.echo(cli_ctx.formatter.render(data))
