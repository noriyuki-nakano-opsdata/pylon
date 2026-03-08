"""Workflow scheduler with priority queues."""

from __future__ import annotations

import enum
import heapq
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pylon.errors import PylonError


class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SchedulerCapacityError(PylonError):
    """Raised when the scheduler queue is at capacity."""

    code = "SCHEDULER_CAPACITY_EXCEEDED"
    status_code = 429


class SchedulerDependencyError(PylonError):
    """Raised when dependency metadata is invalid or cyclic."""

    code = "SCHEDULER_DEPENDENCY_ERROR"
    status_code = 409


@dataclass(order=False)
class WorkflowTask:
    """A schedulable workflow task."""

    id: str
    workflow_id: str
    tenant_id: str
    priority: int = 5  # 0 (highest) to 9 (lowest)
    dependencies: set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: TaskStatus = TaskStatus.PENDING

    def __lt__(self, other: WorkflowTask) -> bool:
        # Lower priority number = higher priority; ties broken by creation time
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class WorkflowScheduler:
    """Priority-queue-based workflow scheduler."""

    def __init__(self, *, max_scheduled_tasks: int = 200) -> None:
        self._heap: list[WorkflowTask] = []
        self._tasks: dict[str, WorkflowTask] = {}
        self._max_scheduled_tasks = max_scheduled_tasks

    def enqueue(self, task: WorkflowTask) -> None:
        if self.size() >= self._max_scheduled_tasks:
            raise SchedulerCapacityError(
                "Scheduler queue is at capacity",
                details={
                    "max_scheduled_tasks": self._max_scheduled_tasks,
                    "task_id": task.id,
                },
            )
        task.status = TaskStatus.PENDING
        self._tasks[task.id] = task
        heapq.heappush(self._heap, task)

    def dequeue(self) -> WorkflowTask | None:
        """Remove and return the highest-priority pending task."""
        ready = self._ready_pending_tasks()
        if not ready:
            return None
        task = ready[0]
        task.status = TaskStatus.RUNNING
        return task

    def dequeue_wave(self) -> list[WorkflowTask]:
        """Remove and return all currently ready pending tasks."""
        wave = self._ready_pending_tasks()
        for task in wave:
            task.status = TaskStatus.RUNNING
        return wave

    def complete(self, task_id: str) -> bool:
        """Mark a running task as completed."""
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return False
        task.status = TaskStatus.COMPLETED
        return True

    def peek(self) -> WorkflowTask | None:
        """Return the highest-priority pending task without removing it."""
        ready = self._ready_pending_tasks()
        return ready[0] if ready else None

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

    def compute_waves(self) -> list[list[WorkflowTask]]:
        """Compute dependency waves using Kahn's algorithm."""
        active_tasks = {
            task_id: task
            for task_id, task in self._tasks.items()
            if task.status != TaskStatus.CANCELLED
        }
        if not active_tasks:
            return []

        indegree = {task_id: 0 for task_id in active_tasks}
        dependents: dict[str, set[str]] = {task_id: set() for task_id in active_tasks}

        for task_id, task in active_tasks.items():
            missing = sorted(dep for dep in task.dependencies if dep not in active_tasks)
            if missing:
                raise SchedulerDependencyError(
                    "Task has unknown dependencies",
                    details={"task_id": task_id, "missing_dependencies": missing},
                )
            indegree[task_id] = len(task.dependencies)
            for dep in task.dependencies:
                dependents[dep].add(task_id)

        ready = sorted(
            [active_tasks[task_id] for task_id, degree in indegree.items() if degree == 0]
        )
        visited: set[str] = set()
        waves: list[list[WorkflowTask]] = []

        while ready:
            current_wave = ready
            waves.append(current_wave)
            next_ready_ids: set[str] = set()

            for task in current_wave:
                visited.add(task.id)
                for dependent_id in dependents[task.id]:
                    indegree[dependent_id] -= 1
                    if indegree[dependent_id] == 0:
                        next_ready_ids.add(dependent_id)

            ready = sorted(active_tasks[task_id] for task_id in next_ready_ids)

        if len(visited) != len(active_tasks):
            remaining = sorted(task_id for task_id in active_tasks if task_id not in visited)
            raise SchedulerDependencyError(
                "Task dependency cycle detected",
                details={"remaining_tasks": remaining},
            )

        return waves

    def _ready_pending_tasks(self) -> list[WorkflowTask]:
        return sorted(
            task
            for task in self._tasks.values()
            if task.status == TaskStatus.PENDING
            and all(self._is_dependency_satisfied(dep) for dep in task.dependencies)
        )

    def _is_dependency_satisfied(self, dependency_id: str) -> bool:
        dependency = self._tasks.get(dependency_id)
        return dependency is not None and dependency.status == TaskStatus.COMPLETED
