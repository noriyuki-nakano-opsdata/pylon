from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowNode:
    """A single node in a workflow graph."""

    name: str
    agent: str
    handler: Callable[..., Any] | None = None


@dataclass(frozen=True)
class WorkflowEdge:
    """A directed edge between two workflow nodes."""

    source: str
    target: str
    condition: Callable[..., bool] | None = None


@dataclass(frozen=True)
class WorkflowGraph:
    """Immutable representation of a validated workflow graph."""

    name: str
    nodes: dict[str, WorkflowNode]
    edges: list[WorkflowEdge]
    entry_point: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a plain dict representation."""
        return {
            "name": self.name,
            "entry_point": self.entry_point,
            "nodes": {
                n.name: {"agent": n.agent, "has_handler": n.handler is not None}
                for n in self.nodes.values()
            },
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "has_condition": e.condition is not None,
                }
                for e in self.edges
            ],
        }


class WorkflowBuilderError(Exception):
    """Raised when a workflow cannot be built due to validation errors."""


class WorkflowBuilder:
    """Fluent API for constructing workflow graphs.

    Usage::

        graph = (
            WorkflowBuilder("my_workflow")
            .add_node("start", agent="researcher")
            .add_node("finish", agent="writer")
            .add_edge("start", "finish")
            .set_entry("start")
            .build()
        )
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: list[WorkflowEdge] = []
        self._entry_point: str | None = None

    def add_node(
        self,
        name: str,
        agent: str,
        handler: Callable[..., Any] | None = None,
    ) -> WorkflowBuilder:
        """Add a node to the workflow. Returns self for chaining."""
        if name in self._nodes:
            raise WorkflowBuilderError(f"Duplicate node name: {name!r}")
        self._nodes[name] = WorkflowNode(name=name, agent=agent, handler=handler)
        return self

    def add_edge(
        self,
        source: str,
        target: str,
        condition: Callable[..., bool] | None = None,
    ) -> WorkflowBuilder:
        """Add a directed edge between two nodes. Returns self for chaining."""
        self._edges.append(WorkflowEdge(source=source, target=target, condition=condition))
        return self

    def set_entry(self, node_name: str) -> WorkflowBuilder:
        """Set the entry point node. Returns self for chaining."""
        self._entry_point = node_name
        return self

    def build(self) -> WorkflowGraph:
        """Validate and build the immutable WorkflowGraph.

        Raises WorkflowBuilderError if:
          - No entry point is set
          - Entry point references a non-existent node
          - An edge references a non-existent source or target node
        """
        if self._entry_point is None:
            raise WorkflowBuilderError("No entry point set. Call .set_entry() before .build().")

        if self._entry_point not in self._nodes:
            raise WorkflowBuilderError(
                f"Entry point {self._entry_point!r} does not match any node. "
                f"Available nodes: {list(self._nodes.keys())}"
            )

        node_names = set(self._nodes.keys())
        for edge in self._edges:
            if edge.source not in node_names:
                raise WorkflowBuilderError(
                    f"Edge source {edge.source!r} does not match any node. "
                    f"Available nodes: {list(self._nodes.keys())}"
                )
            if edge.target not in node_names:
                raise WorkflowBuilderError(
                    f"Edge target {edge.target!r} does not match any node. "
                    f"Available nodes: {list(self._nodes.keys())}"
                )

        return WorkflowGraph(
            name=self._name,
            nodes=dict(self._nodes),
            edges=list(self._edges),
            entry_point=self._entry_point,
        )
