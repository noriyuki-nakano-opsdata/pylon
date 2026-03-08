"""SQLite-backed control-plane store for durable workflow lifecycle state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError

_SCHEMA_VERSION = 1


class SQLiteWorkflowControlPlaneStore:
    """Durable relational control-plane store backed by SQLite.

    This backend is intended as a local durable relational store that shares the
    same write-side contract as future PostgreSQL-backed implementations.
    Handler registries remain process-local and are intentionally not persisted.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        node_handlers: dict[str, dict[str, Any]] | None = None,
        agent_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._path = Path(path)
        self._node_handlers = dict(node_handlers or {})
        self._agent_handlers = dict(agent_handlers or {})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_projects (
                    tenant_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    project_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, workflow_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    run_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_tenant_workflow
                ON workflow_runs (tenant_id, workflow_id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    tenant_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, workflow_id, idempotency_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id
                ON checkpoints (run_id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approvals_run_id
                ON approvals (run_id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_entries (
                    entry_id INTEGER PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_entries_tenant_created
                ON audit_entries (tenant_id, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_entries_event_type
                ON audit_entries (event_type)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_tasks_status_created
                ON queue_tasks (status, created_at)
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES ('schema_version', ?)
                """,
                (str(_SCHEMA_VERSION),),
            )
            connection.commit()

    def _load_json(self, payload: str) -> dict[str, Any]:
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("Stored control-plane payload must be an object")
        return raw

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
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO workflow_projects (tenant_id, workflow_id, project_json)
                VALUES (?, ?, ?)
                """,
                (
                    tenant_id,
                    workflow_id,
                    json.dumps(resolved.model_dump(mode="json"), sort_keys=True),
                ),
            )
            connection.commit()
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM workflow_projects WHERE tenant_id = ? AND workflow_id = ?",
                (tenant_id, workflow_id),
            )
            connection.commit()

    def get_workflow_project(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> PylonProject | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_json
                FROM workflow_projects
                WHERE tenant_id = ? AND workflow_id = ?
                """,
                (tenant_id, workflow_id),
            ).fetchone()
        if row is None:
            return None
        return PylonProject.model_validate(self._load_json(str(row["project_json"])))

    def list_workflow_projects(
        self,
        *,
        tenant_id: str = "default",
    ) -> list[tuple[str, PylonProject]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT workflow_id, project_json
                FROM workflow_projects
                WHERE tenant_id = ?
                ORDER BY workflow_id
                """,
                (tenant_id,),
            ).fetchall()
        return [
            (
                str(row["workflow_id"]),
                PylonProject.model_validate(self._load_json(str(row["project_json"]))),
            )
            for row in rows
        ]

    def list_all_workflow_projects(self) -> list[tuple[str, str, PylonProject]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT tenant_id, workflow_id, project_json
                FROM workflow_projects
                ORDER BY tenant_id, workflow_id
                """
            ).fetchall()
        return [
            (
                str(row["tenant_id"]),
                str(row["workflow_id"]),
                PylonProject.model_validate(self._load_json(str(row["project_json"]))),
            )
            for row in rows
        ]

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT run_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["run_json"]))

    def put_run_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str = "default",
        parameters: dict[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_record["id"])
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT run_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            current_version = 0
            if existing is not None:
                current_version = int(
                    self._load_json(str(existing["run_json"])).get("record_version", 0)
                )
            if expected_record_version is not None and current_version != expected_record_version:
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
            connection.execute(
                """
                INSERT OR REPLACE INTO workflow_runs (
                    run_id, tenant_id, workflow_id, status, created_at, run_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tenant_id,
                    workflow_id,
                    str(stored.get("status", "")),
                    stored.get("created_at"),
                    json.dumps(stored, sort_keys=True, default=str),
                ),
            )
            connection.commit()
        return stored

    def list_all_run_records(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_json FROM workflow_runs ORDER BY created_at, run_id"
            ).fetchall()
        return [self._load_json(str(row["run_json"])) for row in rows]

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.run_json
                FROM idempotency_keys AS k
                JOIN workflow_runs AS r ON r.run_id = k.run_id
                WHERE k.tenant_id = ? AND k.workflow_id = ? AND k.idempotency_key = ?
                """,
                (tenant_id, workflow_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["run_json"]))

    def put_run_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
        run_id: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT run_id
                FROM idempotency_keys
                WHERE tenant_id = ? AND workflow_id = ? AND idempotency_key = ?
                """,
                (tenant_id, workflow_id, idempotency_key),
            ).fetchone()
            if row is not None and str(row["run_id"]) != run_id:
                raise ConcurrencyError(
                    f"Idempotency key already bound for workflow {workflow_id}",
                    details={
                        "workflow_id": workflow_id,
                        "tenant_id": tenant_id,
                        "idempotency_key": idempotency_key,
                        "existing_run_id": str(row["run_id"]),
                        "run_id": run_id,
                    },
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO idempotency_keys (
                    tenant_id, workflow_id, idempotency_key, run_id
                ) VALUES (?, ?, ?, ?)
                """,
                (tenant_id, workflow_id, idempotency_key, run_id),
            )
            connection.commit()

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["payload_json"]))

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO checkpoints (checkpoint_id, run_id, payload_json)
                VALUES (?, ?, ?)
                """,
                (
                    str(checkpoint_payload["id"]),
                    str(checkpoint_payload.get("run_id", "")),
                    json.dumps(dict(checkpoint_payload), sort_keys=True, default=str),
                ),
            )
            connection.commit()

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY checkpoint_id
                """,
                (run_id,),
            ).fetchall()
        return [self._load_json(str(row["payload_json"])) for row in rows]

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["payload_json"]))

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO approvals (approval_id, run_id, payload_json)
                VALUES (?, ?, ?)
                """,
                (
                    str(approval_payload["id"]),
                    str(approval_payload.get("run_id", "")),
                    json.dumps(dict(approval_payload), sort_keys=True, default=str),
                ),
            )
            connection.commit()

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM approvals
                WHERE run_id = ?
                ORDER BY approval_id
                """,
                (run_id,),
            ).fetchall()
        return [self._load_json(str(row["payload_json"])) for row in rows]

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM approvals ORDER BY approval_id"
            ).fetchall()
        return [self._load_json(str(row["payload_json"])) for row in rows]

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM audit_entries WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["payload_json"]))

    def get_last_audit_record(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM audit_entries
                ORDER BY entry_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["payload_json"]))

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO audit_entries (
                    entry_id, tenant_id, event_type, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(audit_payload["id"]),
                    str(audit_payload.get("tenant_id", "default")),
                    str(audit_payload.get("event_type", "")),
                    str(audit_payload.get("created_at", "")),
                    json.dumps(audit_payload, sort_keys=True, default=str),
                ),
            )
            connection.commit()

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM audit_entries"
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY entry_id"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._load_json(str(row["payload_json"])) for row in rows]

    def get_queue_task_record(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM queue_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_json(str(row["payload_json"]))

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO queue_tasks (
                    task_id, status, created_at, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(task_payload["id"]),
                    str(task_payload.get("status", "")),
                    str(task_payload.get("created_at", "")),
                    json.dumps(task_payload, sort_keys=True, default=str),
                ),
            )
            connection.commit()

    def delete_queue_task_record(self, task_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM queue_tasks WHERE task_id = ?",
                (task_id,),
            )
            connection.commit()
        return cursor.rowcount > 0

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM queue_tasks"
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at, task_id"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._load_json(str(row["payload_json"])) for row in rows]

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        handlers = self._node_handlers.get(workflow_id)
        return None if handlers is None else dict(handlers)

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        handlers = self._agent_handlers.get(workflow_id)
        return None if handlers is None else dict(handlers)

    def set_handlers(
        self,
        workflow_id: str,
        *,
        node_handlers: dict[str, Any] | None = None,
        agent_handlers: dict[str, Any] | None = None,
    ) -> None:
        if node_handlers is not None:
            self._node_handlers[workflow_id] = dict(node_handlers)
        if agent_handlers is not None:
            self._agent_handlers[workflow_id] = dict(agent_handlers)
