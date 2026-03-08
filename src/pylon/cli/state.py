"""Persistent local state for CLI workflows and settings."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from pylon.control_plane import JsonFileWorkflowControlPlaneStore, WorkflowRunService


def _pylon_home() -> Path:
    env_home = Path.home()
    pylon_home = Path.home() / ".pylon"
    from os import environ

    configured = environ.get("PYLON_HOME")
    if configured:
        pylon_home = Path(configured)
    elif not env_home.exists():
        pylon_home = Path(".pylon")
    pylon_home.mkdir(parents=True, exist_ok=True)
    return pylon_home


def _state_path() -> Path:
    return _pylon_home() / "state.json"


def _config_path() -> Path:
    return _pylon_home() / "config.yaml"


def _control_plane_path() -> Path:
    return _pylon_home() / "control-plane.json"


def _default_state() -> dict[str, Any]:
    return {
        "runs": {},
        "checkpoints": {},
        "approvals": {},
        "sandboxes": {},
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _default_state()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _default_state()

    if not isinstance(data, dict):
        return _default_state()

    normalized = _default_state()
    for key in ("runs", "checkpoints", "approvals", "sandboxes"):
        value = data.get(key)
        normalized[key] = value if isinstance(value, dict) else {}
    return normalized


def save_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, default=str))


def load_control_plane_store() -> JsonFileWorkflowControlPlaneStore:
    store = JsonFileWorkflowControlPlaneStore(_control_plane_path())
    _migrate_legacy_state(store)
    return store


def load_workflow_service() -> WorkflowRunService:
    return WorkflowRunService(load_control_plane_store())


def _migrate_legacy_state(store: JsonFileWorkflowControlPlaneStore) -> None:
    legacy = load_state()
    if (
        store.list_all_run_records()
        or not legacy["runs"]
        and not legacy["checkpoints"]
        and not legacy["approvals"]
    ):
        return
    for run in legacy["runs"].values():
        workflow_id = str(run.get("workflow_id", run.get("workflow", "")))
        if not workflow_id:
            continue
        tenant_id = str(run.get("tenant_id", "default"))
        store.put_run_record(
            dict(run),
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=run.get("parameters", {}),
        )
    for checkpoint in legacy["checkpoints"].values():
        store.put_checkpoint_record(dict(checkpoint))
    for approval in legacy["approvals"].values():
        store.put_approval_record(dict(approval))


def load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}

    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}

    return data if isinstance(data, dict) else {}


def save_config(config: dict[str, Any]) -> None:
    _config_path().write_text(yaml.safe_dump(config, sort_keys=True))


def now_ts() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex[:12]
    return f"{prefix}{value}" if prefix else value
