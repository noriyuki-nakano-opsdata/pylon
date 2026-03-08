"""pylon replay command."""

from __future__ import annotations

import click

from pylon.cli.errors import fail_command
from pylon.cli.state import load_state
from pylon.errors import ExitCode
from pylon.observability.query_service import build_replay_query_payload
from pylon.types import RunStatus, RunStopReason
from pylon.workflow.replay import ReplayEngine, resolve_replay_view_state


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
        fail_command(
            ctx,
            f"Checkpoint not found: {checkpoint_id}",
            exit_code=ExitCode.WORKFLOW_ERROR,
        )

    source_run_id = checkpoint.get("run_id", "")
    source_run = state["runs"].get(source_run_id, {})
    source_input = source_run.get("input")
    if source_input is None:
        initial_state = {}
    elif isinstance(source_input, dict):
        initial_state = dict(source_input)
    else:
        initial_state = {"input": source_input}
    checkpoint_events = list(checkpoint.get("event_log", []))
    source_events = list(source_run.get("event_log", []))
    max_seq = max(
        (
            int(event.get("seq", 0))
            for event in checkpoint_events
            if event.get("seq") is not None
        ),
        default=0,
    )
    replay_events = source_events
    if max_seq > 0 and source_events:
        replay_events = [
            event for event in source_events if int(event.get("seq", 0)) <= max_seq
        ]
    elif checkpoint_events:
        replay_events = checkpoint_events

    replayed = ReplayEngine.replay_event_log(
        replay_events,
        initial_state=initial_state,
        source_status=RunStatus(str(source_run.get("status", RunStatus.COMPLETED.value))),
        stop_reason=RunStopReason(
            str(source_run.get("stop_reason", RunStopReason.NONE.value))
        ),
        suspension_reason=RunStopReason(
            str(source_run.get("suspension_reason", RunStopReason.NONE.value))
        ),
        active_approval=source_run.get("active_approval"),
    )
    replay_view = resolve_replay_view_state(
        source_status=RunStatus(str(source_run.get("status", RunStatus.COMPLETED.value))),
        stop_reason=RunStopReason(
            str(source_run.get("stop_reason", RunStopReason.NONE.value))
        ),
        suspension_reason=RunStopReason(
            str(source_run.get("suspension_reason", RunStopReason.NONE.value))
        ),
        source_event_count=len(source_events),
        replayed_event_count=len(replay_events),
        active_approval=source_run.get("active_approval"),
        approval_request_id=source_run.get("approval_request_id"),
    )

    click.echo(
        cli_ctx.formatter.render(
            build_replay_query_payload(
                source_run=source_run,
                checkpoint_id=checkpoint_id,
                replayed=replayed,
                replay_view=replay_view,
                approvals=(
                    source_run.get("approvals", [])
                    if replay_view["is_terminal_replay"]
                    else []
                ),
            )
        )
    )
