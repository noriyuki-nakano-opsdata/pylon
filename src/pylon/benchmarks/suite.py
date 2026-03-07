"""Benchmark suite — concrete benchmarks for Pylon subsystems."""

from __future__ import annotations

from pylon.benchmarks.runner import BenchmarkResult, BenchmarkRunner
from pylon.repository.audit import AuditRepository
from pylon.repository.checkpoint import Checkpoint, CheckpointRepository
from pylon.repository.memory import EpisodicEntry, MemoryRepository
from pylon.repository.workflow import WorkflowRun
from pylon.safety.policy import ActionState, PolicyEngine
from pylon.types import AgentConfig, ConditionalEdge, PolicyConfig, WorkflowNode
from pylon.workflow.executor import GraphExecutor
from pylon.workflow.graph import END, WorkflowGraph


async def bench_workflow_execution(
    runner: BenchmarkRunner, *, iterations: int = 50
) -> BenchmarkResult:
    """Measure GraphExecutor overhead for a simple 2-node graph."""

    async def fn() -> None:
        graph = WorkflowGraph(name="bench")
        graph.add_node("a", "agent-a")
        graph.add_node("b", "agent-b")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)

        async def handler(node_id: str, state: dict) -> dict:
            return {"node": node_id}

        run = WorkflowRun(workflow_id="bench-wf")
        executor = GraphExecutor()
        await executor.execute(graph, run, handler)

    return await runner.run(
        "workflow_execution", fn, iterations=iterations, warmup=5
    )


async def bench_checkpoint_save_restore(
    runner: BenchmarkRunner, *, iterations: int = 100
) -> BenchmarkResult:
    """Measure checkpoint create + retrieve roundtrip."""
    repo = CheckpointRepository()

    async def fn() -> None:
        cp = Checkpoint(workflow_run_id="bench-run", node_id="node-1")
        cp.add_event(input_data={"key": "value"}, output_data={"result": 42})
        created = await repo.create(cp)
        await repo.get(created.id)

    return await runner.run(
        "checkpoint_save_restore", fn, iterations=iterations, warmup=10
    )


async def bench_memory_search(
    runner: BenchmarkRunner, *, iterations: int = 100
) -> BenchmarkResult:
    """Measure memory repository store + list operations."""
    repo = MemoryRepository()

    # Pre-populate
    for i in range(50):
        await repo.store_episodic(
            EpisodicEntry(agent_id="bench-agent", content=f"Episode {i}")
        )

    async def fn() -> None:
        await repo.store_episodic(
            EpisodicEntry(agent_id="bench-agent", content="new episode")
        )
        await repo.list_episodic("bench-agent", limit=20)

    return await runner.run(
        "memory_search", fn, iterations=iterations, warmup=10
    )


async def bench_policy_evaluation(
    runner: BenchmarkRunner, *, iterations: int = 200
) -> BenchmarkResult:
    """Measure policy engine throughput."""
    policy = PolicyConfig(
        max_cost_usd=100.0,
        max_duration_seconds=3600,
        max_file_changes=50,
        blocked_actions=["rm -rf", "drop table"],
    )
    engine = PolicyEngine(policy)
    agent = AgentConfig(name="bench-agent")
    state = ActionState(current_cost_usd=5.0, elapsed_seconds=120, file_changes=3)

    async def fn() -> None:
        engine.evaluate_action(agent, "read_file", state)
        engine.evaluate_action(agent, "write_file", state)
        engine.evaluate_action(agent, "execute_command", state)

    return await runner.run(
        "policy_evaluation", fn, iterations=iterations, warmup=20
    )


async def bench_audit_append(
    runner: BenchmarkRunner, *, iterations: int = 100
) -> BenchmarkResult:
    """Measure audit append with HMAC chain computation."""
    repo = AuditRepository(hmac_key=b"benchmark-key-1234567890")

    async def fn() -> None:
        await repo.append(
            event_type="benchmark",
            actor="bench-runner",
            action="test_action",
            details={"iteration": "bench"},
        )

    return await runner.run(
        "audit_append_hmac", fn, iterations=iterations, warmup=10
    )
