from __future__ import annotations

from pathlib import Path

from pylon.control_plane import (
    ControlPlaneBackend,
    ControlPlaneStoreConfig,
    InMemoryWorkflowControlPlaneStore,
    JsonFileWorkflowControlPlaneStore,
    SQLiteWorkflowControlPlaneStore,
    build_workflow_control_plane_store,
)


def test_factory_builds_in_memory_store() -> None:
    store = build_workflow_control_plane_store(
        ControlPlaneStoreConfig(backend=ControlPlaneBackend.MEMORY)
    )
    assert isinstance(store, InMemoryWorkflowControlPlaneStore)


def test_factory_builds_json_file_store(tmp_path: Path) -> None:
    store = build_workflow_control_plane_store(
        ControlPlaneStoreConfig(
            backend=ControlPlaneBackend.JSON_FILE,
            path=str(tmp_path / "control-plane.json"),
        )
    )
    assert isinstance(store, JsonFileWorkflowControlPlaneStore)


def test_factory_builds_sqlite_store(tmp_path: Path) -> None:
    store = build_workflow_control_plane_store(
        ControlPlaneStoreConfig(
            backend=ControlPlaneBackend.SQLITE,
            path=str(tmp_path / "control-plane.db"),
        )
    )
    assert isinstance(store, SQLiteWorkflowControlPlaneStore)
