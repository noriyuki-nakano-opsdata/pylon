"""Bulkhead pattern for concurrency limiting."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class BulkheadFullError(RuntimeError):
    def __init__(self, max_concurrent: int, max_queue: int) -> None:
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        super().__init__(
            f"Bulkhead full: {max_concurrent} active, {max_queue} queued"
        )


@dataclass
class BulkheadStats:
    active: int = 0
    queued: int = 0
    rejected: int = 0
    completed: int = 0


class Bulkhead:
    """Synchronous bulkhead using threading primitives."""

    def __init__(self, max_concurrent: int = 10, max_queue: int = 10) -> None:
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._active_count = 0
        self._queued_count = 0
        self._stats = BulkheadStats()

    @property
    def stats(self) -> BulkheadStats:
        with self._lock:
            return BulkheadStats(
                active=self._stats.active,
                queued=self._stats.queued,
                rejected=self._stats.rejected,
                completed=self._stats.completed,
            )

    def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._active_count < self._max_concurrent:
                self._active_count += 1
                self._stats.active += 1
            elif self._queued_count >= self._max_queue:
                self._stats.rejected += 1
                raise BulkheadFullError(self._max_concurrent, self._max_queue)
            else:
                self._queued_count += 1
                self._stats.queued += 1
                while self._active_count >= self._max_concurrent:
                    self._condition.wait()
                self._queued_count -= 1
                self._stats.queued -= 1
                self._active_count += 1
                self._stats.active += 1

        try:
            return fn(*args, **kwargs)
        finally:
            with self._lock:
                self._active_count -= 1
                self._stats.active -= 1
                self._stats.completed += 1
                self._condition.notify()


class AsyncBulkhead:
    """Async bulkhead using asyncio condition variable."""

    def __init__(self, max_concurrent: int = 10, max_queue: int = 10) -> None:
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._active_count = 0
        self._queued_count = 0
        self._stats = BulkheadStats()

    @property
    def stats(self) -> BulkheadStats:
        return BulkheadStats(
            active=self._stats.active,
            queued=self._stats.queued,
            rejected=self._stats.rejected,
            completed=self._stats.completed,
        )

    async def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        async with self._condition:
            if self._active_count < self._max_concurrent:
                self._active_count += 1
                self._stats.active += 1
            elif self._queued_count >= self._max_queue:
                self._stats.rejected += 1
                raise BulkheadFullError(self._max_concurrent, self._max_queue)
            else:
                self._queued_count += 1
                self._stats.queued += 1
                while self._active_count >= self._max_concurrent:
                    await self._condition.wait()
                self._queued_count -= 1
                self._stats.queued -= 1
                self._active_count += 1
                self._stats.active += 1

        try:
            coro = fn(*args, **kwargs)
            result = await coro
            return result
        finally:
            async with self._condition:
                self._active_count -= 1
                self._stats.active -= 1
                self._stats.completed += 1
                self._condition.notify()
