"""pylon agent command group."""

from __future__ import annotations

import click

from pylon.cli.state import load_state


@click.group()
def agent() -> None:
    """Manage Pylon agents."""


@agent.command("list")
@click.pass_context
def agent_list(ctx: click.Context) -> None:
    """List all agents."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    state = load_state()
    names: set[str] = set()
    for run in state["runs"].values():
        for name in run.get("agents", []):
            names.add(name)

    data = [{"id": f"agent-{name}", "name": name, "state": "ready"} for name in sorted(names)]
    click.echo(cli_ctx.formatter.render(data))


@agent.command("status")
@click.argument("agent_id")
@click.pass_context
def agent_status(ctx: click.Context, agent_id: str) -> None:
    """Show agent status."""
    from pylon.cli.main import get_ctx
    cli_ctx = get_ctx(ctx)

    data = {"id": agent_id, "state": "ready"}
    click.echo(cli_ctx.formatter.render(data))


@agent.command("kill")
@click.argument("agent_id")
@click.pass_context
def agent_kill(ctx: click.Context, agent_id: str) -> None:
    """Kill a running agent."""
    click.echo(f"Kill request sent for agent '{agent_id}'.")
