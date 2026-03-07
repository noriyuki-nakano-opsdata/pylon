"""Task execution workers and worker pool."""

from __future__ import annotations

import enum
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pylon.errors import PylonError

logger = logging.getLogger(__name__)
from pylon.taskqueue.queue import Task, TaskStatus


class WorkerError(PylonError):
    """Error raised by workers."""

    code = "WORKER_ERROR"
    status_code = 500


class WorkerStatus(enum.Enum):
    IDLE = "idle"
    BUSY = "busy"
    STOPPED = "stopped"


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_id: str
    output: Any = None
    error: str | None = None
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class Worker:
    """A task execution worker."""

    name: str = "worker"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: WorkerStatus = WorkerStatus.IDLE
    current_task_id: str | None = None

    def process(
        self,
        task: Task,
        handler: Callable[[Task], Any],
    ) -> TaskResult:
        """Execute a task using the provided handler."""
        if self.status == WorkerStatus.STOPPED:
            raise WorkerError(
                f"Worker '{self.id}' is stopped",
                details={"worker_id": self.id},
            )
        self.status = WorkerStatus.BUSY
        self.current_task_id = task.id

        start = time.monotonic()
        try:
            output = handler(task)
            duration = time.monotonic() - start
            task.transition_to(TaskStatus.COMPLETED)
            return TaskResult(
                task_id=task.id,
                output=output,
                duration_seconds=duration,
            )
        except Exception:
            logger.exception("Task %s execution failed in worker %s", task.id, self.id)
            duration = time.monotonic() - start
            task.transition_to(TaskStatus.FAILED)
            return TaskResult(
                task_id=task.id,
                error="Task execution failed",
                duration_seconds=duration,
            )
        finally:
            self.status = WorkerStatus.IDLE
            self.current_task_id = None

    def stop(self) -> None:
        self.status = WorkerStatus.STOPPED


class WorkerPool:
    """Manages a pool of workers and dispatches tasks."""

    def __init__(self, size: int = 4) -> None:
        self._workers: list[Worker] = [
            Worker(name=f"worker-{i}") for i in range(size)
        ]

    @property
    def workers(self) -> list[Worker]:
        return list(self._workers)

    def get_idle_worker(self) -> Worker | None:
        for w in self._workers:
            if w.status == WorkerStatus.IDLE:
                return w
        return None

    def dispatch(
        self,
        task: Task,
        handler: Callable[[Task], Any],
    ) -> TaskResult | None:
        """Dispatch a task to an idle worker. Returns None if no workers available."""
        worker = self.get_idle_worker()
        if worker is None:
            return None
        return worker.process(task, handler)

    def active_count(self) -> int:
        return sum(1 for w in self._workers if w.status == WorkerStatus.BUSY)

    def idle_count(self) -> int:
        return sum(1 for w in self._workers if w.status == WorkerStatus.IDLE)

    def stop_all(self) -> None:
        for w in self._workers:
            w.stop()
