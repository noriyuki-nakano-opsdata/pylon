# Pylon

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests: 1275 passing](https://img.shields.io/badge/tests-1275%20passing-brightgreen)

**Pylon** is a Python-first autonomous agent orchestration platform with deterministic workflow execution, runtime safety enforcement, and protocol integrations for MCP and A2A.

## Key Features

| Category | Highlights |
|----------|------------|
| **Workflow Engine** | Compiled DAG execution, `ALL_RESOLVED` / `ANY` / `FIRST` join policies, patch-based commits, node-scoped checkpoints, and deterministic replay with state hash verification |
| **Safety** | Rule-of-Two+ enforcement (no frame may combine untrusted input + secret access + external writes), `SafetyContext` / `ToolDescriptor` dynamic checks, prompt guard pipeline |
| **Approval** | Plan/effect binding with drift detection — approvals are invalidated if the action scope changes after sign-off |
| **Protocols** | MCP JSON-RPC server with OAuth 2.1 + PKCE scopes; A2A task routing with peer delegation checks |
| **Infrastructure** | Sandbox policy, versioned secrets, multi-tenant isolation, rate limiting, circuit breaker, plugin system — all shipped as local-first reference implementations |

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
| API / CLI / SDK | `pylon.api`, `pylon.cli`, `pylon.sdk` | Lightweight API server, local CLI, in-memory SDK client |
| DSL / Providers | `pylon.dsl`, `pylon.providers` | YAML/JSON workflow parser, LLM provider abstraction |
| Persistence | `pylon.repository`, `pylon.state`, `pylon.events` | Workflow runs, checkpoints, audit log, state store, event bus |
| Infra | `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy` | Sandbox policy, secret storage, tenant context/isolation |
| Resources | `pylon.resources`, `pylon.resilience` | Rate limiting, pooling, retry, circuit breaker, bulkhead |
| Extensibility | `pylon.plugins`, `pylon.control_plane`, `pylon.taskqueue`, `pylon.observability`, `pylon.config`, `pylon.coding` | Plugins, registries, schedulers, metrics, config, coding loop |

Current source: 129 modules across 31 packages, 37 test files (1,275 test cases).

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
- [Getting Started Guide](docs/getting-started.md) — installation, first project, programmatic API
- [API Reference](docs/api-reference.md) — REST routes and middleware
- [Implemented Specification](docs/SPECIFICATION.md) — full technical specification
- [ADR Index](docs/adr/) — architecture decision records (001–008)
- [Workflow/Safety Implementation Plan](docs/architecture/workflow-safety-implementation-plan.md)

## Current Status

The workflow engine and safety system are the most mature components — they provide compiled deterministic execution, runtime boundary enforcement at MCP/A2A protocol edges, and approval binding with drift detection.

Many infrastructure subsystems (repository, sandbox, secrets, tenancy, plugins) are intentionally shipped as in-memory reference implementations suitable for local development and testing. Production deployments would swap these for persistent backends.

## License

MIT
