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
from pylon.workflow.compiled import CompiledEdge, CompiledNode, CompiledWorkflow

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
                )
                for edge_key, edge in self.get_outbound_edges(node_id)
            )
            compiled_nodes[node_id] = CompiledNode(
                node_id=node_id,
                agent=node.agent,
                node_type=node.node_type,
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
                if _safe_eval_condition(edge.condition, state):
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


_COMPARE_OPS: dict[type, Any] = {
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

_BOOL_OPS: dict[type, Any] = {
    ast.And: all,
    ast.Or: any,
}

_UNARY_OPS: dict[type, Any] = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
}


def _safe_eval_condition(condition: str, state: dict[str, Any]) -> bool:
    """Evaluate a condition string safely using AST-based whitelisting.

    Allowed constructs: comparisons, boolean logic (and/or/not), attribute
    access on ``state``, and literals (str, int, float, bool, None).
    """
    if not condition or not condition.strip():
        return False

    try:
        tree = ast.parse(condition.strip(), mode="eval")
    except SyntaxError as exc:
        raise WorkflowError(f"Invalid condition syntax: {condition}") from exc

    try:
        return bool(_eval_node(tree.body, state))
    except AttributeError as exc:
        raise WorkflowError(f"Condition references missing state field: {exc}") from exc


def _eval_node(node: ast.AST, state: dict[str, Any]) -> Any:  # noqa: PLR0911
    """Recursively evaluate a whitelisted AST node."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, state)

    # Literals: numbers, strings, booleans, None
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool, type(None))):
            raise WorkflowError(f"Unsupported literal type: {type(node.value).__name__}")
        return node.value

    # Attribute access: only state.xxx
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id != "state":
            raise WorkflowError(
                f"Attribute access only allowed on 'state', got: {ast.dump(node.value)}"
            )
        dot = _DotDict(state)
        return getattr(dot, node.attr)

    # Name: only 'state' itself (for nested attribute chains the leaf resolves here)
    if isinstance(node, ast.Name):
        if node.id == "state":
            return _DotDict(state)
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        raise WorkflowError(f"Unsupported name: '{node.id}'")

    # Comparisons: ==, !=, <, >, <=, >=, in, not in, is, is not
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, state)
        for op_node, comparator in zip(node.ops, node.comparators):
            op_func = _COMPARE_OPS.get(type(op_node))
            if op_func is None:
                raise WorkflowError(f"Unsupported comparison: {type(op_node).__name__}")
            right = _eval_node(comparator, state)
            if not op_func(left, right):
                return False
            left = right
        return True

    # Boolean: and, or
    if isinstance(node, ast.BoolOp):
        op_func = _BOOL_OPS.get(type(node.op))
        if op_func is None:
            raise WorkflowError(f"Unsupported boolean op: {type(node.op).__name__}")
        values = [_eval_node(v, state) for v in node.values]
        return op_func(values)

    # Unary: not, - (negative numbers)
    if isinstance(node, ast.UnaryOp):
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise WorkflowError(f"Unsupported unary op: {type(node.op).__name__}")
        return op_func(_eval_node(node.operand, state))

    raise WorkflowError(
        f"Unsupported expression node: {type(node).__name__}"
    )


class _DotDict:
    """Dict wrapper allowing dot notation access for condition evaluation."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(key) from None
