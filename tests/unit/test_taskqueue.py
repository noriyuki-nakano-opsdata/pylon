"""Tests for task queue, workers, scheduler, and retry policies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pylon.taskqueue.queue import Task, TaskQueue, TaskQueueError, TaskStatus
from pylon.taskqueue.worker import Worker, WorkerPool, WorkerStatus, TaskResult, WorkerError
from pylon.taskqueue.scheduler import (
    CronExpression,
    ScheduleType,
    SchedulerError,
    TaskScheduler,
)
from pylon.taskqueue.retry import (
    DeadLetterQueue,
    ExponentialBackoff,
    FixedRetry,
)


# --- Helper ---

def _task(name: str = "test", priority: int = 5) -> Task:
    return Task(name=name, priority=priority)


def _ok_handler(task: Task) -> str:
    return f"done:{task.name}"


def _fail_handler(task: Task) -> str:
    raise ValueError(f"boom:{task.name}")


# === TaskQueue Tests ===


class TestTaskQueue:
    def test_enqueue_and_dequeue(self):
        q = TaskQueue()
        task = _task("t1")
        tid = q.enqueue(task)
        assert tid == task.id
        result = q.dequeue()
        assert result is not None
        assert result.id == tid
        assert result.status == TaskStatus.RUNNING

    def test_dequeue_empty(self):
        q = TaskQueue()
        assert q.dequeue() is None

    def test_priority_order(self):
        q = TaskQueue()
        q.enqueue(_task("low", 9))
        q.enqueue(_task("high", 0))
        q.enqueue(_task("mid", 5))
        assert q.dequeue().name == "high"
        assert q.dequeue().name == "mid"
        assert q.dequeue().name == "low"

    def test_peek(self):
        q = TaskQueue()
        q.enqueue(_task("t1", 3))
        peeked = q.peek()
        assert peeked is not None and peeked.name == "t1"
        assert q.size(TaskStatus.PENDING) == 1

    def test_cancel_pending(self):
        q = TaskQueue()
        task = _task()
        q.enqueue(task)
        assert q.cancel(task.id) is True
        assert task.status == TaskStatus.CANCELLED
        assert q.dequeue() is None

    def test_peek_skips_cancelled(self):
        """peek() must return highest-priority PENDING task even when cancelled tasks exist."""
        q = TaskQueue()
        q.enqueue(_task("high", 0))
        q.enqueue(_task("low", 9))
        # Cancel the high-priority task
        high = q.peek()
        q.cancel(high.id)
        peeked = q.peek()
        assert peeked is not None
        assert peeked.name == "low"

    def test_peek_returns_best_priority_with_mixed_statuses(self):
        """peek() must scan entire heap to find true minimum priority."""
        q = TaskQueue()
        q.enqueue(_task("p5", 5))
        q.enqueue(_task("p1", 1))
        q.enqueue(_task("p3", 3))
        # Cancel p1 so p3 should be returned
        p1 = q.get(q.list()[0].id)
        # Find and cancel the priority-1 task
        for t in q.list():
            if t.name == "p1":
                q.cancel(t.id)
                break
        peeked = q.peek()
        assert peeked is not None
        assert peeked.name == "p3"

    def test_cancel_nonexistent(self):
        q = TaskQueue()
        assert q.cancel("nonexistent") is False

    def test_cancel_completed_fails(self):
        q = TaskQueue()
        task = _task()
        q.enqueue(task)
        t = q.dequeue()
        t.transition_to(TaskStatus.COMPLETED)
        assert q.cancel(t.id) is False

    def test_get(self):
        q = TaskQueue()
        task = _task()
        q.enqueue(task)
        assert q.get(task.id) is task
        assert q.get("nonexistent") is None

    def test_list_all(self):
        q = TaskQueue()
        q.enqueue(_task("a"))
        q.enqueue(_task("b"))
        assert len(q.list()) == 2

    def test_list_by_status(self):
        q = TaskQueue()
        q.enqueue(_task("a"))
        q.enqueue(_task("b"))
        q.dequeue()  # one becomes RUNNING
        assert len(q.list(status=TaskStatus.PENDING)) == 1
        assert len(q.list(status=TaskStatus.RUNNING)) == 1

    def test_list_with_limit(self):
        q = TaskQueue()
        for i in range(5):
            q.enqueue(_task(f"t{i}"))
        assert len(q.list(limit=3)) == 3

    def test_size(self):
        q = TaskQueue()
        assert q.size() == 0
        q.enqueue(_task())
        q.enqueue(_task())
        assert q.size() == 2

    def test_requeue_failed(self):
        q = TaskQueue()
        task = _task()
        q.enqueue(task)
        t = q.dequeue()
        t.transition_to(TaskStatus.FAILED)
        assert q.requeue(t.id) is True
        assert t.status == TaskStatus.PENDING
        assert t.retries == 1

    def test_requeue_non_failed_returns_false(self):
        q = TaskQueue()
        task = _task()
        q.enqueue(task)
        assert q.requeue(task.id) is False  # still PENDING


class TestTaskFSM:
    def test_valid_transition(self):
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

    def test_invalid_transition_raises(self):
        task = _task()
        with pytest.raises(TaskQueueError):
            task.transition_to(TaskStatus.COMPLETED)  # PENDING -> COMPLETED invalid

    def test_completed_sets_completed_at(self):
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        task.transition_to(TaskStatus.COMPLETED)
        assert task.completed_at is not None

    def test_is_terminal(self):
        task = _task()
        assert not task.is_terminal
        task.transition_to(TaskStatus.RUNNING)
        task.transition_to(TaskStatus.COMPLETED)
        assert task.is_terminal


# === Worker Tests ===


class TestWorker:
    def test_process_success(self):
        w = Worker(name="w1")
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        result = w.process(task, _ok_handler)
        assert result.success
        assert result.output == "done:test"
        assert task.status == TaskStatus.COMPLETED
        assert w.status == WorkerStatus.IDLE

    def test_process_failure(self):
        w = Worker(name="w1")
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        result = w.process(task, _fail_handler)
        assert not result.success
        assert "boom" in result.error
        assert task.status == TaskStatus.FAILED

    def test_process_stopped_worker_raises(self):
        w = Worker(name="w1")
        w.stop()
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        with pytest.raises(WorkerError):
            w.process(task, _ok_handler)

    def test_duration_tracked(self):
        w = Worker(name="w1")
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        result = w.process(task, _ok_handler)
        assert result.duration_seconds >= 0


class TestWorkerPool:
    def test_dispatch(self):
        pool = WorkerPool(size=2)
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        result = pool.dispatch(task, _ok_handler)
        assert result is not None
        assert result.success

    def test_idle_and_active_count(self):
        pool = WorkerPool(size=3)
        assert pool.idle_count() == 3
        assert pool.active_count() == 0

    def test_stop_all(self):
        pool = WorkerPool(size=2)
        pool.stop_all()
        assert pool.idle_count() == 0
        task = _task()
        task.transition_to(TaskStatus.RUNNING)
        assert pool.dispatch(task, _ok_handler) is None


# === Scheduler Tests ===


class TestCronExpression:
    def test_every_minute(self):
        cron = CronExpression("* * * * *")
        now = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        nxt = cron.next_run_after(now)
        assert nxt == datetime(2026, 3, 7, 12, 1, 0, tzinfo=timezone.utc)

    def test_every_hour(self):
        cron = CronExpression("0 * * * *")
        now = datetime(2026, 3, 7, 12, 30, 0, tzinfo=timezone.utc)
        nxt = cron.next_run_after(now)
        assert nxt == datetime(2026, 3, 7, 13, 0, 0, tzinfo=timezone.utc)

    def test_daily_at_midnight(self):
        cron = CronExpression("0 0 * * *")
        now = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        nxt = cron.next_run_after(now)
        assert nxt == datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc)

    def test_every_5_minutes(self):
        cron = CronExpression("*/5 * * * *")
        now = datetime(2026, 3, 7, 12, 3, 0, tzinfo=timezone.utc)
        nxt = cron.next_run_after(now)
        assert nxt == datetime(2026, 3, 7, 12, 5, 0, tzinfo=timezone.utc)

    def test_invalid_expression_raises(self):
        with pytest.raises(SchedulerError):
            CronExpression("bad")

    def test_step_zero_rejected(self):
        """*/0 must be rejected at parse time, not cause ZeroDivisionError at runtime."""
        with pytest.raises(SchedulerError):
            CronExpression("*/0 * * * *")

    def test_step_zero_in_other_fields(self):
        with pytest.raises(SchedulerError):
            CronExpression("* */0 * * *")


class TestTaskScheduler:
    def test_schedule_once(self):
        sched = TaskScheduler()
        task = _task("job1")
        run_at = datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)
        entry = sched.schedule(task, run_at)
        assert entry.schedule_type == ScheduleType.ONCE

    def test_get_due_tasks_once(self):
        sched = TaskScheduler()
        past = datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc)
        future = datetime(2026, 3, 7, 20, 0, tzinfo=timezone.utc)
        sched.schedule(_task("past"), past)
        sched.schedule(_task("future"), future)
        now = datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)
        due = sched.get_due_tasks(now)
        assert len(due) == 1
        assert due[0].task.name == "past"

    def test_mark_run_disables_once(self):
        sched = TaskScheduler()
        run_at = datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc)
        entry = sched.schedule(_task(), run_at)
        sched.mark_run(entry.id)
        assert entry.enabled is False

    def test_schedule_recurring(self):
        sched = TaskScheduler()
        entry = sched.schedule_recurring(_task("cron-job"), "* * * * *")
        assert entry.schedule_type == ScheduleType.RECURRING

    def test_cancel(self):
        sched = TaskScheduler()
        entry = sched.schedule(_task(), datetime.now(timezone.utc))
        assert sched.cancel(entry.id) is True
        assert entry.enabled is False

    def test_cancel_nonexistent(self):
        sched = TaskScheduler()
        assert sched.cancel("nope") is False


# === Retry Tests ===


class TestFixedRetry:
    def test_should_retry_within_limit(self):
        policy = FixedRetry(max_retries=3, delay_seconds=2.0)
        task = _task()
        task.retries = 2
        assert policy.should_retry(task) is True

    def test_should_not_retry_at_limit(self):
        policy = FixedRetry(max_retries=3)
        task = _task()
        task.retries = 3
        assert policy.should_retry(task) is False

    def test_fixed_delay(self):
        policy = FixedRetry(delay_seconds=5.0)
        task = _task()
        assert policy.next_delay(task) == 5.0


class TestExponentialBackoff:
    def test_should_retry(self):
        policy = ExponentialBackoff(max_retries=5)
        task = _task()
        task.retries = 4
        assert policy.should_retry(task) is True
        task.retries = 5
        assert policy.should_retry(task) is False

    def test_exponential_delay(self):
        policy = ExponentialBackoff(base_delay_seconds=1.0, max_delay_seconds=60.0)
        task = _task()
        task.retries = 0
        assert policy.next_delay(task) == 1.0
        task.retries = 1
        assert policy.next_delay(task) == 2.0
        task.retries = 2
        assert policy.next_delay(task) == 4.0
        task.retries = 3
        assert policy.next_delay(task) == 8.0

    def test_max_delay_cap(self):
        policy = ExponentialBackoff(base_delay_seconds=1.0, max_delay_seconds=10.0)
        task = _task()
        task.retries = 10  # 2^10 = 1024 > 10
        assert policy.next_delay(task) == 10.0


class TestDeadLetterQueue:
    def test_add_and_get(self):
        dlq = DeadLetterQueue()
        task = _task("dead")
        dlq.add(task)
        assert dlq.get(task.id) is task

    def test_list(self):
        dlq = DeadLetterQueue()
        dlq.add(_task("a"))
        dlq.add(_task("b"))
        assert dlq.size() == 2
        assert len(dlq.list()) == 2

    def test_remove(self):
        dlq = DeadLetterQueue()
        task = _task()
        dlq.add(task)
        assert dlq.remove(task.id) is True
        assert dlq.size() == 0
        assert dlq.remove(task.id) is False
