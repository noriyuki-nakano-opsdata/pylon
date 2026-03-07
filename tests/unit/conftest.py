"""Unit test conftest — isolated fixtures with auto-cleanup."""

from __future__ import annotations

from typing import Any

import pytest

from pylon.types import AgentConfig, AgentState, AutonomyLevel, SandboxTier
from pylon.workflow.graph import END, WorkflowGraph
from pylon.types import ConditionalEdge


@pytest.fixture
def mock_agent_config() -> AgentConfig:
    return AgentConfig(
        name="test-agent",
        model="test/mock-model",
        role="tester",
        autonomy=AutonomyLevel.A2,
        sandbox=SandboxTier.DOCKER,
    )


@pytest.fixture
def simple_graph() -> WorkflowGraph:
    """A -> B -> END linear graph."""
    g = WorkflowGraph(name="simple")
    g.add_node("a", "agent-a")
    g.add_node("b", "agent-b")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    return g


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Auto-cleanup: reset global singletons between tests."""
    yield
    try:
        from pylon.config.registry import reset_registry
        reset_registry()
    except ImportError:
        pass
