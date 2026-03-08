"""pylon replay command."""

from __future__ import annotations

import click

from pylon.cli.state import load_state
from pylon.observability.run_payload import build_public_run_payload
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
        click.echo(f"Checkpoint not found: {checkpoint_id}")
        raise SystemExit(1)

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
            build_public_run_payload(
                run_id=source_run_id,
                workflow_id=str(source_run.get("workflow_id", source_run.get("workflow", ""))),
                project_name=source_run.get("project"),
                workflow_name=source_run.get("workflow"),
                status=replay_view["status"],
                stop_reason=replay_view["stop_reason"],
                suspension_reason=replay_view["suspension_reason"],
                input_data=source_run.get("input"),
                state=replayed.state,
                goal=source_run.get("goal"),
                autonomy=source_run.get("autonomy"),
                verification=source_run.get("verification"),
                runtime_metrics=source_run.get("runtime_metrics"),
                policy_resolution=source_run.get("policy_resolution"),
                refinement_context=source_run.get("refinement_context"),
                approval_context=source_run.get("approval_context"),
                termination_reason=source_run.get("termination_reason"),
                active_approval=replay_view["active_approval"],
                approvals=(
                    source_run.get("approvals", [])
                    if replay_view["is_terminal_replay"]
                    else []
                ),
                approval_request_id=replay_view["approval_request_id"],
                state_version=replayed.state_version,
                state_hash=replayed.state_hash,
                event_log=replayed.event_log,
                checkpoint_ids=[checkpoint_id],
                logs=source_run.get("logs", []),
                created_at=source_run.get("created_at"),
                started_at=source_run.get("started_at"),
                completed_at=source_run.get("completed_at"),
                view_kind="replay",
                replay={
                    "checkpoint_id": checkpoint_id,
                    "source_run": source_run_id,
                    "source_status": source_run.get("status"),
                    "source_stop_reason": source_run.get("stop_reason"),
                    "source_suspension_reason": source_run.get("suspension_reason"),
                    "state_hash_verified": replayed.state_hash_verified,
                },
            )
        )
    )
