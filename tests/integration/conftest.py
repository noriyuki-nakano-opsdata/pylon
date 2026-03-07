"""Integration test conftest -- full-stack fixtures."""

from __future__ import annotations

import pytest

from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.memory import MemoryRepository
from pylon.repository.workflow import WorkflowRepository
from pylon.workflow.graph import END, WorkflowGraph


@pytest.fixture
def full_repos():
    """All four repositories as a dict."""
    return {
        "checkpoint": CheckpointRepository(),
        "workflow": WorkflowRepository(),
        "audit": AuditRepository(hmac_key=b"test-key-at-least-16-bytes"),
        "memory": MemoryRepository(),
    }


@pytest.fixture
def linear_graph() -> WorkflowGraph:
    """A -> B -> C -> END."""
    g = WorkflowGraph(name="linear")
    g.add_node("a", "agent-a")
    g.add_node("b", "agent-b")
    g.add_node("c", "agent-c")
    g.add_edge("a", "b").add_edge("b", "c").add_edge("c", END)
    return g


@pytest.fixture
def conditional_graph() -> WorkflowGraph:
    """A -> B (if approved) or C (default) -> END."""
    g = WorkflowGraph(name="conditional")
    g.add_node("a", "agent-a")
    g.add_node("b", "agent-b")
    g.add_node("c", "agent-c")
    g.add_edge("a", "b", condition="state.approved == True")
    g.add_edge("a", "c")
    g.add_edge("b", END).add_edge("c", END)
    return g


@pytest.fixture
def fanout_graph() -> WorkflowGraph:
    """A -> [B, C] -> D -> END (fan-out / fan-in)."""
    g = WorkflowGraph(name="fanout")
    g.add_node("a", "agent-a")
    g.add_node("b", "agent-b")
    g.add_node("c", "agent-c")
    g.add_node("d", "agent-d")
    g.add_edge("a", "b").add_edge("a", "c")
    g.add_edge("b", "d").add_edge("c", "d")
    g.add_edge("d", END)
    return g
