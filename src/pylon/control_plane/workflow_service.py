"""Shared control-plane service for workflow run lifecycle operations."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Mapping
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pylon.approval import ApprovalManager
from pylon.autonomy.explainability import DecisionExplainer
from pylon.control_plane.adapters import (
    StoreBackedApprovalStore,
    StoreBackedAuditRepository,
)
from pylon.control_plane.lifecycle_handlers import ensure_lifecycle_workflow_handlers
from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError
from pylon.observability.query_service import (
    build_replay_query_payload,
    build_run_query_payload,
)
from pylon.observability.run_record import build_run_record, rebuild_run_record
from pylon.observability.tracing import Tracer
from pylon.repository.audit import default_hmac_key
from pylon.repository.checkpoint import Checkpoint
from pylon.repository.workflow import WorkflowRun
from pylon.runtime import (
    ExecutionArtifacts,
    normalize_runtime_input,
    plan_project_dispatch,
    resume_project_sync,
)
from pylon.runtime.execution import execute_project_sync, serialize_run
from pylon.runtime.llm import LLMRuntime, ProviderRegistry
from pylon.runtime.queued_runner import QueuedWorkflowDispatchRunner
from pylon.skills.runtime import SkillRuntime, get_default_skill_runtime
from pylon.taskqueue import ExponentialBackoff, FixedRetry, TaskStatus
from pylon.types import (
    AutonomyLevel,
    RunStatus,
    RunStopReason,
    WorkflowJoinPolicy,
    WorkflowNodeType,
)
from pylon.workflow.replay import ReplayEngine, resolve_replay_view_state
from pylon.workflow.result import NodeResult
from pylon.workflow.state import compute_state_hash

logger = logging.getLogger(__name__)


def _run_sync(coro: object) -> object:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _invoke_registered_handler_sync(
    handler: Any,
    *,
    node_id: str,
    state: dict[str, Any],
) -> Any:
    signature = inspect.signature(handler)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    has_varargs = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if has_varargs or len(positional) >= 2:
        result = handler(node_id, state)
    elif len(positional) == 1:
        result = handler(state)
    else:
        result = handler()
    if inspect.isawaitable(result):
        return _run_sync(result)
    return result


@runtime_checkable
class WorkflowControlPlaneStore(Protocol):
    """Minimal storage contract used by WorkflowRunService."""

    def get_workflow_project(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> PylonProject | None: ...

    def list_all_workflow_projects(self) -> list[tuple[str, str, PylonProject]]: ...

    def get_run_record(self, run_id: str) -> dict[str, Any] | None: ...

    def put_run_record(
        self,
        run_record: dict[str, Any],
        *,
        workflow_id: str,
        tenant_id: str = "default",
        parameters: Mapping[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]: ...

    def get_checkpoint_record(self, checkpoint_id: str) -> dict[str, Any] | None: ...

    def put_checkpoint_record(self, checkpoint_payload: dict[str, Any]) -> None: ...

    def list_run_checkpoints(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_all_run_records(self) -> list[dict[str, Any]]: ...

    def get_run_record_by_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
    ) -> dict[str, Any] | None: ...

    def put_run_idempotency_key(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
        idempotency_key: str,
        run_id: str,
    ) -> None: ...

    def get_approval_record(self, approval_id: str) -> dict[str, Any] | None: ...

    def put_approval_record(self, approval_payload: dict[str, Any]) -> None: ...

    def list_run_approvals(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_all_approval_records(self) -> list[dict[str, Any]]: ...

    def get_audit_record(self, entry_id: int) -> dict[str, Any] | None: ...

    def get_last_audit_record(self) -> dict[str, Any] | None: ...

    def put_audit_record(self, audit_payload: dict[str, Any]) -> None: ...

    def list_audit_records(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def get_queue_task_record(self, task_id: str) -> dict[str, Any] | None: ...

    def put_queue_task_record(self, task_payload: dict[str, Any]) -> None: ...

    def delete_queue_task_record(self, task_id: str) -> bool: ...

    def list_queue_task_records(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> dict[str, Any] | None: ...

    def put_surface_record(
        self,
        namespace: str,
        record_id: str,
        payload: Mapping[str, Any],
        expected_record_version: int | None = None,
    ) -> dict[str, Any]: ...

    def delete_surface_record(
        self,
        namespace: str,
        record_id: str,
    ) -> bool: ...

    def list_surface_records(
        self,
        namespace: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def allocate_sequence_value(self, name: str) -> int: ...

    def get_node_handlers(self, workflow_id: str) -> dict[str, Any] | None: ...

    def get_agent_handlers(self, workflow_id: str) -> dict[str, Any] | None: ...


class WorkflowRunService:
    """Shared write-side control plane for workflow lifecycle operations."""

    def __init__(
        self,
        store: WorkflowControlPlaneStore,
        *,
        provider_registry: ProviderRegistry | None = None,
        llm_runtime: LLMRuntime | None = None,
        skill_runtime: SkillRuntime | None = None,
        tracer: Tracer | None = None,
        decision_explainer: DecisionExplainer | None = None,
    ) -> None:
        self._store = store
        self._provider_registry = provider_registry
        self._llm_runtime = llm_runtime
        self._skill_runtime = skill_runtime or get_default_skill_runtime()
        self._tracer = tracer
        self._decision_explainer = decision_explainer or DecisionExplainer()

    def _approval_manager(self) -> ApprovalManager:
        return (
            ApprovalManager(
                StoreBackedApprovalStore(self._store),
                StoreBackedAuditRepository(self._store, hmac_key=default_hmac_key()),
            )
        )

    def _current_trace_id(self) -> str | None:
        if self._tracer is None:
            return None
        context = self._tracer.current_context()
        if context is None:
            return None
        return context.trace_id

    def _trace_scope(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        if self._tracer is None:
            return nullcontext(None)
        return self._tracer.start_as_current_span(name, attributes=attributes)

    def _resolve_require_approval_above(self, level: str) -> AutonomyLevel:
        try:
            return AutonomyLevel[str(level).upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid require_approval_above policy value: {level}") from exc

    def _build_queued_dispatch_plan(
        self,
        *,
        workflow_id: str,
        tenant_id: str,
        run_id: str,
        project: PylonProject,
    ) -> dict[str, Any]:
        base_plan = plan_project_dispatch(
            project,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )
        task_id_map = {
            task.task_id: f"{run_id}:{task.node_id}"
            for task in base_plan.tasks
        }
        namespaced_tasks = tuple(
            task.__class__(
                task_id=task_id_map[task.task_id],
                node_id=task.node_id,
                wave_index=task.wave_index,
                depends_on=task.depends_on,
                dependency_task_ids=tuple(
                    task_id_map[dependency_task_id]
                    for dependency_task_id in task.dependency_task_ids
                ),
                node_type=task.node_type,
                join_policy=task.join_policy,
                conditional_inbound=task.conditional_inbound,
                conditional_outbound=task.conditional_outbound,
            )
            for task in base_plan.tasks
        )
        namespaced_plan = base_plan.__class__(
            workflow_id=base_plan.workflow_id,
            tenant_id=base_plan.tenant_id,
            execution_mode=base_plan.execution_mode,
            entry_nodes=base_plan.entry_nodes,
            tasks=namespaced_tasks,
            waves=tuple(
                tuple(node_id for node_id in wave)
                for wave in base_plan.waves
            ),
        )
        return {
            "public_plan": base_plan,
            "execution_plan": namespaced_plan,
        }

    def _validate_queued_execution_support(
        self,
        *,
        project: PylonProject,
        dispatch_plan: Any,
    ) -> None:
        issues: list[str] = []
        if project.goal is not None:
            issues.append("goal-driven workflows")
        require_above = self._resolve_require_approval_above(
            project.policy.require_approval_above
        )
        if any(
            project.agents[node.agent].to_autonomy_level() >= require_above
            for node in project.workflow.nodes.values()
        ):
            issues.append("approval-gated agent autonomy")
        for task in dispatch_plan.tasks:
            if task.conditional_inbound or task.conditional_outbound:
                issues.append("conditional edges")
                break
            if task.join_policy is not WorkflowJoinPolicy.ALL_RESOLVED:
                issues.append("non-default join policies")
                break
            if task.node_type is not WorkflowNodeType.AGENT:
                issues.append(f"node type {task.node_type.value}")
                break
        if issues:
            formatted = ", ".join(dict.fromkeys(issues))
            raise ValueError(
                "queued execution mode currently supports only straight-line agent DAGs "
                f"without goals, approvals, loops, routers, or conditional fan-in/out; "
                f"unsupported features: {formatted}"
            )

    def _invoke_project_node_for_queued_mode(
        self,
        *,
        project: PylonProject,
        workflow_id: str,
        node_id: str,
        state: dict[str, Any],
    ) -> NodeResult:
        node = project.workflow.nodes[node_id]
        custom_handler = None
        node_handlers = self._store.get_node_handlers(workflow_id) or {}
        agent_handlers = self._store.get_agent_handlers(workflow_id) or {}
        if node_id in node_handlers:
            custom_handler = node_handlers[node_id]
        elif node.agent in agent_handlers:
            custom_handler = agent_handlers[node.agent]

        if custom_handler is None:
            if self._provider_registry is None:
                return NodeResult(state_patch={f"{node_id}_done": True})
            single_node_project = PylonProject.model_validate(
                {
                    "version": project.version,
                    "name": f"{project.name}:{node_id}",
                    "description": project.description,
                    "agents": {
                        node.agent: project.agents[node.agent].model_dump(mode="json"),
                    },
                    "workflow": {
                        "type": "graph",
                        "nodes": {
                            node_id: {
                                "agent": node.agent,
                                "node_type": node.node_type,
                                "join_policy": node.join_policy,
                                "loop_max_iterations": node.loop_max_iterations,
                                "loop_criterion": node.loop_criterion,
                                "loop_threshold": node.loop_threshold,
                                "loop_metadata": dict(node.loop_metadata),
                                "next": "END",
                            }
                        },
                    },
                    "policy": project.policy.model_dump(mode="json"),
                }
            )
            artifacts = execute_project_sync(
                single_node_project,
                input_data=dict(state),
                workflow_id=f"{workflow_id}:{node_id}",
                provider_registry=self._provider_registry,
                llm_runtime=self._llm_runtime,
                skill_runtime=self._skill_runtime,
                tracer=self._tracer,
                decision_explainer=self._decision_explainer,
            )
            patch = dict(artifacts.run.state)
            patch.setdefault(f"{node_id}_done", True)
            return NodeResult(state_patch=patch)

        result = NodeResult.from_raw(
            _invoke_registered_handler_sync(
                custom_handler,
                node_id=node_id,
                state=dict(state),
            )
        )
        patch = dict(result.state_patch)
        patch.setdefault(f"{node_id}_done", True)
        return NodeResult(
            state_patch=patch,
            artifacts=list(result.artifacts),
            edge_decisions=dict(result.edge_decisions),
            llm_events=list(result.llm_events),
            tool_events=list(result.tool_events),
            metrics=dict(result.metrics),
            requires_approval=result.requires_approval,
            approval_request_id=result.approval_request_id,
            approval_reason=result.approval_reason,
        )

    def _build_queued_runtime_metrics(
        self,
        *,
        dispatch_plan: Any,
        queue_task_ids: list[str],
        recovered_running_tasks: int,
        queue_state: Mapping[str, Any] | None = None,
        retry_policy: Mapping[str, Any] | None = None,
        lease_timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float | None = None,
    ) -> dict[str, Any]:
        summary = dict(queue_state or {})
        return {
            "execution_mode": "queued",
            "queue": {
                "task_count": len(dispatch_plan.tasks),
                "wave_count": len(dispatch_plan.waves),
                "queue_task_ids": list(queue_task_ids),
                "recovered_running_tasks": recovered_running_tasks,
                "completed_task_ids": list(summary.get("completed_task_ids", [])),
                "failed_task_ids": list(summary.get("failed_task_ids", [])),
                "blocked_task_ids": list(summary.get("blocked_task_ids", [])),
                "retrying_task_ids": list(summary.get("retrying_task_ids", [])),
                "dead_letter_task_ids": list(summary.get("dead_letter_task_ids", [])),
                "retry_policy": dict(retry_policy or {}),
                "lease_timeout_seconds": lease_timeout_seconds,
                "heartbeat_interval_seconds": heartbeat_interval_seconds,
                "heartbeat_total": int(summary.get("heartbeat_total", 0)),
            },
        }

    def _resolve_queued_execution_config(
        self,
        parameters: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if parameters is None:
            return {
                "retry_policy": None,
                "retry_policy_config": None,
                "lease_timeout_seconds": 30.0,
                "heartbeat_interval_seconds": 15.0,
            }
        queued_config = parameters.get("queued")
        if queued_config in (None, {}):
            return {
                "retry_policy": None,
                "retry_policy_config": None,
                "lease_timeout_seconds": 30.0,
                "heartbeat_interval_seconds": 15.0,
            }
        if not isinstance(queued_config, Mapping):
            raise ValueError("parameters.queued must be an object when provided")
        lease_timeout_seconds = float(queued_config.get("lease_timeout_seconds", 30.0))
        if lease_timeout_seconds <= 0:
            raise ValueError("parameters.queued.lease_timeout_seconds must be > 0")
        heartbeat_interval_seconds = float(
            queued_config.get(
                "heartbeat_interval_seconds",
                max(min(lease_timeout_seconds / 2.0, 5.0), 0.1),
            )
        )
        if heartbeat_interval_seconds <= 0:
            raise ValueError(
                "parameters.queued.heartbeat_interval_seconds must be > 0"
            )
        if heartbeat_interval_seconds >= lease_timeout_seconds:
            raise ValueError(
                "parameters.queued.heartbeat_interval_seconds must be < "
                "lease_timeout_seconds"
            )
        retry_config = queued_config.get("retry")
        if retry_config in (None, {}):
            return {
                "retry_policy": None,
                "retry_policy_config": None,
                "lease_timeout_seconds": lease_timeout_seconds,
                "heartbeat_interval_seconds": heartbeat_interval_seconds,
            }
        if not isinstance(retry_config, Mapping):
            raise ValueError("parameters.queued.retry must be an object when provided")

        policy_name = str(retry_config.get("policy", "fixed")).strip().lower()
        max_retries = int(retry_config.get("max_retries", 1))
        if max_retries < 0:
            raise ValueError("parameters.queued.retry.max_retries must be >= 0")

        if policy_name == "fixed":
            delay_seconds = float(retry_config.get("delay_seconds", 1.0))
            if delay_seconds < 0:
                raise ValueError("parameters.queued.retry.delay_seconds must be >= 0")
            return {
                "retry_policy": FixedRetry(max_retries=max_retries, delay_seconds=delay_seconds),
                "retry_policy_config": {
                    "policy": "fixed",
                    "max_retries": max_retries,
                    "delay_seconds": delay_seconds,
                },
                "lease_timeout_seconds": lease_timeout_seconds,
                "heartbeat_interval_seconds": heartbeat_interval_seconds,
            }

        if policy_name in {"exponential", "exponential_backoff"}:
            base_delay_seconds = float(retry_config.get("base_delay_seconds", 1.0))
            max_delay_seconds = float(retry_config.get("max_delay_seconds", 60.0))
            if base_delay_seconds < 0:
                raise ValueError(
                    "parameters.queued.retry.base_delay_seconds must be >= 0"
                )
            if max_delay_seconds < 0:
                raise ValueError(
                    "parameters.queued.retry.max_delay_seconds must be >= 0"
                )
            if max_delay_seconds < base_delay_seconds:
                raise ValueError(
                    "parameters.queued.retry.max_delay_seconds must be >= "
                    "base_delay_seconds"
                )
            return {
                "retry_policy": ExponentialBackoff(
                    max_retries=max_retries,
                    base_delay_seconds=base_delay_seconds,
                    max_delay_seconds=max_delay_seconds,
                ),
                "retry_policy_config": {
                    "policy": "exponential_backoff",
                    "max_retries": max_retries,
                    "base_delay_seconds": base_delay_seconds,
                    "max_delay_seconds": max_delay_seconds,
                },
                "lease_timeout_seconds": lease_timeout_seconds,
                "heartbeat_interval_seconds": heartbeat_interval_seconds,
            }

        raise ValueError(
            "parameters.queued.retry.policy must be one of "
            "['fixed', 'exponential_backoff']"
        )

    def _build_queued_queue_state(
        self,
        *,
        runner: QueuedWorkflowDispatchRunner,
        queue_task_ids: list[str],
        blocked_task_ids: list[str] | tuple[str, ...],
        last_node_id: str | None = None,
        last_task_id: str | None = None,
        retry_policy: Mapping[str, Any] | None = None,
        lease_timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float | None = None,
        heartbeat_total: int = 0,
    ) -> dict[str, Any]:
        queue_tasks_by_id = {task.id: task for task in runner.queue.list()}

        def _task_ids_for(
            *,
            predicate: Any,
        ) -> list[str]:
            return [
                task_id
                for task_id in queue_task_ids
                if (
                    queue_tasks_by_id.get(task_id) is not None
                    and predicate(queue_tasks_by_id[task_id])
                )
            ]

        return {
            "queue_task_ids": list(queue_task_ids),
            "completed_task_ids": _task_ids_for(
                predicate=lambda task: task.status == TaskStatus.COMPLETED
            ),
            "failed_task_ids": _task_ids_for(
                predicate=lambda task: task.status == TaskStatus.FAILED
            ),
            "retrying_task_ids": _task_ids_for(
                predicate=lambda task: (
                    task.status == TaskStatus.PENDING
                    and bool(task.payload.get("retry", {}).get("scheduled"))
                )
            ),
            "dead_letter_task_ids": _task_ids_for(
                predicate=lambda task: bool(task.payload.get("dead_letter"))
            ),
            "blocked_task_ids": list(blocked_task_ids),
            "last_node_id": last_node_id,
            "last_task_id": last_task_id,
            "retry_policy": dict(retry_policy or {}),
            "lease_timeout_seconds": lease_timeout_seconds,
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
            "heartbeat_total": heartbeat_total,
        }

    def _start_queued_run(
        self,
        *,
        workflow_id: str,
        tenant_id: str,
        project: PylonProject,
        input_data: Any,
        parameters: Mapping[str, Any] | None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        run = WorkflowRun(workflow_id=workflow_id, tenant_id=tenant_id)
        run.start()
        initial_state = normalize_runtime_input(input_data) or {}
        dispatch_plans = self._build_queued_dispatch_plan(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            run_id=run.id,
            project=project,
        )
        public_plan = dispatch_plans["public_plan"]
        execution_plan = dispatch_plans["execution_plan"]
        self._validate_queued_execution_support(
            project=project,
            dispatch_plan=public_plan,
        )
        queued_config = self._resolve_queued_execution_config(parameters)
        retry_policy = queued_config["retry_policy"]
        retry_policy_config = queued_config["retry_policy_config"]
        lease_timeout_seconds = float(queued_config["lease_timeout_seconds"])
        heartbeat_interval_seconds = float(queued_config["heartbeat_interval_seconds"])
        runner = QueuedWorkflowDispatchRunner(
            self._store,
            recover_running_tasks=False,
            lease_timeout_seconds=lease_timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            retry_policy=retry_policy,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        queue_task_ids = [task.task_id for task in execution_plan.tasks]
        initial_queue_state = {
            "queue_task_ids": list(queue_task_ids),
            "completed_task_ids": [],
            "failed_task_ids": [],
            "retrying_task_ids": [],
            "dead_letter_task_ids": [],
            "blocked_task_ids": [],
            "last_node_id": None,
            "last_task_id": None,
            "retry_policy": dict(retry_policy_config or {}),
            "lease_timeout_seconds": lease_timeout_seconds,
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
            "heartbeat_total": 0,
        }
        run.state = {
            **initial_state,
            "execution_mode": "queued",
            "dispatch_plan": public_plan.to_dict(),
            "queue": initial_queue_state,
        }
        run.state_hash = compute_state_hash(run.state)
        runtime_metrics = self._build_queued_runtime_metrics(
            dispatch_plan=public_plan,
            queue_task_ids=queue_task_ids,
            recovered_running_tasks=runner.recovered_running_tasks,
            queue_state=initial_queue_state,
            retry_policy=retry_policy_config,
            lease_timeout_seconds=lease_timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
        run_record = build_run_record(
            run_id=run.id,
            workflow_id=workflow_id,
            project_name=project.name,
            workflow_name=workflow_id,
            execution_mode="queued",
            queue_task_ids=queue_task_ids,
            status=run.status,
            stop_reason=run.stop_reason,
            suspension_reason=run.suspension_reason,
            input_data=input_data,
            state=run.state,
            state_version=run.state_version,
            state_hash=run.state_hash,
            event_log=list(run.event_log),
            runtime_metrics=runtime_metrics,
            logs=["execution_mode:queued"],
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at is not None else None,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        stored_run = self._store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
        )
        expected_record_version = int(stored_run.get("record_version", 1))
        wave_writes: dict[int, set[str]] = {}

        while True:
            step = runner.process_next(
                execution_plan,
                handler=lambda dispatch_task, _task: self._invoke_project_node_for_queued_mode(
                    project=project,
                    workflow_id=workflow_id,
                    node_id=dispatch_task.node_id,
                    state=dict(run.state),
                ).to_event_dict(),
            )
            if step.task_id is None:
                break

            node_event = dict((step.result or {}).get("output") or {})
            state_patch = dict(node_event.get("state_patch", {}))
            state_before = dict(run.state)
            error = (step.result or {}).get("error")
            if node_event.get("requires_approval"):
                error = (
                    "queued execution mode does not currently support approval-gated node "
                    "execution"
                )
            if node_event.get("edge_decisions"):
                error = (
                    "queued execution mode does not currently support dynamic edge decisions"
                )

            current_wave = next(
                task.wave_index for task in execution_plan.tasks if task.task_id == step.task_id
            )
            writes = wave_writes.setdefault(current_wave, set())
            conflicting_keys = sorted(set(state_patch) & writes)
            if conflicting_keys:
                error = (
                    "queued execution mode detected conflicting state writes in the same wave: "
                    + ", ".join(conflicting_keys)
                )

            if not error:
                writes.update(state_patch)
                run.state.update(state_patch)
            queue_state = self._build_queued_queue_state(
                runner=runner,
                queue_task_ids=queue_task_ids,
                blocked_task_ids=step.blocked_task_ids,
                last_node_id=step.node_id,
                last_task_id=step.task_id,
                retry_policy=retry_policy_config,
                lease_timeout_seconds=lease_timeout_seconds,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                heartbeat_total=int(run.state.get("queue", {}).get("heartbeat_total", 0))
                + step.heartbeat_count,
            )
            run.state["queue"] = queue_state

            if error and not step.retry_scheduled:
                run.fail(
                    error=error,
                    reason=(
                        RunStopReason.STATE_CONFLICT
                        if conflicting_keys
                        else RunStopReason.WORKFLOW_ERROR
                    ),
                )

            run.state_version += 1
            run.state_hash = compute_state_hash(run.state)
            event = {
                "seq": run.state_version,
                "node_id": step.node_id,
                "execution_mode": "queued",
                "task_id": step.task_id,
                "wave_index": next(
                    task.wave_index for task in execution_plan.tasks if task.task_id == step.task_id
                ),
                "queue_size": step.queue_size,
                "enqueued_task_ids": list(step.enqueued_task_ids),
                "blocked_task_ids": list(step.blocked_task_ids),
                "task_status": step.task_status,
                "lease_owner": step.lease_owner,
                "heartbeat_count": step.heartbeat_count,
                "retry_scheduled": step.retry_scheduled,
                "retry_attempt": step.retry_attempt,
                "dead_lettered": step.dead_lettered,
                "result": dict(step.result or {}),
                "state_patch": state_patch,
                "state_version": run.state_version,
                "state_hash": run.state_hash,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            run.event_log.append(event)

            checkpoint = Checkpoint(
                workflow_run_id=run.id,
                node_id=step.node_id or "",
                state_version=run.state_version,
                state_hash=run.state_hash,
            )
            checkpoint.add_event(
                node_id=step.node_id,
                input_data=state_before,
                seq=run.state_version,
                metrics={
                    "execution_mode": "queued",
                    "task_id": step.task_id,
                    "queue_size": step.queue_size,
                    "lease_owner": step.lease_owner,
                    "heartbeat_count": step.heartbeat_count,
                    "retry_scheduled": step.retry_scheduled,
                    "retry_attempt": step.retry_attempt,
                    "dead_lettered": step.dead_lettered,
                },
                state_patch=state_patch,
                state_version=run.state_version,
                state_hash=run.state_hash,
            )
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run.id
            self._store.put_checkpoint_record(checkpoint_payload)

            if run.status in (RunStatus.FAILED, RunStatus.CANCELLED):
                break

            updated_runtime_metrics = self._build_queued_runtime_metrics(
                dispatch_plan=public_plan,
                queue_task_ids=queue_task_ids,
                recovered_running_tasks=runner.recovered_running_tasks,
                queue_state=run.state.get("queue", {}),
                retry_policy=retry_policy_config,
                lease_timeout_seconds=lease_timeout_seconds,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            )
            run_record = build_run_record(
                run_id=run.id,
                workflow_id=workflow_id,
                project_name=project.name,
                workflow_name=workflow_id,
                execution_mode="queued",
                queue_task_ids=queue_task_ids,
                status=run.status,
                stop_reason=run.stop_reason,
                suspension_reason=run.suspension_reason,
                input_data=input_data,
                state=run.state,
                state_version=run.state_version,
                state_hash=run.state_hash,
                event_log=list(run.event_log),
                runtime_metrics=updated_runtime_metrics,
                checkpoint_ids=[cp["id"] for cp in self._store.list_run_checkpoints(run.id)],
                logs=["execution_mode:queued"],
                created_at=run.created_at.isoformat(),
                started_at=run.started_at.isoformat() if run.started_at is not None else None,
                completed_at=run.completed_at.isoformat() if run.completed_at is not None else None,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
            stored_run = self._store.put_run_record(
                run_record,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                parameters=parameters,
                expected_record_version=expected_record_version,
            )
            expected_record_version = int(stored_run.get("record_version", 1))

        queue_summary = dict(run.state.get("queue", {}))
        if run.status == RunStatus.RUNNING:
            dead_letter_task_ids = list(queue_summary.get("dead_letter_task_ids", []))
            failed_task_ids = list(queue_summary.get("failed_task_ids", []))
            blocked_task_ids = list(queue_summary.get("blocked_task_ids", []))
            if dead_letter_task_ids:
                logger.warning(
                    "Queued run %s failed: exhausted retries for tasks %s",
                    run.id, ", ".join(dead_letter_task_ids),
                )
                run.fail(
                    error="queued execution exhausted retries for tasks: "
                    + ", ".join(dead_letter_task_ids),
                    reason=RunStopReason.WORKFLOW_ERROR,
                )
            elif failed_task_ids or blocked_task_ids:
                all_failing = failed_task_ids + list(blocked_task_ids)
                logger.warning(
                    "Queued run %s failed: tasks %s",
                    run.id, ", ".join(all_failing),
                )
                run.fail(
                    error="queued execution failed for tasks: "
                    + ", ".join(all_failing),
                    reason=RunStopReason.WORKFLOW_ERROR,
                )
            else:
                run.complete()
        runtime_metrics = self._build_queued_runtime_metrics(
            dispatch_plan=public_plan,
            queue_task_ids=queue_task_ids,
            recovered_running_tasks=runner.recovered_running_tasks,
            queue_state=queue_summary,
            retry_policy=retry_policy_config,
            lease_timeout_seconds=lease_timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
        final_record = build_run_record(
            run_id=run.id,
            workflow_id=workflow_id,
            project_name=project.name,
            workflow_name=workflow_id,
            execution_mode="queued",
            queue_task_ids=queue_task_ids,
            status=run.status,
            stop_reason=run.stop_reason,
            suspension_reason=run.suspension_reason,
            input_data=input_data,
            state=run.state,
            state_version=run.state_version,
            state_hash=run.state_hash,
            event_log=list(run.event_log),
            runtime_metrics=runtime_metrics,
            checkpoint_ids=[cp["id"] for cp in self._store.list_run_checkpoints(run.id)],
            logs=["execution_mode:queued"],
            created_at=run.created_at.isoformat(),
            started_at=run.started_at.isoformat() if run.started_at is not None else None,
            completed_at=run.completed_at.isoformat() if run.completed_at is not None else None,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        return self._store.put_run_record(
            final_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
            expected_record_version=expected_record_version,
        )

    def _persist_execution(
        self,
        *,
        workflow_id: str,
        tenant_id: str,
        run_record: dict[str, Any],
        artifacts: ExecutionArtifacts,
        parameters: Mapping[str, Any] | None = None,
        expected_record_version: int | None = None,
    ) -> dict[str, Any]:
        stored_run = self._store.put_run_record(
            run_record,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=parameters,
            expected_record_version=expected_record_version,
        )
        run_id = str(stored_run["id"])
        for checkpoint in artifacts.checkpoints:
            checkpoint_payload = checkpoint.to_dict()
            checkpoint_payload["run_id"] = run_id
            self._store.put_checkpoint_record(checkpoint_payload)
        for approval in artifacts.approvals:
            approval_payload = dict(approval)
            approval_payload["run_id"] = approval_payload.get("run_id") or approval_payload.get(
                "context", {}
            ).get("run_id", run_id)
            self._store.put_approval_record(approval_payload)
        return stored_run

    def start_run(
        self,
        *,
        workflow_id: str,
        tenant_id: str = "default",
        input_data: Any = None,
        parameters: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        execution_mode: str = "inline",
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        with self._trace_scope(
            "workflow.start_run",
            attributes={
                "workflow.id": workflow_id,
                "tenant.id": tenant_id,
                "workflow.execution_mode": execution_mode,
            },
        ):
            resolved_trace_id = trace_id or self._current_trace_id()
            logger.info(
                "start_run workflow_id=%s tenant_id=%s mode=%s",
                workflow_id, tenant_id, execution_mode,
            )
            normalized_idempotency_key = (idempotency_key or "").strip()
            if execution_mode not in {"inline", "queued"}:
                raise ValueError(f"Unsupported execution_mode: {execution_mode}")
            if normalized_idempotency_key:
                existing = self._store.get_run_record_by_idempotency_key(
                    workflow_id,
                    tenant_id=tenant_id,
                    idempotency_key=normalized_idempotency_key,
                )
                if existing is not None:
                    return existing
            project = self._store.get_workflow_project(workflow_id, tenant_id=tenant_id)
            if project is None:
                raise KeyError(f"Workflow not found: {workflow_id}")
            ensure_lifecycle_workflow_handlers(
                self._store,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                provider_registry=self._provider_registry,
                llm_runtime=self._llm_runtime,
                skill_runtime=self._skill_runtime,
            )
            if execution_mode == "queued":
                stored_run = self._start_queued_run(
                    workflow_id=workflow_id,
                    tenant_id=tenant_id,
                    project=project,
                    input_data=input_data,
                    parameters=parameters,
                    correlation_id=correlation_id,
                    trace_id=resolved_trace_id,
                )
                if normalized_idempotency_key:
                    try:
                        self._store.put_run_idempotency_key(
                            workflow_id,
                            tenant_id=tenant_id,
                            idempotency_key=normalized_idempotency_key,
                            run_id=str(stored_run["id"]),
                        )
                    except ConcurrencyError:
                        existing = self._store.get_run_record_by_idempotency_key(
                            workflow_id,
                            tenant_id=tenant_id,
                            idempotency_key=normalized_idempotency_key,
                        )
                        if existing is not None:
                            return existing
                        raise
                    stored_run["idempotency_key"] = normalized_idempotency_key
                    stored_run = self._store.put_run_record(
                        stored_run,
                        workflow_id=workflow_id,
                        tenant_id=tenant_id,
                        parameters=parameters,
                        expected_record_version=int(stored_run.get("record_version", 1)),
                    )
                return stored_run
            artifacts = execute_project_sync(
                project,
                input_data=normalize_runtime_input(input_data),
                workflow_id=workflow_id,
                approval_store=StoreBackedApprovalStore(self._store),
                approval_manager=self._approval_manager(),
                node_handlers=self._store.get_node_handlers(workflow_id),
                agent_handlers=self._store.get_agent_handlers(workflow_id),
                provider_registry=self._provider_registry,
                llm_runtime=self._llm_runtime,
                skill_runtime=self._skill_runtime,
                tracer=self._tracer,
                decision_explainer=self._decision_explainer,
            )
            run_record = serialize_run(
                artifacts,
                project_name=project.name,
                workflow_name=workflow_id,
                input_data=input_data,
                correlation_id=correlation_id,
                trace_id=resolved_trace_id,
            )
            stored_run = self._persist_execution(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                run_record=run_record,
                artifacts=artifacts,
                parameters=parameters,
            )
            if normalized_idempotency_key:
                try:
                    self._store.put_run_idempotency_key(
                        workflow_id,
                        tenant_id=tenant_id,
                        idempotency_key=normalized_idempotency_key,
                        run_id=str(stored_run["id"]),
                    )
                except ConcurrencyError:
                    existing = self._store.get_run_record_by_idempotency_key(
                        workflow_id,
                        tenant_id=tenant_id,
                        idempotency_key=normalized_idempotency_key,
                    )
                    if existing is not None:
                        return existing
                    raise
                stored_run["idempotency_key"] = normalized_idempotency_key
                stored_run = self._store.put_run_record(
                    stored_run,
                    workflow_id=workflow_id,
                    tenant_id=tenant_id,
                    parameters=parameters,
                    expected_record_version=int(stored_run.get("record_version", 1)),
                )
            return stored_run

    def resume_run(
        self,
        run_id: str,
        *,
        tenant_id: str = "default",
        input_data: Any = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        with self._trace_scope(
            "workflow.resume_run",
            attributes={"run.id": run_id, "tenant.id": tenant_id},
        ):
            run = self._store.get_run_record(run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            resolved_correlation_id = correlation_id or run.get("correlation_id")
            resolved_trace_id = trace_id or run.get("trace_id") or self._current_trace_id()
            expected_record_version = int(run.get("record_version", 1))
            workflow_id = str(run.get("workflow_id", run.get("workflow", "")))
            project = self._store.get_workflow_project(workflow_id, tenant_id=tenant_id)
            if project is None:
                raise KeyError(f"Workflow not found: {workflow_id}")
            ensure_lifecycle_workflow_handlers(
                self._store,
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                provider_registry=self._provider_registry,
                llm_runtime=self._llm_runtime,
                skill_runtime=self._skill_runtime,
            )
            raw_input = run.get("input") if input_data is None else input_data
            artifacts = resume_project_sync(
                project,
                run,
                input_data=normalize_runtime_input(raw_input),
                checkpoints=self._store.list_run_checkpoints(run_id),
                approvals=self._store.list_run_approvals(run_id),
                approval_store=StoreBackedApprovalStore(self._store),
                approval_manager=self._approval_manager(),
                provider_registry=self._provider_registry,
                llm_runtime=self._llm_runtime,
                skill_runtime=self._skill_runtime,
                tracer=self._tracer,
                decision_explainer=self._decision_explainer,
                node_handlers=self._store.get_node_handlers(workflow_id),
                agent_handlers=self._store.get_agent_handlers(workflow_id),
            )
            run_record = serialize_run(
                artifacts,
                project_name=project.name,
                workflow_name=workflow_id,
                input_data=raw_input,
                correlation_id=resolved_correlation_id,
                trace_id=resolved_trace_id,
            )
            return self._persist_execution(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                run_record=run_record,
                artifacts=artifacts,
                parameters=run.get("parameters", {}),
                expected_record_version=expected_record_version,
            )

    def approve_request(
        self,
        approval_id: str,
        *,
        tenant_id: str = "default",
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self._trace_scope(
            "workflow.approve_request",
            attributes={"approval.id": approval_id, "tenant.id": tenant_id},
        ):
            logger.info("approve_request approval_id=%s actor=%s", approval_id, actor)
            approval = self._store.get_approval_record(approval_id)
            if approval is None:
                raise KeyError(f"Approval request not found: {approval_id}")
            if approval.get("status") != "pending":
                raise ValueError(f"Approval request already decided: {approval_id}")
            run_id = str(approval.get("run_id", ""))
            run = self._store.get_run_record(run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")

            manager = self._approval_manager()
            _run_sync(manager.approve(approval_id, actor, comment=reason or ""))
            _run_sync(
                manager.validate_binding(
                    approval_id,
                    plan=approval.get("context", {}).get("binding_plan"),
                    effect_envelope=approval.get("context", {}).get("binding_effect_envelope"),
                )
            )
            decided = self._store.get_approval_record(approval_id)
            if decided is not None:
                decided["decided_at"] = decided.get("decided_at") or time.time()
                if reason:
                    decided["reason"] = reason
                self._store.put_approval_record(decided)
            return self.resume_run(run_id, tenant_id=tenant_id)

    def reject_request(
        self,
        approval_id: str,
        *,
        tenant_id: str = "default",
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        logger.info("reject_request approval_id=%s actor=%s", approval_id, actor)
        approval = self._store.get_approval_record(approval_id)
        if approval is None:
            raise KeyError(f"Approval request not found: {approval_id}")
        if approval.get("status") != "pending":
            raise ValueError(f"Approval request already decided: {approval_id}")
        run_id = str(approval.get("run_id", ""))
        run = self._store.get_run_record(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")

        manager = self._approval_manager()
        _run_sync(manager.reject(approval_id, actor, reason or ""))
        decided = self._store.get_approval_record(approval_id)
        if decided is not None:
            decided["decided_at"] = decided.get("decided_at") or time.time()
            if reason:
                decided["reason"] = reason
            self._store.put_approval_record(decided)

        updated = rebuild_run_record(
            run,
            status=RunStatus.CANCELLED,
            stop_reason=RunStopReason.APPROVAL_DENIED,
            suspension_reason=RunStopReason.NONE,
            active_approval=None,
            approvals=self._store.list_run_approvals(run_id),
            approval_request_id=None,
            logs=[*list(run.get("logs", [])), f"approval_rejected:{approval_id}"],
        )
        workflow_id = str(run.get("workflow_id", run.get("workflow", "")))
        return self._store.put_run_record(
            updated,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            parameters=run.get("parameters", {}),
            expected_record_version=int(run.get("record_version", 1)),
        )

    def replay_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        checkpoint = self._store.get_checkpoint_record(checkpoint_id)
        if checkpoint is None:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")
        source_run_id = str(checkpoint.get("run_id", ""))
        source_run = self._store.get_run_record(source_run_id)
        if source_run is None:
            raise KeyError(f"Run not found: {source_run_id}")

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
        return build_replay_query_payload(
            source_run=source_run,
            checkpoint_id=checkpoint_id,
            replayed=replayed,
            replay_view=replay_view,
            approvals=(
                self._store.list_run_approvals(source_run_id)
                if replay_view["is_terminal_replay"]
                else []
            ),
        )

    def get_run_payload(self, run_id: str) -> dict[str, Any]:
        run = self._store.get_run_record(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return build_run_query_payload(run)

    def get_workflow_plan(
        self,
        workflow_id: str,
        *,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        project = self._store.get_workflow_project(workflow_id, tenant_id=tenant_id)
        if project is None:
            raise KeyError(f"Workflow not found: {workflow_id}")
        return plan_project_dispatch(
            project,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        ).to_dict()

    def list_run_payloads(
        self,
        *,
        tenant_id: str = "default",
        workflow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        runs = [
            build_run_query_payload(run)
            for run in self._store.list_all_run_records()
            if run.get("tenant_id", tenant_id) == tenant_id
            and (workflow_id is None or run.get("workflow_id") == workflow_id)
        ]
        runs.sort(key=lambda payload: str(payload.get("created_at", "")), reverse=True)
        return runs

    def list_approval_payloads(
        self,
        *,
        tenant_id: str = "default",
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for approval in self._store.list_all_approval_records():
            approval_run_id = str(approval.get("run_id", ""))
            if run_id is not None and approval_run_id != run_id:
                continue
            if approval_run_id:
                run = self._store.get_run_record(approval_run_id)
                if run is None:
                    continue
                if run.get("tenant_id", tenant_id) != tenant_id:
                    continue
                if workflow_id is not None and run.get("workflow_id") != workflow_id:
                    continue
                approvals.append(
                    {
                        **approval,
                        "workflow_id": run.get("workflow_id"),
                        "tenant_id": run.get("tenant_id"),
                        "run_status": run.get("status"),
                    }
                )
                continue
            context = dict(approval.get("context") or {})
            resource_type = str(context.get("resource_type", ""))
            if resource_type != "experiment_campaign":
                continue
            approval_tenant_id = str(approval.get("tenant_id") or context.get("tenant_id") or "default")
            if approval_tenant_id != tenant_id:
                continue
            if workflow_id is not None:
                continue
            approvals.append(
                {
                    **approval,
                    "workflow_id": None,
                    "tenant_id": approval_tenant_id,
                    "run_status": None,
                    "resource_type": resource_type,
                    "resource_id": str(context.get("resource_id") or context.get("campaign_id") or ""),
                }
            )
        approvals.sort(key=lambda payload: str(payload.get("created_at", "")), reverse=True)
        return approvals

    def list_checkpoint_payloads(
        self,
        *,
        tenant_id: str = "default",
        workflow_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        checkpoints: list[dict[str, Any]] = []
        runs = self._store.list_all_run_records()
        for run in runs:
            current_run_id = str(run.get("id", ""))
            if run_id is not None and current_run_id != run_id:
                continue
            if run.get("tenant_id", tenant_id) != tenant_id:
                continue
            if workflow_id is not None and run.get("workflow_id") != workflow_id:
                continue
            for checkpoint in self._store.list_run_checkpoints(current_run_id):
                checkpoints.append(
                    {
                        **checkpoint,
                        "workflow_id": run.get("workflow_id"),
                        "tenant_id": run.get("tenant_id"),
                        "run_status": run.get("status"),
                    }
                )
        checkpoints.sort(key=lambda payload: str(payload.get("created_at", "")), reverse=True)
        return checkpoints
