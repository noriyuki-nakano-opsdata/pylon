"""Planning helpers for queued or distributed workflow execution modes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from pylon.control_plane.scheduler import WorkflowScheduler, WorkflowTask
from pylon.dsl.parser import PylonProject
from pylon.runtime.execution import compile_project_graph
from pylon.types import WorkflowJoinPolicy, WorkflowNodeType
from pylon.workflow.compiled import CompiledEdge, CompiledWorkflow


@dataclass(frozen=True)
class WorkflowDispatchTask:
    """Read model for a workflow task in a dispatch plan."""

    task_id: str
    node_id: str
    wave_index: int
    depends_on: tuple[str, ...]
    dependency_task_ids: tuple[str, ...]
    node_type: WorkflowNodeType
    join_policy: WorkflowJoinPolicy
    conditional_inbound: bool
    conditional_outbound: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "node_id": self.node_id,
            "wave_index": self.wave_index,
            "depends_on": list(self.depends_on),
            "dependency_task_ids": list(self.dependency_task_ids),
            "node_type": self.node_type.value,
            "join_policy": self.join_policy.value,
            "conditional_inbound": self.conditional_inbound,
            "conditional_outbound": self.conditional_outbound,
        }


@dataclass(frozen=True)
class WorkflowDispatchPlan:
    """Dispatch planning view derived from a compiled workflow."""

    workflow_id: str
    tenant_id: str
    execution_mode: str
    entry_nodes: tuple[str, ...]
    tasks: tuple[WorkflowDispatchTask, ...]
    waves: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "execution_mode": self.execution_mode,
            "entry_nodes": list(self.entry_nodes),
            "task_count": len(self.tasks),
            "wave_count": len(self.waves),
            "waves": [
                {
                    "index": index,
                    "node_ids": list(node_ids),
                    "task_ids": [
                        _task_id_for(self.workflow_id, node_id) for node_id in node_ids
                    ],
                }
                for index, node_ids in enumerate(self.waves)
            ],
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _task_id_for(workflow_id: str, node_id: str) -> str:
    return f"{workflow_id}:{node_id}"


def _edge_catalog(compiled: CompiledWorkflow) -> dict[tuple[str, int], CompiledEdge]:
    return {
        edge.key: edge
        for node in compiled.nodes.values()
        for edge in node.outbound_edges
    }


def build_dispatch_plan(
    compiled: CompiledWorkflow,
    *,
    workflow_id: str,
    tenant_id: str = "default",
) -> WorkflowDispatchPlan:
    """Build a dependency-wave plan from a compiled workflow.

    This does not replace inline execution. It projects the deterministic DAG
    into a scheduler-friendly planning view for queued or distributed runners.
    """

    edge_catalog = _edge_catalog(compiled)
    scheduler = WorkflowScheduler()
    tasks_by_node: dict[str, WorkflowTask] = {}

    for node_index, node_id in enumerate(compiled.nodes):
        node = compiled.nodes[node_id]
        dependency_nodes = tuple(
            sorted({edge_key[0] for edge_key in node.inbound_edge_keys})
        )
        task = WorkflowTask(
            id=_task_id_for(workflow_id, node_id),
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            priority=5,
            dependencies={_task_id_for(workflow_id, source) for source in dependency_nodes},
        )
        # Preserve graph order as a deterministic tie-breaker inside waves.
        task.created_at = task.created_at + timedelta(microseconds=node_index)
        scheduler.enqueue(task)
        tasks_by_node[node_id] = task

    computed_waves = scheduler.compute_waves()
    node_waves = tuple(
        tuple(task.id.split(":", 1)[1] for task in wave)
        for wave in computed_waves
    )
    wave_index_by_node = {
        node_id: wave_index
        for wave_index, wave in enumerate(node_waves)
        for node_id in wave
    }

    dispatch_tasks: list[WorkflowDispatchTask] = []
    for node_id, node in compiled.nodes.items():
        inbound_edges = tuple(
            edge_catalog[key]
            for key in node.inbound_edge_keys
            if key in edge_catalog
        )
        dispatch_tasks.append(
            WorkflowDispatchTask(
                task_id=_task_id_for(workflow_id, node_id),
                node_id=node_id,
                wave_index=wave_index_by_node[node_id],
                depends_on=tuple(sorted({edge.source for edge in inbound_edges})),
                dependency_task_ids=tuple(
                    sorted({_task_id_for(workflow_id, edge.source) for edge in inbound_edges})
                ),
                node_type=node.node_type,
                join_policy=node.join_policy,
                conditional_inbound=any(edge.condition is not None for edge in inbound_edges),
                conditional_outbound=any(
                    edge.condition is not None for edge in node.outbound_edges
                ),
            )
        )

    return WorkflowDispatchPlan(
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        execution_mode="distributed_wave_plan",
        entry_nodes=compiled.entry_nodes,
        tasks=tuple(dispatch_tasks),
        waves=node_waves,
    )


def plan_project_dispatch(
    project: PylonProject,
    *,
    workflow_id: str = "default",
    tenant_id: str = "default",
) -> WorkflowDispatchPlan:
    """Compile a project and derive its dispatch plan."""

    compiled = compile_project_graph(project).compile()
    return build_dispatch_plan(
        compiled,
        workflow_id=workflow_id,
        tenant_id=tenant_id,
    )
