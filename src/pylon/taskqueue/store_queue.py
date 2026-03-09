"""Store-backed task queue for durable local or embedded execution."""

from __future__ import annotations

import heapq
import logging
import threading
from datetime import datetime
from typing import Protocol, runtime_checkable

from pylon.taskqueue.queue import Task, TaskStatus

logger = logging.getLogger(__name__)


@runtime_checkable
class TaskQueueStore(Protocol):
    """Persistence contract required by the durable task queue adapter."""

    def get_queue_task_record(self, task_id: str) -> dict | None: ...

    def put_queue_task_record(self, task_payload: dict) -> None: ...

    def delete_queue_task_record(self, task_id: str) -> bool: ...

    def list_queue_task_records(self, *, status: str | None = None) -> list[dict]: ...


class StoreBackedTaskQueue:
    """TaskQueue semantics backed by a pluggable persistent store."""

    def __init__(self, store: TaskQueueStore) -> None:
        self._store = store
        self._tasks: dict[str, Task] = {}
        self._heap: list[Task] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._heap.clear()
            for payload in self._store.list_queue_task_records():
                task = Task.from_dict(payload)
                self._tasks[task.id] = task
                if task.status == TaskStatus.PENDING:
                    heapq.heappush(self._heap, task)

    def _persist_task(self, task: Task) -> None:
        self._tasks[task.id] = task
        self._store.put_queue_task_record(task.to_dict())

    def save(self, task: Task) -> None:
        """Persist the current state of an already managed task."""
        with self._lock:
            self._persist_task(task)

    def enqueue(self, task: Task) -> str:
        with self._lock:
            task.status = TaskStatus.PENDING
            self._persist_task(task)
            heapq.heappush(self._heap, task)
            logger.debug("Enqueued task %s (priority=%d)", task.id, task.priority)
            return task.id

    def dequeue(
        self,
        *,
        lease_owner: str | None = None,
        lease_timeout_seconds: float | None = None,
        now: datetime | None = None,
    ) -> Task | None:
        with self._lock:
            skipped = 0
            while self._heap:
                task = heapq.heappop(self._heap)
                current = self._tasks.get(task.id)
                if current is None:
                    skipped += 1
                    continue
                if current.status == TaskStatus.PENDING:
                    if lease_owner is not None and lease_timeout_seconds is not None:
                        current.claim_lease(
                            lease_owner=lease_owner,
                            lease_timeout_seconds=lease_timeout_seconds,
                            now=now,
                        )
                    else:
                        current.transition_to(TaskStatus.RUNNING)
                    self._persist_task(current)
                    logger.debug("Dequeued task %s (lease_owner=%s)", current.id, lease_owner)
                    return current
                skipped += 1
            if skipped > 0:
                self._maybe_purge()
            return None

    def peek(self) -> Task | None:
        with self._lock:
            for task in self._heap:
                current = self._tasks.get(task.id)
                if current is not None and current.status == TaskStatus.PENDING:
                    return current
            return None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return False
            task.transition_to(TaskStatus.CANCELLED)
            self._persist_task(task)
            logger.debug("Cancelled task %s", task_id)
            return True

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(
        self,
        status: TaskStatus | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
            if status is not None:
                tasks = [task for task in tasks if task.status == status]
            tasks.sort()
            if limit is not None:
                tasks = tasks[:limit]
            return tasks

    def size(self, status: TaskStatus | None = None) -> int:
        with self._lock:
            if status is None:
                return len(self._tasks)
            return sum(1 for task in self._tasks.values() if task.status == status)

    def requeue(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.FAILED:
                return False
            task.reset_to_pending(increment_retries=True)
            self._persist_task(task)
            heapq.heappush(self._heap, task)
            logger.debug("Requeued task %s (retries=%d)", task_id, task.retries)
            return True

    def heartbeat(
        self,
        task_id: str,
        *,
        lease_owner: str,
        lease_timeout_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            ok = task.heartbeat(
                lease_owner=lease_owner,
                lease_timeout_seconds=lease_timeout_seconds,
                now=now,
            )
            if ok:
                self._persist_task(task)
            logger.debug("Heartbeat task %s owner=%s ok=%s", task_id, lease_owner, ok)
            return ok

    def recover_expired_leases(
        self,
        *,
        now: datetime | None = None,
        include_unleased: bool = False,
    ) -> int:
        """Recover running tasks whose lease has expired."""
        with self._lock:
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
                self._persist_task(task)
                heapq.heappush(self._heap, task)
                recovered += 1
            if recovered:
                logger.info("Recovered %d expired leases", recovered)
            return recovered

    def recover_running(self) -> int:
        """Backward-compatible alias for recovering recoverable running tasks."""
        return self.recover_expired_leases(include_unleased=True)

    def purge(self) -> int:
        with self._lock:
            self._heap = [task for task in self._heap if task.status == TaskStatus.PENDING]
            heapq.heapify(self._heap)
            terminal_ids = [task_id for task_id, task in self._tasks.items() if task.is_terminal]
            for task_id in terminal_ids:
                self._tasks.pop(task_id, None)
                self._store.delete_queue_task_record(task_id)
            return len(terminal_ids)

    def _maybe_purge(self) -> None:
        active_count = sum(1 for task in self._tasks.values() if not task.is_terminal)
        if len(self._heap) > max(active_count * 2, 16):
            self.purge()
