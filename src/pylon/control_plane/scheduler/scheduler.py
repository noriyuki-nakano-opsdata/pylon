"""Workflow scheduler with priority queues."""

from __future__ import annotations

import enum
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone


class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(order=False)
class WorkflowTask:
    """A schedulable workflow task."""

    id: str
    workflow_id: str
    tenant_id: str
    priority: int = 5  # 0 (highest) to 9 (lowest)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: TaskStatus = TaskStatus.PENDING

    def __lt__(self, other: WorkflowTask) -> bool:
        # Lower priority number = higher priority; ties broken by creation time
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class WorkflowScheduler:
    """Priority-queue-based workflow scheduler."""

    def __init__(self) -> None:
        self._heap: list[WorkflowTask] = []
        self._tasks: dict[str, WorkflowTask] = {}

    def enqueue(self, task: WorkflowTask) -> None:
        task.status = TaskStatus.PENDING
        self._tasks[task.id] = task
        heapq.heappush(self._heap, task)

    def dequeue(self) -> WorkflowTask | None:
        """Remove and return the highest-priority pending task."""
        while self._heap:
            task = heapq.heappop(self._heap)
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.RUNNING
                return task
        return None

    def peek(self) -> WorkflowTask | None:
        """Return the highest-priority pending task without removing it."""
        for task in self._heap:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.PENDING:
            return False
        task.status = TaskStatus.CANCELLED
        return True

    def list_pending(self) -> list[WorkflowTask]:
        return sorted(
            [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        )

    def size(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
