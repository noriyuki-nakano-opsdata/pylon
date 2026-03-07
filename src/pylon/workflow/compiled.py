"""Compiled workflow graph structures."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.types import WorkflowNodeType

EdgeKey = tuple[str, int]


@dataclass(frozen=True)
class CompiledEdge:
    """Stable edge representation used by the executor."""

    key: EdgeKey
    source: str
    target: str
    condition: str | None = None


@dataclass(frozen=True)
class CompiledNode:
    """Stable node representation used by the executor."""

    node_id: str
    agent: str
    node_type: WorkflowNodeType
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
