"""Compiled workflow graph structures."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.types import WorkflowJoinPolicy, WorkflowNodeType
from pylon.workflow.conditions import CompiledCondition

EdgeKey = tuple[str, int]


@dataclass(frozen=True)
class CompiledEdge:
    """Stable edge representation used by the executor."""

    key: EdgeKey
    source: str
    target: str
    condition: str | None = None
    predicate: CompiledCondition | None = None

    @property
    def decision_key(self) -> str:
        """Stable serialized identifier for explicit edge decisions."""
        return f"{self.key[0]}:{self.key[1]}"

    def evaluate(self, state: dict[str, object]) -> bool:
        """Evaluate the edge condition against the current workflow state."""
        if self.predicate is None:
            return self.condition is None
        return self.predicate.evaluate(state)


@dataclass(frozen=True)
class CompiledNode:
    """Stable node representation used by the executor."""

    node_id: str
    agent: str
    node_type: WorkflowNodeType
    join_policy: WorkflowJoinPolicy
    inbound_edge_keys: tuple[EdgeKey, ...]
    outbound_edges: tuple[CompiledEdge, ...]


@dataclass(frozen=True)
class CompiledWorkflow:
    """Validated and normalized workflow graph."""

    name: str
    nodes: dict[str, CompiledNode]
    entry_nodes: tuple[str, ...]

    def get_outbound_edges(self, node_id: str) -> tuple[CompiledEdge, ...]:
        return self.nodes[node_id].outbound_edges

    def get_inbound_edges(self, node_id: str) -> tuple[EdgeKey, ...]:
        return self.nodes[node_id].inbound_edge_keys
