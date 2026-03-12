"""Async workflow run manager used by the UI development API server.

This manager provides background-thread execution with persisted run records so
the lifecycle UI can poll for status updates without blocking the request that
starts the run. It also reconciles orphaned async runs after a server restart.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from pylon.control_plane.workflow_service import WorkflowControlPlaneStore
from pylon.lifecycle import (
    default_lifecycle_project_record,
    merge_lifecycle_project_record,
    refresh_lifecycle_recommendations,
    sync_lifecycle_project_with_run,
)
from pylon.observability.query_service import (
    build_run_query_payload,
    rebuild_run_query_payload,
)
from pylon.observability.run_payload import build_public_run_payload
from pylon.runtime import (
    execute_project_sync,
    normalize_runtime_input,
    serialize_run,
)
from pylon.runtime.execution import ExecutionArtifacts
from pylon.runtime.llm import ProviderRegistry
from pylon.types import RunStatus, RunStopReason

logger = logging.getLogger(__name__)

TERMINAL_ASYNC_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    }
)


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_async_running(run_record: dict[str, Any]) -> bool:
    return (
        str(run_record.get("execution_mode", "")) == "async"
        and str(run_record.get("status", "")) == RunStatus.RUNNING.value
    )


def _parse_lifecycle_workflow_id(workflow_id: str) -> tuple[str, str] | None:
    prefix = "lifecycle-"
    if not workflow_id.startswith(prefix):
        return None
    phase, separator, project_id = workflow_id[len(prefix):].partition("-")
    if not separator or not phase or not project_id:
        return None
    return phase, project_id


def _run_order_key(run_record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(run_record.get("completed_at", "")),
        str(run_record.get("created_at", "")),
        str(run_record.get("id", "")),
    )


def _phase_has_persisted_output(
    project_record: Mapping[str, Any],
    *,
    phase: str,
) -> bool:
    if phase == "research":
        research = project_record.get("research")
        return isinstance(research, Mapping) and bool(research)
    if phase == "planning":
        return any(
            isinstance(project_record.get(field), list | dict) and bool(project_record.get(field))
            for field in ("analysis", "features", "planEstimates", "milestones")
        )
    if phase == "design":
        return bool(project_record.get("designVariants")) or bool(project_record.get("selectedDesignId"))
    if phase == "development":
        return bool(project_record.get("buildCode")) or bool(project_record.get("milestoneResults"))
    return False


def _phase_is_in_progress(
    project_record: Mapping[str, Any],
    *,
    phase: str,
) -> bool:
    return any(
        isinstance(entry, Mapping)
        and entry.get("phase") == phase
        and str(entry.get("status", "")) == "in_progress"
        for entry in project_record.get("phaseStatuses", [])
    )


def sync_lifecycle_project_for_run(
    store: WorkflowControlPlaneStore,
    *,
    run_record: Mapping[str, Any],
    workflow_id: str,
    tenant_id: str,
    logger_: logging.Logger | None = None,
) -> bool:
    parsed = _parse_lifecycle_workflow_id(workflow_id)
    if parsed is None:
        return False
    phase, project_id = parsed
    lifecycle_key = f"{tenant_id}:{project_id}"
    existing = store.get_surface_record("lifecycle_projects", lifecycle_key)
    project_record = (
        dict(existing)
        if isinstance(existing, dict)
        else default_lifecycle_project_record(project_id, tenant_id=tenant_id)
    )
    checkpoints = store.list_run_checkpoints(str(run_record.get("id", "")))
    patch = sync_lifecycle_project_with_run(
        project_record,
        phase=phase,
        run_record=dict(run_record),
        checkpoints=checkpoints,
    )
    merged = merge_lifecycle_project_record(project_record, patch)
    merged["recommendations"] = refresh_lifecycle_recommendations(merged)
    store.put_surface_record("lifecycle_projects", lifecycle_key, merged)
    active_logger = logger_ or logger
    active_logger.info(
        "async_workflow_run_synced_lifecycle_project workflow_id=%s tenant_id=%s "
        "project_id=%s phase=%s run_id=%s status=%s checkpoints=%s",
        workflow_id,
        tenant_id,
        project_id,
        phase,
        run_record.get("id"),
        run_record.get("status"),
        len(checkpoints),
    )
    return True


def reconcile_lifecycle_projects_for_terminal_runs(
    store: WorkflowControlPlaneStore,
    *,
    logger_: logging.Logger | None = None,
) -> int:
    runs_by_workflow: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run_record in store.list_all_run_records():
        workflow_id = str(run_record.get("workflow_id", run_record.get("workflow", "")))
        if _parse_lifecycle_workflow_id(workflow_id) is None:
            continue
        if str(run_record.get("status", "")) not in TERMINAL_ASYNC_RUN_STATUSES:
            continue
        tenant_id = str(run_record.get("tenant_id", "default") or "default")
        runs_by_workflow.setdefault((tenant_id, workflow_id), []).append(dict(run_record))

    synced = 0
    for (tenant_id, workflow_id), run_records in runs_by_workflow.items():
        parsed = _parse_lifecycle_workflow_id(workflow_id)
        if parsed is None:
            continue
        phase, project_id = parsed
        lifecycle_key = f"{tenant_id}:{project_id}"
        existing = store.get_surface_record("lifecycle_projects", lifecycle_key)
        replay_full_history = not isinstance(existing, dict) or _phase_is_in_progress(
            existing,
            phase=phase,
        ) or not _phase_has_persisted_output(existing, phase=phase)
        ordered_runs = sorted(run_records, key=_run_order_key)
        candidate_runs = ordered_runs if replay_full_history else ordered_runs[-1:]
        for run_record in candidate_runs:
            existing = store.get_surface_record("lifecycle_projects", lifecycle_key)
            if isinstance(existing, dict) and not _lifecycle_project_sync_needed(
                existing,
                phase=phase,
                run_id=str(run_record.get("id", "")),
                force=replay_full_history,
            ):
                continue
            if sync_lifecycle_project_for_run(
                store,
                run_record=run_record,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                logger_=logger_,
            ):
                synced += 1
    active_logger = logger_ or logger
    if synced:
        active_logger.warning(
            "async_workflow_run_backfilled_lifecycle_projects synced_runs=%s workflows=%s",
            synced,
            len(runs_by_workflow),
        )
    return synced


def _lifecycle_project_sync_needed(
    project_record: Mapping[str, Any],
    *,
    phase: str,
    run_id: str,
    force: bool = False,
) -> bool:
    if force:
        return True
    phase_status = next(
        (
            str(entry.get("status", ""))
            for entry in project_record.get("phaseStatuses", [])
            if isinstance(entry, dict) and entry.get("phase") == phase
        ),
        "",
    )
    if phase_status == "in_progress":
        return True
    phase_runs = [
        entry
        for entry in project_record.get("phaseRuns", [])
        if isinstance(entry, dict) and entry.get("phase") == phase
    ]
    matching = next((entry for entry in phase_runs if str(entry.get("runId", "")) == run_id), None)
    if matching is not None:
        has_tokens = any(key in matching for key in ("totalTokens", "inputTokens", "outputTokens"))
        has_cost_state = "costMeasured" in matching
        return not (has_tokens and has_cost_state)
    return True


class AsyncWorkflowRunManager:
    """Persisted async workflow execution with orphan-run reconciliation."""

    def __init__(
        self,
        store: WorkflowControlPlaneStore,
        *,
        provider_registry: ProviderRegistry | None = None,
        on_terminal_run: Callable[[dict[str, Any], str, str], None] | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._provider_registry = provider_registry
        self._on_terminal_run = on_terminal_run
        self._logger = logger_ or logger
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    def start_run(
        self,
        *,
        workflow_id: str,
        tenant_id: str,
        input_data: Any = None,
        parameters: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        project = self._store.get_workflow_project(workflow_id, tenant_id=tenant_id)
        if project is None:
            raise KeyError(f"Workflow not found: {workflow_id}")

        normalized_idempotency_key = (idempotency_key or "").strip()
        if normalized_idempotency_key:
            existing = self._store.get_run_record_by_idempotency_key(
                workflow_id,
                tenant_id=tenant_id,
                idempotency_key=normalized_idempotency_key,
            )
            if existing is not None:
                self._logger.info(
                    "async_workflow_run_reused workflow_id=%s tenant_id=%s "
                    "idempotency_key=%s run_id=%s status=%s",
                    workflow_id,
                    tenant_id,
                    normalized_idempotency_key,
                    existing.get("id"),
                    existing.get("status"),
                )
                return build_run_query_payload(
                    self._reconcile_record(existing, tenant_id=tenant_id)
                )

        run_id = f"run_async_{uuid.uuid4().hex}"
        now = _utc_now_iso()
        runtime_input = normalize_runtime_input(input_data) or {}
        state = dict(runtime_input)
        state["execution"] = {
            "node_status": {
                node_id: "pending"
                for node_id in project.workflow.nodes
            },
        }
        initial_record = build_public_run_payload(
            run_id=run_id,
            workflow_id=workflow_id,
            project_name=project.name,
            workflow_name=workflow_id,
            execution_mode="async",
            status=RunStatus.RUNNING,
            stop_reason=RunStopReason.NONE,
            suspension_reason=RunStopReason.NONE,
            input_data=input_data,
            state=state,
            event_log=[],
            runtime_metrics={
                "async_worker": {
                    "status": "queued",
                    "thread_name": f"pylon-async-{workflow_id[:24]}-{run_id[-8:]}",
                }
            },
            logs=["execution_mode:async", "async_run:started"],
            created_at=now,
            started_at=now,
        )
        if correlation_id:
            initial_record["correlation_id"] = correlation_id
        if trace_id:
            initial_record["trace_id"] = trace_id
        initial_record["node_status"] = {
            node_id: "pending"
            for node_id in project.workflow.nodes
        }
        stored = self._store.put_run_record(
            initial_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=dict(parameters or {}),
        )
        if normalized_idempotency_key:
            self._store.put_run_idempotency_key(
                workflow_id,
                tenant_id=tenant_id,
                idempotency_key=normalized_idempotency_key,
                run_id=run_id,
            )

        thread_name = f"pylon-async-{workflow_id[:24]}-{run_id[-8:]}"

        thread = threading.Thread(
            target=self._execute_run,
            kwargs={
                "run_id": run_id,
                "workflow_id": workflow_id,
                "tenant_id": tenant_id,
                "input_data": input_data,
            },
            name=thread_name,
            daemon=True,
        )
        with self._lock:
            self._threads[run_id] = thread

        try:
            thread.start()
        except Exception as exc:
            with self._lock:
                self._threads.pop(run_id, None)
            self._logger.exception(
                "async_workflow_run_launch_failed workflow_id=%s tenant_id=%s run_id=%s",
                workflow_id,
                tenant_id,
                run_id,
            )
            stored = self._persist_failed_record(
                stored,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                error=f"Failed to launch async workflow worker: {exc}",
                log_code="async_run:launch_failed",
            )
            return build_run_query_payload(stored)

        self._logger.info(
            "async_workflow_run_started workflow_id=%s tenant_id=%s run_id=%s "
            "nodes=%s correlation_id=%s trace_id=%s",
            workflow_id,
            tenant_id,
            run_id,
            len(project.workflow.nodes),
            correlation_id or "",
            trace_id or "",
        )
        return build_run_query_payload(stored)

    def get_run(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        record = self._store.get_run_record(run_id)
        if record is None:
            return None
        if tenant_id is not None and record.get("tenant_id") != tenant_id:
            return None
        reconciled = self._reconcile_record(record, tenant_id=tenant_id)
        return build_run_query_payload(reconciled)

    def list_runs(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        runs = [
            build_run_query_payload(self._reconcile_record(record, tenant_id=tenant_id))
            for record in self._store.list_all_run_records()
            if record.get("tenant_id", tenant_id) == tenant_id
            and (workflow_id is None or record.get("workflow_id") == workflow_id)
        ]
        runs.sort(key=lambda payload: str(payload.get("created_at", "")), reverse=True)
        return runs

    def reconcile_orphaned_runs(self) -> int:
        recovered = 0
        for record in self._store.list_all_run_records():
            before = str(record.get("status", ""))
            reconciled = self._reconcile_record(record, tenant_id=record.get("tenant_id"))
            if before != str(reconciled.get("status", "")):
                recovered += 1
        if recovered:
            self._logger.warning(
                "async_workflow_run_reconciled recovered_runs=%s",
                recovered,
            )
        return recovered

    def _execute_run(
        self,
        *,
        run_id: str,
        workflow_id: str,
        tenant_id: str,
        input_data: Any,
    ) -> None:
        started_monotonic = time.monotonic()
        try:
            project = self._store.get_workflow_project(workflow_id, tenant_id=tenant_id)
            if project is None:
                raise KeyError(f"Workflow not found: {workflow_id}")
            artifacts = execute_project_sync(
                project,
                input_data=normalize_runtime_input(input_data),
                workflow_id=workflow_id,
                node_handlers=self._store.get_node_handlers(workflow_id),
                agent_handlers=self._store.get_agent_handlers(workflow_id),
                provider_registry=self._provider_registry,
            )
            stored = self._persist_artifacts(
                run_id=run_id,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                input_data=input_data,
                artifacts=artifacts,
                project_name=project.name,
                elapsed_ms=int((time.monotonic() - started_monotonic) * 1000),
            )
            self._logger.info(
                "async_workflow_run_finished workflow_id=%s tenant_id=%s "
                "run_id=%s status=%s events=%s checkpoints=%s duration_ms=%s",
                workflow_id,
                tenant_id,
                run_id,
                stored.get("status"),
                len(stored.get("event_log", [])),
                len(self._store.list_run_checkpoints(run_id)),
                stored.get("runtime_metrics", {}).get("async_duration_ms", 0),
            )
        except Exception as exc:
            self._logger.exception(
                "async_workflow_run_failed workflow_id=%s tenant_id=%s run_id=%s",
                workflow_id,
                tenant_id,
                run_id,
            )
            base = self._store.get_run_record(run_id) or {
                "id": run_id,
                "workflow_id": workflow_id,
                "workflow": workflow_id,
                "tenant_id": tenant_id,
                "status": RunStatus.RUNNING.value,
                "execution_mode": "async",
                "state": normalize_runtime_input(input_data) or {},
                "event_log": [],
            }
            self._persist_failed_record(
                base,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                error=f"Async workflow execution failed: {exc}",
                log_code="async_run:execution_failed",
                elapsed_ms=int((time.monotonic() - started_monotonic) * 1000),
            )
        finally:
            with self._lock:
                self._threads.pop(run_id, None)

    def _persist_artifacts(
        self,
        *,
        run_id: str,
        workflow_id: str,
        tenant_id: str,
        input_data: Any,
        artifacts: ExecutionArtifacts,
        project_name: str,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        existing = self._store.get_run_record(run_id)
        expected_record_version = (
            int(existing.get("record_version", 1))
            if isinstance(existing, dict)
            else None
        )
        run_record = serialize_run(
            artifacts,
            project_name=project_name,
            workflow_name=workflow_id,
            input_data=input_data,
        )
        run_record["id"] = run_id
        run_record["execution_mode"] = "async"
        runtime_metrics = dict(run_record.get("runtime_metrics") or {})
        runtime_metrics["async_duration_ms"] = elapsed_ms
        runtime_metrics["async_worker"] = {
            "status": "completed",
            "thread_name": threading.current_thread().name,
        }
        run_record["runtime_metrics"] = runtime_metrics
        if isinstance(existing, dict):
            if existing.get("correlation_id") is not None:
                run_record["correlation_id"] = existing.get("correlation_id")
            if existing.get("trace_id") is not None:
                run_record["trace_id"] = existing.get("trace_id")
        stored = self._store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=(
                dict(existing.get("parameters", {}))
                if isinstance(existing, dict)
                else {}
            ),
            expected_record_version=expected_record_version,
        )
        for checkpoint in artifacts.checkpoints:
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run_id
            checkpoint_payload["workflow_run_id"] = run_id
            self._store.put_checkpoint_record(checkpoint_payload)
        for approval in artifacts.approvals:
            approval_payload = dict(approval)
            approval_payload["run_id"] = (
                approval_payload.get("run_id")
                or approval_payload.get("context", {}).get("run_id")
                or run_id
            )
            if approval_payload["run_id"] != run_id:
                approval_payload["run_id"] = run_id
            self._store.put_approval_record(approval_payload)
        self._notify_terminal_run(stored, workflow_id=workflow_id, tenant_id=tenant_id)
        return stored

    def _persist_failed_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str,
        error: str,
        log_code: str,
        elapsed_ms: int | None = None,
    ) -> dict[str, Any]:
        expected_record_version = int(run_record.get("record_version", 1))
        rebuilt = rebuild_run_query_payload(
            run_record,
            status=RunStatus.FAILED,
            stop_reason=RunStopReason.WORKFLOW_ERROR,
            suspension_reason=RunStopReason.NONE,
            active_approval=None,
            approval_request_id=None,
            approvals=run_record.get("approvals", []),
            logs=[*list(run_record.get("logs", [])), log_code],
        )
        rebuilt["completed_at"] = _utc_now_iso()
        rebuilt["execution_mode"] = "async"
        rebuilt["error"] = error
        rebuilt["tenant_id"] = tenant_id
        runtime_metrics = dict(rebuilt.get("runtime_metrics") or {})
        if elapsed_ms is not None:
            runtime_metrics["async_duration_ms"] = elapsed_ms
        runtime_metrics["async_worker"] = {
            "status": "failed",
            "thread_name": threading.current_thread().name,
        }
        rebuilt["runtime_metrics"] = runtime_metrics
        state = dict(rebuilt.get("state", {}))
        state["error"] = error
        rebuilt["state"] = state
        stored = self._store.put_run_record(
            rebuilt,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=run_record.get("parameters", {}),
            expected_record_version=expected_record_version,
        )
        self._notify_terminal_run(stored, workflow_id=workflow_id, tenant_id=tenant_id)
        return stored

    def _reconcile_record(
        self,
        run_record: dict[str, Any],
        *,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        if not _is_async_running(run_record):
            return run_record
        run_id = str(run_record.get("id", ""))
        with self._lock:
            thread = self._threads.get(run_id)
        if thread is not None and thread.is_alive():
            return run_record
        reason = (
            "Async workflow worker is no longer running. "
            "The server restarted or the worker exited before persisting a terminal state."
        )
        self._logger.warning(
            "async_workflow_run_orphaned workflow_id=%s tenant_id=%s run_id=%s",
            run_record.get("workflow_id", run_record.get("workflow", "")),
            tenant_id or run_record.get("tenant_id", ""),
            run_id,
        )
        return self._persist_failed_record(
            run_record,
            workflow_id=str(run_record.get("workflow_id", run_record.get("workflow", ""))),
            tenant_id=str(tenant_id or run_record.get("tenant_id", "default")),
            error=reason,
            log_code="async_run:orphaned",
        )

    def _notify_terminal_run(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str,
    ) -> None:
        if str(run_record.get("status", "")) not in TERMINAL_ASYNC_RUN_STATUSES:
            return
        if self._on_terminal_run is None:
            return
        try:
            self._on_terminal_run(run_record, workflow_id, tenant_id)
        except Exception:
            self._logger.exception(
                "async_workflow_run_terminal_callback_failed "
                "workflow_id=%s tenant_id=%s run_id=%s status=%s",
                workflow_id,
                tenant_id,
                run_record.get("id"),
                run_record.get("status"),
            )
