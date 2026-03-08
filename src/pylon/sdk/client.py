from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pylon.approval import ApprovalManager, ApprovalRequest, ApprovalStore
from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.dsl.parser import PylonProject, load_project
from pylon.observability.query_service import (
    build_replay_query_payload,
    build_run_query_payload,
)
from pylon.observability.run_record import rebuild_run_record
from pylon.repository.audit import AuditRepository, default_hmac_key
from pylon.runtime import (
    execute_project_sync,
    execute_single_node_sync,
    normalize_runtime_input,
    plan_project_dispatch,
    resume_project_sync,
    serialize_run,
)
from pylon.sdk.builder import WorkflowBuilder, WorkflowGraph
from pylon.sdk.config import SDKConfig
from pylon.sdk.decorators import AgentRegistry, WorkflowInfo
from pylon.sdk.project import (
    WorkflowBuilderError,
    WorkflowDefinitionValidationError,
    materialize_workflow_definition,
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


@dataclass
class AgentHandle:
    """A reference to a registered agent."""

    id: str
    name: str
    role: str
    capabilities: list[str]
    tools: list[str]


@dataclass
class WorkflowResult:
    """The outcome of a completed workflow run."""

    run_id: str
    status: RunStatus
    output: Any = None
    error: str | None = None
    stop_reason: RunStopReason = RunStopReason.NONE
    suspension_reason: RunStopReason = RunStopReason.NONE


@dataclass
class WorkflowRun:
    """Status snapshot of a workflow run."""

    run_id: str
    workflow_id: str
    workflow_name: str
    status: RunStatus
    project_name: str | None = None
    view_kind: str = "run"
    input_data: Any = None
    output: Any = None
    error: str | None = None
    stop_reason: RunStopReason = RunStopReason.NONE
    suspension_reason: RunStopReason = RunStopReason.NONE
    state: dict[str, Any] = field(default_factory=dict)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    goal: dict[str, Any] | None = None
    autonomy: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    runtime_metrics: dict[str, Any] | None = None
    policy_resolution: dict[str, Any] | None = None
    refinement_context: str | None = None
    approval_context: str | None = None
    termination_reason: str | None = None
    approval_request_id: str | None = None
    active_approval: dict[str, Any] | None = None
    approvals: list[dict[str, Any]] = field(default_factory=list)
    approval_summary: dict[str, Any] | None = None
    execution_summary: dict[str, Any] | None = None
    checkpoint_ids: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    state_version: int = 0
    state_hash: str = ""


class PylonClientError(Exception):
    """Raised on client-level errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class PylonClient:
    """In-memory Pylon client for defining and running agent workflows.

    This implementation stores all state locally so it can be used
    without a running Pylon server.  A future version will add HTTP
    transport.

    Args:
        base_url: The Pylon API base URL (unused in in-memory mode).
        api_key: Optional API key for authentication.
        timeout: Request timeout in seconds.
        config: Optional SDKConfig; overrides individual params when provided.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: int = 30,
        *,
        config: SDKConfig | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = SDKConfig(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
            )

        self._agents: dict[str, AgentHandle] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._run_payloads: dict[str, dict[str, Any]] = {}
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._approvals: dict[str, dict[str, Any]] = {}
        self._workflow_projects: dict[str, PylonProject] = {}
        self._workflow_node_handlers: dict[str, dict[str, Any]] = {}
        self._workflow_agent_handlers: dict[str, dict[str, Any]] = {}
        self._callables: dict[str, Any] = {}

    @property
    def config(self) -> SDKConfig:
        return self._config

    # -- Agent CRUD ----------------------------------------------------------

    def create_agent(
        self,
        name: str,
        role: str = "default",
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> AgentHandle:
        """Register a new agent and return its handle.

        Raises PylonClientError if an agent with the same name already exists.
        """
        if name in self._agents:
            raise PylonClientError(f"Agent {name!r} already exists")

        handle = AgentHandle(
            id=uuid.uuid4().hex[:12],
            name=name,
            role=role,
            capabilities=capabilities or [],
            tools=tools or [],
        )
        self._agents[name] = handle
        return handle

    def list_agents(self) -> list[AgentHandle]:
        """Return a list of all registered agents."""
        return list(self._agents.values())

    def get_agent(self, name: str) -> AgentHandle:
        """Look up an agent by name.

        Raises PylonClientError if not found.
        """
        if name not in self._agents:
            raise PylonClientError(f"Agent {name!r} not found")
        return self._agents[name]

    def delete_agent(self, name: str) -> None:
        """Remove an agent by name.

        Raises PylonClientError if not found.
        """
        if name not in self._agents:
            raise PylonClientError(f"Agent {name!r} not found")
        del self._agents[name]

    # -- Workflow execution --------------------------------------------------

    def _build_workflow_run(self, payload: dict[str, Any]) -> WorkflowRun:
        status = RunStatus(str(payload.get("status", RunStatus.PENDING.value)))
        stop_reason = RunStopReason(
            str(payload.get("stop_reason", RunStopReason.NONE.value))
        )
        suspension_reason = RunStopReason(
            str(payload.get("suspension_reason", RunStopReason.NONE.value))
        )
        state = dict(payload.get("state", {}))
        return WorkflowRun(
            run_id=str(payload["id"]),
            workflow_id=str(payload.get("workflow_id", payload.get("workflow", ""))),
            workflow_name=str(payload.get("workflow", payload.get("workflow_id", ""))),
            status=status,
            project_name=payload.get("project"),
            view_kind=str(payload.get("view_kind", "run")),
            input_data=payload.get("input"),
            output=state.get("output"),
            error=payload.get("error"),
            stop_reason=stop_reason,
            suspension_reason=suspension_reason,
            state=state,
            event_log=list(payload.get("event_log", [])),
            goal=payload.get("goal"),
            autonomy=payload.get("autonomy"),
            verification=payload.get("verification"),
            runtime_metrics=payload.get("runtime_metrics"),
            policy_resolution=payload.get("policy_resolution"),
            refinement_context=payload.get("refinement_context"),
            approval_context=payload.get("approval_context"),
            termination_reason=payload.get("termination_reason"),
            approval_request_id=payload.get("approval_request_id"),
            active_approval=payload.get("active_approval"),
            approvals=list(payload.get("approvals", [])),
            approval_summary=payload.get("approval_summary"),
            execution_summary=payload.get("execution_summary"),
            checkpoint_ids=list(payload.get("checkpoint_ids", [])),
            logs=list(payload.get("logs", [])),
            state_version=int(payload.get("state_version", 0)),
            state_hash=str(payload.get("state_hash", "")),
        )

    def _resolve_project_definition(
        self,
        definition: PylonProject | dict[str, Any] | str | Path,
    ) -> PylonProject:
        if isinstance(definition, PylonProject):
            return definition
        if isinstance(definition, dict):
            return PylonProject.model_validate(definition)
        return load_project(definition)

    def _workflow_summary(self, name: str, project: PylonProject) -> dict[str, Any]:
        return {
            "id": name,
            "project_name": project.name,
            "agent_count": len(project.agents),
            "node_count": len(project.workflow.nodes),
            "goal_enabled": project.goal is not None,
        }

    def _persist_execution(
        self,
        payload: dict[str, Any],
        artifacts: Any,
    ) -> WorkflowRun:
        run_id = str(payload["id"])
        stored_payload = dict(payload)
        self._run_payloads[run_id] = stored_payload
        for checkpoint in artifacts.checkpoints:
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run_id
            self._checkpoints[checkpoint.id] = checkpoint_payload
        for approval in artifacts.approvals:
            approval_payload = dict(approval)
            approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
                "context", {}
            ).get("run_id", run_id)
            self._approvals[approval_payload["id"]] = approval_payload
        run = self._build_workflow_run(build_run_query_payload(stored_payload))
        self._runs[run_id] = run
        return run

    def _checkpoint_payloads_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(checkpoint)
            for checkpoint in self._checkpoints.values()
            if checkpoint.get("run_id") == run_id
        ]

    def _approval_payloads_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(approval)
            for approval in self._approvals.values()
            if approval.get("run_id") == run_id
        ]

    def _approval_manager(self) -> tuple[ApprovalManager, ApprovalStore]:
        store = ApprovalStore()
        for payload in self._approvals.values():
            try:
                approval = ApprovalRequest.from_dict(payload)
            except Exception as exc:
                logger.warning(
                    "Skipping malformed approval payload %s: %s",
                    payload.get("id", "?"),
                    exc,
                )
                continue
            _run_sync(store.create(approval))
        return (
            ApprovalManager(
                store,
                AuditRepository(hmac_key=default_hmac_key()),
            ),
            store,
        )

    def _sync_approvals_from_store(self, store: ApprovalStore) -> None:
        for stored_request in _run_sync(store.list()):
            payload = stored_request.to_dict()
            existing = self._approvals.get(payload["id"], {})
            merged = {**existing, **payload}
            if "run_id" not in merged:
                merged["run_id"] = merged.get("context", {}).get("run_id", "")
            self._approvals[payload["id"]] = merged

    def _rebuild_run_payload(
        self,
        run_payload: dict[str, Any],
        *,
        status: RunStatus,
        stop_reason: RunStopReason,
        suspension_reason: RunStopReason,
        active_approval: dict[str, Any] | None,
        approval_request_id: str | None,
    ) -> dict[str, Any]:
        run_id = str(run_payload["id"])
        updated = rebuild_run_record(
            run_payload,
            status=status,
            stop_reason=stop_reason,
            suspension_reason=suspension_reason,
            active_approval=active_approval,
            approvals=self._approval_payloads_for_run(run_id),
            approval_request_id=approval_request_id,
        )
        self._run_payloads[run_id] = updated
        self._runs[run_id] = self._build_workflow_run(build_run_query_payload(updated))
        return updated

    def run_workflow(
        self,
        name: str,
        input_data: Any = None,
    ) -> WorkflowResult:
        """Execute a workflow synchronously and return the result.

        Workflow execution always uses the canonical compiled graph runtime.
        Ad hoc callable execution is exposed separately via ``run_callable``.
        """
        project = self._workflow_projects.get(name)
        if project is None and name in self._callables:
            raise PylonClientError(
                f"Workflow {name!r} is registered as a callable. Use run_callable() instead."
            )
        if project is None:
            raise PylonClientError(f"Workflow {name!r} not found")
        try:
            artifacts = execute_project_sync(
                project,
                input_data=normalize_runtime_input(input_data),
                workflow_id=name,
                node_handlers=self._workflow_node_handlers.get(name),
                agent_handlers=self._workflow_agent_handlers.get(name),
            )
            payload = serialize_run(
                artifacts,
                project_name=project.name,
                workflow_name=name,
                input_data=input_data,
            )
            run = self._persist_execution(payload, artifacts)
            run_id = run.run_id

            return WorkflowResult(
                run_id=run_id,
                status=run.status,
                output=run.output,
                stop_reason=run.stop_reason,
                suspension_reason=run.suspension_reason,
            )
        except Exception:
            run_id = uuid.uuid4().hex[:12]
            logger.exception("Workflow %r run %s failed", name, run_id)
            run = WorkflowRun(
                run_id=run_id,
                workflow_id=name,
                workflow_name=name,
                status=RunStatus.FAILED,
                input_data=input_data,
                error="Internal execution error",
                stop_reason=RunStopReason.WORKFLOW_ERROR,
            )
            self._runs[run_id] = run
            return WorkflowResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                error="Internal execution error",
                stop_reason=RunStopReason.WORKFLOW_ERROR,
            )

    def run_callable(self, name: str, input_data: Any = None) -> WorkflowResult:
        """Execute an ad hoc callable through the explicit single-step helper path."""
        if name not in self._callables:
            raise PylonClientError(f"Callable {name!r} not found")
        handler = self._callables[name]
        try:
            artifacts = execute_single_node_sync(name, input_data=input_data, handler=handler)
            payload = serialize_run(
                artifacts,
                project_name=name,
                workflow_name=name,
                input_data=input_data,
            )
            run = self._persist_execution(payload, artifacts)
            return WorkflowResult(
                run_id=run.run_id,
                status=run.status,
                output=run.output,
                stop_reason=run.stop_reason,
                suspension_reason=run.suspension_reason,
            )
        except Exception:
            run_id = uuid.uuid4().hex[:12]
            logger.exception("Callable %r run %s failed", name, run_id)
            run = WorkflowRun(
                run_id=run_id,
                workflow_id=name,
                workflow_name=name,
                status=RunStatus.FAILED,
                input_data=input_data,
                error="Internal execution error",
                stop_reason=RunStopReason.WORKFLOW_ERROR,
            )
            self._runs[run_id] = run
            return WorkflowResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                error="Internal execution error",
                stop_reason=RunStopReason.WORKFLOW_ERROR,
            )

    def register_project(
        self,
        name: str,
        definition: PylonProject | dict[str, Any] | str | Path,
    ) -> None:
        """Register a canonical workflow definition."""
        if isinstance(definition, dict):
            validation_result = validate_project_definition(definition)
            if not validation_result.valid:
                report = build_validation_report(validation_result)
                first_issue = validation_result.errors[0]
                raise PylonClientError(
                    f"Invalid workflow definition at {first_issue.field}: {first_issue.message}",
                    details={"validation": report},
                )
        try:
            project, node_handlers, agent_handlers = materialize_workflow_definition(
                definition,
                workflow_name=name,
                registry_agents=AgentRegistry.get_agents(),
                client_agents=self._agents,
                project_loader=load_project,
            )
        except WorkflowDefinitionValidationError as exc:
            raise PylonClientError(
                str(exc),
                details={"validation": exc.report},
            ) from exc
        except WorkflowBuilderError as exc:
            raise PylonClientError(str(exc)) from exc
        self._workflow_projects[name] = project
        self._workflow_node_handlers[name] = dict(node_handlers)
        self._workflow_agent_handlers[name] = dict(agent_handlers)

    def list_workflows(self) -> list[dict[str, Any]]:
        """List canonical workflow definitions known to the client."""
        return [
            self._workflow_summary(name, project)
            for name, project in self._workflow_projects.items()
        ]

    def get_workflow(self, name: str) -> PylonProject:
        """Retrieve a canonical workflow definition by its registered ID."""
        if name not in self._workflow_projects:
            raise PylonClientError(f"Workflow {name!r} not found")
        return self._workflow_projects[name]

    def delete_workflow(self, name: str) -> None:
        """Delete a canonical workflow definition by its registered ID."""
        if name not in self._workflow_projects:
            raise PylonClientError(f"Workflow {name!r} not found")
        del self._workflow_projects[name]
        self._workflow_node_handlers.pop(name, None)
        self._workflow_agent_handlers.pop(name, None)

    def plan_workflow(self, name: str, *, tenant_id: str = "default") -> dict[str, Any]:
        """Return the scheduler-oriented dispatch plan for a workflow."""
        project = self.get_workflow(name)
        return plan_project_dispatch(
            project,
            workflow_id=name,
            tenant_id=tenant_id,
        ).to_dict()

    def register_callable(self, name: str, handler: Any) -> None:
        """Register an explicit ad hoc callable."""
        self._callables[name] = handler

    def delete_callable(self, name: str) -> None:
        """Delete an explicit ad hoc callable."""
        if name not in self._callables:
            raise PylonClientError(f"Callable {name!r} not found")
        del self._callables[name]

    def register_workflow(self, name: str, definition: Any) -> None:
        """Register a canonical workflow definition for graph runtime execution."""
        is_workflow_definition = isinstance(
            definition,
            (PylonProject, dict, str, Path, WorkflowGraph, WorkflowBuilder, WorkflowInfo),
        ) or isinstance(getattr(definition, "_pylon_workflow", None), WorkflowInfo)
        if not is_workflow_definition:
            raise PylonClientError(
                "register_workflow() only accepts canonical workflow definitions. "
                "Use register_callable() for ad hoc single-step handlers."
            )
        if isinstance(definition, dict):
            validation_result = validate_project_definition(definition)
            if not validation_result.valid:
                report = build_validation_report(validation_result)
                first_issue = validation_result.errors[0]
                raise PylonClientError(
                    f"Invalid workflow definition at {first_issue.field}: {first_issue.message}",
                    details={"validation": report},
                )
        try:
            project, node_handlers, agent_handlers = materialize_workflow_definition(
                definition,
                workflow_name=name,
                registry_agents=AgentRegistry.get_agents(),
                client_agents=self._agents,
                project_loader=load_project,
            )
        except WorkflowDefinitionValidationError as exc:
            raise PylonClientError(
                str(exc),
                details={"validation": exc.report},
            ) from exc
        except WorkflowBuilderError as exc:
            raise PylonClientError(str(exc)) from exc
        self._workflow_projects[name] = project
        self._workflow_node_handlers[name] = dict(node_handlers)
        self._workflow_agent_handlers[name] = dict(agent_handlers)

    def resume_run(self, run_id: str, input_data: Any = None) -> WorkflowRun:
        """Resume a paused workflow run through the canonical runtime."""
        if run_id not in self._run_payloads:
            raise PylonClientError(f"Run {run_id!r} not found")
        run_payload = dict(self._run_payloads[run_id])
        workflow_id = str(run_payload.get("workflow_id", run_payload.get("workflow", "")))
        if not workflow_id:
            raise PylonClientError(f"Run {run_id!r} has no associated workflow_id")
        project = self.get_workflow(workflow_id)
        raw_input = run_payload.get("input") if input_data is None else input_data
        try:
            artifacts = resume_project_sync(
                project,
                run_payload,
                input_data=normalize_runtime_input(raw_input),
                checkpoints=self._checkpoint_payloads_for_run(run_id),
                approvals=self._approval_payloads_for_run(run_id),
                node_handlers=self._workflow_node_handlers.get(workflow_id),
                agent_handlers=self._workflow_agent_handlers.get(workflow_id),
            )
        except ValueError as exc:
            raise PylonClientError(str(exc)) from exc
        payload = serialize_run(
            artifacts,
            project_name=project.name,
            workflow_name=workflow_id,
            input_data=raw_input,
        )
        return self._persist_execution(payload, artifacts)

    def approve_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        """Approve a pending approval request and resume its run."""
        if approval_id not in self._approvals:
            raise PylonClientError(f"Approval request {approval_id!r} not found")
        request = self._approvals[approval_id]
        if request.get("status") != "pending":
            raise PylonClientError(f"Approval request already decided: {approval_id}")
        run_id = str(request.get("run_id", ""))
        if run_id not in self._run_payloads:
            raise PylonClientError(f"Run {run_id!r} not found")

        manager, store = self._approval_manager()
        _run_sync(manager.approve(approval_id, "sdk", comment=reason or ""))
        binding_plan = request.get("context", {}).get("binding_plan")
        binding_effects = request.get("context", {}).get("binding_effect_envelope")
        _run_sync(
            manager.validate_binding(
                approval_id,
                plan=binding_plan,
                effect_envelope=binding_effects,
            )
        )
        self._sync_approvals_from_store(store)
        decided = self._approvals[approval_id]
        decided["decided_at"] = decided.get("decided_at") or datetime.now(UTC).isoformat()
        if reason:
            decided["reason"] = reason
        return self.resume_run(run_id)

    def reject_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        """Reject a pending approval request and cancel its run."""
        if approval_id not in self._approvals:
            raise PylonClientError(f"Approval request {approval_id!r} not found")
        request = self._approvals[approval_id]
        if request.get("status") != "pending":
            raise PylonClientError(f"Approval request already decided: {approval_id}")
        run_id = str(request.get("run_id", ""))
        if run_id not in self._run_payloads:
            raise PylonClientError(f"Run {run_id!r} not found")

        manager, store = self._approval_manager()
        _run_sync(manager.reject(approval_id, "sdk", reason or ""))
        self._sync_approvals_from_store(store)
        decided = self._approvals[approval_id]
        decided["decided_at"] = decided.get("decided_at") or datetime.now(UTC).isoformat()
        if reason:
            decided["reason"] = reason

        run_payload = dict(self._run_payloads[run_id])
        run_payload.setdefault("logs", []).append(f"approval_rejected:{approval_id}")
        return self._build_workflow_run(
            self._rebuild_run_payload(
                run_payload,
                status=RunStatus.CANCELLED,
                stop_reason=RunStopReason.APPROVAL_DENIED,
                suspension_reason=RunStopReason.NONE,
                active_approval=None,
                approval_request_id=None,
            )
        )

    def replay_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        """Replay a checkpoint and return the normalized replay payload."""
        checkpoint = self._checkpoints.get(checkpoint_id)
        if checkpoint is None:
            raise PylonClientError(f"Checkpoint {checkpoint_id!r} not found")
        source_run_id = str(checkpoint.get("run_id", ""))
        source_run = self._run_payloads.get(source_run_id)
        if source_run is None:
            raise PylonClientError(f"Run {source_run_id!r} not found")

        source_input = source_run.get("input")
        replay_input = normalize_runtime_input(source_input) or {}
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
            initial_state=replay_input,
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
        return build_replay_query_payload(
            source_run=source_run,
            checkpoint_id=checkpoint_id,
            replayed=replayed,
            replay_view=replay_view,
            approvals=(
                self._approval_payloads_for_run(source_run_id)
                if replay_view["is_terminal_replay"]
                else []
            ),
        )

    def get_run(self, run_id: str) -> WorkflowRun:
        """Retrieve the status of a workflow run by its ID.

        Raises PylonClientError if the run ID is unknown.
        """
        if run_id not in self._run_payloads:
            raise PylonClientError(f"Run {run_id!r} not found")
        payload = build_run_query_payload(self._run_payloads[run_id])
        self._runs[run_id] = self._build_workflow_run(payload)
        return self._runs[run_id]
