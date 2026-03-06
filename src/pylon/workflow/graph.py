"""Workflow graph definition and DAG validation (FR-03, ADR-001).

Graph primitives: Node, Edge, Subgraph, Checkpoint.
Supports conditional transitions and fan-out/fan-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.errors import WorkflowError
from pylon.types import ConditionalEdge, WorkflowNode, WorkflowNodeType


END = "END"


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
                try:
                    if eval(edge.condition, {"__builtins__": {}}, {"state": _DotDict(state)}):  # noqa: S307
                        results.append(edge.target)
                except Exception:
                    pass
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


class _DotDict:
    """Dict wrapper allowing dot notation access for condition evaluation."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(key) from None
