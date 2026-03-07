"""Priority task queue with status FSM."""

from __future__ import annotations

import enum
import heapq
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.errors import PylonError


class TaskQueueError(PylonError):
    """Error raised by the task queue."""

    code = "TASK_QUEUE_ERROR"
    status_code = 400


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
    retries: int = 0
    max_retries: int = 3

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
        if task.status not in (TaskStatus.PENDING, TaskStatus.FAILED):
            raise TaskQueueError(
                f"Cannot enqueue task with status {task.status.value}",
                details={"task_id": task.id},
            )
        if task.status == TaskStatus.FAILED:
            task.transition_to(TaskStatus.PENDING)
        self._tasks[task.id] = task
        heapq.heappush(self._heap, task)
        return task.id

    def dequeue(self) -> Task | None:
        """Remove and return the highest-priority pending task."""
        while self._heap:
            task = heapq.heappop(self._heap)
            if task.status == TaskStatus.PENDING:
                task.transition_to(TaskStatus.RUNNING)
                return task
        return None

    def peek(self) -> Task | None:
        """Return the highest-priority pending task without removing it."""
        best: Task | None = None
        for task in self._heap:
            if task.status == TaskStatus.PENDING:
                if best is None or task < best:
                    best = task
        return best

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
        """Re-enqueue a failed task (for retry). Respects max_retries."""
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.FAILED:
            return False
        if task.retries >= task.max_retries:
            return False
        task.transition_to(TaskStatus.PENDING)
        task.retries += 1
        # Rebuild heap: remove stale entries, ensure task is present exactly once
        self._heap = [t for t in self._heap if t.status == TaskStatus.PENDING and t.id != task.id]
        self._heap.append(task)
        heapq.heapify(self._heap)
        return True
