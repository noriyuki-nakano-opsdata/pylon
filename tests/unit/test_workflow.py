"""Tests for workflow graph engine."""

import pytest

from pylon.errors import WorkflowError
from pylon.types import ConditionalEdge
from pylon.workflow.graph import END, WorkflowGraph


class TestWorkflowGraph:
    def test_simple_linear_graph(self):
        g = WorkflowGraph(name="test")
        g.add_node("step1", "agent1", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent2", next_nodes=[ConditionalEdge(target=END)])
        warnings = g.validate()
        assert len(warnings) == 0

    def test_entry_points(self):
        g = WorkflowGraph(name="test")
        g.add_node("step1", "agent1", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent2", next_nodes=[ConditionalEdge(target=END)])
        assert g.get_entry_nodes() == ["step1"]

    def test_conditional_branching(self):
        g = WorkflowGraph(name="test")
        g.add_node("analyze", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="state.needs_review > 0"),
            ConditionalEdge(target=END, condition="state.needs_review == 0"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])
        warnings = g.validate()
        assert len(warnings) == 0

    def test_get_next_with_condition(self):
        g = WorkflowGraph(name="test")
        g.add_node("analyze", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="state.issues > 0"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])
        g.validate()

        next_nodes = g.get_next_nodes("analyze", {"issues": 5})
        assert next_nodes == ["review"]

        next_nodes = g.get_next_nodes("analyze", {"issues": 0})
        assert next_nodes == []

    def test_cycle_detection(self):
        g = WorkflowGraph(name="test")
        g.add_node("a", "agent1")
        g.add_node("b", "agent2")
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        with pytest.raises(WorkflowError, match="cycle"):
            g.validate()

    def test_empty_graph(self):
        g = WorkflowGraph(name="empty")
        with pytest.raises(WorkflowError, match="no nodes"):
            g.validate()

    def test_duplicate_node(self):
        g = WorkflowGraph(name="test")
        g.add_node("step1", "agent1")
        with pytest.raises(WorkflowError, match="Duplicate"):
            g.add_node("step1", "agent2")

    def test_reserved_end_node(self):
        g = WorkflowGraph(name="test")
        with pytest.raises(WorkflowError, match="reserved"):
            g.add_node(END, "agent1")

    def test_undefined_target(self):
        g = WorkflowGraph(name="test")
        g.add_node("step1", "agent1", next_nodes=[ConditionalEdge(target="nonexistent")])
        with pytest.raises(WorkflowError, match="undefined target"):
            g.validate()

    def test_unreachable_end_warning(self):
        g = WorkflowGraph(name="test")
        g.add_node("step1", "agent1", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent2")  # No path to END
        warnings = g.validate()
        assert any("cannot reach END" in w for w in warnings)

    def test_fan_out(self):
        g = WorkflowGraph(name="test")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="worker1"),
            ConditionalEdge(target="worker2"),
        ])
        g.add_node("worker1", "agent1", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("worker2", "agent2", next_nodes=[ConditionalEdge(target=END)])
        warnings = g.validate()
        assert len(warnings) == 0
