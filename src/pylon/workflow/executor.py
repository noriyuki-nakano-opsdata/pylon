"""Workflow Graph Executor with deterministic DAG scheduling semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.errors import WorkflowError
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.workflow import WorkflowRun
from pylon.types import WorkflowJoinPolicy
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


class GraphExecutor:
    """Deterministic executor for DAG workflows."""

    def __init__(
        self,
        checkpoint_repo: CheckpointRepository | None = None,
    ) -> None:
        self._checkpoint_repo = checkpoint_repo or CheckpointRepository()

    async def execute(
        self,
        graph: WorkflowGraph,
        run: WorkflowRun,
        node_handler: NodeHandler,
        *,
        initial_state: dict[str, Any] | None = None,
        max_steps: int = 100,
    ) -> WorkflowRun:
        """Execute a workflow graph from start to completion."""
        graph.validate()
        compiled = graph.compile()

        ctx = ExecutionContext(
            compiled=compiled,
            run=run,
            state=initial_state or {},
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
            state_version=0,
            state_hash=compute_state_hash(initial_state or {}),
        )
        for outbound in ctx.outbound_edges.values():
            for edge_key, _ in outbound:
                ctx.edge_status[edge_key] = "pending"

        run.start()
        current_nodes = self._refresh_runnable_nodes(ctx)

        try:
            while current_nodes:
                if ctx._step_count >= max_steps:
                    run.state = ctx.state
                    run.state_version = ctx.state_version
                    run.state_hash = ctx.state_hash
                    run.pause("max_steps_exceeded")
                    return run

                ctx._step_count += 1
                input_state_keys = list(ctx.state.keys())
                for node_id in current_nodes:
                    ctx.node_status[node_id] = "running"

                input_state_version = ctx.state_version
                input_state_hash = ctx.state_hash
                results = await self._execute_superstep(ctx, current_nodes)
                patches = {
                    node_id: StatePatch(result.state_patch)
                    for node_id, result in results.items()
                }
                commit_result = CommitEngine.apply_patches(ctx.state, ctx.state_version, patches)
                ctx.state = commit_result.state
                ctx.state_version = commit_result.state_version
                ctx.state_hash = commit_result.state_hash

                event_sequences: dict[str, int] = {}
                for node_id, result in results.items():
                    ctx.node_status[node_id] = "succeeded"
                    seq = len(run.event_log) + 1
                    event_sequences[node_id] = seq
                    run.event_log.append({
                        "seq": seq,
                        "step": ctx._step_count,
                        "attempt_id": 1,
                        "node_id": node_id,
                        "agent": compiled.nodes[node_id].agent,
                        "input_state_version": input_state_version,
                        "input_state_hash": input_state_hash,
                        **result.to_event_dict(scrub_metadata=True),
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
                )

                for node_id in current_nodes:
                    self._resolve_outbound_edges(ctx, node_id, results[node_id])

                current_nodes = self._refresh_runnable_nodes(ctx)

            unresolved = [
                node_id for node_id, status in ctx.node_status.items() if status == "pending"
            ]
            if unresolved:
                raise WorkflowError(
                    "Workflow stalled with unresolved nodes",
                    details={"nodes": unresolved},
                )

            run.state = ctx.state
            run.state_version = ctx.state_version
            run.state_hash = ctx.state_hash
            run.complete()

        except Exception as e:
            run.fail(str(e))
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
            if isinstance(item, Exception):
                raise item
            node_id, result = item
            results[node_id] = result

        return results

    def _resolve_outbound_edges(
        self,
        ctx: ExecutionContext,
        node_id: str,
        result: NodeResult,
    ) -> None:
        matched_decisions: set[str] = set()
        target_counts: dict[str, int] = {}
        for _, outbound_edge in ctx.outbound_edges.get(node_id, []):
            target_counts[outbound_edge.target] = target_counts.get(outbound_edge.target, 0) + 1

        for edge_key, edge in ctx.outbound_edges.get(node_id, []):
            if ctx.edge_status[edge_key] == "blocked":
                continue
            if edge.target != END and self._target_join_closed(ctx, edge.target, edge_key):
                ctx.edge_status[edge_key] = "blocked"
                continue
            decision = self._resolve_edge_decision(
                edge,
                result,
                matched_decisions,
                target_counts,
            )
            taken = edge.evaluate(ctx.state) if decision is None else decision
            ctx.edge_status[edge_key] = "taken" if taken else "not_taken"
        unknown_decisions = sorted(set(result.edge_decisions) - matched_decisions)
        if unknown_decisions:
            raise WorkflowError(
                "Node result references unknown outbound edge decisions",
                details={"node_id": node_id, "decision_keys": unknown_decisions},
            )

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
                attempt_id=1,
                node_id=node_id,
                input_data={"state_snapshot_keys": input_state_keys},
                input_state_version=input_state_version,
                input_state_hash=input_state_hash,
                llm_events=result.llm_events,
                tool_events=result.tool_events,
                artifacts=result.artifacts,
                edge_decisions=result.edge_decisions,
                metrics=result.metrics,
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
    ) -> bool | None:
        decisions = result.edge_decisions
        if edge.decision_key in decisions:
            matched_decisions.add(edge.decision_key)
            return decisions[edge.decision_key]

        if edge.target not in decisions:
            return None
        if target_counts.get(edge.target, 0) > 1:
            raise WorkflowError(
                "Explicit edge decisions by target are ambiguous for duplicate targets",
                details={"target": edge.target, "decision_key": edge.decision_key},
            )
        matched_decisions.add(edge.target)
        return decisions[edge.target]
