"""In-memory control-plane store implementing the shared workflow store contract."""

from __future__ import annotations

import threading
from typing import Any

from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError


class InMemoryWorkflowControlPlaneStore:
    """Volatile control-plane store for tests, SDK local mode, and embedding."""

    def __init__(
        self,
        *,
        node_handlers: dict[str, dict[str, Any]] | None = None,
        agent_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._workflow_projects: dict[tuple[str, str], PylonProject] = {}
        self._workflow_runs_by_id: dict[str, dict[str, Any]] = {}
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._approvals: dict[str, dict[str, Any]] = {}
        self._audit_entries: dict[int, dict[str, Any]] = {}
        self._queue_tasks: dict[str, dict[str, Any]] = {}
        self._surface_records: dict[str, dict[str, dict[str, Any]]] = {}
        self._sequence_counters: dict[str, int] = {}
        self._idempotency_keys: dict[tuple[str, str, str], str] = {}
        self._node_handlers = dict(node_handlers or {})
        self._agent_handlers = dict(agent_handlers or {})

    def _workflow_key(self, workflow_id: str, tenant_id: str) -> tuple[str, str]:
        return tenant_id, workflow_id

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
            self._workflow_projects[self._workflow_key(workflow_id, tenant_id)] = resolved
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        with self._lock:
            self._workflow_projects.pop(self._workflow_key(workflow_id, tenant_id), None)

    def get_workflow_project(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> PylonProject | None:
        with self._lock:
            return self._workflow_projects.get(self._workflow_key(workflow_id, tenant_id))

    def list_workflow_projects(
        self,
        *,
        tenant_id: str = "default",
    ) -> list[tuple[str, PylonProject]]:
        with self._lock:
            results = [
                (workflow_id, project)
                for (owner_tenant_id, workflow_id), project in self._workflow_projects.items()
                if owner_tenant_id == tenant_id
            ]
        results.sort(key=lambda item: item[0])
        return results

    def list_all_workflow_projects(self) -> list[tuple[str, str, PylonProject]]:
        with self._lock:
            results = [
                (tenant_id, workflow_id, project)
                for (tenant_id, workflow_id), project in self._workflow_projects.items()
            ]
        results.sort(key=lambda item: (item[0], item[1]))
        return results

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._workflow_runs_by_id.get(run_id)
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
            existing = self._workflow_runs_by_id.get(str(run_record["id"]))
            current_version = (
                int(existing.get("record_version", 0))
                if isinstance(existing, dict)
                else 0
            )
            if expected_record_version is not None and current_version != expected_record_version:
                raise ConcurrencyError(
                    f"Run record version conflict for {run_record['id']}",
                    details={
                        "run_id": str(run_record["id"]),
                        "expected_record_version": expected_record_version,
                        "actual_record_version": current_version,
                    },
                )
            stored = dict(run_record)
            stored["workflow_id"] = workflow_id
            stored["tenant_id"] = tenant_id
            stored["parameters"] = dict(parameters or {})
            stored["record_version"] = current_version + 1
            self._workflow_runs_by_id[str(stored["id"])] = stored
            return stored

    def list_all_run_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(payload) for payload in self._workflow_runs_by_id.values()]

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            run_id = self._idempotency_keys.get((tenant_id, workflow_id, idempotency_key))
            if run_id is None:
                return None
            payload = self._workflow_runs_by_id.get(run_id)
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
            key = (tenant_id, workflow_id, idempotency_key)
            existing_run_id = self._idempotency_keys.get(key)
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
            self._idempotency_keys[key] = run_id

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._checkpoints.get(checkpoint_id)
            return None if payload is None else dict(payload)

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        with self._lock:
            self._checkpoints[str(checkpoint_payload["id"])] = dict(checkpoint_payload)

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(checkpoint)
                for checkpoint in self._checkpoints.values()
                if checkpoint.get("run_id") == run_id
            ]

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._approvals.get(approval_id)
            return None if payload is None else dict(payload)

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        with self._lock:
            self._approvals[str(approval_payload["id"])] = dict(approval_payload)

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(approval)
                for approval in self._approvals.values()
                if approval.get("run_id") == run_id
            ]

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(payload) for payload in self._approvals.values()]

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            payload = self._audit_entries.get(entry_id)
            return None if payload is None else dict(payload)

    def get_last_audit_record(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._audit_entries:
                return None
            last_id = max(self._audit_entries)
            return dict(self._audit_entries[last_id])

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None:
        with self._lock:
            self._audit_entries[int(audit_payload["id"])] = dict(audit_payload)

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = list(self._audit_entries.values())
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
            payload = self._queue_tasks.get(task_id)
            return None if payload is None else dict(payload)

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None:
        with self._lock:
            self._queue_tasks[str(task_payload["id"])] = dict(task_payload)

    def delete_queue_task_record(self, task_id: str) -> bool:
        with self._lock:
            return self._queue_tasks.pop(task_id, None) is not None

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = list(self._queue_tasks.values())
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
            namespace_records = self._surface_records.get(namespace, {})
            payload = namespace_records.get(record_id)
            return None if payload is None else dict(payload)

    def put_surface_record(
        self,
        namespace: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            namespace_records = self._surface_records.setdefault(namespace, {})
            namespace_records[record_id] = dict(payload)

    def delete_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> bool:
        with self._lock:
            namespace_records = self._surface_records.get(namespace)
            if namespace_records is None:
                return False
            removed = namespace_records.pop(record_id, None)
            if not namespace_records:
                self._surface_records.pop(namespace, None)
            return removed is not None

    def list_surface_records(
        self,
        namespace: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = list(self._surface_records.get(namespace, {}).values())
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
            next_value = self._sequence_counters.get(name, 0) + 1
            self._sequence_counters[name] = next_value
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
