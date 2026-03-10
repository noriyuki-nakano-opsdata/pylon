"""JSON file-backed control-plane store for workflow lifecycle state."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "workflow_projects": {},
        "workflow_runs_by_id": {},
        "checkpoints": {},
        "approvals": {},
        "audit_entries": {},
        "queue_tasks": {},
        "surface_records": {},
        "sequence_counters": {},
        "idempotency_keys": {},
    }


class JsonFileWorkflowControlPlaneStore:
    """Durable JSON-backed store for workflow definitions and run lifecycle data.

    This store persists canonical workflow definitions, raw run records,
    checkpoints, approval records, API surface records, and simple sequence
    counters in a single JSON document.
    Handler registries remain process-local and are intentionally not persisted.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        node_handlers: dict[str, dict[str, Any]] | None = None,
        agent_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._path = Path(path)
        self._node_handlers = dict(node_handlers or {})
        self._agent_handlers = dict(agent_handlers or {})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_state(_default_state())

    def _workflow_key(self, workflow_id: str, tenant_id: str) -> str:
        return f"{tenant_id}:{workflow_id}"

    def _read_state(self) -> dict[str, Any]:
        if not self._path.exists():
            return _default_state()
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid control-plane state file: {self._path}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid control-plane state payload: {self._path}")
        state = _default_state()
        raw_schema_version = raw.get("schema_version", state["schema_version"])
        if not isinstance(raw_schema_version, int) or raw_schema_version < 1:
            raise ValueError(f"Invalid control-plane schema version: {self._path}")
        state["schema_version"] = max(raw_schema_version, state["schema_version"])
        for key in (
            "workflow_projects",
            "workflow_runs_by_id",
            "checkpoints",
            "approvals",
            "audit_entries",
            "queue_tasks",
            "surface_records",
            "sequence_counters",
            "idempotency_keys",
        ):
            value = raw.get(key)
            state[key] = value if isinstance(value, dict) else {}
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True, default=str))
        tmp_path.replace(self._path)

    def register_workflow_project(
        self,
        workflow_id: str,
        project: PylonProject | dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> PylonProject:
        resolved = (
            project
            if isinstance(project, PylonProject)
            else PylonProject.model_validate(project)
        )
        with self._lock:
            state = self._read_state()
            state["workflow_projects"][self._workflow_key(workflow_id, tenant_id)] = {
                "tenant_id": tenant_id,
                "workflow_id": workflow_id,
                "project": resolved.model_dump(mode="json"),
            }
            self._write_state(state)
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        with self._lock:
            state = self._read_state()
            state["workflow_projects"].pop(self._workflow_key(workflow_id, tenant_id), None)
            self._write_state(state)

    def get_workflow_project(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> PylonProject | None:
        with self._lock:
            state = self._read_state()
            payload = state["workflow_projects"].get(
                self._workflow_key(workflow_id, tenant_id)
            )
        if payload is None:
            return None
        return PylonProject.model_validate(payload["project"])

    def list_workflow_projects(
        self,
        *,
        tenant_id: str = "default",
    ) -> list[tuple[str, PylonProject]]:
        with self._lock:
            state = self._read_state()
        results: list[tuple[str, PylonProject]] = []
        for payload in state["workflow_projects"].values():
            if payload.get("tenant_id") != tenant_id:
                continue
            workflow_id = str(payload.get("workflow_id", ""))
            results.append((workflow_id, PylonProject.model_validate(payload["project"])))
        results.sort(key=lambda item: item[0])
        return results

    def list_all_workflow_projects(self) -> list[tuple[str, str, PylonProject]]:
        with self._lock:
            state = self._read_state()
        results: list[tuple[str, str, PylonProject]] = []
        for payload in state["workflow_projects"].values():
            results.append(
                (
                    str(payload.get("tenant_id", "default")),
                    str(payload.get("workflow_id", "")),
                    PylonProject.model_validate(payload["project"]),
                )
            )
        results.sort(key=lambda item: (item[0], item[1]))
        return results

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            payload = state["workflow_runs_by_id"].get(run_id)
        return None if payload is None else dict(payload)

    def put_run_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str = "default",
        parameters: dict[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            run_id = str(run_record["id"])
            existing = state["workflow_runs_by_id"].get(run_id)
            current_version = (
                int(existing.get("record_version", 0))
                if isinstance(existing, dict)
                else 0
            )
            if (
                expected_record_version is not None
                and current_version != expected_record_version
            ):
                raise ConcurrencyError(
                    f"Run record version conflict for {run_id}",
                    details={
                        "run_id": run_id,
                        "expected_record_version": expected_record_version,
                        "actual_record_version": current_version,
                    },
                )
            stored = dict(run_record)
            stored["workflow_id"] = workflow_id
            stored["tenant_id"] = tenant_id
            stored["parameters"] = dict(parameters or {})
            stored["record_version"] = current_version + 1
            state["workflow_runs_by_id"][run_id] = stored
            self._write_state(state)
        return stored

    def list_all_run_records(self) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        return [dict(payload) for payload in state["workflow_runs_by_id"].values()]

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            key = f"{tenant_id}:{workflow_id}:{idempotency_key}"
            run_id = state["idempotency_keys"].get(key)
            if not isinstance(run_id, str):
                return None
            payload = state["workflow_runs_by_id"].get(run_id)
        return None if payload is None else dict(payload)

    def put_run_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
        run_id: str,
    ) -> None:
        with self._lock:
            state = self._read_state()
            key = f"{tenant_id}:{workflow_id}:{idempotency_key}"
            existing_run_id = state["idempotency_keys"].get(key)
            if existing_run_id is not None and existing_run_id != run_id:
                raise ConcurrencyError(
                    f"Idempotency key already bound for workflow {workflow_id}",
                    details={
                        "workflow_id": workflow_id,
                        "tenant_id": tenant_id,
                        "idempotency_key": idempotency_key,
                        "existing_run_id": existing_run_id,
                        "run_id": run_id,
                    },
                )
            state["idempotency_keys"][key] = run_id
            self._write_state(state)

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            payload = state["checkpoints"].get(checkpoint_id)
        return None if payload is None else dict(payload)

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        with self._lock:
            state = self._read_state()
            state["checkpoints"][str(checkpoint_payload["id"])] = dict(checkpoint_payload)
            self._write_state(state)

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        return [
            dict(checkpoint)
            for checkpoint in state["checkpoints"].values()
            if checkpoint.get("run_id") == run_id
        ]

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            payload = state["approvals"].get(approval_id)
        return None if payload is None else dict(payload)

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        with self._lock:
            state = self._read_state()
            state["approvals"][str(approval_payload["id"])] = dict(approval_payload)
            self._write_state(state)

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        return [
            dict(approval)
            for approval in state["approvals"].values()
            if approval.get("run_id") == run_id
        ]

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        return [dict(payload) for payload in state["approvals"].values()]

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            payload = state["audit_entries"].get(str(entry_id))
        return None if payload is None else dict(payload)

    def get_last_audit_record(self) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            if not state["audit_entries"]:
                return None
            last_key = max(state["audit_entries"], key=lambda key: int(key))
            return dict(state["audit_entries"][last_key])

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None:
        with self._lock:
            state = self._read_state()
            state["audit_entries"][str(audit_payload["id"])] = dict(audit_payload)
            self._write_state(state)

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        results = list(state["audit_entries"].values())
        if tenant_id is not None:
            results = [entry for entry in results if entry.get("tenant_id") == tenant_id]
        if event_type is not None:
            results = [entry for entry in results if entry.get("event_type") == event_type]
        results.sort(key=lambda entry: int(entry.get("id", 0)))
        if limit is None:
            return [dict(entry) for entry in results[offset:]]
        return [dict(entry) for entry in results[offset : offset + limit]]

    def get_queue_task_record(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            payload = state["queue_tasks"].get(task_id)
        return None if payload is None else dict(payload)

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None:
        with self._lock:
            state = self._read_state()
            state["queue_tasks"][str(task_payload["id"])] = dict(task_payload)
            self._write_state(state)

    def delete_queue_task_record(self, task_id: str) -> bool:
        with self._lock:
            state = self._read_state()
            removed = state["queue_tasks"].pop(task_id, None)
            if removed is not None:
                self._write_state(state)
                return True
        return False

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
        results = list(state["queue_tasks"].values())
        if status is not None:
            results = [task for task in results if task.get("status") == status]
        results.sort(
            key=lambda task: (
                str(task.get("created_at", "")),
                str(task.get("id", "")),
            )
        )
        return [dict(task) for task in results]

    def get_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            state = self._read_state()
            namespace_records = state["surface_records"].get(namespace, {})
            payload = namespace_records.get(record_id)
        return None if payload is None else dict(payload)

    def put_surface_record(
        self,
        namespace: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            state = self._read_state()
            namespace_records = state["surface_records"].setdefault(namespace, {})
            namespace_records[record_id] = dict(payload)
            self._write_state(state)

    def delete_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> bool:
        with self._lock:
            state = self._read_state()
            namespace_records = state["surface_records"].get(namespace)
            if not isinstance(namespace_records, dict):
                return False
            removed = namespace_records.pop(record_id, None)
            if removed is None:
                return False
            if not namespace_records:
                state["surface_records"].pop(namespace, None)
            self._write_state(state)
            return True

    def list_surface_records(
        self,
        namespace: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
            namespace_records = state["surface_records"].get(namespace, {})
            results = list(namespace_records.values())
        if tenant_id is not None:
            results = [record for record in results if record.get("tenant_id") == tenant_id]
        results.sort(
            key=lambda record: (
                str(record.get("updated_at", record.get("created_at", ""))),
                str(record.get("id", record.get("entry_id", ""))),
            )
        )
        return [dict(record) for record in results]

    def allocate_sequence_value(self, name: str) -> int:
        with self._lock:
            state = self._read_state()
            current = int(state["sequence_counters"].get(name, 0))
            next_value = current + 1
            state["sequence_counters"][name] = next_value
            self._write_state(state)
            return next_value

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            handlers = self._node_handlers.get(workflow_id)
        return None if handlers is None else dict(handlers)

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            handlers = self._agent_handlers.get(workflow_id)
        return None if handlers is None else dict(handlers)

    def set_handlers(
        self,
        workflow_id: str,
        *,
        node_handlers: dict[str, Any] | None = None,
        agent_handlers: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if node_handlers is not None:
                self._node_handlers[workflow_id] = dict(node_handlers)
            if agent_handlers is not None:
                self._agent_handlers[workflow_id] = dict(agent_handlers)
