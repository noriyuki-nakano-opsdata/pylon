"""Workflow graph definition and DAG validation (FR-03, ADR-001)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.errors import WorkflowError
from pylon.types import ConditionalEdge, WorkflowJoinPolicy, WorkflowNode, WorkflowNodeType
from pylon.workflow.compiled import CompiledEdge, CompiledNode, CompiledWorkflow
from pylon.workflow.conditions import compile_condition, safe_eval_condition

END = "END"
EdgeKey = tuple[str, int]


@dataclass
class WorkflowGraph:
    """Executable workflow graph with DAG validation."""

    name: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    _validated: bool = False

    def add_node(
        self,
        node_id: str,
        agent: str,
        *,
        node_type: WorkflowNodeType = WorkflowNodeType.AGENT,
        join_policy: WorkflowJoinPolicy = WorkflowJoinPolicy.ALL_RESOLVED,
        loop_max_iterations: int | None = None,
        loop_criterion: str | None = None,
        loop_threshold: float | None = None,
        loop_metadata: dict[str, Any] | None = None,
        next_nodes: list[ConditionalEdge] | None = None,
    ) -> WorkflowGraph:
        if node_id == END:
            raise WorkflowError(f"'{END}' is reserved and cannot be used as node ID")
        if node_id in self.nodes:
            raise WorkflowError(f"Duplicate node ID: {node_id}")
        self.nodes[node_id] = WorkflowNode(
            id=node_id,
            agent=agent,
            node_type=node_type,
            join_policy=join_policy,
            loop_max_iterations=loop_max_iterations,
            loop_criterion=loop_criterion,
            loop_threshold=loop_threshold,
            loop_metadata=dict(loop_metadata or {}),
            next=next_nodes or [],
        )
        self._validated = False
        return self

    def add_edge(
        self,
        from_node: str,
        to_node: str,
        *,
        condition: str | None = None,
    ) -> WorkflowGraph:
        if from_node not in self.nodes:
            raise WorkflowError(f"Source node not found: {from_node}")
        if to_node != END and to_node not in self.nodes:
            raise WorkflowError(f"Target node not found: {to_node}")
        self.nodes[from_node].next.append(
            ConditionalEdge(target=to_node, condition=condition)
        )
        self._validated = False
        return self

    def validate(self) -> list[str]:
        """Validate graph structure. Returns list of warnings."""
        warnings: list[str] = []

        if not self.nodes:
            raise WorkflowError("Workflow graph has no nodes")

        # Check all edge targets exist
        for node_id, node in self.nodes.items():
            for edge in node.next:
                if edge.target != END and edge.target not in self.nodes:
                    raise WorkflowError(
                        f"Node '{node_id}' references undefined target '{edge.target}'"
                    )

        # Check for entry points (nodes not targeted by any edge)
        targeted = set()
        for node in self.nodes.values():
            for edge in node.next:
                if edge.target != END:
                    targeted.add(edge.target)

        entry_points = set(self.nodes.keys()) - targeted
        if not entry_points:
            raise WorkflowError("No entry point found (possible cycle without entry)")
        if len(entry_points) > 1:
            warnings.append(f"Multiple entry points: {entry_points}")

        # Check all nodes can reach END
        can_reach_end = set()
        for node_id, node in self.nodes.items():
            for edge in node.next:
                if edge.target == END:
                    can_reach_end.add(node_id)

        changed = True
        while changed:
            changed = False
            for node_id, node in self.nodes.items():
                if node_id in can_reach_end:
                    continue
                for edge in node.next:
                    if edge.target in can_reach_end:
                        can_reach_end.add(node_id)
                        changed = True
                        break

        unreachable = set(self.nodes.keys()) - can_reach_end
        if unreachable:
            warnings.append(f"Nodes that cannot reach END: {unreachable}")

        inbound = self.get_inbound_edges()
        for node_id, node in self.nodes.items():
            inbound_count = len(inbound.get(node_id, []))
            if node.node_type == WorkflowNodeType.LOOP:
                if node.loop_max_iterations is None or node.loop_max_iterations < 1:
                    raise WorkflowError(
                        "Loop nodes require loop_max_iterations >= 1",
                        details={"node_id": node_id},
                    )
                if not node.loop_criterion:
                    raise WorkflowError(
                        "Loop nodes require loop_criterion",
                        details={"node_id": node_id},
                    )
                if node.join_policy != WorkflowJoinPolicy.ALL_RESOLVED:
                    raise WorkflowError(
                        "Loop nodes only support join_policy=all_resolved",
                        details={"node_id": node_id, "join_policy": node.join_policy.value},
                    )
            if node.join_policy == WorkflowJoinPolicy.ALL_RESOLVED:
                continue
            if inbound_count < 2:
                raise WorkflowError(
                    f"Join policy '{node.join_policy.value}' requires at least two inbound edges",
                    details={"node_id": node_id, "inbound_edges": inbound_count},
                )
            if node.node_type != WorkflowNodeType.ROUTER:
                raise WorkflowError(
                    f"Join policy '{node.join_policy.value}' requires node_type=router",
                    details={"node_id": node_id, "node_type": node.node_type.value},
                )

        # Simple cycle detection via DFS
        self._detect_cycles()

        self._validated = True
        return warnings

    def get_entry_nodes(self) -> list[str]:
        """Get nodes that are not targeted by any edge (entry points)."""
        targeted = set()
        for node in self.nodes.values():
            for edge in node.next:
                if edge.target != END:
                    targeted.add(edge.target)
        return [nid for nid in self.nodes if nid not in targeted]

    def get_outbound_edges(self, node_id: str) -> list[tuple[EdgeKey, ConditionalEdge]]:
        """Return outbound edges with stable keys scoped to the source node."""
        if node_id not in self.nodes:
            raise WorkflowError(f"Node not found: {node_id}")
        return [((node_id, index), edge) for index, edge in enumerate(self.nodes[node_id].next)]

    def get_inbound_edges(self) -> dict[str, list[EdgeKey]]:
        """Return inbound edges grouped by target node."""
        inbound: dict[str, list[EdgeKey]] = {node_id: [] for node_id in self.nodes}
        for node_id in self.nodes:
            for edge_key, edge in self.get_outbound_edges(node_id):
                if edge.target != END:
                    inbound.setdefault(edge.target, []).append(edge_key)
        return inbound

    def compile(self) -> CompiledWorkflow:
        """Validate and compile the graph into stable execution structures."""
        self.validate()

        inbound = self.get_inbound_edges()
        compiled_nodes: dict[str, CompiledNode] = {}
        for node_id, node in self.nodes.items():
            outbound_edges = tuple(
                CompiledEdge(
                    key=edge_key,
                    source=node_id,
                    target=edge.target,
                    condition=edge.condition,
                    predicate=compile_condition(edge.condition),
                )
                for edge_key, edge in self.get_outbound_edges(node_id)
            )
            compiled_nodes[node_id] = CompiledNode(
                node_id=node_id,
                agent=node.agent,
                node_type=node.node_type,
                join_policy=node.join_policy,
                loop_max_iterations=node.loop_max_iterations,
                loop_criterion=node.loop_criterion,
                loop_threshold=node.loop_threshold,
                loop_metadata=dict(node.loop_metadata),
                inbound_edge_keys=tuple(inbound.get(node_id, [])),
                outbound_edges=outbound_edges,
            )

        return CompiledWorkflow(
            name=self.name,
            nodes=compiled_nodes,
            entry_nodes=tuple(self.get_entry_nodes()),
        )

    def get_next_nodes(self, node_id: str, state: dict[str, Any] | None = None) -> list[str]:
        """Get next node IDs based on conditions and state."""
        if node_id not in self.nodes:
            raise WorkflowError(f"Node not found: {node_id}")

        node = self.nodes[node_id]
        if not node.next:
            return []

        results = []
        for edge in node.next:
            if edge.target == END:
                continue
            if edge.condition is None:
                results.append(edge.target)
            elif state is not None:
                if safe_eval_condition(edge.condition, state):
                    results.append(edge.target)
        return results

    def _detect_cycles(self) -> None:
        """Detect cycles using DFS."""
        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node_id: str) -> None:
            visited.add(node_id)
            in_stack.add(node_id)
            for edge in self.nodes[node_id].next:
                if edge.target == END:
                    continue
                if edge.target in in_stack:
                    raise WorkflowError(f"Cycle detected involving node '{edge.target}'")
                if edge.target not in visited:
                    dfs(edge.target)
            in_stack.remove(node_id)

        for node_id in self.nodes:
            if node_id not in visited:
                dfs(node_id)

_safe_eval_condition = safe_eval_condition
