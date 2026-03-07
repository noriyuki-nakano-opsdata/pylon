"""Workflow Graph Executor — Pregel-style superstep execution (FR-03, ADR-001).

Executes workflow graphs with:
- Fan-out/fan-in parallel node execution (asyncio.gather)
- Conditional edge evaluation
- Event log capture (LLM responses + tool results)
- Checkpoint at each node completion
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.errors import WorkflowError
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.workflow import WorkflowRun
from pylon.workflow.graph import WorkflowGraph

# Type alias for node execution functions
NodeHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ExecutionContext:
    """Context for a single workflow execution."""

    graph: WorkflowGraph
    run: WorkflowRun
    state: dict[str, Any] = field(default_factory=dict)
    node_handler: NodeHandler | None = None
    checkpoint_repo: CheckpointRepository | None = None
    max_steps: int = 100
    _step_count: int = 0


class GraphExecutor:
    """Pregel-style superstep executor for workflow graphs.

    Each superstep:
    1. Identify ready nodes (entry points or nodes whose predecessors completed)
    2. Execute ready nodes in parallel (fan-out)
    3. Capture results in event log
    4. Evaluate conditional edges to determine next nodes
    5. Checkpoint state
    6. Repeat until all paths reach END
    """

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
        """Execute a workflow graph from start to completion.

        Args:
            graph: Validated workflow graph
            run: WorkflowRun to track execution
            node_handler: async function(node_id, state) -> result_dict
            initial_state: Initial state dict
            max_steps: Max supersteps to prevent infinite loops

        Returns:
            Updated WorkflowRun with final state and event log
        """
        graph.validate()

        ctx = ExecutionContext(
            graph=graph,
            run=run,
            state=initial_state or {},
            node_handler=node_handler,
            checkpoint_repo=self._checkpoint_repo,
            max_steps=max_steps,
        )

        run.start()
        current_nodes = graph.get_entry_nodes()

        try:
            while current_nodes and ctx._step_count < max_steps:
                ctx._step_count += 1

                # Execute current nodes in parallel (fan-out)
                results = await self._execute_superstep(ctx, current_nodes)

                # Merge results into state
                for node_id, result in results.items():
                    ctx.state.update(result)

                # Record in event log
                for node_id, result in results.items():
                    event = {
                        "step": ctx._step_count,
                        "node_id": node_id,
                        "agent": graph.nodes[node_id].agent,
                        "output": result,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    run.event_log.append(event)

                # Checkpoint
                await self._checkpoint(ctx, current_nodes, results)

                # Determine next nodes via conditional edges
                next_nodes: list[str] = []
                for node_id in current_nodes:
                    targets = graph.get_next_nodes(node_id, ctx.state)
                    next_nodes.extend(targets)

                # Deduplicate
                current_nodes = list(dict.fromkeys(next_nodes))

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

        tasks = [run_node(nid) for nid in node_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, dict[str, Any]] = {}
        for item in completed:
            if isinstance(item, Exception):
                raise item
            node_id, result = item
            results[node_id] = result

        return results

    async def _checkpoint(
        self,
        ctx: ExecutionContext,
        node_ids: list[str],
        results: dict[str, dict[str, Any]],
    ) -> None:
        """Create checkpoint after superstep completion."""
        checkpoint = Checkpoint(
            workflow_run_id=ctx.run.id,
            node_id=",".join(node_ids),
        )
        for node_id, result in results.items():
            checkpoint.add_event(
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
        """Replay a workflow from its event log (deterministic replay).

        Re-injects captured LLM responses and tool results instead of
        calling the handler again.
        """
        replay_state: dict[str, Any] = {}

        for event in run.event_log:
            output = event.get("output", {})
            replay_state.update(output)

        run.state = replay_state
        return run
