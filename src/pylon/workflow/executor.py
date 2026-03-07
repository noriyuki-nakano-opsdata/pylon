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
from pylon.workflow.compiled import CompiledWorkflow
from pylon.workflow.graph import END, WorkflowGraph, _safe_eval_condition

NodeHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


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
                    run.pause("max_steps_exceeded")
                    return run

                ctx._step_count += 1
                for node_id in current_nodes:
                    ctx.node_status[node_id] = "running"

                results = await self._execute_superstep(ctx, current_nodes)
                self._detect_state_conflicts(results)

                for node_id, result in results.items():
                    ctx.state.update(result)
                    ctx.node_status[node_id] = "succeeded"
                    run.event_log.append({
                        "step": ctx._step_count,
                        "node_id": node_id,
                        "agent": compiled.nodes[node_id].agent,
                        "output": result,
                        "timestamp": datetime.now(UTC).isoformat(),
                    })

                await self._checkpoint(ctx, results)

                for node_id in current_nodes:
                    self._resolve_outbound_edges(ctx, node_id)

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
            run.complete()

        except Exception as e:
            run.fail(str(e))
            raise WorkflowError(
                f"Workflow execution failed at step {ctx._step_count}: {e}"
            ) from e

        return run

    async def _execute_superstep(
        self, ctx: ExecutionContext, node_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Execute multiple nodes in parallel (fan-out)."""
        if not ctx.node_handler:
            raise WorkflowError("No node_handler provided")

        async def run_node(node_id: str) -> tuple[str, dict[str, Any]]:
            result = await ctx.node_handler(node_id, dict(ctx.state))
            return node_id, result

        tasks = [run_node(node_id) for node_id in node_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, dict[str, Any]] = {}
        for item in completed:
            if isinstance(item, Exception):
                raise item
            node_id, result = item
            results[node_id] = result

        return results

    def _detect_state_conflicts(self, results: dict[str, dict[str, Any]]) -> None:
        owners: dict[str, str] = {}
        conflicts: dict[str, set[str]] = {}

        for node_id, result in results.items():
            for key in result:
                owner = owners.get(key)
                if owner is None:
                    owners[key] = node_id
                    continue
                conflicts.setdefault(key, {owner})
                conflicts[key].add(node_id)

        if conflicts:
            details = ", ".join(
                f"{key}={sorted(nodes)}" for key, nodes in sorted(conflicts.items())
            )
            raise WorkflowError(f"State conflict detected for keys: {details}")

    def _resolve_outbound_edges(self, ctx: ExecutionContext, node_id: str) -> None:
        for edge_key, edge in ctx.outbound_edges.get(node_id, []):
            taken = edge.condition is None
            if edge.condition is not None:
                taken = _safe_eval_condition(edge.condition, ctx.state)
            ctx.edge_status[edge_key] = "taken" if taken else "not_taken"

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
                if any(state == "pending" for state in inbound_statuses):
                    continue

                if any(state == "taken" for state in inbound_statuses):
                    ctx.node_status[node_id] = "runnable"
                    changed = True
                    continue

                ctx.node_status[node_id] = "skipped"
                for edge_key, edge in ctx.outbound_edges.get(node_id, []):
                    if edge.target != END and ctx.edge_status[edge_key] == "pending":
                        ctx.edge_status[edge_key] = "not_taken"
                changed = True

        return [node_id for node_id, status in ctx.node_status.items() if status == "runnable"]

    async def _checkpoint(
        self,
        ctx: ExecutionContext,
        results: dict[str, dict[str, Any]],
    ) -> None:
        """Create node-scoped checkpoints after completion."""
        for node_id, result in results.items():
            checkpoint = Checkpoint(
                workflow_run_id=ctx.run.id,
                node_id=node_id,
            )
            checkpoint.add_event(
                node_id=node_id,
                input_data={"state_snapshot_keys": list(ctx.state.keys())},
                output_data=result,
            )
            await self._checkpoint_repo.create(checkpoint)

    async def replay(
        self,
        graph: WorkflowGraph,
        run: WorkflowRun,
        node_handler: NodeHandler,
    ) -> WorkflowRun:
        """Replay a workflow from its event log."""
        replay_state: dict[str, Any] = {}

        for event in run.event_log:
            output = event.get("output", {})
            replay_state.update(output)

        run.state = replay_state
        return run
