"""Workflow replay helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.errors import WorkflowError
from pylon.observability.execution_summary import build_execution_summary
from pylon.types import RunStatus, RunStopReason
from pylon.workflow.state import compute_state_hash


@dataclass(frozen=True)
class ReplayResult:
    """State reconstructed from an event log."""

    state: dict[str, Any]
    state_version: int
    state_hash: str
    event_log: list[dict[str, Any]]
    execution_summary: dict[str, Any]
    state_hash_verified: bool = False


class ReplayEngine:
    """Reconstructs workflow state from event logs."""

    @staticmethod
    def replay_event_log(
        event_log: list[dict[str, Any]],
        *,
        initial_state: dict[str, Any] | None = None,
        initial_version: int = 0,
        source_status: RunStatus = RunStatus.COMPLETED,
        stop_reason: RunStopReason = RunStopReason.NONE,
        suspension_reason: RunStopReason = RunStopReason.NONE,
        active_approval: dict[str, Any] | None = None,
    ) -> ReplayResult:
        state: dict[str, Any] = dict(initial_state or {})
        version = initial_version
        state_hash_verified = False
        verification_disabled = False

        for event in event_log:
            patch = event.get("state_patch")
            if patch is None:
                patch = event.get("output")
            if patch is None:
                continue
            if patch:  # Skip empty dicts to avoid unnecessary version bumps
                state.update(patch)
                version = int(event.get("state_version", version + 1))
                if event.get("state_patch_scrubbed"):
                    verification_disabled = True
                    continue
                if verification_disabled:
                    continue
                computed_hash = compute_state_hash(state)
                expected_hash = event.get("state_hash")
                if expected_hash and expected_hash != computed_hash:
                    raise WorkflowError(
                        "Replay state hash mismatch",
                        details={
                            "node_id": event.get("node_id"),
                            "expected_hash": expected_hash,
                            "computed_hash": computed_hash,
                        },
                    )
                if expected_hash:
                    state_hash_verified = True

        return ReplayResult(
            state=state,
            state_version=version,
            state_hash=compute_state_hash(state),
            event_log=list(event_log),
            execution_summary=build_execution_summary(
                status=source_status,
                stop_reason=stop_reason,
                suspension_reason=suspension_reason,
                state=state,
                event_log=list(event_log),
                active_approval=active_approval,
            ),
            state_hash_verified=state_hash_verified,
        )


def resolve_replay_view_state(
    *,
    source_status: RunStatus,
    stop_reason: RunStopReason,
    suspension_reason: RunStopReason,
    source_event_count: int,
    replayed_event_count: int,
    active_approval: dict[str, Any] | None = None,
    approval_request_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the public-facing run state for a replay view.

    A replay of an intermediate checkpoint should not claim the terminal state of
    the source run. Only a replay that reaches the source frontier inherits the
    source status/reasons/active approval.
    """
    is_terminal_replay = replayed_event_count >= source_event_count
    if is_terminal_replay:
        return {
            "status": source_status,
            "stop_reason": stop_reason,
            "suspension_reason": suspension_reason,
            "active_approval": active_approval,
            "approval_request_id": approval_request_id,
            "is_terminal_replay": True,
        }
    return {
        "status": RunStatus.RUNNING,
        "stop_reason": RunStopReason.NONE,
        "suspension_reason": RunStopReason.NONE,
        "active_approval": None,
        "approval_request_id": None,
        "is_terminal_replay": False,
    }
