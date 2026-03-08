"""Factory and settings for selecting workflow control-plane backends."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pylon.control_plane.file_store import JsonFileWorkflowControlPlaneStore
from pylon.control_plane.in_memory_store import InMemoryWorkflowControlPlaneStore
from pylon.control_plane.sqlite_store import SQLiteWorkflowControlPlaneStore
from pylon.control_plane.workflow_service import WorkflowControlPlaneStore
from pylon.errors import ConfigError


class ControlPlaneBackend(enum.StrEnum):
    MEMORY = "memory"
    JSON_FILE = "json_file"
    SQLITE = "sqlite"


@dataclass(frozen=True)
class ControlPlaneStoreConfig:
    """Configuration for selecting a workflow control-plane backend."""

    backend: ControlPlaneBackend = ControlPlaneBackend.MEMORY
    path: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any] | None,
        *,
        default_backend: ControlPlaneBackend,
        default_path: str | None = None,
    ) -> ControlPlaneStoreConfig:
        raw = dict(payload or {})
        backend_value = str(raw.get("backend", default_backend.value))
        try:
            backend = ControlPlaneBackend(backend_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported control_plane backend: {backend_value}",
                details={"backend": backend_value},
            ) from exc
        path = raw.get("path", default_path)
        if path is not None and not isinstance(path, str):
            raise ConfigError(
                "control_plane.path must be a string",
                details={"path": path},
            )
        return cls(backend=backend, path=path)


def build_workflow_control_plane_store(
    config: ControlPlaneStoreConfig,
    *,
    node_handlers: dict[str, dict[str, Any]] | None = None,
    agent_handlers: dict[str, dict[str, Any]] | None = None,
) -> WorkflowControlPlaneStore:
    """Build a workflow control-plane store from backend settings."""

    if config.backend is ControlPlaneBackend.MEMORY:
        return InMemoryWorkflowControlPlaneStore(
            node_handlers=node_handlers,
            agent_handlers=agent_handlers,
        )

    if config.backend is ControlPlaneBackend.JSON_FILE:
        path = config.path or str(Path(".pylon") / "control-plane.json")
        return JsonFileWorkflowControlPlaneStore(
            path,
            node_handlers=node_handlers,
            agent_handlers=agent_handlers,
        )

    if config.backend is ControlPlaneBackend.SQLITE:
        path = config.path or str(Path(".pylon") / "control-plane.db")
        return SQLiteWorkflowControlPlaneStore(
            path,
            node_handlers=node_handlers,
            agent_handlers=agent_handlers,
        )

    raise ConfigError(
        f"Unsupported control_plane backend: {config.backend.value}",
        details={"backend": config.backend.value},
    )
