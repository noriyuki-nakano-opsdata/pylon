"""Workflow graph definition and DAG validation (FR-03, ADR-001).

Graph primitives: Node, Edge, Subgraph, Checkpoint.
Supports conditional transitions and fan-out/fan-in.
"""

from __future__ import annotations

import ast
import operator
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
                    if _safe_eval_condition(edge.condition, state):  # noqa: S307
                        results.append(edge.target)
                except Exception as exc:
                    raise WorkflowError(
                        f"Condition evaluation failed on edge "
                        f"{node_id}->{edge.target}: {exc}",
                    ) from exc
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


_SAFE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _resolve_name(node: ast.AST, state: dict[str, Any]) -> Any:
    """Resolve a dotted name like 'state.foo' from the state dict."""
    if isinstance(node, ast.Attribute):
        parent = _resolve_name(node.value, state)
        if isinstance(parent, dict):
            if node.attr not in parent:
                raise AttributeError(node.attr)
            return parent[node.attr]
        return getattr(parent, node.attr)
    if isinstance(node, ast.Name):
        if node.id == "state":
            return state
        raise WorkflowError(f"Unsafe name in condition: '{node.id}' (only 'state' allowed)")
    if isinstance(node, ast.Constant):
        return node.value
    raise WorkflowError(f"Unsupported AST node in condition: {type(node).__name__}")


def _safe_eval_condition(condition: str, state: dict[str, Any]) -> bool:
    """Safely evaluate a simple comparison condition without eval().

    Supports: state.field == value, state.field > 0, value in state.field, etc.
    """
    try:
        tree = ast.parse(condition, mode="eval")
    except SyntaxError as exc:
        raise WorkflowError(f"Invalid condition syntax: {condition}") from exc

    expr = tree.body

    # Boolean literals
    if isinstance(expr, ast.Constant) and isinstance(expr.value, bool):
        return expr.value

    # Simple name / attribute (truthy check)
    if isinstance(expr, (ast.Name, ast.Attribute)):
        return bool(_resolve_name(expr, state))

    # Comparison: left op right
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1 and len(expr.comparators) == 1:
        op_type = type(expr.ops[0])
        if op_type not in _SAFE_OPS:
            raise WorkflowError(f"Unsupported operator in condition: {type(expr.ops[0]).__name__}")
        left = _resolve_name(expr.left, state)
        right = _resolve_name(expr.comparators[0], state)
        return _SAFE_OPS[op_type](left, right)

    raise WorkflowError(f"Unsupported condition expression: {condition}")
