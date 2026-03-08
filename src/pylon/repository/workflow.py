"""Workflow Repository — Graph definition + run persistence (FR-03).

Stores workflow definitions and run state with event logs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.errors import ConcurrencyError, WorkflowError
from pylon.types import RunStatus, RunStopReason

_VALID_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING},
    RunStatus.RUNNING: {
        RunStatus.WAITING_APPROVAL,
        RunStatus.PAUSED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.WAITING_APPROVAL: {
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
    },
    RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
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
    state_version: int = 0
    state_hash: str = ""
    stop_reason: RunStopReason = RunStopReason.NONE
    suspension_reason: RunStopReason = RunStopReason.NONE
    approval_request_id: str | None = None
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
        self.suspension_reason = RunStopReason.NONE
        self.started_at = datetime.now(UTC)

    def resume(self) -> None:
        self._validate_transition(RunStatus.RUNNING)
        self.status = RunStatus.RUNNING
        self.suspension_reason = RunStopReason.NONE
        self.approval_request_id = None
        if self.started_at is None:
            self.started_at = datetime.now(UTC)

    def complete(self, reason: RunStopReason = RunStopReason.NONE) -> None:
        self._validate_transition(RunStatus.COMPLETED)
        self.status = RunStatus.COMPLETED
        self.stop_reason = reason
        self.suspension_reason = RunStopReason.NONE
        self.approval_request_id = None
        self.completed_at = datetime.now(UTC)

    def pause(self, reason: RunStopReason = RunStopReason.NONE) -> None:
        self._validate_transition(RunStatus.PAUSED)
        self.status = RunStatus.PAUSED
        self.suspension_reason = reason
        if reason != RunStopReason.NONE:
            self.state["pause_reason"] = reason.value

    def wait_for_approval(
        self,
        approval_request_id: str | None = None,
        reason: RunStopReason = RunStopReason.APPROVAL_REQUIRED,
    ) -> None:
        self._validate_transition(RunStatus.WAITING_APPROVAL)
        self.status = RunStatus.WAITING_APPROVAL
        self.suspension_reason = reason
        self.approval_request_id = approval_request_id
        self.state["pause_reason"] = reason.value
        if approval_request_id is not None:
            self.state["approval_request_id"] = approval_request_id

    def fail(
        self,
        error: str | None = None,
        *,
        reason: RunStopReason = RunStopReason.WORKFLOW_ERROR,
    ) -> None:
        self._validate_transition(RunStatus.FAILED)
        self.status = RunStatus.FAILED
        self.stop_reason = reason
        self.suspension_reason = RunStopReason.NONE
        self.approval_request_id = None
        self.completed_at = datetime.now(UTC)
        if error:
            self.state["error"] = error

    def cancel(self, reason: RunStopReason = RunStopReason.EXTERNAL_STOP) -> None:
        self._validate_transition(RunStatus.CANCELLED)
        self.status = RunStatus.CANCELLED
        self.stop_reason = reason
        self.suspension_reason = RunStopReason.NONE
        self.approval_request_id = None
        self.completed_at = datetime.now(UTC)


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

    async def update_run(
        self, run: WorkflowRun, *, expected_version: int | None = None
    ) -> WorkflowRun:
        if expected_version is not None:
            existing = self._runs.get(run.id)
            current = existing.state_version if existing else 0
            if current != expected_version:
                raise ConcurrencyError(
                    f"Version conflict on run {run.id}: "
                    f"expected {expected_version}, got {current}",
                    details={
                        "run_id": run.id,
                        "expected_version": expected_version,
                        "current_version": current,
                    },
                )
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
