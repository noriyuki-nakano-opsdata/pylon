"""Priority task queue with status FSM."""

from __future__ import annotations

import enum
import heapq
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pylon.errors import ExitCode, PylonError


class TaskQueueError(PylonError):
    """Error raised by the task queue."""

    code = "TASK_QUEUE_ERROR"
    status_code = 400
    exit_code = ExitCode.TASK_QUEUE_ERROR


class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_VALID_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.PENDING},  # allow retry -> re-enqueue
    TaskStatus.CANCELLED: set(),
}


@dataclass
class Task:
    """A unit of work with priority and retry tracking."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 5  # 0 (highest) to 9 (lowest)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    retries: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "payload": dict(self.payload),
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "started_at": self.started_at.astimezone(UTC).isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.astimezone(UTC).isoformat() if self.completed_at else None
            ),
            "lease_owner": self.lease_owner,
            "lease_expires_at": (
                self.lease_expires_at.astimezone(UTC).isoformat()
                if self.lease_expires_at
                else None
            ),
            "last_heartbeat_at": (
                self.last_heartbeat_at.astimezone(UTC).isoformat()
                if self.last_heartbeat_at
                else None
            ),
            "retries": self.retries,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Task:
        created_at = _parse_datetime(payload.get("created_at")) or datetime.now(UTC)
        started_at = _parse_datetime(payload.get("started_at"))
        completed_at = _parse_datetime(payload.get("completed_at"))
        lease_expires_at = _parse_datetime(payload.get("lease_expires_at"))
        last_heartbeat_at = _parse_datetime(payload.get("last_heartbeat_at"))
        return cls(
            id=str(payload.get("id", str(uuid.uuid4()))),
            name=str(payload.get("name", "")),
            payload=dict(payload.get("payload", {})),
            priority=int(payload.get("priority", 5)),
            status=TaskStatus(str(payload.get("status", TaskStatus.PENDING.value))),
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            lease_owner=(
                str(payload["lease_owner"])
                if payload.get("lease_owner") not in (None, "")
                else None
            ),
            lease_expires_at=lease_expires_at,
            last_heartbeat_at=last_heartbeat_at,
            retries=int(payload.get("retries", 0)),
            max_retries=int(payload.get("max_retries", 3)),
        )

    def transition_to(self, target: TaskStatus) -> None:
        valid = _VALID_TASK_TRANSITIONS.get(self.status, set())
        if target not in valid:
            raise TaskQueueError(
                f"Invalid task transition: {self.status.value} -> {target.value}",
                details={"task_id": self.id},
            )
        self.status = target
        if target == TaskStatus.RUNNING:
            self.started_at = datetime.now(UTC)
        elif target in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            self.completed_at = datetime.now(UTC)
            self._clear_lease()
        elif target == TaskStatus.CANCELLED:
            self.completed_at = datetime.now(UTC)
            self._clear_lease()

    def reset_to_pending(self, *, increment_retries: bool = False) -> None:
        """Reset a failed or abandoned task back to pending state."""
        self.status = TaskStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self._clear_lease()
        if increment_retries:
            self.retries += 1

    def claim_lease(
        self,
        *,
        lease_owner: str,
        lease_timeout_seconds: float,
        now: datetime | None = None,
    ) -> None:
        """Mark the task as running and assign a renewable lease."""
        effective_now = now or datetime.now(UTC)
        if self.status == TaskStatus.PENDING:
            self.transition_to(TaskStatus.RUNNING)
            self.started_at = effective_now
        elif self.status != TaskStatus.RUNNING:
            raise TaskQueueError(
                f"Cannot claim lease for task in status {self.status.value}",
                details={"task_id": self.id},
            )
        self.lease_owner = lease_owner
        self.last_heartbeat_at = effective_now
        self.lease_expires_at = effective_now + timedelta(seconds=lease_timeout_seconds)

    def heartbeat(
        self,
        *,
        lease_owner: str,
        lease_timeout_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        """Extend the task lease if the caller currently owns it."""
        effective_now = now or datetime.now(UTC)
        if self.status != TaskStatus.RUNNING:
            return False
        if self.lease_owner != lease_owner:
            return False
        if self.lease_expires_at is not None and self.lease_expires_at < effective_now:
            return False
        self.last_heartbeat_at = effective_now
        self.lease_expires_at = effective_now + timedelta(seconds=lease_timeout_seconds)
        return True

    def lease_expired(self, *, now: datetime | None = None) -> bool:
        """Return True when a running task lease has expired."""
        if self.status != TaskStatus.RUNNING or self.lease_expires_at is None:
            return False
        effective_now = now or datetime.now(UTC)
        return self.lease_expires_at <= effective_now

    def _clear_lease(self) -> None:
        self.lease_owner = None
        self.lease_expires_at = None
        self.last_heartbeat_at = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def __lt__(self, other: Task) -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class TaskQueue:
    """Priority-queue-based task queue."""

    def __init__(self) -> None:
        self._heap: list[Task] = []
        self._tasks: dict[str, Task] = {}

    def enqueue(self, task: Task) -> str:
        """Add a task to the queue. Returns the task ID."""
        task.status = TaskStatus.PENDING
        self._tasks[task.id] = task
        heapq.heappush(self._heap, task)
        return task.id

    def dequeue(self) -> Task | None:
        """Remove and return the highest-priority pending task."""
        skipped = 0
        while self._heap:
            task = heapq.heappop(self._heap)
            if task.status == TaskStatus.PENDING:
                task.transition_to(TaskStatus.RUNNING)
                return task
            skipped += 1
        if skipped > 0:
            self._maybe_purge()
        return None

    def dequeue_with_lease(
        self,
        *,
        lease_owner: str,
        lease_timeout_seconds: float,
        now: datetime | None = None,
    ) -> Task | None:
        """Remove and return the highest-priority pending task with a lease."""
        skipped = 0
        while self._heap:
            task = heapq.heappop(self._heap)
            if task.status == TaskStatus.PENDING:
                task.claim_lease(
                    lease_owner=lease_owner,
                    lease_timeout_seconds=lease_timeout_seconds,
                    now=now,
                )
                return task
            skipped += 1
        if skipped > 0:
            self._maybe_purge()
        return None

    def peek(self) -> Task | None:
        """Return the highest-priority pending task without removing it."""
        for task in self._heap:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False
        task.transition_to(TaskStatus.CANCELLED)
        return True

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(
        self,
        status: TaskStatus | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort()
        if limit is not None:
            tasks = tasks[:limit]
        return tasks

    def size(self, status: TaskStatus | None = None) -> int:
        if status is None:
            return len(self._tasks)
        return sum(1 for t in self._tasks.values() if t.status == status)

    def requeue(self, task_id: str) -> bool:
        """Re-enqueue a failed task (for retry)."""
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.FAILED:
            return False
        task.reset_to_pending(increment_retries=True)
        heapq.heappush(self._heap, task)
        return True

    def heartbeat(
        self,
        task_id: str,
        *,
        lease_owner: str,
        lease_timeout_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        return task.heartbeat(
            lease_owner=lease_owner,
            lease_timeout_seconds=lease_timeout_seconds,
            now=now,
        )

    def recover_expired_leases(
        self,
        *,
        now: datetime | None = None,
        include_unleased: bool = False,
    ) -> int:
        """Recover only running tasks whose lease has expired."""
        recovered = 0
        for task in list(self._tasks.values()):
            if task.status != TaskStatus.RUNNING:
                continue
            should_recover = task.lease_expired(now=now) or (
                include_unleased and task.lease_owner is None
            )
            if not should_recover:
                continue
            task.reset_to_pending(increment_retries=True)
            heapq.heappush(self._heap, task)
            recovered += 1
        return recovered

    def purge(self) -> int:
        """Remove non-PENDING tasks from heap and terminal tasks from _tasks.

        Returns the number of terminal tasks removed from _tasks.
        """
        self._heap = [t for t in self._heap if t.status == TaskStatus.PENDING]
        heapq.heapify(self._heap)
        terminal_ids = [
            tid for tid, t in self._tasks.items() if t.is_terminal
        ]
        for tid in terminal_ids:
            del self._tasks[tid]
        return len(terminal_ids)

    def _maybe_purge(self) -> None:
        """Auto-purge when heap has grown much larger than active task count."""
        active_count = sum(
            1 for t in self._tasks.values() if not t.is_terminal
        )
        if len(self._heap) > max(active_count * 2, 16):
            self.purge()


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
