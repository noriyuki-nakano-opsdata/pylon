"""pylon replay command."""

from __future__ import annotations

import click

from pylon.cli.state import load_state, new_id, now_ts, save_state


@click.command()
@click.argument("checkpoint_id")
@click.pass_context
def replay(ctx: click.Context, checkpoint_id: str) -> None:
    """Replay a workflow from a checkpoint."""
    from pylon.cli.main import get_ctx

    cli_ctx = get_ctx(ctx)
    state = load_state()
    checkpoint = state["checkpoints"].get(checkpoint_id)
    if checkpoint is None:
        click.echo(f"Checkpoint not found: {checkpoint_id}")
        raise SystemExit(1)

    source_run_id = checkpoint.get("run_id", "")
    source_run = state["runs"].get(source_run_id, {})
    replay_run_id = new_id("run_")
    now = now_ts()

    replay_run = {
        "id": replay_run_id,
        "project": source_run.get("project", "unknown"),
        "workflow": source_run.get("workflow", "default"),
        "status": "completed",
        "replay_of": source_run_id,
        "replay_checkpoint": checkpoint_id,
        "agents": source_run.get("agents", []),
        "nodes": source_run.get("nodes", []),
        "checkpoint_ids": [checkpoint_id],
        "logs": [f"replay:{checkpoint_id}", f"source_run:{source_run_id}"],
        "created_at": now,
        "updated_at": now,
    }

    state["runs"][replay_run_id] = replay_run
    save_state(state)

    click.echo(
        cli_ctx.formatter.render(
            {
                "run_id": replay_run_id,
                "status": "completed",
                "source_run": source_run_id,
                "checkpoint_id": checkpoint_id,
            }
        )
    )

