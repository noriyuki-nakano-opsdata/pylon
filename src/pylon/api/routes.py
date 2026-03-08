"""Route definitions for the Pylon API.

Each route handler follows HandlerFunc protocol: (Request) -> Response.
Routes use in-memory stores for demonstration.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from pylon.api.schemas import (
    APPROVAL_DECISION_SCHEMA,
    CREATE_AGENT_SCHEMA,
    KILL_SWITCH_SCHEMA,
    WORKFLOW_DEFINITION_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    validate,
)
from pylon.api.server import APIServer, Request, Response
from pylon.approval import ApprovalManager, ApprovalRequest, ApprovalStore
from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.dsl.parser import PylonProject
from pylon.observability.query_service import (
    build_replay_query_payload,
    build_run_query_payload,
)
from pylon.observability.run_record import rebuild_run_record
from pylon.repository.audit import AuditRepository, default_hmac_key
from pylon.runtime import (
    execute_project_sync,
    normalize_runtime_input,
    plan_project_dispatch,
    resume_project_sync,
    serialize_run,
)
from pylon.types import RunStatus, RunStopReason
from pylon.workflow.replay import ReplayEngine, resolve_replay_view_state

logger = logging.getLogger(__name__)


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RouteStore:
    """In-memory data store for route handlers."""

    def __init__(self) -> None:
        self.agents: dict[str, dict] = {}
        self.workflow_projects: dict[tuple[str, str], PylonProject] = {}
        self.workflow_tenants: dict[tuple[str, str], str] = {}
        self.workflow_runs: dict[tuple[str, str], dict[str, dict]] = {}
        self.workflow_runs_by_id: dict[str, dict] = {}
        self.checkpoints: dict[str, dict] = {}
        self.approvals: dict[str, dict] = {}
        self.kill_switches: dict[str, dict] = {}  # scope -> event

    def _workflow_key(self, workflow_id: str, tenant_id: str) -> tuple[str, str]:
        return tenant_id, workflow_id

    def register_workflow_project(
        self,
        workflow_id: str,
        project: PylonProject | dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> PylonProject:
        """Register a canonical workflow definition for API execution."""
        resolved = (
            project
            if isinstance(project, PylonProject)
            else PylonProject.model_validate(project)
        )
        key = self._workflow_key(workflow_id, tenant_id)
        self.workflow_projects[key] = resolved
        self.workflow_tenants[key] = tenant_id
        return resolved

    def remove_workflow_project(self, workflow_id: str, *, tenant_id: str) -> None:
        key = self._workflow_key(workflow_id, tenant_id)
        self.workflow_projects.pop(key, None)
        self.workflow_tenants.pop(key, None)

    def get_workflow_project(self, workflow_id: str, *, tenant_id: str) -> PylonProject | None:
        return self.workflow_projects.get(self._workflow_key(workflow_id, tenant_id))

    def list_workflow_projects(self, *, tenant_id: str) -> list[tuple[str, PylonProject]]:
        return [
            (workflow_id, project)
            for (owner_tenant_id, workflow_id), project in self.workflow_projects.items()
            if owner_tenant_id == tenant_id
        ]

    def workflow_exists(self, workflow_id: str) -> bool:
        return any(
            stored_workflow_id == workflow_id
            for _, stored_workflow_id in self.workflow_projects
        )

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(checkpoint)
            for checkpoint in self.checkpoints.values()
            if checkpoint.get("run_id") == run_id
        ]

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(approval)
            for approval in self.approvals.values()
            if approval.get("run_id") == run_id
        ]


def _require_tenant_id(request: Request) -> str | None:
    """Extract tenant_id from request context; return None if missing."""
    return request.context.get("tenant_id")


def _tenant_required_response() -> Response:
    return Response(status_code=401, body={"error": "Tenant context required"})


def register_routes(server: APIServer, store: RouteStore | None = None) -> RouteStore:
    """Register all API routes on the server. Returns the store."""
    s = store or RouteStore()

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

    def _approval_manager() -> tuple[ApprovalManager, ApprovalStore]:
        approval_store = ApprovalStore()
        for payload in s.approvals.values():
            try:
                approval = ApprovalRequest.from_dict(payload)
            except Exception:
                logger.warning("Failed to parse approval payload: %s", payload)
                continue
            _run_sync(approval_store.create(approval))
        return (
            ApprovalManager(
                approval_store,
                AuditRepository(hmac_key=default_hmac_key()),
            ),
            approval_store,
        )

    def _sync_approvals_from_store(approval_store: ApprovalStore) -> None:
        for stored_request in _run_sync(approval_store.list()):
            payload = stored_request.to_dict()
            existing = s.approvals.get(payload["id"], {})
            merged = {**existing, **payload}
            if "run_id" not in merged:
                merged["run_id"] = merged.get("context", {}).get("run_id", "")
            s.approvals[payload["id"]] = merged

    def _persist_execution(
        *,
        workflow_id: str,
        tenant_id: str,
        run_payload: dict[str, Any],
        artifacts: Any,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_payload["id"])
        stored_run = dict(run_payload)
        stored_run["workflow_id"] = workflow_id
        stored_run["tenant_id"] = tenant_id
        stored_run["parameters"] = dict(parameters or {})
        s.workflow_runs.setdefault((tenant_id, workflow_id), {})[run_id] = stored_run
        s.workflow_runs_by_id[run_id] = stored_run
        for checkpoint in artifacts.checkpoints:
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run_id
            s.checkpoints[checkpoint.id] = checkpoint_payload
        for approval in artifacts.approvals:
            approval_payload = dict(approval)
            approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
                "context", {}
            ).get("run_id", run_id)
            s.approvals[approval_payload["id"]] = approval_payload
        return stored_run

    def health(request: Request) -> Response:
        return Response(body={"status": "ok", "timestamp": time.time()})

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
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        assert project is not None
        return Response(
            body=plan_project_dispatch(
                project,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
            ).to_dict()
        )

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
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        assert project is not None
        body = request.body or {}
        raw_input = body.get("input")
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        artifacts = execute_project_sync(
            project,
            input_data=normalize_runtime_input(raw_input),
            workflow_id=workflow_id,
        )
        run_record = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=raw_input,
        )
        stored_run = _persist_execution(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            run_payload=run_record,
            artifacts=artifacts,
            parameters=body.get("parameters", {}),
        )
        run_id = stored_run["id"]
        location = f"/api/v1/workflow-runs/{run_id}"
        return Response(
            status_code=202,
            headers={"content-type": "application/json", "location": location},
            body=build_run_query_payload(stored_run),
        )

    def get_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        run_id = request.path_params.get("run_id", "")
        runs = s.workflow_runs.get((tenant_id, workflow_id), {})
        run = runs.get(run_id)
        if run is None:
            existing_run = s.workflow_runs_by_id.get(run_id)
            if (
                existing_run is not None
                and str(existing_run.get("workflow_id", existing_run.get("workflow", "")))
                == workflow_id
                and existing_run.get("tenant_id") != tenant_id
            ):
                return Response(status_code=403, body={"error": "Forbidden"})
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        return Response(body=build_run_query_payload(run))

    def get_workflow_run_by_id(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.workflow_runs_by_id.get(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=build_run_query_payload(run))

    def resume_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.workflow_runs_by_id.get(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})

        workflow_id = str(run.get("workflow_id", run.get("workflow", "")))
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        if project is None:
            return Response(
                status_code=404,
                body={"error": f"Workflow not found: {workflow_id}"},
            )
        raw_input = body.get("input", run.get("input"))
        try:
            artifacts = resume_project_sync(
                project,
                run,
                input_data=normalize_runtime_input(raw_input),
                checkpoints=s.list_run_checkpoints(run_id),
                approvals=s.list_run_approvals(run_id),
            )
        except ValueError as exc:
            return Response(status_code=409, body={"error": str(exc)})
        run_record = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=raw_input,
        )
        stored_run = _persist_execution(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            run_payload=run_record,
            artifacts=artifacts,
            parameters=run.get("parameters", {}),
        )
        return Response(body=build_run_query_payload(stored_run))

    def approve_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.approvals.get(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.workflow_runs_by_id.get(run_id)
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

        manager, approval_store = _approval_manager()
        _run_sync(manager.approve(approval_id, "api", comment=reason or ""))
        _run_sync(
            manager.validate_binding(
                approval_id,
                plan=approval.get("context", {}).get("binding_plan"),
                effect_envelope=approval.get("context", {}).get("binding_effect_envelope"),
            )
        )
        _sync_approvals_from_store(approval_store)
        decided = s.approvals[approval_id]
        decided["decided_at"] = decided.get("decided_at") or time.time()
        if reason:
            decided["reason"] = reason

        workflow_id = str(run.get("workflow_id", run.get("workflow", "")))
        project = s.get_workflow_project(workflow_id, tenant_id=tenant_id)
        if project is None:
            return Response(
                status_code=404,
                body={"error": f"Workflow not found: {workflow_id}"},
            )
        try:
            artifacts = resume_project_sync(
                project,
                run,
                input_data=normalize_runtime_input(run.get("input")),
                checkpoints=s.list_run_checkpoints(run_id),
                approvals=s.list_run_approvals(run_id),
            )
        except Exception:
            logger.exception("Failed to resume run %s after approval", run_id)
            return Response(
                status_code=500,
                body={"error": f"Failed to resume run after approval: {run_id}"},
            )
        run_record = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=run.get("input"),
        )
        stored_run = _persist_execution(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            run_payload=run_record,
            artifacts=artifacts,
            parameters=run.get("parameters", {}),
        )
        return Response(body=build_run_query_payload(stored_run))

    def reject_request(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        approval_id = request.path_params.get("approval_id", "")
        approval = s.approvals.get(approval_id)
        if approval is None:
            return Response(
                status_code=404,
                body={"error": f"Approval request not found: {approval_id}"},
            )
        run_id = str(approval.get("run_id", ""))
        run = s.workflow_runs_by_id.get(run_id)
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

        manager, approval_store = _approval_manager()
        _run_sync(manager.reject(approval_id, "api", reason or ""))
        _sync_approvals_from_store(approval_store)
        decided = s.approvals[approval_id]
        decided["decided_at"] = decided.get("decided_at") or time.time()
        if reason:
            decided["reason"] = reason

        updated = rebuild_run_record(
            run,
            status=RunStatus.CANCELLED,
            stop_reason=RunStopReason.APPROVAL_DENIED,
            suspension_reason=RunStopReason.NONE,
            active_approval=None,
            approvals=s.list_run_approvals(run_id),
            approval_request_id=None,
            logs=[*list(run.get("logs", [])), f"approval_rejected:{approval_id}"],
        )
        updated["workflow_id"] = str(run.get("workflow_id", run.get("workflow", "")))
        updated["tenant_id"] = tenant_id
        updated["parameters"] = dict(run.get("parameters", {}))
        workflow_id = updated["workflow_id"]
        s.workflow_runs.setdefault((tenant_id, workflow_id), {})[run_id] = updated
        s.workflow_runs_by_id[run_id] = updated
        return Response(body=build_run_query_payload(updated))

    def replay_checkpoint(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        checkpoint_id = request.path_params.get("checkpoint_id", "")
        checkpoint = s.checkpoints.get(checkpoint_id)
        if checkpoint is None:
            return Response(
                status_code=404,
                body={"error": f"Checkpoint not found: {checkpoint_id}"},
            )
        source_run_id = str(checkpoint.get("run_id", ""))
        source_run = s.workflow_runs_by_id.get(source_run_id)
        if source_run is None:
            return Response(
                status_code=404,
                body={"error": f"Run not found: {source_run_id}"},
            )
        if source_run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})

        source_input = source_run.get("input")
        initial_state = normalize_runtime_input(source_input) or {}
        checkpoint_events = list(checkpoint.get("event_log", []))
        source_events = list(source_run.get("event_log", []))
        max_seq = max(
            (
                int(event.get("seq", 0))
                for event in checkpoint_events
                if event.get("seq") is not None
            ),
            default=0,
        )
        replay_events = source_events
        if max_seq > 0 and source_events:
            replay_events = [
                event for event in source_events if int(event.get("seq", 0)) <= max_seq
            ]
        elif checkpoint_events:
            replay_events = checkpoint_events

        replayed = ReplayEngine.replay_event_log(
            replay_events,
            initial_state=initial_state,
            source_status=RunStatus(str(source_run.get("status", RunStatus.COMPLETED.value))),
            stop_reason=RunStopReason(
                str(source_run.get("stop_reason", RunStopReason.NONE.value))
            ),
            suspension_reason=RunStopReason(
                str(source_run.get("suspension_reason", RunStopReason.NONE.value))
            ),
            active_approval=source_run.get("active_approval"),
        )
        replay_view = resolve_replay_view_state(
            source_status=RunStatus(str(source_run.get("status", RunStatus.COMPLETED.value))),
            stop_reason=RunStopReason(
                str(source_run.get("stop_reason", RunStopReason.NONE.value))
            ),
            suspension_reason=RunStopReason(
                str(source_run.get("suspension_reason", RunStopReason.NONE.value))
            ),
            source_event_count=len(source_events),
            replayed_event_count=len(replay_events),
            active_approval=source_run.get("active_approval"),
            approval_request_id=source_run.get("approval_request_id"),
        )
        return Response(
            body=build_replay_query_payload(
                source_run=source_run,
                checkpoint_id=checkpoint_id,
                replayed=replayed,
                replay_view=replay_view,
                approvals=(
                    s.list_run_approvals(source_run_id)
                    if replay_view["is_terminal_replay"]
                    else []
                ),
            )
        )

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
    server.add_route("POST", "/agents", create_agent)
    server.add_route("GET", "/agents", list_agents)
    server.add_route("GET", "/agents/{id}", get_agent)
    server.add_route("DELETE", "/agents/{id}", delete_agent)
    server.add_route("POST", "/workflows", create_workflow)
    server.add_route("GET", "/workflows", list_workflows)
    server.add_route("GET", "/workflows/{id}", get_workflow)
    server.add_route("GET", "/workflows/{id}/plan", get_workflow_plan)
    server.add_route("DELETE", "/workflows/{id}", delete_workflow)
    server.add_route("POST", "/workflows/{id}/run", start_workflow_run)
    server.add_route("GET", "/workflows/{id}/runs/{run_id}", get_workflow_run)
    server.add_route("GET", "/api/v1/workflow-runs/{run_id}", get_workflow_run_by_id)
    server.add_route("POST", "/api/v1/workflow-runs/{run_id}/resume", resume_workflow_run)
    server.add_route("POST", "/api/v1/approvals/{approval_id}/approve", approve_request)
    server.add_route("POST", "/api/v1/approvals/{approval_id}/reject", reject_request)
    server.add_route("GET", "/api/v1/checkpoints/{checkpoint_id}/replay", replay_checkpoint)
    server.add_route("POST", "/kill-switch", activate_kill_switch)

    return s
