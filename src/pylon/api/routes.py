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

logger = logging.getLogger(__name__)

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
from pylon.dsl.parser import PylonProject
from pylon.observability.run_payload import build_public_run_payload
from pylon.repository.audit import AuditRepository, default_hmac_key
from pylon.runtime import (
    execute_project_sync,
    normalize_runtime_input,
    resume_project_sync,
    serialize_run,
)
from pylon.types import RunStatus, RunStopReason
from pylon.workflow.replay import ReplayEngine, resolve_replay_view_state


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
        run_payload["workflow_id"] = workflow_id
        run_payload["tenant_id"] = tenant_id
        run_payload["parameters"] = dict(parameters or {})
        s.workflow_runs.setdefault((tenant_id, workflow_id), {})[run_id] = run_payload
        s.workflow_runs_by_id[run_id] = run_payload
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
        return run_payload

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
        }
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
        run = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=raw_input,
        )
        run = _persist_execution(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            run_payload=run,
            artifacts=artifacts,
            parameters=body.get("parameters", {}),
        )
        run_id = run["id"]
        location = f"/api/v1/workflow-runs/{run_id}"
        return Response(
            status_code=202,
            headers={"content-type": "application/json", "location": location},
            body=run,
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
        return Response(body=run)

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
        return Response(body=run)

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
        run_payload = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=raw_input,
        )
        return Response(
            body=_persist_execution(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                run_payload=run_payload,
                artifacts=artifacts,
                parameters=run.get("parameters", {}),
            )
        )

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
        run_payload = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=run.get("input"),
        )
        return Response(
            body=_persist_execution(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                run_payload=run_payload,
                artifacts=artifacts,
                parameters=run.get("parameters", {}),
            )
        )

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

        updated = build_public_run_payload(
            run_id=str(run["id"]),
            workflow_id=str(run.get("workflow_id", run.get("workflow", ""))),
            project_name=run.get("project"),
            workflow_name=run.get("workflow"),
            status=RunStatus.CANCELLED,
            stop_reason=RunStopReason.APPROVAL_DENIED,
            suspension_reason=RunStopReason.NONE,
            input_data=run.get("input"),
            state=dict(run.get("state", {})),
            goal=run.get("goal"),
            autonomy=run.get("autonomy"),
            verification=run.get("verification"),
            runtime_metrics=run.get("runtime_metrics"),
            policy_resolution=run.get("policy_resolution"),
            refinement_context=run.get("refinement_context"),
            approval_context=run.get("approval_context"),
            termination_reason=run.get("termination_reason"),
            active_approval=None,
            approvals=s.list_run_approvals(run_id),
            approval_request_id=None,
            state_version=int(run.get("state_version", 0)),
            state_hash=str(run.get("state_hash", "")),
            event_log=list(run.get("event_log", [])),
            checkpoint_ids=list(run.get("checkpoint_ids", [])),
            logs=[*list(run.get("logs", [])), f"approval_rejected:{approval_id}"],
            created_at=run.get("created_at"),
            started_at=run.get("started_at"),
            completed_at=run.get("completed_at"),
        )
        updated["workflow_id"] = str(run.get("workflow_id", run.get("workflow", "")))
        updated["tenant_id"] = tenant_id
        updated["parameters"] = dict(run.get("parameters", {}))
        workflow_id = updated["workflow_id"]
        s.workflow_runs.setdefault((tenant_id, workflow_id), {})[run_id] = updated
        s.workflow_runs_by_id[run_id] = updated
        return Response(body=updated)

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
            body=build_public_run_payload(
                run_id=source_run_id,
                workflow_id=str(source_run.get("workflow_id", source_run.get("workflow", ""))),
                project_name=source_run.get("project"),
                workflow_name=source_run.get("workflow"),
                status=replay_view["status"],
                stop_reason=replay_view["stop_reason"],
                suspension_reason=replay_view["suspension_reason"],
                input_data=source_input,
                state=replayed.state,
                goal=source_run.get("goal"),
                autonomy=source_run.get("autonomy"),
                verification=source_run.get("verification"),
                runtime_metrics=source_run.get("runtime_metrics"),
                policy_resolution=source_run.get("policy_resolution"),
                refinement_context=source_run.get("refinement_context"),
                approval_context=source_run.get("approval_context"),
                termination_reason=source_run.get("termination_reason"),
                active_approval=replay_view["active_approval"],
                approvals=(
                    s.list_run_approvals(source_run_id)
                    if replay_view["is_terminal_replay"]
                    else []
                ),
                approval_request_id=replay_view["approval_request_id"],
                state_version=replayed.state_version,
                state_hash=replayed.state_hash,
                event_log=replayed.event_log,
                checkpoint_ids=[checkpoint_id],
                logs=list(source_run.get("logs", [])),
                created_at=source_run.get("created_at"),
                started_at=source_run.get("started_at"),
                completed_at=source_run.get("completed_at"),
                view_kind="replay",
                replay={
                    "checkpoint_id": checkpoint_id,
                    "source_run": source_run_id,
                    "source_status": source_run.get("status"),
                    "source_stop_reason": source_run.get("stop_reason"),
                    "source_suspension_reason": source_run.get("suspension_reason"),
                    "state_hash_verified": replayed.state_hash_verified,
                },
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
