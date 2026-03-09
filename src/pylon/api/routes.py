"""Route definitions for the Pylon API.

Each route handler follows HandlerFunc protocol: (Request) -> Response.
Routes project API concerns over a pluggable workflow control-plane backend.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pylon.api.authz import require_scopes
from pylon.api.health import build_default_checker, build_default_readiness_checker
from pylon.api.observability import APIObservabilityBundle
from pylon.api.schemas import (
    APPROVAL_DECISION_SCHEMA,
    CREATE_AGENT_SCHEMA,
    KILL_SWITCH_SCHEMA,
    WORKFLOW_DEFINITION_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    validate,
)
from pylon.api.server import APIServer, HandlerFunc, Request, Response
from pylon.control_plane import (
    ControlPlaneBackend,
    ControlPlaneStoreConfig,
    WorkflowControlPlaneStore,
    build_workflow_control_plane_store,
)
from pylon.control_plane.workflow_service import WorkflowRunService
from pylon.dsl.parser import PylonProject

logger = logging.getLogger(__name__)


class RouteStore:
    """API facade over the shared workflow control-plane store."""

    def __init__(
        self,
        *,
        control_plane_store: WorkflowControlPlaneStore | None = None,
        control_plane_backend: ControlPlaneBackend | str = ControlPlaneBackend.MEMORY,
        control_plane_path: str | None = None,
    ) -> None:
        self.agents: dict[str, dict] = {}
        self.kill_switches: dict[str, dict] = {}  # scope -> event
        if control_plane_store is None:
            backend = (
                control_plane_backend
                if isinstance(control_plane_backend, ControlPlaneBackend)
                else ControlPlaneBackend(str(control_plane_backend))
            )
            control_plane_store = build_workflow_control_plane_store(
                ControlPlaneStoreConfig(
                    backend=backend,
                    path=control_plane_path,
                )
            )
        self._control_plane_store = control_plane_store
        self._workflow_index: dict[str, set[str]] = {}
        self._rebuild_workflow_index()

    @property
    def control_plane_store(self) -> WorkflowControlPlaneStore:
        return self._control_plane_store

    @property
    def workflow_runs_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            str(run["id"]): run
            for run in self._control_plane_store.list_all_run_records()
        }

    @property
    def checkpoints(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for run in self._control_plane_store.list_all_run_records():
            run_id = str(run.get("id", ""))
            for checkpoint in self._control_plane_store.list_run_checkpoints(run_id):
                records[str(checkpoint["id"])] = checkpoint
        return records

    @property
    def approvals(self) -> dict[str, dict[str, Any]]:
        return {
            str(approval["id"]): approval
            for approval in self._control_plane_store.list_all_approval_records()
        }

    def _rebuild_workflow_index(self) -> None:
        self._workflow_index.clear()
        for tenant_id, workflow_id, _ in self._control_plane_store.list_all_workflow_projects():
            self._workflow_index.setdefault(workflow_id, set()).add(tenant_id)

    def register_workflow_project(
        self,
        workflow_id: str,
        project: PylonProject | dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> PylonProject:
        """Register a canonical workflow definition for API execution."""
        resolved = self._control_plane_store.register_workflow_project(
            workflow_id,
            project,
            tenant_id=tenant_id,
        )
        self._workflow_index.setdefault(workflow_id, set()).add(tenant_id)
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        self._control_plane_store.remove_workflow_project(workflow_id, tenant_id=tenant_id)
        tenants = self._workflow_index.get(workflow_id)
        if tenants is not None:
            tenants.discard(tenant_id)
            if not tenants:
                self._workflow_index.pop(workflow_id, None)

    def get_workflow_project(self, workflow_id: str, *, tenant_id: str) -> PylonProject | None:
        return self._control_plane_store.get_workflow_project(workflow_id, tenant_id=tenant_id)

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_run_record(run_id)

    def put_run_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str = "default",
        parameters: dict[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]:
        return self._control_plane_store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
            expected_record_version=expected_record_version,
        )

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_checkpoint_record(checkpoint_id)

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_checkpoint_record(checkpoint_payload)

    def list_workflow_projects(self, *, tenant_id: str) -> list[tuple[str, PylonProject]]:
        return self._control_plane_store.list_workflow_projects(tenant_id=tenant_id)

    def workflow_exists(self, workflow_id: str) -> bool:
        return workflow_id in self._workflow_index

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return self._control_plane_store.list_run_checkpoints(run_id)

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_approval_record(approval_id)

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_approval_record(approval_payload)

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        return self._control_plane_store.list_run_approvals(run_id)

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_node_handlers(workflow_id)

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_agent_handlers(workflow_id)

    def list_all_run_records(self) -> list[dict[str, Any]]:
        return self._control_plane_store.list_all_run_records()

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return self._control_plane_store.get_run_record_by_idempotency_key(
            workflow_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

    def put_run_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
        run_id: str,
    ) -> None:
        self._control_plane_store.put_run_idempotency_key(
            workflow_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            run_id=run_id,
        )

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        return self._control_plane_store.list_all_approval_records()

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None:
        return self._control_plane_store.get_audit_record(entry_id)

    def get_last_audit_record(self) -> dict[str, Any] | None:
        return self._control_plane_store.get_last_audit_record()

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_audit_record(audit_payload)

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._control_plane_store.list_audit_records(
            tenant_id=tenant_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )

    def get_queue_task_record(self, task_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_queue_task_record(task_id)

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_queue_task_record(task_payload)

    def delete_queue_task_record(self, task_id: str) -> bool:
        return self._control_plane_store.delete_queue_task_record(task_id)

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._control_plane_store.list_queue_task_records(status=status)

    def get_run_record_for_workflow(
        self,
        workflow_id: str,
        run_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        run = self.get_run_record(run_id)
        if run is None:
            return None
        if str(run.get("workflow_id", run.get("workflow", ""))) != workflow_id:
            return None
        if run.get("tenant_id") != tenant_id:
            return None
        return run


def _require_tenant_id(request: Request) -> str | None:
    """Extract tenant_id from request context; return None if missing."""
    return request.context.get("tenant_id")


def _tenant_required_response() -> Response:
    return Response(status_code=401, body={"error": "Tenant context required"})


def register_routes(
    server: APIServer,
    store: RouteStore | None = None,
    *,
    control_plane_store: WorkflowControlPlaneStore | None = None,
    control_plane_backend: ControlPlaneBackend | str = ControlPlaneBackend.MEMORY,
    control_plane_path: str | None = None,
    observability: APIObservabilityBundle | None = None,
    readiness_route_enabled: bool = True,
    metrics_route_enabled: bool = True,
) -> RouteStore:
    """Register all API routes on the server. Returns the store."""
    s = store or RouteStore(
        control_plane_store=control_plane_store,
        control_plane_backend=control_plane_backend,
        control_plane_path=control_plane_path,
    )
    if observability is not None:
        setattr(s, "_observability", observability)
    workflow_service = WorkflowRunService(s)

    def _workflow_summary(
        workflow_id: str,
        project: PylonProject,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {
            "id": workflow_id,
            "project_name": project.name,
            "tenant_id": tenant_id,
            "agent_count": len(project.agents),
            "node_count": len(project.workflow.nodes),
            "goal_enabled": project.goal is not None,
        }

    def _ensure_workflow_access(
        workflow_id: str,
        tenant_id: str,
    ) -> Response | None:
        if s.get_workflow_project(workflow_id, tenant_id=tenant_id) is not None:
            return None
        if not s.workflow_exists(workflow_id):
            return Response(
                status_code=404,
                body={"error": f"Workflow not found: {workflow_id}"},
            )
        return Response(status_code=403, body={"error": "Forbidden"})

    checker = observability.health_checker if observability is not None else build_default_checker()
    readiness_checker = (
        observability.readiness_checker
        if observability is not None
        else build_default_readiness_checker()
    )

    def _scoped(
        handler: HandlerFunc,
        *,
        any_of: tuple[str, ...] = (),
        all_of: tuple[str, ...] = (),
    ) -> HandlerFunc:
        def wrapped(request: Request) -> Response:
            auth_error = require_scopes(request, any_of=any_of, all_of=all_of)
            if auth_error is not None:
                return auth_error
            return handler(request)

        return wrapped

    def health(request: Request) -> Response:
        report = checker.run_all_sync()
        status_code = 200 if report["status"] != "unhealthy" else 503
        report["timestamp"] = time.time()
        return Response(status_code=status_code, body=report)

    def ready(request: Request) -> Response:
        report = readiness_checker.run_all_sync()
        ready_flag = report["status"] == "healthy"
        report["timestamp"] = time.time()
        report["ready"] = ready_flag
        report["status"] = "ready" if ready_flag else "not_ready"
        return Response(status_code=200 if ready_flag else 503, body=report)

    def metrics(request: Request) -> Response:
        if observability is None or observability.prometheus_exporter is None:
            return Response(
                status_code=404,
                body={"error": "Metrics exporter not configured"},
            )
        observability.prometheus_exporter.export_metrics(observability.metrics.get_metrics())
        return Response(
            headers={"content-type": "text/plain; version=0.0.4; charset=utf-8"},
            body=observability.prometheus_exporter.render_latest(),
        )

    def create_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, CREATE_AGENT_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        agent_id = uuid.uuid4().hex[:12]
        agent = {
            "id": agent_id,
            "name": body["name"],
            "model": body.get("model", ""),
            "role": body.get("role", ""),
            "autonomy": body.get("autonomy", "A2"),
            "tools": body.get("tools", []),
            "sandbox": body.get("sandbox", "gvisor"),
            "status": "ready",
            "tenant_id": tenant_id,
        }
        s.agents[agent_id] = agent
        return Response(status_code=201, body=agent)

    def list_agents(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agents = [a for a in s.agents.values() if a.get("tenant_id") == tenant_id]
        return Response(body={"agents": agents, "count": len(agents)})

    def get_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=agent)

    def delete_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.agents[agent_id]
        return Response(status_code=204, body=None)

    def create_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_DEFINITION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        workflow_id = str(body["id"])
        if s.get_workflow_project(workflow_id, tenant_id=tenant_id) is not None:
            return Response(
                status_code=409,
                body={"error": f"Workflow already exists: {workflow_id}"},
            )
        from pylon.config.pipeline import build_validation_report, validate_project_definition

        validation_result = validate_project_definition(body["project"])
        validation_report = build_validation_report(validation_result)
        if not validation_result.valid:
            return Response(
                status_code=422,
                body={
                    "error": "Workflow project validation failed",
                    "validation": validation_report,
                    "issues": [issue.to_dict() for issue in validation_result.issues],
                    "stages_passed": validation_result.stages_passed,
                },
            )
        try:
            project = s.register_workflow_project(
                workflow_id,
                body["project"],
                tenant_id=tenant_id,
            )
        except Exception as exc:
            return Response(status_code=422, body={"error": str(exc)})

        payload = {
            **_workflow_summary(workflow_id, project, tenant_id=tenant_id),
            "project": project.model_dump(mode="json"),
            "validation": validation_report,
        }
        if validation_result.warnings:
            payload["validation_warnings"] = [
                issue.to_dict() for issue in validation_result.warnings
            ]
        return Response(status_code=201, body=payload)

    def list_workflows(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflows = [
            _workflow_summary(workflow_id, project, tenant_id=tenant_id)
            for workflow_id, project in s.list_workflow_projects(tenant_id=tenant_id)
        ]
        return Response(body={"workflows": workflows, "count": len(workflows)})

    def get_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        assert project is not None
        return Response(
            body={
                **_workflow_summary(workflow_id, project, tenant_id=tenant_id),
                "project": project.model_dump(mode="json"),
            }
        )

    def get_workflow_plan(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        return Response(
            body=workflow_service.get_workflow_plan(
                workflow_id,
                tenant_id=tenant_id,
            )
        )

    def list_workflow_runs(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        runs = workflow_service.list_run_payloads(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
        )
        return Response(body={"runs": runs, "count": len(runs)})

    def delete_workflow(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        s.remove_workflow_project(workflow_id, tenant_id=tenant_id)
        return Response(status_code=204, body=None)

    def start_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        access_error = _ensure_workflow_access(workflow_id, tenant_id)
        if access_error is not None:
            return access_error
        body = request.body or {}
        raw_input = body.get("input")
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        try:
            stored_run = workflow_service.start_run(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                input_data=raw_input,
                parameters=body.get("parameters", {}),
                idempotency_key=body.get("idempotency_key"),
                execution_mode=body.get("execution_mode", "inline"),
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=400, body={"error": str(exc)})
        run_id = stored_run["id"]
        location = f"/api/v1/workflow-runs/{run_id}"
        return Response(
            status_code=202,
            headers={"content-type": "application/json", "location": location},
            body=workflow_service.get_run_payload(run_id),
        )

    def get_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record_for_workflow(workflow_id, run_id, tenant_id=tenant_id)
        if run is None:
            existing_run = s.get_run_record(run_id)
            if (
                existing_run is not None
                and str(existing_run.get("workflow_id", existing_run.get("workflow", "")))
                == workflow_id
                and existing_run.get("tenant_id") != tenant_id
            ):
                return Response(status_code=403, body={"error": "Forbidden"})
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        return Response(body=workflow_service.get_run_payload(run_id))

    def get_workflow_run_by_id(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=workflow_service.get_run_payload(run_id))

    def list_runs(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        runs = workflow_service.list_run_payloads(tenant_id=tenant_id)
        return Response(body={"runs": runs, "count": len(runs)})

    def list_approvals(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approvals = workflow_service.list_approval_payloads(tenant_id=tenant_id)
        return Response(body={"approvals": approvals, "count": len(approvals)})

    def list_run_approvals(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        approvals = workflow_service.list_approval_payloads(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        return Response(body={"approvals": approvals, "count": len(approvals)})

    def list_checkpoints(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        checkpoints = workflow_service.list_checkpoint_payloads(tenant_id=tenant_id)
        return Response(body={"checkpoints": checkpoints, "count": len(checkpoints)})

    def list_run_checkpoints(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        checkpoints = workflow_service.list_checkpoint_payloads(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        return Response(body={"checkpoints": checkpoints, "count": len(checkpoints)})

    def resume_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        raw_input = body.get("input", run.get("input"))
        try:
            stored_run = workflow_service.resume_run(
                run_id,
                tenant_id=tenant_id,
                input_data=raw_input,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=workflow_service.get_run_payload(str(stored_run["id"])))

    def approve_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.get_approval_record(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        if approval.get("status") != "pending":
            return Response(
                status_code=409,
                body={"error": f"Approval request already decided: {approval_id}"},
            )
        body = request.body or {}
        valid, errors = validate(body, APPROVAL_DECISION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        reason = body.get("reason")

        try:
            stored_run = workflow_service.approve_request(
                approval_id,
                tenant_id=tenant_id,
                actor="api",
                reason=reason,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        except Exception:
            logger.exception("Failed to resume run %s after approval", run_id)
            return Response(
                status_code=500,
                body={"error": f"Failed to resume run after approval: {run_id}"},
            )
        return Response(body=workflow_service.get_run_payload(str(stored_run["id"])))

    def reject_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.get_approval_record(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.get_run_record(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        if approval.get("status") != "pending":
            return Response(
                status_code=409,
                body={"error": f"Approval request already decided: {approval_id}"},
            )
        body = request.body or {}
        valid, errors = validate(body, APPROVAL_DECISION_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        reason = body.get("reason")

        try:
            updated = workflow_service.reject_request(
                approval_id,
                tenant_id=tenant_id,
                actor="api",
                reason=reason,
            )
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        return Response(body=workflow_service.get_run_payload(str(updated["id"])))

    def replay_checkpoint(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        checkpoint_id = request.path_params.get("checkpoint_id", "")
        checkpoint = s.get_checkpoint_record(checkpoint_id)
        if checkpoint is None:
            return Response(
                status_code=404,
                body={"error": f"Checkpoint not found: {checkpoint_id}"},
            )
        source_run_id = str(checkpoint.get("run_id", ""))
        source_run = s.get_run_record(source_run_id)
        if source_run is None:
            return Response(
                status_code=404,
                body={"error": f"Run not found: {source_run_id}"},
            )
        if source_run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        try:
            payload = workflow_service.replay_checkpoint(checkpoint_id)
        except KeyError as exc:
            return Response(status_code=404, body={"error": str(exc)})
        return Response(body=payload)

    def activate_kill_switch(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, KILL_SWITCH_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        scope: str = body["scope"]

        # Authorization: global scope requires admin tenant
        if scope == "global" and tenant_id != "admin":
            return Response(
                status_code=403,
                body={"error": "Only admin tenant can activate global kill switch"},
            )

        # Authorization: tenant-scoped switches only for own tenant
        if scope.startswith("tenant:"):
            scope_tenant = scope[len("tenant:"):]
            if scope_tenant != tenant_id:
                return Response(
                    status_code=403,
                    body={"error": "Cannot activate kill switch for another tenant"},
                )

        event = {
            "scope": scope,
            "reason": body["reason"],
            "issued_by": body["issued_by"],
            "parent_scope": body.get("parent_scope", ""),
            "activated_at": time.time(),
        }
        s.kill_switches[scope] = event
        return Response(status_code=201, body=event)

    server.add_route("GET", "/health", health)
    if readiness_route_enabled:
        server.add_route("GET", "/ready", ready)
    if metrics_route_enabled:
        server.add_route(
            "GET",
            "/metrics",
            _scoped(metrics, all_of=("observability:read",)),
        )
    server.add_route(
        "POST", "/agents", _scoped(create_agent, all_of=("agents:write",))
    )
    server.add_route("GET", "/agents", _scoped(list_agents, all_of=("agents:read",)))
    server.add_route(
        "GET", "/agents/{id}", _scoped(get_agent, all_of=("agents:read",))
    )
    server.add_route(
        "DELETE", "/agents/{id}", _scoped(delete_agent, all_of=("agents:write",))
    )
    server.add_route(
        "POST", "/workflows", _scoped(create_workflow, all_of=("workflows:write",))
    )
    server.add_route(
        "GET", "/workflows", _scoped(list_workflows, all_of=("workflows:read",))
    )
    server.add_route(
        "GET", "/workflows/{id}", _scoped(get_workflow, all_of=("workflows:read",))
    )
    server.add_route(
        "GET",
        "/workflows/{id}/plan",
        _scoped(get_workflow_plan, all_of=("workflows:read",)),
    )
    server.add_route(
        "DELETE",
        "/workflows/{id}",
        _scoped(delete_workflow, all_of=("workflows:write",)),
    )
    server.add_route(
        "GET",
        "/workflows/{id}/runs",
        _scoped(list_workflow_runs, all_of=("runs:read",)),
    )
    server.add_route(
        "POST",
        "/workflows/{id}/run",
        _scoped(start_workflow_run, all_of=("runs:write",)),
    )
    server.add_route(
        "GET", "/api/v1/workflow-runs", _scoped(list_runs, all_of=("runs:read",))
    )
    server.add_route(
        "GET",
        "/workflows/{id}/runs/{run_id}",
        _scoped(get_workflow_run, all_of=("runs:read",)),
    )
    server.add_route(
        "GET",
        "/api/v1/workflow-runs/{run_id}",
        _scoped(get_workflow_run_by_id, all_of=("runs:read",)),
    )
    server.add_route(
        "GET",
        "/api/v1/workflow-runs/{run_id}/approvals",
        _scoped(list_run_approvals, all_of=("approvals:read",)),
    )
    server.add_route(
        "GET",
        "/api/v1/workflow-runs/{run_id}/checkpoints",
        _scoped(list_run_checkpoints, all_of=("checkpoints:read",)),
    )
    server.add_route(
        "POST",
        "/api/v1/workflow-runs/{run_id}/resume",
        _scoped(resume_workflow_run, all_of=("runs:write",)),
    )
    server.add_route(
        "GET",
        "/api/v1/approvals",
        _scoped(list_approvals, all_of=("approvals:read",)),
    )
    server.add_route(
        "POST",
        "/api/v1/approvals/{approval_id}/approve",
        _scoped(approve_request, all_of=("approvals:write",)),
    )
    server.add_route(
        "POST",
        "/api/v1/approvals/{approval_id}/reject",
        _scoped(reject_request, all_of=("approvals:write",)),
    )
    server.add_route(
        "GET",
        "/api/v1/checkpoints",
        _scoped(list_checkpoints, all_of=("checkpoints:read",)),
    )
    server.add_route(
        "GET",
        "/api/v1/checkpoints/{checkpoint_id}/replay",
        _scoped(replay_checkpoint, all_of=("checkpoints:read",)),
    )
    server.add_route(
        "POST",
        "/kill-switch",
        _scoped(activate_kill_switch, all_of=("kill-switch:write",)),
    )

    return s
