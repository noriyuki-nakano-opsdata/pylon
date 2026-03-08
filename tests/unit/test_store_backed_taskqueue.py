from __future__ import annotations

from pathlib import Path

from pylon.control_plane import (
    InMemoryWorkflowControlPlaneStore,
    JsonFileWorkflowControlPlaneStore,
    SQLiteWorkflowControlPlaneStore,
)
from pylon.taskqueue import StoreBackedTaskQueue, Task, TaskStatus


def test_store_backed_queue_persists_pending_task_in_memory() -> None:
    store = InMemoryWorkflowControlPlaneStore()
    queue = StoreBackedTaskQueue(store)

    task = Task(name="build", priority=3, payload={"wave": 0})
    queue.enqueue(task)

    reloaded = StoreBackedTaskQueue(store)
    pending = reloaded.dequeue()

    assert pending is not None
    assert pending.id == task.id
    assert pending.status == TaskStatus.RUNNING
    assert store.get_queue_task_record(task.id)["status"] == TaskStatus.RUNNING.value


def test_store_backed_queue_persists_json_file_backend(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    queue = StoreBackedTaskQueue(store)
    task = Task(name="wave-0", payload={"node_ids": ["start", "finish"]})
    queue.enqueue(task)

    reloaded_store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    reloaded = StoreBackedTaskQueue(reloaded_store)
    restored = reloaded.get(task.id)

    assert restored is not None
    assert restored.name == "wave-0"
    assert restored.payload["node_ids"] == ["start", "finish"]
    assert restored.status == TaskStatus.PENDING


def test_store_backed_queue_persists_sqlite_requeue_and_purge(tmp_path: Path) -> None:
    store = SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db")
    queue = StoreBackedTaskQueue(store)
    task = Task(name="wave-1")
    queue.enqueue(task)

    running = queue.dequeue()
    assert running is not None
    running.transition_to(TaskStatus.FAILED)
    store.put_queue_task_record(running.to_dict())

    reloaded = StoreBackedTaskQueue(SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db"))
    assert reloaded.requeue(task.id) is True
    pending = reloaded.get(task.id)
    assert pending is not None
    assert pending.status == TaskStatus.PENDING
    assert pending.retries == 1

    current = reloaded.dequeue()
    assert current is not None
    current.transition_to(TaskStatus.COMPLETED)
    store.put_queue_task_record(current.to_dict())
    purged = reloaded.purge()

    assert purged == 1
    assert store.get_queue_task_record(task.id) is None


def test_store_backed_queue_can_recover_running_tasks(tmp_path: Path) -> None:
    store = JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    queue = StoreBackedTaskQueue(store)
    task = Task(name="wave-2")
    queue.enqueue(task)

    running = queue.dequeue()
    assert running is not None
    queue.save(running)

    reloaded = StoreBackedTaskQueue(
        JsonFileWorkflowControlPlaneStore(tmp_path / "control-plane.json")
    )
    recovered = reloaded.recover_running()

    assert recovered == 1
    pending = reloaded.get(task.id)
    assert pending is not None
    assert pending.status == TaskStatus.PENDING
    assert pending.retries == 1
    assert pending.started_at is None
    assert pending.completed_at is None


def test_store_backed_queue_persists_lease_and_heartbeat(tmp_path: Path) -> None:
    store = SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db")
    queue = StoreBackedTaskQueue(store)
    task = Task(name="wave-lease")
    queue.enqueue(task)

    running = queue.dequeue(lease_owner="worker-1", lease_timeout_seconds=10)
    assert running is not None
    assert running.lease_owner == "worker-1"

    reloaded = StoreBackedTaskQueue(SQLiteWorkflowControlPlaneStore(tmp_path / "control-plane.db"))
    persisted = reloaded.get(task.id)
    assert persisted is not None
    assert persisted.lease_owner == "worker-1"
    assert persisted.lease_expires_at is not None

    assert reloaded.heartbeat(
        task.id,
        lease_owner="worker-1",
        lease_timeout_seconds=10,
    ) is True
