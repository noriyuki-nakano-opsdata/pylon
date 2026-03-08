from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pylon.control_plane import (
    JsonFileWorkflowControlPlaneStore,
    SQLiteWorkflowControlPlaneStore,
)
from pylon.errors import PylonError
from pylon.runtime import (
    QueuedWorkflowDispatchRunner,
    WorkflowDispatchPlan,
    WorkflowDispatchTask,
)
from pylon.taskqueue import FixedRetry, StoreBackedTaskQueue, TaskStatus
from pylon.types import WorkflowJoinPolicy, WorkflowNodeType


def _dispatch_plan() -> WorkflowDispatchPlan:
    return WorkflowDispatchPlan(
        workflow_id="wf",
        tenant_id="tenant-a",
        execution_mode="distributed_wave_plan",
        entry_nodes=("start",),
        tasks=(
            WorkflowDispatchTask(
                task_id="wf:start",
                node_id="start",
                wave_index=0,
                depends_on=(),
                dependency_task_ids=(),
                node_type=WorkflowNodeType.AGENT,
                join_policy=WorkflowJoinPolicy.ALL_RESOLVED,
                conditional_inbound=False,
                conditional_outbound=False,
            ),
            WorkflowDispatchTask(
                task_id="wf:finish",
                node_id="finish",
                wave_index=1,
                depends_on=("start",),
                dependency_task_ids=("wf:start",),
                node_type=WorkflowNodeType.AGENT,
                join_policy=WorkflowJoinPolicy.ALL_RESOLVED,
                conditional_inbound=False,
                conditional_outbound=False,
            ),
        ),
        waves=(("start",), ("finish",)),
    )


def test_queued_runner_drains_dispatch_plan_and_persists_results(tmp_path: Path) -> None:
    store = SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db")
    runner = QueuedWorkflowDispatchRunner(store)

    run = runner.drain(
        _dispatch_plan(),
        handler=lambda dispatch_task, task: {"node_id": dispatch_task.node_id, "task_id": task.id},
    )

    assert run.completed_task_ids == ("wf:finish", "wf:start")
    assert run.failed_task_ids == ()
    assert run.blocked_task_ids == ()

    reloaded_queue = StoreBackedTaskQueue(
        SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db")
    )
    start_task = reloaded_queue.get("wf:start")
    finish_task = reloaded_queue.get("wf:finish")
    assert start_task is not None
    assert finish_task is not None
    assert start_task.status == TaskStatus.COMPLETED
    assert finish_task.status == TaskStatus.COMPLETED
    assert start_task.payload["result"]["output"] == {"node_id": "start", "task_id": "wf:start"}
    assert finish_task.payload["result"]["output"] == {
        "node_id": "finish",
        "task_id": "wf:finish",
    }


def test_queued_runner_marks_dependents_blocked_on_failure(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    runner = QueuedWorkflowDispatchRunner(store)

    class _FailureError(PylonError):
        code = "QUEUE_HANDLER_FAILURE"

    run = runner.drain(
        _dispatch_plan(),
        handler=lambda dispatch_task, _task: (
            (_ for _ in ()).throw(_FailureError("boom"))
            if dispatch_task.node_id == "start"
            else {"node_id": dispatch_task.node_id}
        ),
    )

    assert run.completed_task_ids == ()
    assert run.failed_task_ids == ("wf:start",)
    assert run.dead_letter_task_ids == ("wf:start",)
    assert run.blocked_task_ids == ("wf:finish",)


def test_queued_runner_retries_failed_task_then_succeeds(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    runner = QueuedWorkflowDispatchRunner(
        store,
        retry_policy=FixedRetry(max_retries=1, delay_seconds=0.0),
    )
    attempts = {"start": 0, "finish": 0}

    def _handler(dispatch_task, task):  # type: ignore[no-untyped-def]
        attempts[dispatch_task.node_id] += 1
        if dispatch_task.node_id == "start" and attempts["start"] == 1:
            raise PylonError("boom")
        return {"node_id": dispatch_task.node_id, "task_id": task.id}

    run = runner.drain(_dispatch_plan(), handler=_handler)

    assert run.completed_task_ids == ("wf:finish", "wf:start")
    assert run.failed_task_ids == ()
    assert run.dead_letter_task_ids == ()
    assert attempts == {"start": 2, "finish": 1}

    reloaded_queue = StoreBackedTaskQueue(
        JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    )
    start_task = reloaded_queue.get("wf:start")
    assert start_task is not None
    assert start_task.status == TaskStatus.COMPLETED
    assert start_task.retries == 1
    assert "retry" not in start_task.payload


def test_queued_runner_moves_exhausted_task_to_dead_letter(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    runner = QueuedWorkflowDispatchRunner(
        store,
        retry_policy=FixedRetry(max_retries=1, delay_seconds=0.0),
    )

    def _handler(dispatch_task, _task):  # type: ignore[no-untyped-def]
        if dispatch_task.node_id == "start":
            raise PylonError("boom")
        return {"node_id": dispatch_task.node_id}

    run = runner.drain(_dispatch_plan(), handler=_handler)

    assert run.completed_task_ids == ()
    assert run.failed_task_ids == ("wf:start",)
    assert run.dead_letter_task_ids == ("wf:start",)
    assert run.blocked_task_ids == ("wf:finish",)

    reloaded_queue = StoreBackedTaskQueue(
        JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    )
    start_task = reloaded_queue.get("wf:start")
    assert start_task is not None
    assert start_task.status == TaskStatus.FAILED
    assert start_task.retries == 1
    assert start_task.payload["dead_letter"] is True
    assert start_task.payload["retry"]["scheduled"] is False


def test_queued_runner_recovers_running_tasks_after_restart(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    plan = _dispatch_plan()
    initial_runner = QueuedWorkflowDispatchRunner(
        store,
        recover_running_tasks=False,
        lease_timeout_seconds=1,
    )
    initial_runner.enqueue_ready_tasks(plan)
    task = initial_runner.queue.dequeue(lease_owner="worker-1", lease_timeout_seconds=1)
    assert task is not None
    assert task.lease_expires_at is not None
    task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    initial_runner.queue.save(task)

    restarted_runner = QueuedWorkflowDispatchRunner(
        JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    )

    assert restarted_runner.recovered_running_tasks == 1
    recovered = restarted_runner.queue.get("wf:start")
    assert recovered is not None
    assert recovered.status == TaskStatus.PENDING
    assert recovered.retries == 1


def test_queued_runner_heartbeats_long_running_task(tmp_path: Path) -> None:
    store = SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db")
    runner = QueuedWorkflowDispatchRunner(
        store,
        lease_timeout_seconds=0.05,
        heartbeat_interval_seconds=0.01,
    )

    def _handler(dispatch_task, task):  # type: ignore[no-untyped-def]
        assert dispatch_task.node_id == "start"
        time.sleep(0.12)
        return {"node_id": dispatch_task.node_id, "task_id": task.id}

    step = runner.process_next(_dispatch_plan(), handler=_handler)

    assert step.task_id == "wf:start"
    assert step.heartbeat_count >= 1
    assert step.lease_owner is not None

    persisted = runner.queue.get("wf:start")
    assert persisted is not None
    assert persisted.status == TaskStatus.COMPLETED
    assert persisted.last_heartbeat_at is None
