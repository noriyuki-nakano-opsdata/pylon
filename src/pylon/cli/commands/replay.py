"""pylon replay command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_workflow_service
from pylon.errors import ExitCode


@click.command()
@click.argument("checkpoint_id")
@click.pass_context
def replay(ctx: click.Context, checkpoint_id: str) -> None:
    """Replay a workflow from a checkpoint."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    workflow_service = load_workflow_service()
    try:
        payload = workflow_service.replay_checkpoint(checkpoint_id)
    except KeyError:
        fail_command(
            ctx,
            f"Checkpoint not found: {checkpoint_id}",
            exit_code=ExitCode.WORKFLOW_ERROR,
        )

    click.echo(
        cli_ctx.formatter.render(payload)
    )
