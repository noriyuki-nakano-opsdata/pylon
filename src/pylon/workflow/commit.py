"""State commit helpers for workflow execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.errors import WorkflowError
from pylon.workflow.state import StatePatch, compute_state_hash


@dataclass(frozen=True)
class CommitResult:
    """Result of applying one or more state patches."""

    state: dict[str, Any]
    state_version: int
    state_hash: str


class CommitEngine:
    """Applies patches deterministically and computes state metadata."""

    @staticmethod
    def apply_patches(
        state: dict[str, Any],
        state_version: int,
        patches: dict[str, StatePatch],
    ) -> CommitResult:
        owners: dict[str, str] = {}
        conflicts: dict[str, set[str]] = {}

        for node_id, patch in patches.items():
            for key in patch.updates:
                owner = owners.get(key)
                if owner is None:
                    owners[key] = node_id
                    continue
                conflicts.setdefault(key, {owner})
                conflicts[key].add(node_id)

        if conflicts:
            details = ", ".join(
                f"{key}={sorted(nodes)}" for key, nodes in sorted(conflicts.items())
            )
            raise WorkflowError(f"State conflict detected for keys: {details}")

        merged = dict(state)
        for patch in patches.values():
            merged.update(patch.updates)

        next_version = state_version + 1
        return CommitResult(
            state=merged,
            state_version=next_version,
            state_hash=compute_state_hash(merged),
        )
