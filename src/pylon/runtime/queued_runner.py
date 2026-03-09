"""Queue-backed local runner for workflow dispatch plans."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pylon.runtime.planning import WorkflowDispatchPlan, WorkflowDispatchTask
from pylon.taskqueue import (
    DeadLetterQueue,
    RetryPolicy,
    StoreBackedTaskQueue,
    Task,
    TaskResult,
    TaskStatus,
    Worker,
)
from pylon.taskqueue.store_queue import TaskQueueStore

logger = logging.getLogger(__name__)

DispatchHandler = Callable[[WorkflowDispatchTask, Task], Any]


@dataclass(frozen=True)
class QueuedDispatchStep:
    """Result of a single queue-backed dispatch step."""

    task_id: str | None
    node_id: str | None
    enqueued_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    queue_size: int
    task_status: str | None = None
    lease_owner: str | None = None
    heartbeat_count: int = 0
    retry_scheduled: bool = False
    retry_attempt: int | None = None
    dead_lettered: bool = False
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class QueuedDispatchRun:
    """Summary of draining a dispatch plan through the durable queue."""

    workflow_id: str
    tenant_id: str
    steps: tuple[QueuedDispatchStep, ...]
    completed_task_ids: tuple[str, ...]
    failed_task_ids: tuple[str, ...]
    dead_letter_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    queue_size: int
    recovered_running_tasks: int = 0


class QueuedWorkflowDispatchRunner:
    """Run a workflow dispatch plan through a durable task queue.

    This runner executes the scheduler-friendly dispatch plan, not the full
    workflow state machine. It is intended as the queue/worker bridge for local
    or embedded queued execution modes.
    """

    def __init__(
        self,
        store: TaskQueueStore,
        *,
        queue: StoreBackedTaskQueue | None = None,
        worker: Worker | None = None,
        lease_timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        dead_letter_queue: DeadLetterQueue | None = None,
        recover_running_tasks: bool = True,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self._correlation_id = correlation_id
        self._trace_id = trace_id
        self._store = store
        self._queue = queue or StoreBackedTaskQueue(store)
        self._worker = worker or Worker(name="queue-runner")
        self._lease_timeout_seconds = lease_timeout_seconds
        if heartbeat_interval_seconds is None:
            heartbeat_interval_seconds = max(min(lease_timeout_seconds / 2.0, 5.0), 0.1)
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._retry_policy = retry_policy
        self._dead_letter_queue = dead_letter_queue or DeadLetterQueue()
        self._recovered_running_tasks = 0
        if recover_running_tasks:
            self._recovered_running_tasks = self._queue.recover_expired_leases(
                include_unleased=True
            )
            if self._recovered_running_tasks:
                logger.info("Recovered %d expired leases", self._recovered_running_tasks)

    @property
    def queue(self) -> StoreBackedTaskQueue:
        return self._queue

    @property
    def recovered_running_tasks(self) -> int:
        return self._recovered_running_tasks

    @property
    def retry_policy(self) -> RetryPolicy | None:
        return self._retry_policy

    @property
    def heartbeat_interval_seconds(self) -> float:
        return self._heartbeat_interval_seconds

    @property
    def dead_letter_queue(self) -> DeadLetterQueue:
        return self._dead_letter_queue

    def enqueue_ready_tasks(self, plan: WorkflowDispatchPlan) -> tuple[str, ...]:
        """Enqueue tasks whose dependencies are satisfied and not yet present."""
        existing = {task.id: task for task in self._queue.list()}
        enqueued: list[str] = []
        for dispatch_task in sorted(plan.tasks, key=lambda item: (item.wave_index, item.task_id)):
            if dispatch_task.task_id in existing:
                continue
            dependency_states = [
                existing.get(task_id)
                for task_id in dispatch_task.dependency_task_ids
            ]
            if any(state is None for state in dependency_states):
                continue
            if any(
                state is not None and state.status != TaskStatus.COMPLETED
                for state in dependency_states
            ):
                continue
            payload = {
                    "workflow_id": plan.workflow_id,
                    "tenant_id": plan.tenant_id,
                    "node_id": dispatch_task.node_id,
                    "wave_index": dispatch_task.wave_index,
                    "dependency_task_ids": list(dispatch_task.dependency_task_ids),
            }
            if self._correlation_id is not None:
                payload["correlation_id"] = self._correlation_id
            if self._trace_id is not None:
                payload["trace_id"] = self._trace_id
            task = Task(
                id=dispatch_task.task_id,
                name=f"workflow-dispatch:{dispatch_task.node_id}",
                priority=min(dispatch_task.wave_index, 9),
                payload=payload,
            )
            self._queue.enqueue(task)
            existing[task.id] = task
            enqueued.append(task.id)
            logger.debug("Enqueued task %s for node %s", task.id, dispatch_task.node_id)
        return tuple(enqueued)

    def process_next(
        self,
        plan: WorkflowDispatchPlan,
        *,
        handler: DispatchHandler,
    ) -> QueuedDispatchStep:
        """Process one queued dispatch task."""
        pre_enqueued = self.enqueue_ready_tasks(plan)
        task = self._queue.dequeue(
            lease_owner=self._worker.id,
            lease_timeout_seconds=self._lease_timeout_seconds,
        )
        if task is None:
            return QueuedDispatchStep(
                task_id=None,
                node_id=None,
                enqueued_task_ids=pre_enqueued,
                blocked_task_ids=self._blocked_task_ids(plan),
                queue_size=self._queue.size(),
                task_status=None,
                lease_owner=None,
                heartbeat_count=0,
                retry_scheduled=False,
                retry_attempt=None,
                dead_lettered=False,
                result=None,
            )

        dispatch_task = self._task_index(plan)[task.id]
        leased_owner = task.lease_owner or self._worker.id
        result, heartbeat_count = self._process_with_heartbeat(
            task,
            lambda current: self._worker.process(
                current,
                lambda leased_task: handler(dispatch_task, leased_task),
            ),
        )
        self._persist_task_result(task, result)
        self._apply_retry_policy(task, result)
        task_after = self._queue.get(task.id)
        retry_payload = (
            dict(task_after.payload.get("retry", {}))
            if task_after is not None and isinstance(task_after.payload, dict)
            else {}
        )
        post_enqueued = self.enqueue_ready_tasks(plan)
        enqueued = tuple(dict.fromkeys((*pre_enqueued, *post_enqueued)))
        return QueuedDispatchStep(
            task_id=task.id,
            node_id=dispatch_task.node_id,
            enqueued_task_ids=enqueued,
            blocked_task_ids=self._blocked_task_ids(plan),
            queue_size=self._queue.size(),
            task_status=task_after.status.value if task_after is not None else None,
            lease_owner=leased_owner,
            heartbeat_count=heartbeat_count,
            retry_scheduled=bool(retry_payload.get("scheduled")),
            retry_attempt=(
                int(retry_payload.get("attempt"))
                if retry_payload.get("attempt") is not None
                else (task_after.retries if task_after is not None else None)
            ),
            dead_lettered=bool(
                task_after.payload.get("dead_letter")
                if task_after is not None and isinstance(task_after.payload, dict)
                else False
            ),
            result=self._result_payload(result),
        )

    def drain(
        self,
        plan: WorkflowDispatchPlan,
        *,
        handler: DispatchHandler,
    ) -> QueuedDispatchRun:
        """Drain the queue until no runnable tasks remain."""
        steps: list[QueuedDispatchStep] = []
        while True:
            step = self.process_next(plan, handler=handler)
            steps.append(step)
            if step.task_id is None:
                break

        tasks = {task.id: task for task in self._queue.list()}
        completed = tuple(
            sorted(
                task_id
                for task_id, task in tasks.items()
                if task.status == TaskStatus.COMPLETED
            )
        )
        failed = tuple(
            sorted(
                task_id
                for task_id, task in tasks.items()
                if task.status == TaskStatus.FAILED
            )
        )
        dead_letter = tuple(
            sorted(task.id for task in self._dead_letter_queue.list())
        )
        blocked = self._blocked_task_ids(plan)
        return QueuedDispatchRun(
            workflow_id=plan.workflow_id,
            tenant_id=plan.tenant_id,
            steps=tuple(steps),
            completed_task_ids=completed,
            failed_task_ids=failed,
            dead_letter_task_ids=dead_letter,
            blocked_task_ids=blocked,
            queue_size=self._queue.size(),
            recovered_running_tasks=self._recovered_running_tasks,
        )

    def _task_index(
        self,
        plan: WorkflowDispatchPlan,
    ) -> dict[str, WorkflowDispatchTask]:
        return {task.task_id: task for task in plan.tasks}

    def _persist_task_result(self, task: Task, result: TaskResult) -> None:
        task.payload["result"] = self._result_payload(result)
        self._queue.save(task)

    def _process_with_heartbeat(
        self,
        task: Task,
        handler: Callable[[Task], TaskResult],
    ) -> tuple[TaskResult, int]:
        if (
            self._heartbeat_interval_seconds <= 0
            or task.lease_owner is None
            or self._lease_timeout_seconds <= 0
        ):
            return handler(task), 0

        stop_event = threading.Event()
        heartbeat_count = 0
        heartbeat_lock = threading.Lock()

        def _heartbeat_loop() -> None:
            nonlocal heartbeat_count
            while not stop_event.wait(self._heartbeat_interval_seconds):
                ok = self._queue.heartbeat(
                    task.id,
                    lease_owner=task.lease_owner or self._worker.id,
                    lease_timeout_seconds=self._lease_timeout_seconds,
                )
                if not ok:
                    logger.warning("Heartbeat failed for task %s, lease lost", task.id)
                    break
                with heartbeat_lock:
                    heartbeat_count += 1

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"pylon-heartbeat-{task.id}",
            daemon=True,
        )
        heartbeat_thread.start()
        result: TaskResult | None = None
        try:
            result = handler(task)
        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=max(self._heartbeat_interval_seconds * 2.0, 0.5))
        with heartbeat_lock:
            final_count = heartbeat_count
        if result is None:
            raise RuntimeError("handler did not return a TaskResult")
        return result, final_count

    def _apply_retry_policy(self, task: Task, result: TaskResult) -> None:
        if result.success:
            task.payload.pop("retry", None)
            task.payload.pop("dead_letter", None)
            self._queue.save(task)
            return
        if self._retry_policy is not None and self._retry_policy.should_retry(task):
            delay_seconds = self._retry_policy.next_delay(task)
            logger.info("Scheduling retry %d for task %s", task.retries + 1, task.id)
            task.payload["retry"] = {
                "scheduled": True,
                "delay_seconds": delay_seconds,
                "attempt": task.retries + 1,
            }
            self._queue.save(task)
            self._queue.requeue(task.id)
            retry_task = self._queue.get(task.id)
            if retry_task is not None:
                retry_task.payload["retry"] = {
                    "scheduled": True,
                    "delay_seconds": delay_seconds,
                    "attempt": retry_task.retries,
                }
                self._queue.save(retry_task)
            return
        logger.warning("Task %s dead-lettered after %d retries", task.id, task.retries)
        task.payload["dead_letter"] = True
        task.payload["retry"] = {
            "scheduled": False,
            "delay_seconds": 0.0,
            "attempt": task.retries,
        }
        self._dead_letter_queue.add(task)
        self._queue.save(task)

    def _blocked_task_ids(self, plan: WorkflowDispatchPlan) -> tuple[str, ...]:
        tasks = {task.id: task for task in self._queue.list()}
        blocked: list[str] = []
        for dispatch_task in plan.tasks:
            if dispatch_task.task_id in tasks:
                continue
            dependency_states = [
                tasks.get(task_id)
                for task_id in dispatch_task.dependency_task_ids
            ]
            if any(
                state is not None
                and (
                    state.status == TaskStatus.CANCELLED
                    or (
                        state.status == TaskStatus.FAILED
                        and bool(state.payload.get("dead_letter"))
                    )
                )
                for state in dependency_states
            ):
                blocked.append(dispatch_task.task_id)
        return tuple(sorted(blocked))

    @staticmethod
    def _result_payload(result: TaskResult) -> dict[str, Any]:
        return {
            "task_id": result.task_id,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "error_code": result.error_code,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
        }
