"""Retry policies and dead letter queue."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from pylon.taskqueue.queue import Task


class RetryPolicy(abc.ABC):
    """Base class for retry strategies."""

    @abc.abstractmethod
    def should_retry(self, task: Task) -> bool: ...

    @abc.abstractmethod
    def next_delay(self, task: Task) -> float:
        """Return delay in seconds before the next retry."""
        ...


@dataclass
class FixedRetry(RetryPolicy):
    """Fixed-interval retry policy."""

    max_retries: int = 3
    delay_seconds: float = 1.0

    def should_retry(self, task: Task) -> bool:
        return task.retries < self.max_retries

    def next_delay(self, task: Task) -> float:
        return self.delay_seconds


@dataclass
class ExponentialBackoff(RetryPolicy):
    """Exponential backoff retry policy."""

    max_retries: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    def should_retry(self, task: Task) -> bool:
        return task.retries < self.max_retries

    def next_delay(self, task: Task) -> float:
        delay = self.base_delay_seconds * (2 ** task.retries)
        return min(delay, self.max_delay_seconds)


class DeadLetterQueue:
    """Holds tasks that have exhausted all retries."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())

    def remove(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def size(self) -> int:
        return len(self._tasks)
