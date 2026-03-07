"""Workflow replay helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.errors import WorkflowError
from pylon.workflow.state import compute_state_hash


@dataclass(frozen=True)
class ReplayResult:
    """State reconstructed from an event log."""

    state: dict[str, Any]
    state_version: int
    state_hash: str


class ReplayEngine:
    """Reconstructs workflow state from event logs."""

    @staticmethod
    def replay_event_log(event_log: list[dict[str, Any]]) -> ReplayResult:
        state: dict[str, Any] = {}
        version = 0

        for event in event_log:
            patch = event.get("state_patch")
            if patch is None:
                patch = event.get("output", {})
            if patch:
                state.update(patch)
                version = int(event.get("state_version", version + 1))
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

        return ReplayResult(
            state=state,
            state_version=version,
            state_hash=compute_state_hash(state),
        )
