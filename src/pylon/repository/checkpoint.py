"""Checkpoint Repository — Event log persistence (FR-03, ADR-007).

Checkpoints are event logs, NOT state snapshots.
Large state (>1MB) is stored in S3/MinIO; checkpoint contains URI reference.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Checkpoint:
    """Checkpoint record with event log entries."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_run_id: str = ""
    node_id: str = ""
    event_log: list[dict[str, Any]] = field(default_factory=list)
    state_ref: str | None = None  # URI for large state in S3/MinIO
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_event(
        self,
        *,
        input_data: Any,
        llm_response: Any | None = None,
        tool_results: list[Any] | None = None,
        output_data: Any | None = None,
    ) -> None:
        self.event_log.append({
            "node_id": self.node_id,
            "input": input_data,
            "llm_response": llm_response,
            "tool_results": tool_results or [],
            "output": output_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_run_id": self.workflow_run_id,
            "node_id": self.node_id,
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
