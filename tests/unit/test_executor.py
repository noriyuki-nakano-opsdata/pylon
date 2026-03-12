"""Tests for workflow graph executor."""

import pytest

from pylon.approval import ApprovalManager, ApprovalStore
from pylon.autonomy.evaluation import VerificationDisposition
from pylon.autonomy.goals import (
    FailurePolicy,
    GoalConstraints,
    GoalSpec,
    RefinementPolicy,
    RunCompletionPolicy,
    SuccessCriterion,
)
from pylon.autonomy.termination import (
    CostBudget,
    ExternalStop,
    MaxIterations,
    QualityThreshold,
    StuckDetector,
    TokenBudget,
)
from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import CheckpointRepository
from pylon.repository.workflow import RunStatus, WorkflowRun
from pylon.types import ConditionalEdge, RunStopReason, WorkflowJoinPolicy, WorkflowNodeType
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph
from pylon.workflow.result import NodeResult
from pylon.workflow.state import compute_state_hash


async def mock_handler(node_id: str, state: dict) -> dict:
    """Simple mock handler that returns node-specific state."""
    if node_id == "analyze":
        return {"issues_found": 3, "analyzed": True}
    elif node_id == "review":
        return {"reviewed": True, "comments": 5}
    elif node_id == "approve":
        return {"approved": True}
    elif node_id == "worker1":
        return {"worker1_done": True}
    elif node_id == "worker2":
        return {"worker2_done": True}
    return {f"{node_id}_done": True}


class TestGraphExecutor:
    @pytest.fixture
    def executor(self):
        return GraphExecutor()

    @pytest.mark.asyncio
    async def test_linear_execution(self, executor):
        g = WorkflowGraph(name="linear")
        g.add_node("analyze", "planner", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("analyzed") is True
        assert len(result.event_log) == 1
        assert result.state_version == 1
        assert result.state_hash != ""

    @pytest.mark.asyncio
    async def test_multi_step_execution(self, executor):
        g = WorkflowGraph(name="multi")
        g.add_node("analyze", "planner", next_nodes=[ConditionalEdge(target="review")])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("analyzed") is True
        assert result.state.get("reviewed") is True
        assert len(result.event_log) == 2

    @pytest.mark.asyncio
    async def test_conditional_branching(self, executor):
        g = WorkflowGraph(name="conditional")
        g.add_node("analyze", "planner", next_nodes=[
            ConditionalEdge(target="review", condition="state.issues_found > 0"),
            ConditionalEdge(target=END, condition="state.issues_found == 0"),
        ])
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler)

        # mock_handler returns issues_found=3, so review should execute
        assert result.state.get("reviewed") is True
        assert len(result.event_log) == 2

    @pytest.mark.asyncio
    async def test_fan_out(self, executor):
        g = WorkflowGraph(name="fanout")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="worker1"),
            ConditionalEdge(target="worker2"),
        ])
        g.add_node("worker1", "agent1", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("worker2", "agent2", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")

        async def fanout_handler(node_id: str, state: dict) -> dict:
            return {f"{node_id}_done": True}

        result = await executor.execute(g, run, fanout_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state.get("worker1_done") is True
        assert result.state.get("worker2_done") is True

    @pytest.mark.asyncio
    async def test_checkpoints_created(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="cp-test")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        await executor.execute(g, run, mock_handler)

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert len(checkpoints) == 2  # One per superstep
        assert [cp.node_id for cp in checkpoints] == ["step1", "step2"]
        assert [cp.event_log[0]["node_id"] for cp in checkpoints] == ["step1", "step2"]
        assert all(cp.state_version > 0 for cp in checkpoints)
        assert all(cp.state_hash for cp in checkpoints)

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, executor):
        """Verify max_steps prevents infinite loops."""
        g = WorkflowGraph(name="limited")
        # Create a long chain
        for i in range(10):
            next_target = f"step{i+1}" if i < 9 else END
            g.add_node(f"step{i}", "agent", next_nodes=[ConditionalEdge(target=next_target)])

        run = WorkflowRun(workflow_id="wf-1")
        result = await executor.execute(g, run, mock_handler, max_steps=5)

        # Should pause after 5 steps even though graph has 10
        assert result.status == RunStatus.PAUSED
        assert len(result.event_log) == 5
        assert "pause_reason" in result.state
        assert result.suspension_reason == RunStopReason.LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_join_node_executes_once_after_all_inbound_edges_resolve(self, executor):
        g = WorkflowGraph(name="join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="fast"),
            ConditionalEdge(target="slow"),
        ])
        g.add_node("fast", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("slow", "agent2", next_nodes=[ConditionalEdge(target="mid")])
        g.add_node("mid", "agent3", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("join", "agent4", next_nodes=[ConditionalEdge(target=END)])

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order == ["start", "fast", "slow", "mid", "join"]
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_parallel_conflicting_writes_fail(self, executor):
        g = WorkflowGraph(name="conflict")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="worker1"),
            ConditionalEdge(target="worker2"),
        ])
        g.add_node("worker1", "agent1", next_nodes=[ConditionalEdge(target=END)])
        g.add_node("worker2", "agent2", next_nodes=[ConditionalEdge(target=END)])

        async def conflicting_handler(node_id: str, state: dict) -> dict:
            if node_id == "start":
                return {"started": True}
            return {"shared": node_id}

        run = WorkflowRun(workflow_id="wf-conflict")
        with pytest.raises(Exception, match="State conflict"):
            await executor.execute(g, run, conflicting_handler)

        assert run.status == RunStatus.FAILED
        assert run.stop_reason == RunStopReason.STATE_CONFLICT

    @pytest.mark.asyncio
    async def test_invalid_condition_fails_run(self, executor):
        g = WorkflowGraph(name="bad-condition")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="next", condition="state.missing > 0"),
        ])
        g.add_node("next", "agent1", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-bad-condition")
        with pytest.raises(Exception, match="missing"):
            await executor.execute(g, run, mock_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_any_join_router_executes_before_all_inbound_edges_resolve(self, executor):
        g = WorkflowGraph(name="any-join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="fast"),
            ConditionalEdge(target="slow"),
        ])
        g.add_node("fast", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("slow", "agent2", next_nodes=[ConditionalEdge(target="mid")])
        g.add_node("mid", "agent3", next_nodes=[ConditionalEdge(target="late")])
        g.add_node("late", "agent4", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "router",
            node_type=WorkflowNodeType.ROUTER,
            join_policy=WorkflowJoinPolicy.ANY,
            next_nodes=[ConditionalEdge(target=END)],
        )

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-any-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order.index("join") < execution_order.index("late")
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_first_join_router_selects_deterministic_winner(self, executor):
        g = WorkflowGraph(name="first-join")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="left"),
            ConditionalEdge(target="right"),
        ])
        g.add_node("left", "agent1", next_nodes=[ConditionalEdge(target="join")])
        g.add_node("right", "agent2", next_nodes=[ConditionalEdge(target="join")])
        g.add_node(
            "join",
            "router",
            node_type=WorkflowNodeType.ROUTER,
            join_policy=WorkflowJoinPolicy.FIRST,
            next_nodes=[ConditionalEdge(target=END)],
        )

        execution_order: list[str] = []

        async def ordered_handler(node_id: str, state: dict) -> dict:
            execution_order.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-first-join")
        result = await executor.execute(g, run, ordered_handler)

        assert result.status == RunStatus.COMPLETED
        assert execution_order == ["start", "left", "right", "join"]
        assert sum(1 for event in result.event_log if event["node_id"] == "join") == 1

    @pytest.mark.asyncio
    async def test_node_result_can_suspend_run_for_approval(self, executor):
        g = WorkflowGraph(name="approval")
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        async def approval_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(
                state_patch={"reviewed": True},
                requires_approval=True,
                approval_request_id="apr-test",
                approval_reason="human sign-off required",
            )

        run = WorkflowRun(workflow_id="wf-approval")
        result = await executor.execute(g, run, approval_handler)

        assert result.status == RunStatus.WAITING_APPROVAL
        assert result.suspension_reason == RunStopReason.APPROVAL_REQUIRED
        assert result.approval_request_id == "apr-test"
        assert result.state["approval_reason"] == "human sign-off required"
        assert result.state["pending_approval_nodes"] == ["review"]

    @pytest.mark.asyncio
    async def test_termination_policy_max_iterations_pauses_run(self, executor):
        g = WorkflowGraph(name="termination-iterations")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-term-iterations")
        result = await executor.execute(
            g,
            run,
            mock_handler,
            termination_policy=MaxIterations(1),
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.LIMIT_EXCEEDED
        assert result.state["runtime_metrics"]["iterations"] == 1

    @pytest.mark.asyncio
    async def test_termination_policy_token_budget_pauses_run(self, executor):
        g = WorkflowGraph(name="termination-tokens")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def token_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(
                state_patch={f"{node_id}_done": True},
                metrics={"token_usage": {"input_tokens": 9, "output_tokens": 4}},
            )

        run = WorkflowRun(workflow_id="wf-term-tokens")
        result = await executor.execute(
            g,
            run,
            token_handler,
            termination_policy=TokenBudget(max_total_tokens=10),
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.TOKEN_BUDGET_EXCEEDED
        assert result.state["runtime_metrics"]["token_usage"]["total_tokens"] == 13

    @pytest.mark.asyncio
    async def test_termination_policy_cost_budget_pauses_run(self, executor):
        g = WorkflowGraph(name="termination-cost")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def cost_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(
                state_patch={f"{node_id}_done": True},
                metrics={"estimated_cost_usd": 0.30},
            )

        run = WorkflowRun(workflow_id="wf-term-cost")
        result = await executor.execute(
            g,
            run,
            cost_handler,
            termination_policy=CostBudget(max_usd=0.25),
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.COST_BUDGET_EXCEEDED
        assert result.state["runtime_metrics"]["estimated_cost_usd"] == pytest.approx(0.30)

    @pytest.mark.asyncio
    async def test_termination_policy_external_stop_pauses_run(self, executor):
        g = WorkflowGraph(name="termination-external")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-term-external")
        result = await executor.execute(
            g,
            run,
            mock_handler,
            termination_policy=ExternalStop(),
            external_stop_requested=True,
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.EXTERNAL_STOP

    @pytest.mark.asyncio
    async def test_goal_spec_constraints_pause_run_without_explicit_policy(self, executor):
        g = WorkflowGraph(name="goal-spec")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        goal = GoalSpec(
            objective="finish quickly",
            constraints=GoalConstraints(max_iterations=1),
        )

        run = WorkflowRun(workflow_id="wf-goal")
        result = await executor.execute(g, run, mock_handler, goal_spec=goal)

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.LIMIT_EXCEEDED
        assert result.state["goal"]["objective"] == "finish quickly"
        assert result.state["autonomy"]["goal"]["objective"] == "finish quickly"
        assert result.state["policy_resolution"]["goal_termination_policy"] == {
            "kind": "max_iterations",
            "max_iterations": 1,
        }
        assert result.state["policy_resolution"]["effective_termination_policy"] == {
            "kind": "max_iterations",
            "max_iterations": 1,
        }
        assert result.state["policy_resolution"]["external_stop_requested"] is False

    @pytest.mark.asyncio
    async def test_goal_spec_can_compose_with_explicit_termination_policy(self, executor):
        g = WorkflowGraph(name="goal-and-explicit")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        goal = GoalSpec(
            objective="bounded by goal",
            constraints=GoalConstraints(max_iterations=10),
        )

        run = WorkflowRun(workflow_id="wf-goal-explicit")
        result = await executor.execute(
            g,
            run,
            mock_handler,
            goal_spec=goal,
            termination_policy=ExternalStop(),
            external_stop_requested=True,
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.EXTERNAL_STOP
        assert result.state["policy_resolution"]["goal_termination_policy"] == {
            "kind": "max_iterations",
            "max_iterations": 10,
        }
        assert result.state["policy_resolution"]["effective_termination_policy"] == {
            "kind": "any",
            "conditions": [
                {"kind": "external_stop"},
                {"kind": "max_iterations", "max_iterations": 10},
            ],
        }
        assert result.state["policy_resolution"]["external_stop_requested"] is True

    @pytest.mark.asyncio
    async def test_runtime_metrics_collect_model_route_history(self, executor):
        g = WorkflowGraph(name="routing-metrics")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(objective="route model")

        async def routed_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(
                state_patch={"done": True},
                metrics={
                    "model_route": {
                        "provider_name": "anthropic",
                        "model_id": "claude-sonnet",
                        "tier": "standard",
                        "reasoning": "tool support required",
                        "cache_strategy": "explicit",
                        "batch_eligible": False,
                    },
                    "estimated_cost_usd": 0.12,
                    "token_usage": {"input_tokens": 20, "output_tokens": 10},
                },
            )

        run = WorkflowRun(workflow_id="wf-routing")
        result = await executor.execute(g, run, routed_handler, goal_spec=goal)

        assert result.status == RunStatus.COMPLETED
        runtime_metrics = result.state["runtime_metrics"]
        assert runtime_metrics["estimated_cost_usd"] == pytest.approx(0.12)
        assert runtime_metrics["token_usage"]["total_tokens"] == 30
        assert runtime_metrics["model_routes"] == [
            {
                "provider_name": "anthropic",
                "model_id": "claude-sonnet",
                "tier": "standard",
                "reasoning": "tool support required",
                "cache_strategy": "explicit",
                "batch_eligible": False,
            }
        ]
        assert result.state["autonomy"]["model_routes"] == runtime_metrics["model_routes"]

    @pytest.mark.asyncio
    async def test_runtime_metrics_do_not_double_count_llm_usage_when_metrics_already_include_it(
        self, executor
    ):
        g = WorkflowGraph(name="routing-double-count")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def routed_handler(node_id: str, state: dict) -> NodeResult:
            del node_id, state
            return NodeResult(
                state_patch={"done": True},
                metrics={
                    "estimated_cost_usd": 0.12,
                    "token_usage": {"input_tokens": 20, "output_tokens": 10},
                },
                llm_events=[
                    {
                        "usage": {"input_tokens": 20, "output_tokens": 10},
                        "estimated_cost_usd": 0.12,
                    }
                ],
            )

        run = WorkflowRun(workflow_id="wf-routing-double-count")
        result = await executor.execute(g, run, routed_handler)

        assert result.state["runtime_metrics"]["estimated_cost_usd"] == pytest.approx(0.12)
        assert result.state["runtime_metrics"]["token_usage"]["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_goal_success_criteria_require_workflow_end_by_default(self, executor):
        g = WorkflowGraph(name="quality-success")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target="finalize")])
        g.add_node("finalize", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="ship once quality is high enough",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
        )

        async def quality_handler(node_id: str, state: dict) -> NodeResult:
            if node_id == "draft":
                return NodeResult(
                    state_patch={"draft": "good enough"},
                    metrics={"response_quality_score": 0.92},
                )
            return NodeResult(state_patch={"finalized": True})

        run = WorkflowRun(workflow_id="wf-quality-success")
        result = await executor.execute(g, run, quality_handler, goal_spec=goal)

        assert result.status == RunStatus.COMPLETED
        assert result.stop_reason == RunStopReason.QUALITY_REACHED
        assert result.state["finalized"] is True
        assert result.state["goal_status"]["satisfied"] is True
        assert result.state["verification"]["disposition"] == VerificationDisposition.SUCCESS.value
        assert len(result.event_log) == 2
        assert result.event_log[0]["verification"]["disposition"] == "success"
        assert result.event_log[1]["verification"]["disposition"] == "success"

    @pytest.mark.asyncio
    async def test_goal_success_can_complete_early_when_explicitly_enabled(self, executor):
        g = WorkflowGraph(name="quality-success-early")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target="finalize")])
        g.add_node("finalize", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="ship once quality is high enough",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
            completion_policy=RunCompletionPolicy.COMPLETE_ON_GOAL,
        )

        async def quality_handler(node_id: str, state: dict) -> NodeResult:
            if node_id == "draft":
                return NodeResult(
                    state_patch={"draft": "good enough"},
                    metrics={"response_quality_score": 0.92},
                )
            return NodeResult(state_patch={"finalized": True})

        run = WorkflowRun(workflow_id="wf-quality-success-early")
        result = await executor.execute(g, run, quality_handler, goal_spec=goal)

        assert result.status == RunStatus.COMPLETED
        assert result.stop_reason == RunStopReason.QUALITY_REACHED
        assert "finalized" not in result.state
        assert len(result.event_log) == 1

    @pytest.mark.asyncio
    async def test_terminal_goal_failure_marks_run_failed(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="quality-failure")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target="finalize")])
        g.add_node("finalize", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="must publish final answer",
            success_criteria=(
                SuccessCriterion(
                    type="state_value",
                    metadata={"key": "final_answer", "terminal_on_failure": True},
                ),
            ),
            failure_policy=FailurePolicy.FAIL,
        )

        async def incomplete_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(state_patch={"draft": node_id})

        run = WorkflowRun(workflow_id="wf-quality-failure")
        result = await executor.execute(g, run, incomplete_handler, goal_spec=goal)

        assert result.status == RunStatus.FAILED
        assert result.stop_reason == RunStopReason.QUALITY_FAILED
        assert result.state["verification"]["disposition"] == VerificationDisposition.FAIL.value
        assert result.state["error"] == "terminal criterion failed: state_value"

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert checkpoints[0].event_log[0]["verification"]["disposition"] == "fail"
        assert checkpoints[0].event_log[0]["evaluation_results"][0]["kind"] == "state_value"

    @pytest.mark.asyncio
    async def test_default_failure_policy_escalates_terminal_goal_failure(self, executor):
        g = WorkflowGraph(name="quality-escalate")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="must produce final answer",
            success_criteria=(
                SuccessCriterion(
                    type="state_value",
                    metadata={"key": "final_answer", "terminal_on_failure": True},
                ),
            ),
        )

        async def incomplete_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(state_patch={"draft": "missing"})

        run = WorkflowRun(workflow_id="wf-quality-escalate")
        result = await executor.execute(g, run, incomplete_handler, goal_spec=goal)

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.ESCALATION_REQUIRED
        assert result.state["goal_failure_policy"] == FailurePolicy.ESCALATE.value
        assert result.state["escalation_reason"] == "terminal criterion failed: state_value"

    @pytest.mark.asyncio
    async def test_request_approval_failure_policy_waits_for_human_review(self, executor):
        g = WorkflowGraph(name="quality-request-approval")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="obtain human review when quality is low",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.9),),
            failure_policy=FailurePolicy.REQUEST_APPROVAL,
        )

        async def low_quality_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(
                state_patch={"draft": "needs review"},
                metrics={"response_quality_score": 0.4},
            )

        run = WorkflowRun(workflow_id="wf-quality-request-approval")
        result = await executor.execute(g, run, low_quality_handler, goal_spec=goal)

        assert result.status == RunStatus.WAITING_APPROVAL
        assert result.suspension_reason == RunStopReason.APPROVAL_REQUIRED
        assert result.state["goal_failure_policy"] == FailurePolicy.REQUEST_APPROVAL.value
        assert result.state["approval_context"] == "goal_verification"
        assert result.state["approval_reason"] == "one or more success criteria not yet satisfied"

    @pytest.mark.asyncio
    async def test_request_approval_failure_policy_uses_approval_manager(self):
        manager = ApprovalManager(
            ApprovalStore(),
            AuditRepository(hmac_key=b"test-key-at-least-16b"),
        )
        executor = GraphExecutor(approval_manager=manager)
        g = WorkflowGraph(name="quality-request-approval-managed")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="obtain human review when quality is low",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.9),),
            failure_policy=FailurePolicy.REQUEST_APPROVAL,
        )

        async def low_quality_handler(node_id: str, state: dict) -> NodeResult:
            del node_id, state
            return NodeResult(
                state_patch={"draft": "needs review"},
                metrics={"response_quality_score": 0.4},
            )

        run = WorkflowRun(workflow_id="wf-quality-request-approval-managed")
        result = await executor.execute(g, run, low_quality_handler, goal_spec=goal)

        assert result.status == RunStatus.WAITING_APPROVAL
        assert result.approval_request_id is not None
        stored = await manager.get_request(result.approval_request_id)
        assert stored is not None
        assert stored.context["kind"] == "goal_verification"

    @pytest.mark.asyncio
    async def test_refine_can_rerun_workflow_with_max_replans(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="quality-replan")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="improve draft until quality passes",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
            constraints=GoalConstraints(max_replans=1),
        )

        async def improving_handler(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("attempt", 0)) + 1
            score = 0.4 if attempt == 1 else 0.95
            return NodeResult(
                state_patch={"attempt": attempt, "draft": f"v{attempt}"},
                metrics={"response_quality_score": score},
            )

        run = WorkflowRun(workflow_id="wf-quality-replan")
        result = await executor.execute(g, run, improving_handler, goal_spec=goal)

        assert result.status == RunStatus.COMPLETED
        assert result.stop_reason == RunStopReason.QUALITY_REACHED
        assert result.state["attempt"] == 2
        assert result.state["runtime_metrics"]["replan_count"] == 1
        assert result.state["autonomy"]["replan_count"] == 1
        assert len(result.event_log) == 2
        assert result.event_log[0]["attempt_id"] == 1
        assert result.event_log[1]["attempt_id"] == 2

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert checkpoints[0].event_log[0]["attempt_id"] == 1
        assert checkpoints[1].event_log[0]["attempt_id"] == 2

    @pytest.mark.asyncio
    async def test_refine_exhausts_max_replans_before_escalation(self, executor):
        g = WorkflowGraph(name="quality-replan-exhausted")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="improve if possible",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
            constraints=GoalConstraints(max_replans=1),
        )

        async def always_low_quality(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("attempt", 0)) + 1
            return NodeResult(
                state_patch={"attempt": attempt},
                metrics={"response_quality_score": 0.2},
            )

        run = WorkflowRun(workflow_id="wf-quality-replan-exhausted")
        result = await executor.execute(g, run, always_low_quality, goal_spec=goal)

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.ESCALATION_REQUIRED
        assert result.state["attempt"] == 2
        assert result.state["runtime_metrics"]["replan_count"] == 1
        assert result.state["autonomy"]["replan_count"] == 1
        assert result.state["replan_reason"] == "one or more success criteria not yet satisfied"

    @pytest.mark.asyncio
    async def test_refine_exhaustion_uses_refinement_policy_over_goal_failure_policy(
        self, executor
    ):
        g = WorkflowGraph(name="quality-replan-refinement-policy")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])
        goal = GoalSpec(
            objective="improve if possible",
            success_criteria=(SuccessCriterion(type="response_quality", threshold=0.8),),
            constraints=GoalConstraints(max_replans=1),
            failure_policy=FailurePolicy.REQUEST_APPROVAL,
            refinement_policy=RefinementPolicy(exhaustion_policy=FailurePolicy.FAIL),
        )

        async def always_low_quality(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("attempt", 0)) + 1
            return NodeResult(
                state_patch={"attempt": attempt},
                metrics={"response_quality_score": 0.2},
            )

        run = WorkflowRun(workflow_id="wf-quality-replan-refinement-policy")
        result = await executor.execute(g, run, always_low_quality, goal_spec=goal)

        assert result.status == RunStatus.FAILED
        assert result.stop_reason == RunStopReason.QUALITY_FAILED

    @pytest.mark.asyncio
    async def test_loop_node_retries_until_local_criterion_passes(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="loop-node-success")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=2,
            loop_criterion="response_quality",
            loop_threshold=0.8,
            next_nodes=[ConditionalEdge(target=END)],
        )

        async def improving_handler(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("draft_attempt", 0)) + 1
            score = 0.3 if attempt == 1 else 0.92
            return NodeResult(
                state_patch={"draft_attempt": attempt},
                metrics={"response_quality_score": score},
            )

        run = WorkflowRun(workflow_id="wf-loop-node")
        result = await executor.execute(g, run, improving_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state["draft_attempt"] == 2
        assert len(result.event_log) == 2
        assert result.event_log[0]["loop_iteration"] == 1
        assert result.event_log[0]["loop_evaluation"]["passed"] is False
        assert result.event_log[1]["loop_iteration"] == 2
        assert result.event_log[1]["loop_evaluation"]["passed"] is True

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert checkpoints[0].event_log[0]["loop_iteration"] == 1
        assert checkpoints[1].event_log[0]["loop_iteration"] == 2

    @pytest.mark.asyncio
    async def test_loop_node_exhaustion_fails_run(self, executor):
        g = WorkflowGraph(name="loop-node-exhausted")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=2,
            loop_criterion="response_quality",
            loop_threshold=0.8,
            next_nodes=[ConditionalEdge(target=END)],
        )

        async def low_quality_handler(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("draft_attempt", 0)) + 1
            return NodeResult(
                state_patch={"draft_attempt": attempt},
                metrics={"response_quality_score": 0.1},
            )

        run = WorkflowRun(workflow_id="wf-loop-node-exhausted")
        result = await executor.execute(g, run, low_quality_handler)

        assert result.status == RunStatus.FAILED
        assert result.stop_reason == RunStopReason.LOOP_EXHAUSTED
        assert result.state["refinement_context"] == "loop_node"

    @pytest.mark.asyncio
    async def test_loop_node_exhaustion_uses_goal_failure_policy_escalate(self, executor):
        g = WorkflowGraph(name="loop-node-escalate")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=2,
            loop_criterion="response_quality",
            loop_threshold=0.8,
            next_nodes=[ConditionalEdge(target=END)],
        )
        goal = GoalSpec(
            objective="keep refining until acceptable",
            failure_policy=FailurePolicy.ESCALATE,
        )

        async def low_quality_handler(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("draft_attempt", 0)) + 1
            return NodeResult(
                state_patch={"draft_attempt": attempt},
                metrics={"response_quality_score": 0.1},
            )

        run = WorkflowRun(workflow_id="wf-loop-node-escalate")
        result = await executor.execute(g, run, low_quality_handler, goal_spec=goal)

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.ESCALATION_REQUIRED
        assert result.state["refinement_context"] == "loop_node"

    @pytest.mark.asyncio
    async def test_loop_node_exhaustion_can_request_approval(self):
        manager = ApprovalManager(
            ApprovalStore(),
            AuditRepository(hmac_key=b"test-key-at-least-16b"),
        )
        executor = GraphExecutor(approval_manager=manager)
        g = WorkflowGraph(name="loop-node-request-approval")
        g.add_node(
            "draft",
            "writer",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=2,
            loop_criterion="response_quality",
            loop_threshold=0.8,
            next_nodes=[ConditionalEdge(target=END)],
        )
        goal = GoalSpec(
            objective="keep refining until acceptable",
            failure_policy=FailurePolicy.REQUEST_APPROVAL,
        )

        async def low_quality_handler(node_id: str, state: dict) -> NodeResult:
            attempt = int(state.get("draft_attempt", 0)) + 1
            return NodeResult(
                state_patch={"draft_attempt": attempt},
                metrics={"response_quality_score": 0.1},
            )

        run = WorkflowRun(workflow_id="wf-loop-node-request-approval")
        result = await executor.execute(g, run, low_quality_handler, goal_spec=goal)

        assert result.status == RunStatus.WAITING_APPROVAL
        assert result.state["approval_context"] == "loop_node"
        stored = await manager.get_request(result.approval_request_id)
        assert stored is not None
        assert stored.context["kind"] == "loop_node"

    @pytest.mark.asyncio
    async def test_structured_node_result_persists_rich_event_data(self, executor):
        repo = CheckpointRepository()
        executor = GraphExecutor(checkpoint_repo=repo)

        g = WorkflowGraph(name="structured")
        g.add_node("start", "planner", next_nodes=[
            ConditionalEdge(target="next", condition="state.should_route"),
            ConditionalEdge(target=END, condition="not state.should_route"),
        ])
        g.add_node("next", "agent1", next_nodes=[ConditionalEdge(target=END)])

        async def structured_handler(node_id: str, state: dict) -> dict | NodeResult:
            if node_id == "start":
                return NodeResult(
                    state_patch={"should_route": False, "started": True},
                    event_output={"started": True, "summary": "routed"},
                    artifacts=[{"kind": "report", "name": "analysis.json"}],
                    edge_decisions={"next": True, "END": False},
                    llm_events=[{"model": "test-model", "tokens": 42}],
                    tool_events=[{"tool": "search", "status": "ok"}],
                    metrics={"latency_ms": 12},
                )
            return NodeResult(state_patch={"finished": True})

        run = WorkflowRun(workflow_id="wf-structured")
        result = await executor.execute(g, run, structured_handler)

        assert result.status == RunStatus.COMPLETED
        assert result.state["finished"] is True
        assert len(result.event_log) == 2
        start_event = result.event_log[0]
        assert start_event["state_patch"] == {"should_route": False, "started": True}
        assert start_event["output"] == {"started": True, "summary": "routed"}
        assert start_event["edge_decisions"] == {"next": True, "END": False}
        assert start_event["edge_resolutions"] == [
            {
                "edge_key": "start:0",
                "target": "next",
                "condition": "state.should_route",
                "status": "taken",
                "decision_source": "explicit_target",
                "reason": "explicit decision evaluated to true",
            },
            {
                "edge_key": "start:1",
                "target": "END",
                "condition": "not state.should_route",
                "status": "not_taken",
                "decision_source": "explicit_target",
                "reason": "explicit decision evaluated to false",
            },
        ]
        assert start_event["artifacts"] == [{"kind": "report", "name": "analysis.json"}]
        assert start_event["tool_events"] == [{"tool": "search", "status": "ok"}]
        assert start_event["llm_events"] == [{"model": "test-model", "tokens": 42}]
        assert start_event["metrics"] == {"latency_ms": 12}
        assert start_event["input_state_version"] == 0

        checkpoints = await repo.list(workflow_run_id=run.id)
        assert checkpoints[0].event_log[0]["state_patch"] == {
            "should_route": False,
            "started": True,
        }
        assert checkpoints[0].event_log[0]["tool_events"] == [{"tool": "search", "status": "ok"}]
        assert checkpoints[0].event_log[0]["artifacts"] == [
            {"kind": "report", "name": "analysis.json"}
        ]
        assert checkpoints[0].event_log[0]["edge_resolutions"] == start_event["edge_resolutions"]

    @pytest.mark.asyncio
    async def test_unknown_edge_decision_fails_run(self, executor):
        g = WorkflowGraph(name="bad-decision")
        g.add_node("start", "planner", next_nodes=[ConditionalEdge(target=END)])

        async def bad_handler(node_id: str, state: dict) -> NodeResult:
            return NodeResult(state_patch={"started": True}, edge_decisions={"missing": True})

        run = WorkflowRun(workflow_id="wf-bad-decision")
        with pytest.raises(Exception, match="unknown outbound edge decisions"):
            await executor.execute(g, run, bad_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_handler_error_fails_run(self, executor):
        g = WorkflowGraph(name="error")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def failing_handler(node_id: str, state: dict) -> dict:
            raise RuntimeError("handler failed")

        run = WorkflowRun(workflow_id="wf-1")
        with pytest.raises(Exception):
            await executor.execute(g, run, failing_handler)

        assert run.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_replay(self, executor):
        """Replay should reconstruct state from event log."""
        g = WorkflowGraph(name="replay")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        run.event_log = [
            {
                "step": 1,
                "node_id": "step1",
                "agent": "agent",
                "state_patch": {"key": "value"},
                "state_version": 1,
                "state_hash": compute_state_hash({"key": "value"}),
            },
        ]

        replayed = await executor.replay(g, run, mock_handler)
        assert replayed.state.get("key") == "value"
        assert replayed.state_version == 1
        assert replayed.state_hash != ""
        assert replayed.event_log == run.event_log

    @pytest.mark.asyncio
    async def test_replay_hash_mismatch_fails(self, executor):
        g = WorkflowGraph(name="replay")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target=END)])

        run = WorkflowRun(workflow_id="wf-1")
        run.event_log = [
            {
                "step": 1,
                "node_id": "step1",
                "agent": "agent",
                "state_patch": {"key": "value"},
                "state_version": 1,
                "state_hash": "invalid",
            },
        ]

        with pytest.raises(Exception, match="hash mismatch"):
            await executor.replay(g, run, mock_handler)

    @pytest.mark.asyncio
    async def test_quality_threshold_termination_completes_run(self, executor):
        g = WorkflowGraph(name="quality-threshold")
        g.add_node("draft", "agent", next_nodes=[ConditionalEdge(target=END)])

        async def quality_handler(node_id: str, state: dict) -> NodeResult:
            del node_id, state
            return NodeResult(
                state_patch={"draft": "done"},
                metrics={"response_quality_score": 0.95},
            )

        run = WorkflowRun(workflow_id="wf-quality-threshold")
        result = await executor.execute(
            g,
            run,
            quality_handler,
            termination_policy=QualityThreshold(0.9),
        )

        assert result.status == RunStatus.COMPLETED
        assert result.stop_reason == RunStopReason.QUALITY_REACHED
        assert "termination_reason" in result.state

    @pytest.mark.asyncio
    async def test_stuck_detector_pauses_repeating_loop_signature(self, executor):
        g = WorkflowGraph(name="stuck-loop")
        g.add_node(
            "draft",
            "agent",
            node_type=WorkflowNodeType.LOOP,
            loop_max_iterations=5,
            loop_criterion="state_value",
            loop_metadata={"key": "missing"},
            next_nodes=[ConditionalEdge(target=END)],
        )

        async def no_progress_handler(node_id: str, state: dict) -> NodeResult:
            del node_id, state
            return NodeResult(state_patch={})

        run = WorkflowRun(workflow_id="wf-stuck-loop")
        result = await executor.execute(
            g,
            run,
            no_progress_handler,
            termination_policy=StuckDetector(window=2),
        )

        assert result.status == RunStatus.PAUSED
        assert result.suspension_reason == RunStopReason.STUCK_DETECTED
        assert "termination_reason" in result.state

    @pytest.mark.asyncio
    async def test_resume_from_paused_limit_continues_without_rerunning_completed_nodes(
        self, executor
    ):
        g = WorkflowGraph(name="resume-limit")
        g.add_node("step1", "agent", next_nodes=[ConditionalEdge(target="step2")])
        g.add_node("step2", "agent", next_nodes=[ConditionalEdge(target=END)])

        calls: list[str] = []

        async def handler(node_id: str, state: dict) -> dict:
            del state
            calls.append(node_id)
            return {f"{node_id}_done": True}

        run = WorkflowRun(workflow_id="wf-resume-limit")
        paused = await executor.execute(g, run, handler, max_steps=1)

        assert paused.status == RunStatus.PAUSED
        assert paused.suspension_reason == RunStopReason.LIMIT_EXCEEDED
        assert calls == ["step1"]

        resumed = await executor.resume(g, paused, handler, max_steps=5)

        assert resumed.status == RunStatus.COMPLETED
        assert calls == ["step1", "step2"]
        assert resumed.state["execution"]["step_count"] == 2

    @pytest.mark.asyncio
    async def test_resume_from_waiting_approval_completes_without_rerunning_gate_node(
        self, executor
    ):
        g = WorkflowGraph(name="resume-approval")
        g.add_node("review", "reviewer", next_nodes=[ConditionalEdge(target=END)])

        calls: list[str] = []

        async def handler(node_id: str, state: dict) -> NodeResult:
            del state
            calls.append(node_id)
            if len(calls) == 1:
                return NodeResult(
                    state_patch={"reviewed": True},
                    requires_approval=True,
                    approval_request_id="apr-test",
                    approval_reason="manual review required",
                )
            return NodeResult(state_patch={"reviewed": True})

        run = WorkflowRun(workflow_id="wf-resume-approval")
        waiting = await executor.execute(g, run, handler)

        assert waiting.status == RunStatus.WAITING_APPROVAL
        assert calls == ["review"]

        resumed = await executor.resume(g, waiting, handler)

        assert resumed.status == RunStatus.COMPLETED
        assert calls == ["review"]
        assert resumed.stop_reason == RunStopReason.NONE
