"""Workflow Repository — Graph definition + run persistence (FR-03).

Stores workflow definitions and run state with event logs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowDefinition:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    tenant_id: str = "default"
    graph: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WorkflowRun:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = ""
    tenant_id: str = "default"
    status: RunStatus = RunStatus.PENDING
    event_log: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def start(self) -> None:
        self.status = RunStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        self.status = RunStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)

    def fail(self, error: str | None = None) -> None:
        self.status = RunStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        if error:
            self.state["error"] = error


class WorkflowRepository:
    """In-memory workflow repository.

    Production uses PostgreSQL via asyncpg.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._runs: dict[str, WorkflowRun] = {}

    # -- Definitions --

    async def create_definition(self, defn: WorkflowDefinition) -> WorkflowDefinition:
        self._definitions[defn.id] = defn
        return defn

    async def get_definition(self, id: str) -> WorkflowDefinition | None:
        return self._definitions.get(id)

    async def list_definitions(
        self, *, tenant_id: str = "default", limit: int = 50
    ) -> list[WorkflowDefinition]:
        results = [d for d in self._definitions.values() if d.tenant_id == tenant_id]
        results.sort(key=lambda d: d.created_at, reverse=True)
        return results[:limit]

    # -- Runs --

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        self._runs[run.id] = run
        return run

    async def get_run(self, id: str) -> WorkflowRun | None:
        return self._runs.get(id)

    async def update_run(self, run: WorkflowRun) -> WorkflowRun:
        self._runs[run.id] = run
        return run

    async def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        tenant_id: str = "default",
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> list[WorkflowRun]:
        results = [r for r in self._runs.values() if r.tenant_id == tenant_id]
        if workflow_id:
            results = [r for r in results if r.workflow_id == workflow_id]
        if status:
            results = [r for r in results if r.status == status]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
