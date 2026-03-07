"""Workflow Repository — Graph definition + run persistence (FR-03).

Stores workflow definitions and run state with event logs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pylon.errors import WorkflowError


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_VALID_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED},
    RunStatus.PAUSED: {RunStatus.RUNNING},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


@dataclass
class WorkflowDefinition:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    tenant_id: str = "default"
    graph: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def _validate_transition(self, target: RunStatus) -> None:
        valid = _VALID_RUN_TRANSITIONS.get(self.status, set())
        if target not in valid:
            raise WorkflowError(
                f"Invalid run transition: {self.status.value} -> {target.value}",
                details={"run_id": self.id, "current": self.status.value, "target": target.value},
            )

    def start(self) -> None:
        self._validate_transition(RunStatus.RUNNING)
        self.status = RunStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def complete(self) -> None:
        self._validate_transition(RunStatus.COMPLETED)
        self.status = RunStatus.COMPLETED
        self.completed_at = datetime.now(UTC)

    def pause(self, reason: str | None = None) -> None:
        self._validate_transition(RunStatus.PAUSED)
        self.status = RunStatus.PAUSED
        if reason:
            self.state["pause_reason"] = reason

    def fail(self, error: str | None = None) -> None:
        self._validate_transition(RunStatus.FAILED)
        self.status = RunStatus.FAILED
        self.completed_at = datetime.now(UTC)
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
