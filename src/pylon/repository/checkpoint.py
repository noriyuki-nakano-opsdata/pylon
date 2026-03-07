"""Checkpoint Repository — Event log persistence (FR-03, ADR-007).

Checkpoints are event logs, NOT state snapshots.
Large state (>1MB) is stored in S3/MinIO; checkpoint contains URI reference.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.safety.scrubber import scrub_secrets


@dataclass
class Checkpoint:
    """Checkpoint record with event log entries."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_run_id: str = ""
    node_id: str = ""
    state_version: int = 0
    state_hash: str = ""
    event_log: list[dict[str, Any]] = field(default_factory=list)
    state_ref: str | None = None  # URI for large state in S3/MinIO
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_event(
        self,
        *,
        node_id: str | None = None,
        input_data: Any,
        seq: int | None = None,
        attempt_id: int | None = None,
        input_state_version: int | None = None,
        input_state_hash: str | None = None,
        llm_response: Any | None = None,
        llm_events: list[Any] | None = None,
        tool_results: list[Any] | None = None,
        tool_events: list[Any] | None = None,
        artifacts: list[Any] | None = None,
        edge_decisions: dict[str, bool] | None = None,
        metrics: dict[str, Any] | None = None,
        state_patch: dict[str, Any] | None = None,
        output_data: Any | None = None,
        state_version: int | None = None,
        state_hash: str | None = None,
    ) -> None:
        patch = state_patch if state_patch is not None else output_data
        self.event_log.append({
            "seq": seq,
            "attempt_id": attempt_id,
            "node_id": node_id or self.node_id,
            "input": scrub_secrets(input_data),
            "input_state_version": input_state_version,
            "input_state_hash": input_state_hash,
            "llm_response": scrub_secrets(llm_response),
            "llm_events": scrub_secrets(llm_events or []),
            "tool_results": scrub_secrets(tool_results or tool_events or []),
            "tool_events": scrub_secrets(tool_events or tool_results or []),
            "artifacts": scrub_secrets(artifacts or []),
            "edge_decisions": edge_decisions or {},
            "metrics": scrub_secrets(metrics or {}),
            "state_patch": patch,
            "output": patch,
            "state_version": state_version if state_version is not None else self.state_version,
            "state_hash": state_hash if state_hash is not None else self.state_hash,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_run_id": self.workflow_run_id,
            "node_id": self.node_id,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "event_log": self.event_log,
            "state_ref": self.state_ref,
            "created_at": self.created_at.isoformat(),
        }


class CheckpointRepository:
    """In-memory checkpoint repository.

    Production implementation uses PostgreSQL via asyncpg.
    """

    def __init__(self) -> None:
        self._store: dict[str, Checkpoint] = {}

    async def get(self, id: str) -> Checkpoint | None:
        return self._store.get(id)

    async def list(
        self, *, workflow_run_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Checkpoint]:
        results = list(self._store.values())
        if workflow_run_id:
            results = [c for c in results if c.workflow_run_id == workflow_run_id]
        results.sort(key=lambda c: c.created_at)
        return results[offset : offset + limit]

    async def create(self, checkpoint: Checkpoint) -> Checkpoint:
        self._store[checkpoint.id] = checkpoint
        return checkpoint

    async def delete(self, id: str) -> bool:
        return self._store.pop(id, None) is not None

    async def get_latest(self, workflow_run_id: str) -> Checkpoint | None:
        """Get latest checkpoint for a workflow run."""
        checkpoints = await self.list(workflow_run_id=workflow_run_id)
        return checkpoints[-1] if checkpoints else None
