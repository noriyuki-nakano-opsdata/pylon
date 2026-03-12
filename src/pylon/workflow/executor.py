"""Workflow Graph Executor with deterministic DAG scheduling semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.approval.manager import ApprovalManager
from pylon.autonomy.context import AutonomyContext
from pylon.autonomy.evaluation import (
    Critic,
    EvaluationResult,
    VerificationDecision,
    VerificationDisposition,
    Verifier,
)
from pylon.autonomy.goals import FailurePolicy, GoalSpec, RunCompletionPolicy, SuccessCriterion
from pylon.autonomy.routing import CacheStrategy, ModelRouteDecision, ModelTier
from pylon.autonomy.termination import (
    TerminationCondition,
    TerminationState,
    describe_termination_condition,
)
from pylon.errors import WorkflowError
from pylon.providers.base import TokenUsage
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.workflow import WorkflowRun
from pylon.types import (
    AutonomyLevel,
    RunStatus,
    RunStopReason,
    WorkflowJoinPolicy,
    WorkflowNodeType,
)
from pylon.workflow.commit import CommitEngine
from pylon.workflow.compiled import CompiledWorkflow
from pylon.workflow.graph import END, WorkflowGraph
from pylon.workflow.replay import ReplayEngine
from pylon.workflow.result import NodeResult
from pylon.workflow.state import StatePatch, compute_state_hash

NodeHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | NodeResult]]


@dataclass
class ExecutionContext:
    """Context for a single workflow execution."""

    compiled: CompiledWorkflow
    run: WorkflowRun
    state: dict[str, Any] = field(default_factory=dict)
    node_handler: NodeHandler | None = None
    checkpoint_repo: CheckpointRepository | None = None
    max_steps: int = 100
    _step_count: int = 0
    node_status: dict[str, str] = field(default_factory=dict)
    edge_status: dict[tuple[str, int], str] = field(default_factory=dict)
    inbound_edges: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    outbound_edges: dict[str, list[tuple[tuple[str, int], Any]]] = field(default_factory=dict)
    state_version: int = 0
    state_hash: str = ""
    join_winners: dict[str, tuple[str, int]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    termination_policy: TerminationCondition | None = None
    external_stop_requested: bool = False
    autonomy_context: AutonomyContext | None = None
    model_route_history: list[dict[str, Any]] = field(default_factory=list)
    node_loop_counts: dict[str, int] = field(default_factory=dict)
    critic: Critic = field(default_factory=Critic)
    verifier: Verifier = field(default_factory=Verifier)
    last_verification: dict[str, Any] | None = None
    approval_manager: ApprovalManager | None = None
    step_signatures: list[str] = field(default_factory=list)


class GraphExecutor:
    """Deterministic executor for DAG workflows."""

    def __init__(
        self,
        checkpoint_repo: CheckpointRepository | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._checkpoint_repo = checkpoint_repo or CheckpointRepository()
        self._approval_manager = approval_manager

    async def execute(
        self,
        graph: WorkflowGraph,
        run: WorkflowRun,
        node_handler: NodeHandler,
        *,
        initial_state: dict[str, Any] | None = None,
        max_steps: int = 100,
        termination_policy: TerminationCondition | None = None,
        external_stop_requested: bool = False,
        goal_spec: GoalSpec | None = None,
    ) -> WorkflowRun:
        """Execute a workflow graph from start to completion."""
        graph.validate()
        compiled = graph.compile()

        effective_termination_policy = self._compose_termination_policy(
            goal_spec=goal_spec,
            explicit_policy=termination_policy,
        )
        ctx = self._new_context(
            compiled=compiled,
            run=run,
            state=initial_state or {},
            node_handler=node_handler,
            max_steps=max_steps,
            termination_policy=effective_termination_policy,
            external_stop_requested=external_stop_requested,
            goal_spec=goal_spec,
        )

        run.start()
        if goal_spec is not None:
            goal_payload = goal_spec.to_dict()
            init_updates: dict[str, Any] = {"goal": goal_payload}
            if ctx.autonomy_context is not None:
                init_updates["autonomy"] = ctx.autonomy_context.to_dict()
            commit_result = CommitEngine.apply_patches(
                ctx.state,
                ctx.state_version,
                {"__init__": StatePatch(updates=init_updates)},
            )
            ctx.state = commit_result.state
            ctx.state_version = commit_result.state_version
            ctx.state_hash = commit_result.state_hash
            run.state = dict(ctx.state)
            run.state_version = ctx.state_version
            run.state_hash = ctx.state_hash
        current_nodes = self._refresh_runnable_nodes(ctx)
        return await self._run_loop(ctx, current_nodes)

    async def resume(
        self,
        graph: WorkflowGraph,
        run: WorkflowRun,
        node_handler: NodeHandler,
        *,
        max_steps: int = 100,
        termination_policy: TerminationCondition | None = None,
        external_stop_requested: bool = False,
        goal_spec: GoalSpec | None = None,
    ) -> WorkflowRun:
        """Resume a previously paused or approval-blocked workflow run."""
        graph.validate()
        compiled = graph.compile()
        effective_termination_policy = self._compose_termination_policy(
            goal_spec=goal_spec,
            explicit_policy=termination_policy,
        )
        ctx = self._new_context(
            compiled=compiled,
            run=run,
            state=dict(run.state),
            node_handler=node_handler,
            max_steps=max_steps,
            termination_policy=effective_termination_policy,
            external_stop_requested=external_stop_requested,
            goal_spec=goal_spec,
        )
        if goal_spec is not None:
            goal_payload = goal_spec.to_dict()
            run.state["goal"] = goal_payload
            ctx.state["goal"] = goal_payload
            if ctx.autonomy_context is not None:
                autonomy_payload = ctx.autonomy_context.to_dict()
                run.state["autonomy"] = autonomy_payload
                ctx.state["autonomy"] = autonomy_payload
        self._restore_execution_snapshot(ctx, run)
        run.resume()
        current_nodes = self._refresh_runnable_nodes(ctx)
        return await self._run_loop(ctx, current_nodes)

    def _new_context(
        self,
        *,
        compiled: CompiledWorkflow,
        run: WorkflowRun,
        state: dict[str, Any],
        node_handler: NodeHandler,
        max_steps: int,
        termination_policy: TerminationCondition | None,
        external_stop_requested: bool,
        goal_spec: GoalSpec | None,
    ) -> ExecutionContext:
        clean_state = dict(state)
        for runtime_key in (
            "execution",
            "runtime_metrics",
            "pause_reason",
            "approval_request_id",
            "approval_reason",
            "approval_context",
            "pending_approval_nodes",
            "termination_reason",
            "verification",
            "goal_status",
            "goal_failure_policy",
            "escalation_reason",
            "refinement_context",
            "refinement_details",
            "replan_reason",
            "replan_count",
        ):
            clean_state.pop(runtime_key, None)
        ctx = ExecutionContext(
            compiled=compiled,
            run=run,
            state=clean_state,
            node_handler=node_handler,
            checkpoint_repo=self._checkpoint_repo,
            max_steps=max_steps,
            node_status={node_id: "pending" for node_id in compiled.nodes},
            inbound_edges={
                node_id: list(compiled.get_inbound_edges(node_id)) for node_id in compiled.nodes
            },
            outbound_edges={
                node_id: [(edge.key, edge) for edge in compiled.get_outbound_edges(node_id)]
                for node_id in compiled.nodes
            },
            state_version=run.state_version,
            state_hash=run.state_hash or compute_state_hash(clean_state),
            termination_policy=termination_policy,
            external_stop_requested=external_stop_requested,
            autonomy_context=(
                AutonomyContext(run_id=run.id, workflow_id=run.workflow_id, goal=goal_spec)
                if goal_spec is not None
                else None
            ),
            approval_manager=self._approval_manager,
        )
        for outbound in ctx.outbound_edges.values():
            for edge_key, _ in outbound:
                ctx.edge_status[edge_key] = "pending"
        return ctx

    async def _run_loop(self, ctx: ExecutionContext, current_nodes: list[str]) -> WorkflowRun:
        run = ctx.run
        compiled = ctx.compiled
        try:
            while current_nodes:
                if ctx._step_count >= ctx.max_steps:
                    self._assign_run_state(run, ctx)
                    run.pause(RunStopReason.LIMIT_EXCEEDED)
                    return run

                ctx._step_count += 1
                input_state_keys = list(ctx.state.keys())
                for node_id in current_nodes:
                    ctx.node_status[node_id] = "running"

                input_state_version = ctx.state_version
                input_state_hash = ctx.state_hash
                attempt_id = self._current_attempt_id(ctx)
                results = await self._execute_superstep(ctx, current_nodes)
                patches = {
                    node_id: StatePatch(result.state_patch)
                    for node_id, result in results.items()
                }
                commit_result = CommitEngine.apply_patches(ctx.state, ctx.state_version, patches)
                ctx.state = commit_result.state
                ctx.state_version = commit_result.state_version
                ctx.state_hash = commit_result.state_hash
                self._update_runtime_telemetry(ctx, results)
                verification = self._evaluate_goal_progress(ctx, run, results)
                loop_evaluations = self._evaluate_loop_nodes(ctx, run, results)
                event_loop_iterations = {
                    node_id: self._current_loop_iteration(ctx, node_id)
                    for node_id in results
                }

                repeating_nodes, exhausted_nodes = self._prepare_loop_repeats(
                    ctx,
                    results,
                    loop_evaluations,
                )
                if exhausted_nodes:
                    reason = (
                        "loop node exhausted iterations without satisfying criterion: "
                        + ",".join(item["node_id"] for item in exhausted_nodes)
                    )
                    if await self._apply_refinement_failure_policy(
                        ctx,
                        run,
                        reason=reason,
                        stop_reason=RunStopReason.LOOP_EXHAUSTED,
                        context="loop_node",
                        details={"nodes": exhausted_nodes},
                    ):
                        return run
                edge_resolutions: dict[str, list[dict[str, Any]]] = {}
                for node_id in current_nodes:
                    if node_id in repeating_nodes:
                        continue
                    edge_resolutions[node_id] = self._resolve_outbound_edges(
                        ctx, node_id, results[node_id]
                    )

                event_sequences: dict[str, int] = {}
                for node_id, result in results.items():
                    if node_id not in repeating_nodes:
                        ctx.node_status[node_id] = "succeeded"
                    seq = len(run.event_log) + 1
                    event_sequences[node_id] = seq
                    run.event_log.append({
                        "seq": seq,
                        "step": ctx._step_count,
                        "attempt_id": attempt_id,
                        "replan_count": (
                            ctx.autonomy_context.replan_count if ctx.autonomy_context else 0
                        ),
                        "node_id": node_id,
                        "agent": compiled.nodes[node_id].agent,
                        "loop_iteration": event_loop_iterations[node_id],
                        "input_state_version": input_state_version,
                        "input_state_hash": input_state_hash,
                        **result.to_event_dict(scrub_metadata=True),
                        "edge_resolutions": edge_resolutions.get(node_id, []),
                        "loop_evaluation": self._event_loop_evaluation(
                            loop_evaluations.get(node_id)
                        ),
                        "evaluation_results": self._event_evaluation_results(verification),
                        "verification": self._event_verification(verification),
                        "state_version": ctx.state_version,
                        "state_hash": ctx.state_hash,
                        "timestamp": datetime.now(UTC).isoformat(),
                    })

                await self._checkpoint(
                    ctx,
                    results,
                    input_state_version=input_state_version,
                    input_state_hash=input_state_hash,
                    input_state_keys=input_state_keys,
                    event_sequences=event_sequences,
                    attempt_id=attempt_id,
                    loop_evaluations=loop_evaluations,
                    verification=verification,
                    edge_resolutions=edge_resolutions,
                    event_loop_iterations=event_loop_iterations,
                )

                approval_wait = self._extract_approval_wait(results)
                if approval_wait is not None:
                    self._assign_run_state(run, ctx)
                    run.wait_for_approval(
                        approval_request_id=approval_wait["approval_request_id"],
                        reason=RunStopReason.APPROVAL_REQUIRED,
                    )
                    if approval_wait["approval_reason"]:
                        run.state["approval_reason"] = approval_wait["approval_reason"]
                    if approval_wait["pending_nodes"]:
                        run.state["pending_approval_nodes"] = approval_wait["pending_nodes"]
                    return run

                next_nodes = self._refresh_runnable_nodes(ctx)
                if await self._apply_verification_policy(
                    ctx,
                    run,
                    verification=verification,
                    has_future_nodes=bool(next_nodes),
                ):
                    return run
                if not next_nodes:
                    next_nodes = self._refresh_runnable_nodes(ctx)

                ctx.step_signatures.append(
                    self._step_signature(
                        ctx,
                        executed_nodes=current_nodes,
                        next_nodes=next_nodes,
                    )
                )

                termination_decision = self._evaluate_termination(ctx)
                if termination_decision is not None:
                    self._assign_run_state(run, ctx)
                    if termination_decision.target_status == RunStatus.COMPLETED:
                        run.complete(reason=termination_decision.stop_reason)
                    elif termination_decision.target_status == RunStatus.FAILED:
                        run.fail(
                            termination_decision.reason,
                            reason=termination_decision.stop_reason,
                        )
                    else:
                        run.pause(termination_decision.stop_reason)
                    run.state["termination_reason"] = termination_decision.reason
                    return run

                current_nodes = next_nodes

            unresolved = [
                node_id for node_id, status in ctx.node_status.items() if status == "pending"
            ]
            if unresolved:
                raise WorkflowError(
                    "Workflow stalled with unresolved nodes",
                    details={"nodes": unresolved},
                )

            self._assign_run_state(run, ctx)
            run.complete()

        except Exception as e:
            self._assign_run_state(run, ctx)
            run.fail(str(e), reason=self._classify_failure_reason(e))
            raise WorkflowError(
                f"Workflow execution failed at step {ctx._step_count}: {e}"
            ) from e

        return run

    async def _execute_superstep(
        self, ctx: ExecutionContext, node_ids: list[str]
    ) -> dict[str, NodeResult]:
        """Execute multiple nodes in parallel (fan-out)."""
        if not ctx.node_handler:
            raise WorkflowError("No node_handler provided")

        async def run_node(node_id: str) -> tuple[str, NodeResult]:
            raw_result = await ctx.node_handler(node_id, dict(ctx.state))
            return node_id, NodeResult.from_raw(raw_result)

        tasks = [run_node(node_id) for node_id in node_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, NodeResult] = {}
        for item in completed:
            if isinstance(item, BaseException):
                raise item
            node_id, result = item
            results[node_id] = result

        return results

    def _resolve_outbound_edges(
        self,
        ctx: ExecutionContext,
        node_id: str,
        result: NodeResult,
    ) -> list[dict[str, Any]]:
        matched_decisions: set[str] = set()
        resolutions: list[dict[str, Any]] = []
        target_counts: dict[str, int] = {}
        for _, outbound_edge in ctx.outbound_edges.get(node_id, []):
            target_counts[outbound_edge.target] = target_counts.get(outbound_edge.target, 0) + 1

        for edge_key, edge in ctx.outbound_edges.get(node_id, []):
            if ctx.edge_status[edge_key] == "blocked":
                continue
            if edge.target != END and self._target_join_closed(ctx, edge.target, edge_key):
                ctx.edge_status[edge_key] = "blocked"
                resolutions.append({
                    "edge_key": self._serialize_edge_key(edge_key),
                    "target": edge.target,
                    "condition": edge.condition,
                    "status": "blocked",
                    "decision_source": "join_policy",
                    "reason": "target join already closed",
                })
                continue
            decision, decision_source = self._resolve_edge_decision(
                edge,
                result,
                matched_decisions,
                target_counts,
            )
            if decision is None:
                taken = edge.evaluate(ctx.state)
                decision_source = "default" if edge.condition is None else "condition"
                reason = (
                    "default edge selected"
                    if edge.condition is None
                    else f"condition evaluated to {str(taken).lower()}"
                )
            else:
                taken = decision
                reason = f"explicit decision evaluated to {str(taken).lower()}"
            ctx.edge_status[edge_key] = "taken" if taken else "not_taken"
            resolutions.append({
                "edge_key": self._serialize_edge_key(edge_key),
                "target": edge.target,
                "condition": edge.condition,
                "status": ctx.edge_status[edge_key],
                "decision_source": decision_source,
                "reason": reason,
            })
        unknown_decisions = sorted(set(result.edge_decisions) - matched_decisions)
        if unknown_decisions:
            raise WorkflowError(
                "Node result references unknown outbound edge decisions",
                details={"node_id": node_id, "decision_keys": unknown_decisions},
            )
        return resolutions

    def _refresh_runnable_nodes(self, ctx: ExecutionContext) -> list[str]:
        changed = True
        while changed:
            changed = False
            for node_id, status in list(ctx.node_status.items()):
                if status != "pending":
                    continue

                inbound = ctx.inbound_edges.get(node_id, [])
                if not inbound:
                    ctx.node_status[node_id] = "runnable"
                    changed = True
                    continue

                inbound_statuses = [ctx.edge_status[edge_key] for edge_key in inbound]
                policy = ctx.compiled.nodes[node_id].join_policy
                next_status = self._resolve_join_status(
                    ctx,
                    node_id,
                    inbound,
                    inbound_statuses,
                    policy,
                )
                if next_status is None:
                    continue
                ctx.node_status[node_id] = next_status
                if next_status == "skipped":
                    for edge_key, edge in ctx.outbound_edges.get(node_id, []):
                        if edge.target != END and ctx.edge_status[edge_key] == "pending":
                            ctx.edge_status[edge_key] = "not_taken"
                changed = True

        return [node_id for node_id, status in ctx.node_status.items() if status == "runnable"]

    def _extract_approval_wait(
        self,
        results: dict[str, NodeResult],
    ) -> dict[str, Any] | None:
        approval_results = [
            (node_id, result) for node_id, result in results.items() if result.requires_approval
        ]
        if not approval_results:
            return None

        approval_request_id = next(
            (
                result.approval_request_id
                for _, result in approval_results
                if result.approval_request_id is not None
            ),
            None,
        )
        approval_reasons = sorted(
            {
                result.approval_reason
                for _, result in approval_results
                if result.approval_reason
            }
        )
        return {
            "approval_request_id": approval_request_id,
            "approval_reason": "; ".join(approval_reasons),
            "pending_nodes": [node_id for node_id, _ in approval_results],
        }

    def _update_runtime_telemetry(
        self,
        ctx: ExecutionContext,
        results: dict[str, NodeResult],
    ) -> None:
        token_usage = ctx.token_usage
        estimated_cost = ctx.estimated_cost_usd
        for result in results.values():
            metrics = result.metrics
            model_route = metrics.get("model_route")
            if isinstance(model_route, dict):
                route_payload = self._normalize_model_route(model_route)
                ctx.model_route_history.append(route_payload)
            metrics_has_usage = isinstance(metrics.get("token_usage"), dict)
            if metrics_has_usage:
                usage = metrics["token_usage"]
                token_usage.input_tokens += int(usage.get("input_tokens", 0))
                token_usage.output_tokens += int(usage.get("output_tokens", 0))
                token_usage.cache_read_tokens += int(usage.get("cache_read_tokens", 0))
                token_usage.cache_write_tokens += int(usage.get("cache_write_tokens", 0))
            else:
                token_usage.input_tokens += int(metrics.get("input_tokens", 0))
                token_usage.output_tokens += int(metrics.get("output_tokens", 0))
                token_usage.cache_read_tokens += int(metrics.get("cache_read_tokens", 0))
                token_usage.cache_write_tokens += int(metrics.get("cache_write_tokens", 0))
            metrics_has_cost = "estimated_cost_usd" in metrics
            if metrics_has_cost:
                estimated_cost += float(metrics.get("estimated_cost_usd", 0.0))

            if not metrics_has_usage:
                for event in result.llm_events:
                    event_usage = event.get("usage")
                    if isinstance(event_usage, dict):
                        token_usage.input_tokens += int(event_usage.get("input_tokens", 0))
                        token_usage.output_tokens += int(event_usage.get("output_tokens", 0))
                        token_usage.cache_read_tokens += int(
                            event_usage.get("cache_read_tokens", 0)
                        )
                        token_usage.cache_write_tokens += int(
                            event_usage.get("cache_write_tokens", 0)
                        )
            if not metrics_has_cost:
                for event in result.llm_events:
                    estimated_cost += float(
                        event.get("estimated_cost_usd", event.get("cost_usd", 0.0))
                    )

        ctx.estimated_cost_usd = estimated_cost
        if ctx.autonomy_context is not None:
            ctx.autonomy_context.current_iteration = ctx._step_count
            ctx.autonomy_context.token_usage = TokenUsage(
                input_tokens=token_usage.input_tokens,
                output_tokens=token_usage.output_tokens,
                cache_read_tokens=token_usage.cache_read_tokens,
                cache_write_tokens=token_usage.cache_write_tokens,
            )
            ctx.autonomy_context.estimated_cost_usd = estimated_cost
            ctx.autonomy_context.model_routes = [
                self._decision_from_payload(payload) for payload in ctx.model_route_history
            ]
            ctx.autonomy_context.last_verification = ctx.last_verification

    def _evaluate_goal_progress(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        results: dict[str, NodeResult],
    ) -> VerificationDecision | None:
        if ctx.autonomy_context is None or not ctx.autonomy_context.goal.success_criteria:
            return None
        evaluations = ctx.critic.evaluate(
            ctx.autonomy_context.goal,
            state=ctx.state,
            event_log=run.event_log,
            results=results,
        )
        verification = ctx.verifier.verify(ctx.autonomy_context.goal, evaluations)
        if verification is None:
            return None
        verification_payload = verification.to_dict()
        ctx.last_verification = verification_payload
        ctx.autonomy_context.last_verification = verification_payload
        ctx.autonomy_context.evaluation_history.append({
            "iteration": ctx._step_count,
            **verification_payload,
        })
        return verification

    def _evaluate_loop_nodes(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        results: dict[str, NodeResult],
    ) -> dict[str, EvaluationResult]:
        loop_evaluations: dict[str, EvaluationResult] = {}
        for node_id, result in results.items():
            compiled_node = ctx.compiled.nodes[node_id]
            if compiled_node.node_type != WorkflowNodeType.LOOP:
                continue
            criterion = SuccessCriterion(
                type=compiled_node.loop_criterion or "state_value",
                threshold=compiled_node.loop_threshold,
                metadata=dict(compiled_node.loop_metadata),
            )
            loop_goal = GoalSpec(
                objective=f"loop:{node_id}",
                success_criteria=(criterion,),
            )
            evaluations = ctx.critic.evaluate(
                loop_goal,
                state=ctx.state,
                event_log=run.event_log,
                results={node_id: result},
            )
            if not evaluations:
                continue
            evaluation = evaluations[0]
            loop_evaluations[node_id] = evaluation
        return loop_evaluations

    def _prepare_loop_repeats(
        self,
        ctx: ExecutionContext,
        results: dict[str, NodeResult],
        loop_evaluations: dict[str, EvaluationResult],
    ) -> tuple[set[str], list[dict[str, Any]]]:
        repeating_nodes: set[str] = set()
        exhausted_nodes: list[dict[str, Any]] = []
        for node_id, evaluation in loop_evaluations.items():
            loop_iteration = self._current_loop_iteration(ctx, node_id)
            if evaluation.passed:
                ctx.node_loop_counts.pop(node_id, None)
                continue

            max_iterations = ctx.compiled.nodes[node_id].loop_max_iterations or 1
            if loop_iteration >= max_iterations:
                ctx.node_loop_counts[node_id] = loop_iteration
                exhausted_nodes.append({
                    "node_id": node_id,
                    "loop_iteration": loop_iteration,
                    "max_iterations": max_iterations,
                    "criterion": ctx.compiled.nodes[node_id].loop_criterion,
                })
                continue

            ctx.node_loop_counts[node_id] = loop_iteration
            ctx.node_status[node_id] = "pending"
            repeating_nodes.add(node_id)
        return repeating_nodes, exhausted_nodes

    async def _apply_verification_policy(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        *,
        verification: VerificationDecision | None,
        has_future_nodes: bool,
    ) -> bool:
        if verification is None:
            return False
        if verification.disposition == VerificationDisposition.SUCCESS:
            ctx.state["goal_status"] = {
                "satisfied": True,
                "reason": verification.reason,
                "completion_policy": (
                    ctx.autonomy_context.goal.completion_policy.value
                    if ctx.autonomy_context is not None
                    else RunCompletionPolicy.REQUIRE_WORKFLOW_END.value
                ),
            }
            ctx.state_version += 1
            ctx.state_hash = compute_state_hash(ctx.state)
            if (
                ctx.autonomy_context is not None
                and ctx.autonomy_context.goal.completion_policy
                == RunCompletionPolicy.REQUIRE_WORKFLOW_END
                and has_future_nodes
            ):
                return False
            self._assign_run_state(run, ctx)
            run.complete(reason=RunStopReason.QUALITY_REACHED)
            return True
        if (
            verification.disposition == VerificationDisposition.REFINE
            and has_future_nodes
        ):
            return False
        if (
            verification.disposition == VerificationDisposition.REFINE
            and self._schedule_replan(ctx, verification.reason)
        ):
            return False
        if verification.disposition == VerificationDisposition.FAIL:
            return await self._apply_goal_failure_policy(
                ctx,
                run,
                reason=verification.reason,
                stop_reason=RunStopReason.QUALITY_FAILED,
                context="goal_verification",
            )
        return await self._apply_refinement_failure_policy(
            ctx,
            run,
            reason=verification.reason,
            stop_reason=RunStopReason.QUALITY_FAILED,
            context="goal_verification",
        )

    async def _apply_goal_failure_policy(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        *,
        reason: str,
        stop_reason: RunStopReason,
        context: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        failure_policy = (
            ctx.autonomy_context.goal.failure_policy
            if ctx.autonomy_context is not None
            else FailurePolicy.FAIL
        )
        self._assign_run_state(run, ctx)
        run.state["goal_failure_policy"] = failure_policy.value
        run.state["refinement_context"] = context
        if details:
            run.state["refinement_details"] = details

        if failure_policy == FailurePolicy.FAIL:
            run.fail(reason, reason=stop_reason)
            return True

        if failure_policy == FailurePolicy.REQUEST_APPROVAL:
            approval_request_id = await self._submit_verification_approval_request(
                ctx,
                reason,
                context=context,
            )
            run.wait_for_approval(
                approval_request_id=approval_request_id,
                reason=RunStopReason.APPROVAL_REQUIRED,
            )
            run.state["approval_reason"] = reason
            run.state["approval_context"] = context
            return True

        run.pause(RunStopReason.ESCALATION_REQUIRED)
        run.state["escalation_reason"] = reason
        return True

    async def _apply_refinement_failure_policy(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        *,
        reason: str,
        stop_reason: RunStopReason,
        context: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        failure_policy = (
            ctx.autonomy_context.goal.resolved_refinement_failure_policy()
            if ctx.autonomy_context is not None
            else FailurePolicy.FAIL
        )
        return await self._apply_goal_failure_policy(
            ctx,
            run,
            reason=reason,
            stop_reason=stop_reason,
            context=context,
            details=details,
        ) if (
            ctx.autonomy_context is None
            or failure_policy == ctx.autonomy_context.goal.failure_policy
        ) else await self._apply_specific_failure_policy(
            ctx,
            run,
            failure_policy=failure_policy,
            reason=reason,
            stop_reason=stop_reason,
            context=context,
            details=details,
        )

    async def _apply_specific_failure_policy(
        self,
        ctx: ExecutionContext,
        run: WorkflowRun,
        *,
        failure_policy: FailurePolicy,
        reason: str,
        stop_reason: RunStopReason,
        context: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        self._assign_run_state(run, ctx)
        run.state["goal_failure_policy"] = failure_policy.value
        run.state["refinement_context"] = context
        if details:
            run.state["refinement_details"] = details

        if failure_policy == FailurePolicy.FAIL:
            run.fail(reason, reason=stop_reason)
            return True

        if failure_policy == FailurePolicy.REQUEST_APPROVAL:
            approval_request_id = await self._submit_verification_approval_request(
                ctx,
                reason,
                context=context,
            )
            run.wait_for_approval(
                approval_request_id=approval_request_id,
                reason=RunStopReason.APPROVAL_REQUIRED,
            )
            run.state["approval_reason"] = reason
            run.state["approval_context"] = context
            return True

        run.pause(RunStopReason.ESCALATION_REQUIRED)
        run.state["escalation_reason"] = reason
        return True

    async def _submit_verification_approval_request(
        self,
        ctx: ExecutionContext,
        reason: str,
        *,
        context: str = "goal_verification",
    ) -> str | None:
        if ctx.approval_manager is None:
            return None
        goal = ctx.autonomy_context.goal if ctx.autonomy_context is not None else None
        plan = {
            "kind": context,
            "workflow_id": ctx.run.workflow_id,
            "objective": goal.objective if goal is not None else "",
            "reason": reason,
            "step_count": ctx._step_count,
        }
        effect_envelope = {
            "allowed_effect_scopes": (
                sorted(goal.allowed_effect_scopes) if goal is not None else []
            ),
            "allowed_secret_scopes": (
                sorted(goal.allowed_secret_scopes) if goal is not None else []
            ),
        }
        request = await ctx.approval_manager.submit_request(
            agent_id=f"workflow:{ctx.run.workflow_id}",
            action=f"workflow.{context}",
            autonomy_level=AutonomyLevel.A3,
            context={
                "kind": context,
                "run_id": ctx.run.id,
                "workflow_id": ctx.run.workflow_id,
                "reason": reason,
                "binding_plan": plan,
                "binding_effect_envelope": effect_envelope,
            },
            plan=plan,
            effect_envelope=effect_envelope,
        )
        return request.id

    def _schedule_replan(self, ctx: ExecutionContext, reason: str) -> bool:
        if ctx.autonomy_context is None:
            return False
        max_replans = ctx.autonomy_context.goal.resolved_max_replans()
        if max_replans is None or ctx.autonomy_context.replan_count >= max_replans:
            return False

        ctx.autonomy_context.replan_count += 1
        ctx.state["replan_reason"] = reason
        ctx.state["replan_count"] = ctx.autonomy_context.replan_count
        ctx.node_loop_counts.clear()
        ctx.step_signatures.clear()
        ctx.state["autonomy"] = ctx.autonomy_context.to_dict()
        ctx.node_status = {node_id: "pending" for node_id in ctx.compiled.nodes}
        ctx.join_winners.clear()
        for outbound in ctx.outbound_edges.values():
            for edge_key, _ in outbound:
                ctx.edge_status[edge_key] = "pending"
        self._refresh_runnable_nodes(ctx)
        return True

    def _current_attempt_id(self, ctx: ExecutionContext) -> int:
        if ctx.autonomy_context is None:
            return 1
        return ctx.autonomy_context.replan_count + 1

    def _current_loop_iteration(self, ctx: ExecutionContext, node_id: str) -> int:
        return ctx.node_loop_counts.get(node_id, 0) + 1

    def _evaluate_termination(self, ctx: ExecutionContext):
        if ctx.termination_policy is None:
            return None
        decision = ctx.termination_policy.evaluate(
            TerminationState(
                iterations=ctx._step_count,
                token_usage=TokenUsage(
                    input_tokens=ctx.token_usage.input_tokens,
                    output_tokens=ctx.token_usage.output_tokens,
                    cache_read_tokens=ctx.token_usage.cache_read_tokens,
                    cache_write_tokens=ctx.token_usage.cache_write_tokens,
                ),
                estimated_cost_usd=ctx.estimated_cost_usd,
                elapsed_seconds=(datetime.now(UTC) - ctx.started_at).total_seconds(),
                external_stop_requested=ctx.external_stop_requested,
                quality_score=self._termination_quality_score(ctx),
                recent_step_signatures=tuple(ctx.step_signatures),
            )
        )
        return decision if decision.matched else None

    def _termination_quality_score(self, ctx: ExecutionContext) -> float | None:
        verification = ctx.last_verification
        if isinstance(verification, dict):
            results = verification.get("results")
            if isinstance(results, list) and results:
                scores = [
                    float(result.get("score", 0.0))
                    for result in results
                    if isinstance(result, dict)
                ]
                if scores:
                    return min(scores)
        for event in reversed(ctx.run.event_log):
            metrics = event.get("metrics", {})
            if isinstance(metrics, dict) and "response_quality_score" in metrics:
                return float(metrics["response_quality_score"])
        return None

    def _write_runtime_metrics(self, run: WorkflowRun, ctx: ExecutionContext) -> None:
        run.state["runtime_metrics"] = {
            "iterations": ctx._step_count,
            "replan_count": ctx.autonomy_context.replan_count if ctx.autonomy_context else 0,
            "elapsed_seconds": (datetime.now(UTC) - ctx.started_at).total_seconds(),
            "estimated_cost_usd": ctx.estimated_cost_usd,
            "token_usage": {
                "input_tokens": ctx.token_usage.input_tokens,
                "output_tokens": ctx.token_usage.output_tokens,
                "cache_read_tokens": ctx.token_usage.cache_read_tokens,
                "cache_write_tokens": ctx.token_usage.cache_write_tokens,
                "total_tokens": ctx.token_usage.total_tokens,
                "metered_tokens": ctx.token_usage.metered_tokens,
                "reasoning_tokens": ctx.token_usage.reasoning_tokens,
            },
            "model_routes": list(ctx.model_route_history),
        }
        if ctx.autonomy_context is not None:
            run.state["autonomy"] = ctx.autonomy_context.to_dict()
        if ctx.last_verification is not None:
            run.state["verification"] = ctx.last_verification

    def _write_policy_resolution(self, run: WorkflowRun, ctx: ExecutionContext) -> None:
        if ctx.autonomy_context is None:
            return
        goal = ctx.autonomy_context.goal
        goal_termination_policy = goal.constraints.to_termination_condition()
        run.state["policy_resolution"] = {
            "goal_failure_policy": goal.failure_policy.value,
            "refinement_exhaustion_policy": goal.resolved_refinement_failure_policy().value,
            "completion_policy": goal.completion_policy.value,
            "resolved_max_replans": goal.resolved_max_replans(),
            "goal_termination_policy": describe_termination_condition(goal_termination_policy),
            "effective_termination_policy": describe_termination_condition(ctx.termination_policy),
            "external_stop_requested": ctx.external_stop_requested,
            "refinement_context": run.state.get("refinement_context"),
            "approval_context": run.state.get("approval_context"),
        }

    def _assign_run_state(self, run: WorkflowRun, ctx: ExecutionContext) -> None:
        run.state = dict(ctx.state)
        run.state_version = ctx.state_version
        run.state_hash = ctx.state_hash
        self._write_runtime_metrics(run, ctx)
        self._write_policy_resolution(run, ctx)
        run.state["execution"] = self._execution_snapshot(ctx)

    def _execution_snapshot(self, ctx: ExecutionContext) -> dict[str, Any]:
        return {
            "step_count": ctx._step_count,
            "max_steps": ctx.max_steps,
            "node_status": dict(ctx.node_status),
            "edge_status": {
                self._serialize_edge_key(edge_key): status
                for edge_key, status in ctx.edge_status.items()
            },
            "join_winners": {
                node_id: self._serialize_edge_key(edge_key)
                for node_id, edge_key in ctx.join_winners.items()
            },
            "edge_catalog": {
                self._serialize_edge_key(edge.key): {
                    "source": edge.source,
                    "target": edge.target,
                    "condition": edge.condition,
                }
                for node in ctx.compiled.nodes.values()
                for edge in node.outbound_edges
            },
            "node_loop_counts": dict(ctx.node_loop_counts),
            "state_version": ctx.state_version,
            "state_hash": ctx.state_hash,
            "started_at": ctx.started_at.isoformat(),
            "token_usage": {
                "input_tokens": ctx.token_usage.input_tokens,
                "output_tokens": ctx.token_usage.output_tokens,
                "cache_read_tokens": ctx.token_usage.cache_read_tokens,
                "cache_write_tokens": ctx.token_usage.cache_write_tokens,
                "total_tokens": ctx.token_usage.total_tokens,
                "metered_tokens": ctx.token_usage.metered_tokens,
                "reasoning_tokens": ctx.token_usage.reasoning_tokens,
            },
            "estimated_cost_usd": ctx.estimated_cost_usd,
            "model_routes": list(ctx.model_route_history),
            "replan_count": ctx.autonomy_context.replan_count if ctx.autonomy_context else 0,
            "last_verification": ctx.last_verification,
            "step_signatures": list(ctx.step_signatures),
        }

    def _restore_execution_snapshot(self, ctx: ExecutionContext, run: WorkflowRun) -> None:
        snapshot = run.state.get("execution")
        if not isinstance(snapshot, dict):
            return
        ctx._step_count = int(snapshot.get("step_count", 0))
        ctx.max_steps = max(int(snapshot.get("max_steps", ctx.max_steps)), ctx.max_steps)
        node_status = snapshot.get("node_status", {})
        if isinstance(node_status, dict):
            for node_id, status in node_status.items():
                if node_id in ctx.node_status:
                    ctx.node_status[node_id] = str(status)
        edge_status = snapshot.get("edge_status", {})
        if isinstance(edge_status, dict):
            for raw_key, status in edge_status.items():
                edge_key = self._deserialize_edge_key(raw_key)
                if edge_key in ctx.edge_status:
                    ctx.edge_status[edge_key] = str(status)
        join_winners = snapshot.get("join_winners", {})
        if isinstance(join_winners, dict):
            for node_id, raw_key in join_winners.items():
                if node_id in ctx.compiled.nodes:
                    ctx.join_winners[node_id] = self._deserialize_edge_key(raw_key)
        loop_counts = snapshot.get("node_loop_counts", {})
        if isinstance(loop_counts, dict):
            ctx.node_loop_counts = {
                str(node_id): int(count) for node_id, count in loop_counts.items()
            }
        ctx.state_version = int(snapshot.get("state_version", run.state_version))
        ctx.state_hash = str(
            snapshot.get("state_hash", run.state_hash or compute_state_hash(ctx.state))
        )
        started_at = snapshot.get("started_at")
        if started_at:
            ctx.started_at = datetime.fromisoformat(str(started_at))
        token_usage = snapshot.get("token_usage", {})
        if isinstance(token_usage, dict):
            ctx.token_usage = TokenUsage(
                input_tokens=int(token_usage.get("input_tokens", 0)),
                output_tokens=int(token_usage.get("output_tokens", 0)),
                cache_read_tokens=int(token_usage.get("cache_read_tokens", 0)),
                cache_write_tokens=int(token_usage.get("cache_write_tokens", 0)),
            )
        ctx.estimated_cost_usd = float(snapshot.get("estimated_cost_usd", 0.0))
        routes = snapshot.get("model_routes", [])
        if isinstance(routes, list):
            ctx.model_route_history = [
                self._normalize_model_route(route)
                for route in routes
                if isinstance(route, dict)
            ]
        if ctx.autonomy_context is not None:
            ctx.autonomy_context.current_iteration = ctx._step_count
            ctx.autonomy_context.replan_count = int(snapshot.get("replan_count", 0))
            ctx.autonomy_context.token_usage = TokenUsage(
                input_tokens=ctx.token_usage.input_tokens,
                output_tokens=ctx.token_usage.output_tokens,
                cache_read_tokens=ctx.token_usage.cache_read_tokens,
                cache_write_tokens=ctx.token_usage.cache_write_tokens,
            )
            ctx.autonomy_context.estimated_cost_usd = ctx.estimated_cost_usd
            ctx.autonomy_context.model_routes = [
                self._decision_from_payload(payload) for payload in ctx.model_route_history
            ]
        last_verification = snapshot.get("last_verification")
        if isinstance(last_verification, dict):
            ctx.last_verification = dict(last_verification)
            if ctx.autonomy_context is not None:
                ctx.autonomy_context.last_verification = dict(last_verification)
        step_signatures = snapshot.get("step_signatures", [])
        if isinstance(step_signatures, list):
            ctx.step_signatures = [str(signature) for signature in step_signatures]

    def _serialize_edge_key(self, edge_key: tuple[str, int]) -> str:
        return f"{edge_key[0]}:{edge_key[1]}"

    def _deserialize_edge_key(self, value: Any) -> tuple[str, int]:
        raw = str(value)
        source, _, index = raw.rpartition(":")
        if not source:
            raise WorkflowError("Invalid serialized edge key", details={"edge_key": value})
        return source, int(index)

    def _step_signature(
        self,
        ctx: ExecutionContext,
        *,
        executed_nodes: list[str],
        next_nodes: list[str],
    ) -> str:
        executed = ",".join(sorted(executed_nodes))
        upcoming = ",".join(sorted(next_nodes))
        return f"{ctx.state_hash}|{executed}|{upcoming}"

    def _compose_termination_policy(
        self,
        *,
        goal_spec: GoalSpec | None,
        explicit_policy: TerminationCondition | None,
    ) -> TerminationCondition | None:
        goal_policy = (
            goal_spec.constraints.to_termination_condition() if goal_spec is not None else None
        )
        if goal_policy is None:
            return explicit_policy
        if explicit_policy is None:
            return goal_policy
        return explicit_policy | goal_policy

    def _normalize_model_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "provider_name": str(payload.get("provider_name", "")),
            "model_id": str(payload.get("model_id", "")),
            "tier": str(payload.get("tier", ModelTier.STANDARD.value)),
            "reasoning": str(payload.get("reasoning", "")),
            "cache_strategy": str(payload.get("cache_strategy", "none")),
            "batch_eligible": bool(payload.get("batch_eligible", False)),
        }
        return normalized

    def _decision_from_payload(self, payload: dict[str, Any]) -> ModelRouteDecision:
        tier_value = payload.get("tier", ModelTier.STANDARD.value)
        return ModelRouteDecision(
            provider_name=str(payload.get("provider_name", "")),
            model_id=str(payload.get("model_id", "")),
            tier=ModelTier(tier_value),
            reasoning=str(payload.get("reasoning", "")),
            cache_strategy=CacheStrategy(str(payload.get("cache_strategy", "none"))),
            batch_eligible=bool(payload.get("batch_eligible", False)),
        )

    def _resolve_join_status(
        self,
        ctx: ExecutionContext,
        node_id: str,
        inbound: list[tuple[str, int]],
        inbound_statuses: list[str],
        policy: WorkflowJoinPolicy,
    ) -> str | None:
        taken_edges = [edge_key for edge_key in inbound if ctx.edge_status[edge_key] == "taken"]
        has_pending = any(state == "pending" for state in inbound_statuses)

        if policy == WorkflowJoinPolicy.ALL_RESOLVED:
            if has_pending:
                return None
            return "runnable" if taken_edges else "skipped"

        if policy == WorkflowJoinPolicy.ANY:
            if taken_edges:
                self._block_pending_inbound_edges(ctx, inbound)
                return "runnable"
            if has_pending:
                return None
            return "skipped"

        if policy == WorkflowJoinPolicy.FIRST:
            if taken_edges:
                winner = min(taken_edges)
                ctx.join_winners[node_id] = winner
                self._block_losing_inbound_edges(ctx, inbound, winner)
                return "runnable"
            if has_pending:
                return None
            return "skipped"

        raise WorkflowError(f"Unsupported join policy: {policy.value}")

    def _classify_failure_reason(self, error: Exception) -> RunStopReason:
        message = str(error)
        if "State conflict" in message:
            return RunStopReason.STATE_CONFLICT
        if "Loop node exhausted iterations" in message:
            return RunStopReason.LOOP_EXHAUSTED
        return RunStopReason.WORKFLOW_ERROR

    def _block_pending_inbound_edges(
        self,
        ctx: ExecutionContext,
        inbound: list[tuple[str, int]],
    ) -> None:
        for edge_key in inbound:
            if ctx.edge_status[edge_key] == "pending":
                ctx.edge_status[edge_key] = "blocked"

    def _block_losing_inbound_edges(
        self,
        ctx: ExecutionContext,
        inbound: list[tuple[str, int]],
        winner: tuple[str, int],
    ) -> None:
        for edge_key in inbound:
            if edge_key == winner:
                continue
            if ctx.edge_status[edge_key] in {"pending", "taken"}:
                ctx.edge_status[edge_key] = "blocked"

    def _target_join_closed(
        self,
        ctx: ExecutionContext,
        target_node_id: str,
        edge_key: tuple[str, int],
    ) -> bool:
        target = ctx.compiled.nodes[target_node_id]
        target_status = ctx.node_status[target_node_id]
        if target.join_policy == WorkflowJoinPolicy.ALL_RESOLVED:
            return False
        if target.join_policy == WorkflowJoinPolicy.FIRST:
            winner = ctx.join_winners.get(target_node_id)
            return winner is not None and winner != edge_key
        return target_status in {"runnable", "running", "succeeded"}

    async def _checkpoint(
        self,
        ctx: ExecutionContext,
        results: dict[str, NodeResult],
        *,
        input_state_version: int,
        input_state_hash: str,
        input_state_keys: list[str],
        event_sequences: dict[str, int],
        attempt_id: int,
        loop_evaluations: dict[str, EvaluationResult],
        verification: VerificationDecision | None,
        edge_resolutions: dict[str, list[dict[str, Any]]],
        event_loop_iterations: dict[str, int],
    ) -> None:
        """Create node-scoped checkpoints after completion."""
        for node_id, result in results.items():
            checkpoint = Checkpoint(
                workflow_run_id=ctx.run.id,
                node_id=node_id,
                state_version=ctx.state_version,
                state_hash=ctx.state_hash,
            )
            checkpoint.add_event(
                seq=event_sequences[node_id],
                attempt_id=attempt_id,
                replan_count=ctx.autonomy_context.replan_count if ctx.autonomy_context else 0,
                loop_iteration=event_loop_iterations[node_id],
                node_id=node_id,
                input_data={"state_snapshot_keys": input_state_keys},
                input_state_version=input_state_version,
                input_state_hash=input_state_hash,
                llm_events=result.llm_events,
                tool_events=result.tool_events,
                artifacts=result.artifacts,
                edge_decisions=result.edge_decisions,
                edge_resolutions=edge_resolutions.get(node_id, []),
                metrics=result.metrics,
                loop_evaluation=self._event_loop_evaluation(loop_evaluations.get(node_id)),
                evaluation_results=self._event_evaluation_results(verification),
                verification=self._event_verification(verification),
                state_patch=result.state_patch,
                state_version=ctx.state_version,
                state_hash=ctx.state_hash,
            )
            await self._checkpoint_repo.create(checkpoint)

    async def replay(
        self,
        graph: WorkflowGraph,
        run: WorkflowRun,
        node_handler: NodeHandler,
    ) -> WorkflowRun:
        """Replay a workflow from its event log."""
        replayed = ReplayEngine.replay_event_log(run.event_log)
        run.state = replayed.state
        run.state_version = replayed.state_version
        run.state_hash = replayed.state_hash
        return run

    def _resolve_edge_decision(
        self,
        edge: Any,
        result: NodeResult,
        matched_decisions: set[str],
        target_counts: dict[str, int],
    ) -> tuple[bool | None, str | None]:
        decisions = result.edge_decisions
        if edge.decision_key in decisions:
            matched_decisions.add(edge.decision_key)
            return decisions[edge.decision_key], "explicit_edge_key"

        if edge.target not in decisions:
            return None, None
        if target_counts.get(edge.target, 0) > 1:
            raise WorkflowError(
                "Explicit edge decisions by target are ambiguous for duplicate targets",
                details={"target": edge.target, "decision_key": edge.decision_key},
            )
        matched_decisions.add(edge.target)
        return decisions[edge.target], "explicit_target"

    def _event_evaluation_results(
        self,
        verification: VerificationDecision | None,
    ) -> list[dict[str, Any]]:
        if verification is None:
            return []
        return [result.to_dict() for result in verification.results]

    def _event_verification(
        self,
        verification: VerificationDecision | None,
    ) -> dict[str, Any] | None:
        if verification is None:
            return None
        return verification.to_dict()

    def _event_loop_evaluation(
        self,
        evaluation: EvaluationResult | None,
    ) -> dict[str, Any] | None:
        if evaluation is None:
            return None
        return evaluation.to_dict()
