"""pylon sandbox command group."""

from __future__ import annotations

import click

from pylon.cli.state import load_state, save_state


@click.group(name="sandbox")
def sandbox() -> None:
    """Manage local sandbox records."""


@sandbox.command("list")
@click.pass_context
def sandbox_list(ctx: click.Context) -> None:
    """List sandbox instances tracked by CLI."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    state = load_state()
    items = list(state["sandboxes"].values())
    click.echo(cli_ctx.formatter.render(items))


@sandbox.command("clean")
@click.option("--all", "clean_all", is_flag=True, help="Remove all sandbox records.")
def sandbox_clean(clean_all: bool) -> None:
    """Remove non-running sandbox records."""
    state = load_state()
    sandboxes = state["sandboxes"]
    if clean_all:
        removed = len(sandboxes)
        sandboxes.clear()
    else:
        removable = [
            sandbox_id
            for sandbox_id, item in sandboxes.items()
            if item.get("status") != "running"
        ]
        removed = len(removable)
        for sandbox_id in removable:
            del sandboxes[sandbox_id]
    save_state(state)
    click.echo(f"Removed {removed} sandbox record(s).")

