"""Shared public execution helpers backed by the workflow runtime."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pylon.agents.cognitive import ReActEngine
from pylon.approval import ApprovalManager, ApprovalRequest, ApprovalStore
from pylon.autonomy.explainability import DecisionExplainer
from pylon.autonomy.goals import GoalSpec
from pylon.autonomy.routing import ModelRouter, ModelRouteRequest
from pylon.dsl.parser import ConditionalNext, GoalDef, PylonProject
from pylon.observability.metrics import MetricsCollector
from pylon.observability.run_record import build_run_record
from pylon.observability.tracing import Span, Tracer
from pylon.providers.base import Message
from pylon.repository.audit import AuditRepository, default_hmac_key
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.workflow import WorkflowRun
from pylon.runtime.llm import (
    LLMRuntime,
    ProviderRegistry,
    estimate_message_tokens,
    messages_from_input,
)
from pylon.skills.runtime import SkillRuntime, get_default_skill_runtime
from pylon.types import (
    AutonomyLevel,
    ConditionalEdge,
    RunStatus,
    RunStopReason,
    WorkflowNodeType,
)
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph
from pylon.workflow.result import NodeResult

_UNSET = object()


@dataclass(frozen=True)
class ExecutionArtifacts:
    """Result bundle for a public workflow execution."""

    run: WorkflowRun
    checkpoints: tuple[Checkpoint, ...]
    approvals: tuple[dict[str, Any], ...] = ()


def normalize_runtime_input(input_data: Any) -> dict[str, Any] | None:
    """Normalize public input into the workflow runtime state shape."""
    if input_data is None:
        return None
    if isinstance(input_data, dict):
        return dict(input_data)
    return {"input": input_data}


def _resolve_require_approval_above(level: str) -> AutonomyLevel:
    try:
        return AutonomyLevel[str(level).upper()]
    except KeyError as exc:
        raise ValueError(f"Invalid require_approval_above policy value: {level}") from exc


def _run_sync(coro: Any) -> Any:
    """Run a coroutine without mutating the process-global current event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _trace_scope(
    tracer: Tracer | None,
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Any:
    if tracer is None:
        return nullcontext(None)
    return tracer.start_as_current_span(name, attributes=attributes)


def _span_payload(span: Span | None) -> dict[str, str] | None:
    if span is None:
        return None
    payload = {"trace_id": span.trace_id, "span_id": span.span_id}
    if span.parent_id:
        payload["parent_id"] = span.parent_id
    return payload


def compile_project_graph(project: PylonProject) -> WorkflowGraph:
    """Compile a validated project definition into the runtime workflow graph."""
    graph = WorkflowGraph(name=project.name)
    for node_id, node in project.workflow.nodes.items():
        next_nodes: list[ConditionalEdge] = []
        if isinstance(node.next, str):
            next_nodes.append(ConditionalEdge(target=node.next))
        elif isinstance(node.next, list):
            for edge in node.next:
                if isinstance(edge, ConditionalNext):
                    next_nodes.append(
                        ConditionalEdge(target=edge.target, condition=edge.condition)
                    )
                else:
                    next_nodes.append(ConditionalEdge(target=str(edge)))

        graph.add_node(
            node_id,
            node.agent,
            node_type=WorkflowNodeType(node.node_type),
            join_policy=node.join_policy,
            loop_max_iterations=node.loop_max_iterations,
            loop_criterion=node.loop_criterion,
            loop_threshold=node.loop_threshold,
            loop_metadata=dict(node.loop_metadata),
            next_nodes=next_nodes,
        )
    return graph


def _goal_spec_for_project(project: PylonProject) -> GoalSpec | None:
    if project.goal is None:
        return None
    if isinstance(project.goal, GoalDef):
        return project.goal.to_goal_spec()
    return project.goal


def _build_node_approval_binding(
    project: PylonProject,
    workflow_id: str,
    node_id: str,
    *,
    goal_spec: GoalSpec | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = project.workflow.nodes[node_id]
    agent = project.agents[node.agent]
    plan = {
        "kind": "workflow_node",
        "project": project.name,
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_type": node.node_type,
        "agent": node.agent,
        "next": (
            [node.next]
            if isinstance(node.next, str)
            else [
                edge.model_dump() if isinstance(edge, ConditionalNext) else str(edge)
                for edge in (node.next or [])
            ]
        ),
    }
    effect_envelope = {
        "autonomy": agent.autonomy,
        "tools": list(agent.tools),
        "sandbox": agent.sandbox,
        "input_trust": agent.input_trust,
        "allowed_effect_scopes": (
            sorted(goal_spec.allowed_effect_scopes) if goal_spec is not None else []
        ),
        "allowed_secret_scopes": (
            sorted(goal_spec.allowed_secret_scopes) if goal_spec is not None else []
        ),
    }
    return plan, effect_envelope


def _deserialize_approval(payload: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest.from_dict(payload)


def _build_messages_for_node(
    node_id: str,
    state: dict[str, Any],
) -> list[Message] | None:
    node_messages = state.get(f"{node_id}_messages")
    if node_messages is not None:
        return messages_from_input(node_messages)
    shared_messages = state.get("messages")
    if shared_messages is not None:
        return messages_from_input(shared_messages)
    node_prompt = state.get(f"{node_id}_prompt")
    if node_prompt is not None:
        return messages_from_input(node_prompt)
    shared_prompt = state.get("prompt")
    if shared_prompt is not None:
        return messages_from_input(shared_prompt)
    return None


def _workspace_for_state(state: dict[str, Any]) -> Path | None:
    candidate = state.get("workspace") or state.get("cwd") or state.get("repo_path")
    if not candidate:
        return None
    return Path(str(candidate)).expanduser()


async def _execute_tool_enabled_interaction(
    *,
    messages: list[Message],
    static_instruction: str,
    preferred_model: str,
    route_request: ModelRouteRequest,
    provider_registry: ProviderRegistry,
    llm_runtime: LLMRuntime,
    available_tools: list[dict[str, Any]],
    tool_executors: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    llm_events: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    last_model = preferred_model
    last_route: dict[str, Any] | None = None
    last_context: dict[str, Any] = {}

    async def chat_fn(run_messages: list[Message], **kwargs: Any):
        nonlocal last_model, last_route, last_context
        result = await llm_runtime.chat(
            registry=provider_registry,
            request=route_request,
            messages=run_messages,
            preferred_model=preferred_model,
            static_instruction=static_instruction,
            tools=kwargs.get("tools"),
        )
        usage = result.response.usage
        llm_events.append(
            {
                "provider": result.route.provider_name,
                "model": result.response.model,
                "usage": (
                    {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cache_read_tokens": usage.cache_read_tokens,
                        "cache_write_tokens": usage.cache_write_tokens,
                        "reasoning_tokens": usage.reasoning_tokens,
                        "total_tokens": usage.total_tokens,
                        "metered_tokens": usage.metered_tokens,
                    }
                    if usage is not None
                    else None
                ),
                "estimated_cost_usd": result.estimated_cost_usd,
                "cache_strategy": result.route.cache_strategy.value,
                "reasoning": result.route.reasoning,
                "context": dict(result.context),
                "tool_loop": True,
            }
        )
        last_model = result.response.model
        last_route = result.route.to_dict()
        last_context = dict(result.context)
        return result.response

    async def tool_executor(tool_name: str, tool_input: dict[str, Any]) -> str:
        executor = tool_executors.get(tool_name)
        if executor is None:
            raise RuntimeError(f"Tool '{tool_name}' is not available")
        output = await executor(tool_input)
        tool_events.append(
            {
                "name": tool_name,
                "input": dict(tool_input),
                "output": output,
            }
        )
        return output

    engine = ReActEngine()
    result = await engine.run(
        messages=messages,
        chat_fn=chat_fn,
        tool_executor=tool_executor,
        available_tools=available_tools,
    )
    metrics: dict[str, Any] = {"tool_iterations": result.total_iterations}
    if last_route is not None:
        metrics["model_route"] = last_route
    if last_context:
        metrics["context"] = last_context
    return result.final_answer, last_model, llm_events, tool_events, metrics


async def _invoke_registered_handler(
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
        return await result
    return result


def _checkpoint_from_payload(payload: dict[str, Any]) -> Checkpoint:
    checkpoint = Checkpoint(
        id=str(payload["id"]),
        workflow_run_id=str(payload.get("workflow_run_id", payload.get("run_id", ""))),
        node_id=str(payload.get("node_id", "")),
        state_version=int(payload.get("state_version", 0)),
        state_hash=str(payload.get("state_hash", "")),
        event_log=list(payload.get("event_log", [])),
        state_ref=payload.get("state_ref"),
        created_at=(
            datetime.fromisoformat(str(payload["created_at"]))
            if payload.get("created_at") is not None
            else datetime.now()
        ),
    )
    return checkpoint


def deserialize_run(payload: dict[str, Any]) -> WorkflowRun:
    """Reconstruct a workflow run from serialized public state."""
    run = WorkflowRun(
        id=str(payload["id"]),
        workflow_id=str(payload.get("workflow_id", payload.get("workflow", "default"))),
        status=RunStatus(str(payload.get("status", RunStatus.PENDING.value))),
        event_log=list(payload.get("event_log", [])),
        state=dict(payload.get("state", {})),
        state_version=int(payload.get("state_version", 0)),
        state_hash=str(payload.get("state_hash", "")),
        stop_reason=RunStopReason(str(payload.get("stop_reason", RunStopReason.NONE.value))),
        suspension_reason=RunStopReason(
            str(payload.get("suspension_reason", RunStopReason.NONE.value))
        ),
        approval_request_id=payload.get("approval_id") or payload.get("approval_request_id"),
        created_at=(
            datetime.fromisoformat(str(payload["created_at"]))
            if payload.get("created_at") is not None
            else datetime.now()
        ),
    )
    started_at = payload.get("started_at")
    completed_at = payload.get("completed_at")
    if started_at:
        run.started_at = datetime.fromisoformat(str(started_at))
    if completed_at:
        run.completed_at = datetime.fromisoformat(str(completed_at))
    return run


def execute_project_sync(
    project: PylonProject,
    *,
    input_data: dict[str, Any] | None = None,
    workflow_id: str = "default",
    existing_run: WorkflowRun | None = None,
    existing_checkpoints: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    existing_approvals: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    provider_registry: ProviderRegistry | None = None,
    model_router: ModelRouter | None = None,
    llm_runtime: LLMRuntime | None = None,
    tracer: Tracer | None = None,
    decision_explainer: DecisionExplainer | None = None,
    approval_store: ApprovalStore | None = None,
    approval_manager: ApprovalManager | None = None,
    node_handlers: dict[str, Any] | None = None,
    agent_handlers: dict[str, Any] | None = None,
    skill_runtime: SkillRuntime | None = None,
    progress_callback: Any | None = None,
    expected_resume_input: dict[str, Any] | None | object = _UNSET,
) -> ExecutionArtifacts:
    """Execute a DSL project through the shared runtime."""

    async def _run() -> ExecutionArtifacts:
        repo = CheckpointRepository()
        for payload in existing_checkpoints:
            await repo.create(_checkpoint_from_payload(payload))
        effective_approval_store = approval_store or ApprovalStore()
        for payload in existing_approvals:
            await effective_approval_store.create(_deserialize_approval(payload))
        effective_approval_manager = approval_manager or ApprovalManager(
            effective_approval_store,
            AuditRepository(hmac_key=default_hmac_key()),
        )
        executor = GraphExecutor(
            checkpoint_repo=repo,
            approval_manager=effective_approval_manager,
            progress_observer=progress_callback,
        )
        graph = compile_project_graph(project)
        run = existing_run or WorkflowRun(id=f"run_{uuid.uuid4().hex}", workflow_id=workflow_id)

        require_above = _resolve_require_approval_above(project.policy.require_approval_above)
        goal_spec = _goal_spec_for_project(project)
        route_metrics = MetricsCollector()
        effective_decision_explainer = decision_explainer or DecisionExplainer()
        effective_llm_runtime = llm_runtime or LLMRuntime(
            router=model_router or ModelRouter(),
            metrics=route_metrics,
            tracer=tracer,
            decision_explainer=effective_decision_explainer,
        )
        effective_skill_runtime = skill_runtime or get_default_skill_runtime()
        if tracer is not None and getattr(effective_llm_runtime, "tracer", None) is None:
            effective_llm_runtime.tracer = tracer
        if (
            getattr(effective_llm_runtime, "decision_explainer", None) is None
            and effective_decision_explainer is not None
        ):
            effective_llm_runtime.decision_explainer = effective_decision_explainer

        async def handler(node_id: str, state: dict[str, Any]) -> NodeResult:
            node = project.workflow.nodes[node_id]
            agent = project.agents[node.agent]
            with _trace_scope(
                tracer,
                "workflow.node.execute",
                attributes={
                    "workflow.id": workflow_id,
                    "workflow.node.id": node_id,
                    "workflow.agent.id": node.agent,
                },
            ) as node_span:
                patch: dict[str, Any] = {}
                metrics: dict[str, Any] = {}
                llm_events: list[dict[str, Any]] = []
                artifacts: list[dict[str, Any]] = []
                edge_decisions: dict[str, bool] = {}
                tool_events: list[dict[str, Any]] = []
                requires_approval = False
                approval_reason = ""

                custom_handler = None
                if node_handlers is not None and node_id in node_handlers:
                    custom_handler = node_handlers[node_id]
                elif agent_handlers is not None and node.agent in agent_handlers:
                    custom_handler = agent_handlers[node.agent]

                if custom_handler is not None:
                    custom_result = NodeResult.from_raw(
                        await _invoke_registered_handler(
                            custom_handler,
                            node_id=node_id,
                            state=dict(state),
                        )
                    )
                    patch.update(custom_result.state_patch)
                    metrics.update(custom_result.metrics)
                    llm_events.extend(custom_result.llm_events)
                    artifacts.extend(custom_result.artifacts)
                    edge_decisions.update(custom_result.edge_decisions)
                    tool_events.extend(custom_result.tool_events)
                    requires_approval = custom_result.requires_approval
                    approval_reason = custom_result.approval_reason
                else:
                    messages = None
                    if provider_registry is not None:
                        messages = _build_messages_for_node(node_id, state)
                    if provider_registry is not None and messages is not None:
                        base_instruction = str(
                            node.loop_metadata.get("static_instruction", agent.role or "")
                        )
                        static_instruction, effective_skills = effective_skill_runtime.augment_instruction(
                            base_instruction,
                            assigned_skill_ids=list(getattr(agent, "skills", [])),
                            workspace=_workspace_for_state(state),
                            reference_hints=state.get("skill_reference_hints"),
                        )
                        available_skill_tools = [
                            tool.provider_tool()
                            for tool in effective_skills.available_tools
                        ]
                        tool_executors = {
                            tool.name: tool.executor
                            for tool in effective_skills.available_tools
                            if tool.executor is not None
                        }
                        route_request = ModelRouteRequest(
                            purpose=str(node.loop_metadata.get("route_purpose", node_id)),
                            input_tokens_estimate=estimate_message_tokens(messages),
                            requires_tools=bool(agent.tools or available_skill_tools),
                            latency_sensitive=bool(
                                node.loop_metadata.get("latency_sensitive", False)
                            ),
                            quality_sensitive=bool(
                                node.loop_metadata.get("quality_sensitive", False)
                            ),
                            cacheable_prefix=bool(
                                node.loop_metadata.get("cacheable_prefix", False)
                            ),
                            batch_eligible=bool(node.loop_metadata.get("batch_eligible", False)),
                            remaining_budget_usd=(
                                (
                                    goal_spec.constraints.max_cost_usd
                                    - sum(
                                        e.get("estimated_cost_usd", 0.0)
                                        for e in llm_events
                                    )
                                )
                                if goal_spec is not None
                                and goal_spec.constraints.max_cost_usd is not None
                                else None
                            ),
                        )
                        metrics["activated_skills"] = effective_skills.skill_ids
                        metrics["activated_skill_aliases"] = effective_skills.skill_aliases
                        metrics["activated_skill_version_refs"] = (
                            effective_skills.skill_version_refs
                        )
                        metrics["activated_tools"] = [
                            tool.name for tool in effective_skills.available_tools
                        ]
                        metrics["loaded_skill_contexts"] = [
                            {
                                "skill_id": item.get("skill_id"),
                                "contract_id": item.get("contract_id"),
                                "path": item.get("path"),
                            }
                            for item in effective_skills.loaded_contexts
                        ]
                        metrics["skill_context_warnings"] = list(
                            effective_skills.context_warnings
                        )
                        metrics["loaded_skill_references"] = [
                            {
                                "skill_id": item.get("skill_id"),
                                "path": item.get("path"),
                                "title": item.get("title"),
                            }
                            for item in effective_skills.loaded_references
                        ]
                        metrics["skill_reference_warnings"] = list(
                            effective_skills.reference_warnings
                        )
                        metrics["unavailable_skill_tools"] = [
                            {
                                "name": tool.name,
                                "skill_id": tool.skill_id,
                                "reason": tool.unavailable_reason,
                            }
                            for tool in effective_skills.unavailable_tools
                        ]
                        if available_skill_tools and tool_executors:
                            (
                                response_text,
                                response_model,
                                node_llm_events,
                                node_tool_events,
                                node_metrics,
                            ) = await _execute_tool_enabled_interaction(
                                messages=messages,
                                static_instruction=static_instruction,
                                preferred_model=agent.resolve_model(),
                                route_request=route_request,
                                provider_registry=provider_registry,
                                llm_runtime=effective_llm_runtime,
                                available_tools=available_skill_tools,
                                tool_executors=tool_executors,
                            )
                            patch[f"{node_id}_response"] = response_text
                            patch["last_response"] = response_text
                            patch["last_model"] = response_model
                            metrics.update(node_metrics)
                            llm_events.extend(node_llm_events)
                            tool_events.extend(node_tool_events)
                        else:
                            llm_result = await effective_llm_runtime.chat(
                                registry=provider_registry,
                                request=route_request,
                                messages=messages,
                                preferred_model=agent.resolve_model(),
                                static_instruction=static_instruction,
                            )
                            patch[f"{node_id}_response"] = llm_result.response.content
                            patch["last_response"] = llm_result.response.content
                            patch["last_model"] = llm_result.response.model
                            metrics["model_route"] = llm_result.route.to_dict()
                            metrics["context"] = dict(llm_result.context)
                            usage = llm_result.response.usage
                            usage_payload = None
                            if usage is not None:
                                usage_payload = {
                                    "input_tokens": usage.input_tokens,
                                    "output_tokens": usage.output_tokens,
                                    "cache_read_tokens": usage.cache_read_tokens,
                                    "cache_write_tokens": usage.cache_write_tokens,
                                    "reasoning_tokens": usage.reasoning_tokens,
                                    "total_tokens": usage.total_tokens,
                                    "metered_tokens": usage.metered_tokens,
                                }
                            llm_events.append(
                                {
                                    "provider": llm_result.route.provider_name,
                                    "model": llm_result.response.model,
                                    "usage": usage_payload,
                                    "estimated_cost_usd": llm_result.estimated_cost_usd,
                                    "cache_strategy": llm_result.route.cache_strategy.value,
                                    "reasoning": llm_result.route.reasoning,
                                    "context": dict(llm_result.context),
                                }
                            )

                    if node.node_type == WorkflowNodeType.LOOP.value:
                        patch[f"{node_id}_loop_iteration"] = int(
                            state.get(f"{node_id}_loop_iteration", 0)
                        ) + 1
                        if node.loop_criterion == "state_value":
                            key = str(node.loop_metadata.get("key", ""))
                            if key:
                                patch[key] = node.loop_metadata.get("value", True)
                        elif node.loop_criterion == "response_quality":
                            metrics["response_quality_score"] = float(
                                node.loop_metadata.get("score", 1.0)
                            )
                patch.setdefault(f"{node_id}_done", True)
                node_trace = _span_payload(node_span)
                if node_trace is not None:
                    metrics["trace"] = node_trace

                if requires_approval or agent.to_autonomy_level() >= require_above:
                    plan, effect_envelope = _build_node_approval_binding(
                        project,
                        workflow_id,
                        node_id,
                        goal_spec=goal_spec,
                    )
                    approval = await effective_approval_manager.submit_request(
                        agent_id=node.agent,
                        action=f"workflow.node:{node_id}",
                        autonomy_level=agent.to_autonomy_level(),
                        context={
                            "kind": "node",
                            "run_id": run.id,
                            "workflow_id": workflow_id,
                            "node_id": node_id,
                            "binding_plan": plan,
                            "binding_effect_envelope": effect_envelope,
                            **({"trace": node_trace} if node_trace is not None else {}),
                        },
                        plan=plan,
                        effect_envelope=effect_envelope,
                    )
                    return NodeResult(
                        state_patch=patch,
                        artifacts=artifacts,
                        edge_decisions=edge_decisions,
                        metrics=metrics,
                        llm_events=llm_events,
                        tool_events=tool_events,
                        requires_approval=True,
                        approval_request_id=approval.id,
                        approval_reason=approval_reason
                        or f"agent '{node.agent}' requires approval",
                    )

                return NodeResult(
                    state_patch=patch,
                    artifacts=artifacts,
                    edge_decisions=edge_decisions,
                    llm_events=llm_events,
                    tool_events=tool_events,
                    metrics=metrics,
                )

        max_steps = max(len(project.workflow.nodes), 1) * 10
        with _trace_scope(
            tracer,
            "workflow.execute",
            attributes={
                "workflow.id": workflow_id,
                "workflow.run_id": run.id,
                "workflow.resume": existing_run is not None,
            },
        ):
            if existing_run is None:
                executed = await executor.execute(
                    graph,
                    run,
                    handler,
                    initial_state=dict(input_data or {}),
                    goal_spec=goal_spec,
                    max_steps=max_steps,
                )
            else:
                if (
                    expected_resume_input is not _UNSET
                    and input_data is not None
                    and input_data != expected_resume_input
                ):
                    raise ValueError("resume input_data must match the existing run input")
                executed = await executor.resume(
                    graph,
                    run,
                    handler,
                    goal_spec=goal_spec,
                    max_steps=max_steps,
                )
        checkpoints = tuple(await repo.list(workflow_run_id=executed.id))
        approvals = tuple(
            request.to_dict()
            for request in await effective_approval_store.list()
            if request.context.get("run_id") == executed.id
        )
        return ExecutionArtifacts(
            run=executed,
            checkpoints=checkpoints,
            approvals=approvals,
        )

    return _run_sync(_run())


def resume_project_sync(
    project: PylonProject,
    run_payload: dict[str, Any],
    *,
    input_data: dict[str, Any] | None = None,
    checkpoints: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    approvals: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    provider_registry: ProviderRegistry | None = None,
    model_router: ModelRouter | None = None,
    llm_runtime: LLMRuntime | None = None,
    tracer: Tracer | None = None,
    decision_explainer: DecisionExplainer | None = None,
    approval_store: ApprovalStore | None = None,
    approval_manager: ApprovalManager | None = None,
    node_handlers: dict[str, Any] | None = None,
    agent_handlers: dict[str, Any] | None = None,
    skill_runtime: SkillRuntime | None = None,
    progress_callback: Any | None = None,
) -> ExecutionArtifacts:
    """Resume a previously suspended project run through the shared runtime."""
    return execute_project_sync(
        project,
        input_data=input_data,
        workflow_id=str(run_payload.get("workflow_id", run_payload.get("workflow", "default"))),
        existing_run=deserialize_run(run_payload),
        existing_checkpoints=checkpoints,
        existing_approvals=approvals,
        provider_registry=provider_registry,
        model_router=model_router,
        llm_runtime=llm_runtime,
        tracer=tracer,
        decision_explainer=decision_explainer,
        approval_store=approval_store,
        approval_manager=approval_manager,
        node_handlers=node_handlers,
        agent_handlers=agent_handlers,
        skill_runtime=skill_runtime,
        progress_callback=progress_callback,
        expected_resume_input=normalize_runtime_input(run_payload.get("input")),
    )


def execute_single_node_sync(
    workflow_name: str,
    *,
    input_data: Any = None,
    handler: Any | None = None,
    agent_name: str = "runtime",
) -> ExecutionArtifacts:
    """Execute a one-node workflow through the shared runtime."""

    async def _run() -> ExecutionArtifacts:
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)
        graph = WorkflowGraph(name=workflow_name)
        graph.add_node("start", agent_name, next_nodes=[ConditionalEdge(target=END)])
        run = WorkflowRun(id=f"run_{uuid.uuid4().hex}", workflow_id=workflow_name)

        async def node_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
            del node_id, state
            if handler is None:
                raw_output = input_data
            else:
                raw_output = handler(input_data)
                if inspect.isawaitable(raw_output):
                    raw_output = await raw_output
            return NodeResult(state_patch={"output": raw_output})

        executed = await executor.execute(graph, run, node_handler, initial_state={})
        checkpoints = tuple(await repo.list(workflow_run_id=executed.id))
        return ExecutionArtifacts(run=executed, checkpoints=checkpoints)

    return _run_sync(_run())


def serialize_run(
    artifacts: ExecutionArtifacts,
    *,
    project_name: str | None = None,
    workflow_name: str | None = None,
    input_data: Any = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Serialize runtime execution artifacts into the canonical stored run record."""
    run = artifacts.run
    approvals = [dict(approval) for approval in artifacts.approvals]
    approval_id = next(
        (
            approval["id"]
            for approval in approvals
            if approval.get("status") == "pending"
        ),
        None,
    )
    active_approval = next(
        (approval for approval in approvals if approval.get("id") == approval_id),
        None,
    )
    logs = [
        f"run:{run.id} workflow:{workflow_name or run.workflow_id}",
        *(
            f"node:{event.get('node_id', 'unknown')} status:ok attempt:{event.get('attempt_id', 1)}"
            for event in run.event_log
        ),
    ]
    if approval_id is not None:
        logs.append(f"approval_required:{approval_id}")
    return build_run_record(
        run_id=run.id,
        workflow_id=run.workflow_id,
        project_name=project_name,
        workflow_name=workflow_name,
        status=run.status,
        stop_reason=run.stop_reason,
        suspension_reason=run.suspension_reason,
        input_data=input_data,
        state=dict(run.state),
        goal=run.state.get("goal"),
        autonomy=run.state.get("autonomy"),
        verification=run.state.get("verification"),
        runtime_metrics=run.state.get("runtime_metrics"),
        policy_resolution=run.state.get("policy_resolution"),
        refinement_context=run.state.get("refinement_context"),
        approval_context=run.state.get("approval_context"),
        termination_reason=run.state.get("termination_reason"),
        active_approval=active_approval,
        approvals=approvals,
        approval_request_id=run.approval_request_id,
        state_version=run.state_version,
        state_hash=run.state_hash,
        event_log=list(run.event_log),
        checkpoint_ids=[checkpoint.id for checkpoint in artifacts.checkpoints],
        logs=logs,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )
