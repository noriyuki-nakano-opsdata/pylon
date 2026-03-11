from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pylon.config.pipeline import build_validation_report, validate_project_definition
from pylon.control_plane import (
    ControlPlaneBackend,
    ControlPlaneStoreConfig,
    build_workflow_control_plane_store,
)
from pylon.control_plane.workflow_service import WorkflowControlPlaneStore, WorkflowRunService
from pylon.dsl.parser import PylonProject, load_project
from pylon.observability.query_service import build_run_query_payload
from pylon.runtime import (
    execute_single_node_sync,
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

logger = logging.getLogger(__name__)


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
    execution_mode: str = "inline"
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
    queue_task_ids: list[str] = field(default_factory=list)
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
        control_plane_store: WorkflowControlPlaneStore | None = None,
        control_plane_backend: str | ControlPlaneBackend = ControlPlaneBackend.MEMORY,
        control_plane_path: str | None = None,
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
        self._callables: dict[str, Any] = {}
        if control_plane_store is not None:
            self._control_plane_store = control_plane_store
        else:
            backend = (
                control_plane_backend
                if isinstance(control_plane_backend, ControlPlaneBackend)
                else ControlPlaneBackend(str(control_plane_backend))
            )
            self._control_plane_store = build_workflow_control_plane_store(
                ControlPlaneStoreConfig(
                    backend=backend,
                    path=control_plane_path,
                )
            )

    @property
    def config(self) -> SDKConfig:
        return self._config

    @property
    def _workflow_service(self) -> WorkflowRunService:
        return WorkflowRunService(self)

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
            execution_mode=str(payload.get("execution_mode", "inline")),
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
            queue_task_ids=list(payload.get("queue_task_ids", [])),
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

    def get_workflow_project(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> PylonProject | None:
        project = self._control_plane_store.get_workflow_project(
            workflow_id,
            tenant_id=tenant_id,
        )
        if project is None and tenant_id != "default":
            return self._control_plane_store.get_workflow_project(
                workflow_id,
                tenant_id="default",
            )
        return project

    def get_run_record(self, run_id: str) -> dict[str, Any] | None:
        payload = self._run_payloads.get(run_id)
        if payload is None:
            payload = self._control_plane_store.get_run_record(run_id)
            if payload is not None:
                self._run_payloads[run_id] = dict(payload)
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
        stored_payload = self._control_plane_store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
            expected_record_version=expected_record_version,
        )
        run_id = str(stored_payload["id"])
        self._run_payloads[run_id] = stored_payload
        self._runs[run_id] = self._build_workflow_run(build_run_query_payload(stored_payload))
        return stored_payload

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None:
        checkpoint = self._control_plane_store.get_checkpoint_record(checkpoint_id)
        return None if checkpoint is None else dict(checkpoint)

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_checkpoint_record(checkpoint_payload)
        self._checkpoints[str(checkpoint_payload["id"])] = dict(checkpoint_payload)

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        checkpoints = self._control_plane_store.list_run_checkpoints(run_id)
        self._checkpoints.update({str(cp["id"]): dict(cp) for cp in checkpoints})
        return checkpoints

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None:
        approval = self._control_plane_store.get_approval_record(approval_id)
        return None if approval is None else dict(approval)

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None:
        self._control_plane_store.put_approval_record(approval_payload)
        self._approvals[str(approval_payload["id"])] = dict(approval_payload)

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]:
        approvals = self._control_plane_store.list_run_approvals(run_id)
        self._approvals.update({str(ap["id"]): dict(ap) for ap in approvals})
        return approvals

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_node_handlers(workflow_id)

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None:
        return self._control_plane_store.get_agent_handlers(workflow_id)

    def list_all_run_records(self) -> list[dict[str, Any]]:
        payloads = self._control_plane_store.list_all_run_records()
        self._run_payloads.update({str(payload["id"]): dict(payload) for payload in payloads})
        return payloads

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        payload = self._control_plane_store.get_run_record_by_idempotency_key(
            workflow_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if payload is not None:
            self._run_payloads[str(payload["id"])] = dict(payload)
        return payload

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
        payload = self._control_plane_store.get_run_record(run_id)
        if payload is not None:
            payload["idempotency_key"] = idempotency_key
            self._run_payloads[run_id] = payload
            self._runs[run_id] = self._build_workflow_run(build_run_query_payload(payload))

    def list_all_approval_records(self) -> list[dict[str, Any]]:
        payloads = self._control_plane_store.list_all_approval_records()
        self._approvals.update({str(payload["id"]): dict(payload) for payload in payloads})
        return payloads

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

    def allocate_sequence_value(self, name: str) -> int:
        return self._control_plane_store.allocate_sequence_value(name)

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

    def _persist_execution(
        self,
        payload: dict[str, Any],
        artifacts: Any,
    ) -> WorkflowRun:
        run_id = str(payload["id"])
        stored_payload = self.put_run_record(
            payload,
            workflow_id=str(payload.get("workflow_id", payload.get("workflow", ""))),
            parameters=payload.get("parameters", {}),
        )
        for checkpoint in artifacts.checkpoints:
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run_id
            self.put_checkpoint_record(checkpoint_payload)
        for approval in artifacts.approvals:
            approval_payload = dict(approval)
            approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
                "context", {}
            ).get("run_id", run_id)
            self.put_approval_record(approval_payload)
        run = self._build_workflow_run(build_run_query_payload(stored_payload))
        self._runs[run_id] = run
        return run

    def run_workflow(
        self,
        name: str,
        input_data: Any = None,
        *,
        idempotency_key: str | None = None,
        execution_mode: str = "inline",
    ) -> WorkflowResult:
        """Execute a workflow synchronously and return the result.

        Workflow execution always uses the canonical compiled graph runtime.
        Ad hoc callable execution is exposed separately via ``run_callable``.
        """
        project = self._control_plane_store.get_workflow_project(name)
        if project is None and name in self._callables:
            raise PylonClientError(
                f"Workflow {name!r} is registered as a callable. Use run_callable() instead."
            )
        if project is None:
            raise PylonClientError(f"Workflow {name!r} not found")
        try:
            stored_run = self._workflow_service.start_run(
                workflow_id=name,
                input_data=input_data,
                idempotency_key=idempotency_key,
                execution_mode=execution_mode,
            )
            run = self._build_workflow_run(
                self._workflow_service.get_run_payload(str(stored_run["id"]))
            )
            run_id = run.run_id

            return WorkflowResult(
                run_id=run_id,
                status=run.status,
                output=run.output,
                stop_reason=run.stop_reason,
                suspension_reason=run.suspension_reason,
            )
        except PylonClientError:
            raise
        except ValueError as exc:
            raise PylonClientError(str(exc)) from exc
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
        self._control_plane_store.register_workflow_project(name, project)
        if hasattr(self._control_plane_store, "set_handlers"):
            getattr(self._control_plane_store, "set_handlers")(
                name,
                node_handlers=dict(node_handlers),
                agent_handlers=dict(agent_handlers),
            )

    def list_workflows(self) -> list[dict[str, Any]]:
        """List canonical workflow definitions known to the client."""
        return [
            self._workflow_summary(name, project)
            for name, project in self._control_plane_store.list_workflow_projects()
        ]

    def get_workflow(self, name: str) -> PylonProject:
        """Retrieve a canonical workflow definition by its registered ID."""
        project = self._control_plane_store.get_workflow_project(name)
        if project is None:
            raise PylonClientError(f"Workflow {name!r} not found")
        return project

    def delete_workflow(self, name: str) -> None:
        """Delete a canonical workflow definition by its registered ID."""
        if self._control_plane_store.get_workflow_project(name) is None:
            raise PylonClientError(f"Workflow {name!r} not found")
        self._control_plane_store.remove_workflow_project(name, tenant_id="default")

    def plan_workflow(self, name: str, *, tenant_id: str = "default") -> dict[str, Any]:
        """Return the scheduler-oriented dispatch plan for a workflow."""
        try:
            return self._workflow_service.get_workflow_plan(
                name,
                tenant_id=tenant_id,
            )
        except KeyError as exc:
            raise PylonClientError(str(exc)) from exc

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
        self._control_plane_store.register_workflow_project(name, project)
        if hasattr(self._control_plane_store, "set_handlers"):
            getattr(self._control_plane_store, "set_handlers")(
                name,
                node_handlers=dict(node_handlers),
                agent_handlers=dict(agent_handlers),
            )

    def resume_run(self, run_id: str, input_data: Any = None) -> WorkflowRun:
        """Resume a paused workflow run through the canonical runtime."""
        try:
            stored_run = self._workflow_service.resume_run(
                run_id,
                input_data=input_data,
            )
        except KeyError as exc:
            raise PylonClientError(str(exc)) from exc
        except ValueError as exc:
            raise PylonClientError(str(exc)) from exc
        return self._build_workflow_run(
            self._workflow_service.get_run_payload(str(stored_run["id"]))
        )

    def approve_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        """Approve a pending approval request and resume its run."""
        try:
            stored_run = self._workflow_service.approve_request(
                approval_id,
                actor="sdk",
                reason=reason,
            )
        except KeyError as exc:
            raise PylonClientError(str(exc)) from exc
        except ValueError as exc:
            raise PylonClientError(str(exc)) from exc
        return self._build_workflow_run(
            self._workflow_service.get_run_payload(str(stored_run["id"]))
        )

    def reject_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        """Reject a pending approval request and cancel its run."""
        try:
            stored_run = self._workflow_service.reject_request(
                approval_id,
                actor="sdk",
                reason=reason,
            )
        except KeyError as exc:
            raise PylonClientError(str(exc)) from exc
        except ValueError as exc:
            raise PylonClientError(str(exc)) from exc
        return self._build_workflow_run(
            self._workflow_service.get_run_payload(str(stored_run["id"]))
        )

    def replay_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        """Replay a checkpoint and return the normalized replay payload."""
        try:
            return self._workflow_service.replay_checkpoint(checkpoint_id)
        except KeyError as exc:
            raise PylonClientError(str(exc)) from exc

    def get_run(self, run_id: str) -> WorkflowRun:
        """Retrieve the status of a workflow run by its ID.

        Raises PylonClientError if the run ID is unknown.
        """
        if self._control_plane_store.get_run_record(run_id) is None:
            raise PylonClientError(f"Run {run_id!r} not found")
        payload = self._workflow_service.get_run_payload(run_id)
        self._run_payloads[run_id] = dict(payload)
        self._runs[run_id] = self._build_workflow_run(payload)
        return self._runs[run_id]

    def list_runs(self, *, workflow_id: str | None = None) -> list[WorkflowRun]:
        """List workflow runs projected through the canonical query service."""
        payloads = self._workflow_service.list_run_payloads(workflow_id=workflow_id)
        runs = [self._build_workflow_run(payload) for payload in payloads]
        for run in runs:
            self._runs[run.run_id] = run
        return runs

    def list_approvals(
        self,
        *,
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List approval records for operator-facing inspection."""
        return self._workflow_service.list_approval_payloads(
            workflow_id=workflow_id,
            run_id=run_id,
        )

    def list_checkpoints(
        self,
        *,
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List checkpoint records for operator-facing inspection."""
        return self._workflow_service.list_checkpoint_payloads(
            workflow_id=workflow_id,
            run_id=run_id,
        )
