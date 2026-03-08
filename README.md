# Pylon

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests: 1445 passing](https://img.shields.io/badge/tests-1445%20passing-brightgreen)

**Pylon** is a Python-first autonomous agent orchestration platform with deterministic workflow execution, runtime safety enforcement, and protocol integrations for MCP and A2A.

## Key Features

| Category | Highlights |
|----------|------------|
| **Workflow Engine** | Compiled DAG execution, `ALL_RESOLVED` / `ANY` / `FIRST` join policies, patch-based commits, node-scoped checkpoints, pause/resume, and deterministic replay with state hash verification |
| **Safety** | Rule-of-Two+ enforcement (no frame may combine untrusted input + secret access + external writes), `SafetyContext` / `ToolDescriptor` dynamic checks, prompt guard pipeline |
| **Approval** | Plan/effect binding with drift detection, executor-integrated approval waits, and replayable approval context |
| **Protocols** | MCP JSON-RPC server with OAuth 2.1 + PKCE scopes; A2A task routing with peer delegation checks |
| **Infrastructure** | Sandbox policy, versioned secrets, multi-tenant isolation, rate limiting, circuit breaker, plugin system, scheduler wave planning — all shipped as local-first reference implementations |

## Quick Start

```bash
pip install pylon-ai

mkdir my-project && cd my-project
pylon init --name my-project
pylon run
```

## Programmatic API

```python
import asyncio
from pylon.workflow import WorkflowGraph, GraphExecutor, END, NodeResult
from pylon.types import ConditionalEdge
from pylon.repository.workflow import WorkflowRun

async def main():
    # 1. Build graph
    graph = WorkflowGraph(name="example")
    graph.add_node("plan", "planner", next_nodes=[
        ConditionalEdge(target="review"),
    ])
    graph.add_node("review", "reviewer", next_nodes=[
        ConditionalEdge(target="apply", condition="state.approved == True"),
        ConditionalEdge(target=END, condition="state.approved == False"),
    ])
    graph.add_node("apply", "applier", next_nodes=[
        ConditionalEdge(target=END),
    ])

    # 2. Define handlers
    async def handler(node_id: str, state: dict) -> dict:
        if node_id == "plan":
            return {"plan": "refactor auth module"}
        elif node_id == "review":
            return {"approved": True}
        return {"applied": True}

    # 3. Execute
    run = WorkflowRun(workflow_id="example")
    executor = GraphExecutor()
    result = await executor.execute(
        graph, run, node_handler=handler,
        initial_state={"task": "refactor"},
    )
    print(f"Status: {result.status.value}")
    print(f"Final state: {result.state}")

asyncio.run(main())
```

## SDK Authoring Surfaces

`pylon.sdk.PylonClient` keeps canonical workflow execution separate from
explicit single-step callable execution.

Canonical workflow definitions can come from:

- `PylonProject`
- `dict` or `pylon.yaml` path
- `WorkflowBuilder`
- `WorkflowGraph`
- `@workflow`-decorated factory

These are materialized into a canonical `PylonProject` before execution, so
`run_workflow()` still uses the same compiled graph runtime as the CLI and API.
Plain callables are not treated as workflows. Register them explicitly through
`register_callable()` and run them through `run_callable()`.

```python
from pylon.sdk import PylonClient, agent, workflow

client = PylonClient()

@agent(name="researcher", role="research")
def researcher(state):
    return {"topic": str(state["topic"]).upper()}

@agent(name="writer", role="write")
def writer(state):
    return {"summary": f"summary:{state['topic']}"}

@workflow(name="pipeline")
def define(builder):
    builder.add_node("research", agent="researcher")
    builder.add_node("write", agent="writer")
    builder.add_edge("research", "write")
    builder.set_entry("research")

client.register_workflow("pipeline", define)
result = client.run_workflow("pipeline", input_data={"topic": "agents"})
run = client.get_run(result.run_id)
```

Current limitation:

- callable edge conditions in `WorkflowBuilder` cannot be materialized into the
  canonical runtime; use string conditions in the DSL/runtime graph for those
  cases

Control-plane backend selection:

- CLI can switch `memory`, `json_file`, and `sqlite` backends through
  `control_plane.backend` / `control_plane.path` in `config.yaml`, or
  `PYLON_CONTROL_PLANE_BACKEND` / `PYLON_CONTROL_PLANE_PATH`
- SDK can switch backends through `PylonClient(control_plane_backend=..., control_plane_path=...)`
- all backends share the same `WorkflowControlPlaneStore` contract

## Dispatch Planning

Pylon now exposes a scheduler-oriented planning view without changing the
canonical inline execution semantics.

- `pylon.runtime.plan_project_dispatch(...)` derives dependency waves from the compiled DAG
- `PylonClient.plan_workflow(...)` returns the same public dispatch plan
- `GET /workflows/{id}/plan` exposes the plan through the lightweight API

This planning view is meant for queued or distributed runners. Inline execution
still uses `GraphExecutor` directly.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Developer Surfaces: cli / api / sdk / dsl              │
├─────────────────────────────────────────────────────────┤
│  Execution Core: workflow / agents / safety / approval  │
├─────────────────────────────────────────────────────────┤
│  Protocol Boundaries: mcp / a2a / providers             │
├─────────────────────────────────────────────────────────┤
│  State & Infra: repository / state / events / sandbox   │
│                 secrets / tenancy / resources            │
├─────────────────────────────────────────────────────────┤
│  Support: taskqueue / plugins / resilience / config     │
│           observability / coding / control_plane        │
└─────────────────────────────────────────────────────────┘
```

## Module Structure

| Area | Package | Description |
|------|---------|-------------|
| Core | `pylon.types`, `pylon.errors` | Shared enums, dataclasses, and error hierarchy |
| Workflow | `pylon.workflow` | Compiled DAG execution, conditions, patch commits, replay, structured node results |
| Safety | `pylon.safety` | Capability validation, autonomy gates, prompt guard, input/output validation, secret scrubbing |
| Agents | `pylon.agents` | Agent lifecycle, registry, pool, supervisor |
| Approval | `pylon.approval` | Approval manager with plan/effect binding verification |
| Protocols | `pylon.protocols.mcp`, `pylon.protocols.a2a` | MCP JSON-RPC server with OAuth, A2A tasks with peer delegation |
| API / CLI / SDK | `pylon.api`, `pylon.cli`, `pylon.sdk` | Lightweight API server, local CLI, and SDK surfaces over the shared control plane |
| DSL / Providers | `pylon.dsl`, `pylon.providers` | YAML/JSON workflow parser, LLM provider abstraction |
| Persistence | `pylon.repository`, `pylon.state`, `pylon.events` | Workflow runs, checkpoints, audit log, state store, event bus |
| Infra | `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy` | Sandbox policy, secret storage, tenant context/isolation |
| Resources | `pylon.resources`, `pylon.resilience` | Rate limiting, pooling, retry, circuit breaker, bulkhead |
| Extensibility | `pylon.plugins`, `pylon.control_plane`, `pylon.taskqueue`, `pylon.observability`, `pylon.config`, `pylon.coding` | Plugins, registries, schedulers, metrics, config, coding loop |

Current source: 173 Python modules across 33 package directories, 42 test files (1,380 passing tests).

## Project Configuration

Pylon projects are configured via `pylon.yaml`:

```yaml
version: "1"
name: my-project

agents:
  coder:
    model: anthropic/claude-sonnet-4-20250514
    role: "Write clean, tested code"
    autonomy: A2
    tools: [file-read, file-write]
    sandbox: docker
    input_trust: untrusted

  reviewer:
    model: anthropic/claude-sonnet-4-20250514
    role: "Review code for quality and security"
    autonomy: A3
    tools: [file-read]
    sandbox: docker

workflow:
  type: graph
  nodes:
    plan:
      agent: coder
      next: [review]
    review:
      agent: reviewer
      next:
        - target: plan
          condition: "state.needs_revision == True"
        - target: END

policy:
  max_cost_usd: 10.0
  max_duration: 60m
  require_approval_above: A3
  safety:
    blocked_actions: [git-push, db-write]
    max_file_changes: 50
  compliance:
    audit_log: required
```

## CLI Commands

```bash
pylon init --name <name>       # Initialize project with pylon.yaml
pylon run [--input <json>]     # Execute workflow
pylon inspect <run-id>         # Show run details
pylon logs <run-id> [--follow] # Stream run logs
pylon replay <checkpoint-id>   # Replay from checkpoint
pylon approve <id> [--deny]    # Approve or deny an action
pylon doctor                   # Check project health
pylon dev                      # Start development mode
pylon config get|set|list      # Manage configuration
pylon sandbox list|clean       # Manage sandboxes
pylon login                    # Authenticate
```

## Running Tests

```bash
make install     # pip install -e ".[dev]"
make test        # pytest tests/unit/ -v
make test-all    # pytest tests/ -v
make lint        # ruff check src tests
make typecheck   # mypy src/pylon/
make format      # ruff format src tests
```

## Documentation

- [Architecture Overview](docs/architecture.md) — layered module structure
- [Runtime Flows](docs/architecture/runtime-flows.md) — execution paths for workflow, MCP, A2A, CLI, and approval
- [Module Map](docs/architecture/module-map.md) — package-by-package reference with maturity guide
- [Pylon vNext Target Architecture](docs/architecture/pylon-vnext-target-architecture.md) — target three-layer runtime-centered architecture
- [Pylon vNext Type Design](docs/architecture/pylon-vnext-type-design.md) — proposed types for goals, termination, routing, and evaluation
- [Pylon vNext Implementation Plan](docs/architecture/pylon-vnext-implementation-plan.md) — ordered delivery plan for bounded autonomy
- [Production Readiness Plan](docs/architecture/production-readiness-implementation-plan.md) — required work to move from reference implementations to production backends
- [Getting Started Guide](docs/getting-started.md) — installation, first project, programmatic API
- [API Reference](docs/api-reference.md) — REST routes and middleware
- [Implemented Specification](docs/SPECIFICATION.md) — full technical specification
- [ADR Index](docs/adr/) — architecture decision records (001–009)
- [Workflow/Safety Implementation Plan](docs/architecture/workflow-safety-implementation-plan.md)

## Current Status

The workflow engine and safety system are the most mature components. Workflow runs now use a shared runtime path across CLI/API/SDK helpers, API route definitions are registered as canonical `PylonProject` resources, and SDK workflow execution is separated from explicit ad hoc callable execution. Persisted runs are stored as raw command-side records, while public views rebuild normalized `execution_summary`, `approval_summary`, and replay metadata through shared query services. A scheduler-facing `distributed_wave_plan` is also available as a deployment-planning view over the same compiled DAG.

Many infrastructure subsystems (repository, sandbox, secrets, tenancy, plugins) are intentionally shipped as in-memory reference implementations suitable for local development and testing. Production deployments would swap these for persistent backends.

## License

MIT
