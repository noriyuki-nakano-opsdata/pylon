"""Tests for workflow graph engine."""

import pytest

from pylon.errors import WorkflowError
from pylon.types import ConditionalEdge, WorkflowJoinPolicy, WorkflowNodeType
from pylon.workflow.conditions import compile_condition, safe_eval_condition
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

    def test_compile_returns_stable_execution_structures(self):
        g = WorkflowGraph(name="compiled")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="state.needs_review > 0"),
            ConditionalEdge(target="audit"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("audit", "auditor", next_nodes=[ConditionalEdge(target=END)])

        compiled = g.compile()
        review_edge = compiled.get_outbound_edges("start")[0]

        assert compiled.entry_nodes == ("start",)
        assert compiled.nodes["start"].agent == "planner"
        assert {edge.target for edge in compiled.get_outbound_edges("start")} == {"review", "audit"}
        assert len(compiled.get_inbound_edges("review")) == 1
        assert review_edge.condition == "state.needs_review > 0"
        assert review_edge.predicate is not None
        assert review_edge.evaluate({"needs_review": 1}) is True
        assert review_edge.evaluate({"needs_review": 0}) is False

    def test_compile_rejects_invalid_condition(self):
        g = WorkflowGraph(name="compiled")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="__import__('os')"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        with pytest.raises(WorkflowError, match="Unsupported"):
            g.compile()

    def test_validate_rejects_any_join_on_non_router(self):
        g = WorkflowGraph(name="join-policy")
        g.add_node("left", "agent", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("right", "agent", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "agent",
            join_policy=WorkflowJoinPolicy.ANY,
            next_nodes=[ConditionalEdge(target=END)],
        )

        with pytest.raises(WorkflowError, match="node_type=router"):
            g.validate()

    def test_validate_rejects_any_join_with_single_inbound(self):
        g = WorkflowGraph(name="join-policy")
        g.add_node("start", "agent", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "router",
            node_type=WorkflowNodeType.ROUTER,
            join_policy=WorkflowJoinPolicy.ANY,
            next_nodes=[ConditionalEdge(target=END)],
        )

        with pytest.raises(WorkflowError, match="at least two inbound edges"):
            g.validate()

    def test_validate_rejects_loop_node_without_loop_configuration(self):
        g = WorkflowGraph(name="loop-node")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            next_nodes=[ConditionalEdge(target=END)],
        )

        with pytest.raises(WorkflowError, match="loop_max_iterations"):
            g.validate()

    def test_compile_preserves_loop_node_configuration(self):
        g = WorkflowGraph(name="loop-node")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=3,
            loop_criterion="response_quality",
            loop_threshold=0.8,
            next_nodes=[ConditionalEdge(target=END)],
        )

        compiled = g.compile()

        assert compiled.nodes["draft"].node_type == WorkflowNodeType.LOOP
        assert compiled.nodes["draft"].loop_max_iterations == 3
        assert compiled.nodes["draft"].loop_criterion == "response_quality"
        assert compiled.nodes["draft"].loop_threshold == 0.8


class TestSafeConditionEvaluator:
    """Tests for the AST-based safe condition evaluator replacing eval()."""

    # -- Valid conditions --

    def test_equality(self):
        assert safe_eval_condition('state.status == "done"', {"status": "done"}) is True
        assert safe_eval_condition('state.status == "done"', {"status": "pending"}) is False

    def test_numeric_comparison(self):
        assert safe_eval_condition("state.count > 0", {"count": 5}) is True
        assert safe_eval_condition("state.count > 0", {"count": 0}) is False
        assert safe_eval_condition("state.count <= 10", {"count": 10}) is True

    def test_boolean_and(self):
        assert safe_eval_condition(
            "state.x and state.y", {"x": True, "y": True}
        ) is True
        assert safe_eval_condition(
            "state.x and state.y", {"x": True, "y": False}
        ) is False

    def test_boolean_or(self):
        assert safe_eval_condition(
            "state.x or state.y", {"x": False, "y": True}
        ) is True
        assert safe_eval_condition(
            "state.x or state.y", {"x": False, "y": False}
        ) is False

    def test_not(self):
        assert safe_eval_condition("not state.flag", {"flag": False}) is True
        assert safe_eval_condition("not state.flag", {"flag": True}) is False

    def test_none_comparison(self):
        assert safe_eval_condition("state.val is None", {"val": None}) is True
        assert safe_eval_condition("state.val is not None", {"val": 42}) is True

    def test_chained_comparison(self):
        assert safe_eval_condition("0 < state.x < 10", {"x": 5}) is True
        assert safe_eval_condition("0 < state.x < 10", {"x": 15}) is False

    def test_negative_number(self):
        assert safe_eval_condition("state.temp < -5", {"temp": -10}) is True

    # -- Empty / whitespace conditions --

    def test_empty_condition(self):
        compiled = compile_condition("   ")
        assert compiled is not None
        assert compiled.evaluate({"x": 1}) is False
        assert safe_eval_condition("", {"x": 1}) is False

    # -- Malicious conditions must be blocked --

    def test_blocks_import(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition("__import__('os').system('id')")

    def test_blocks_dunder_class(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition("().__class__.__bases__[0].__subclasses__()")

    def test_blocks_exec(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition('exec("print(1)")')

    def test_blocks_open(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition('open("/etc/passwd")')

    def test_blocks_lambda(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition("(lambda: 1)()")

    def test_blocks_arbitrary_name(self):
        with pytest.raises(WorkflowError, match="Unsupported name"):
            compile_condition("os")

    def test_blocks_attribute_on_non_state(self):
        with pytest.raises(WorkflowError, match="Attribute access only allowed on 'state'"):
            compile_condition('"".__class__')

    def test_blocks_list_comprehension(self):
        with pytest.raises(WorkflowError, match="Unsupported"):
            compile_condition("[x for x in range(10)]")

    # -- Integration: used via get_next_nodes --

    def test_get_next_nodes_safe_condition(self):
        g = WorkflowGraph(name="test")
        g.add_node("a", "agent", next_nodes=[
            ConditionalEdge(target="b", condition='state.status == "ready"'),
        ])
        g.add_node("b", "agent", next_nodes=[ConditionalEdge(target=END)])
        g.validate()

        assert g.get_next_nodes("a", {"status": "ready"}) == ["b"]
        assert g.get_next_nodes("a", {"status": "blocked"}) == []

    def test_get_next_nodes_malicious_condition_raises(self):
        """Malicious conditions should fail deterministically."""
        g = WorkflowGraph(name="test")
        g.add_node("a", "agent", next_nodes=[
            ConditionalEdge(target="b", condition="__import__('os')"),
        ])
        g.add_node("b", "agent", next_nodes=[ConditionalEdge(target=END)])
        g.validate()

        with pytest.raises(WorkflowError, match="Unsupported"):
            g.get_next_nodes("a", {"x": 1})

    def test_get_next_nodes_missing_state_field_raises(self):
        """Missing state field should fail deterministically."""
        g = WorkflowGraph(name="test")
        g.add_node("a", "agent", next_nodes=[
            ConditionalEdge(target="b", condition="state.missing > 0"),
        ])
        g.add_node("b", "agent", next_nodes=[ConditionalEdge(target=END)])
        g.validate()

        with pytest.raises(WorkflowError, match="missing"):
            g.get_next_nodes("a", {"x": 1})
