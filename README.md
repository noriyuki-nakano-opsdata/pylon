# Pylon

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

**Pylon** is a Python-first autonomous agent orchestration platform with deterministic workflow execution, runtime safety enforcement, local/in-memory reference surfaces, and protocol integrations for MCP and A2A.

## Key Features

- **Deterministic DAG Workflow Engine** -- graph compilation, join policies, patch-based commits, checkpoints, and replay
- **Rule-of-Two+ Enforcement** -- no single execution frame may combine untrusted input, secret access, and external writes
- **Runtime Safety Context** -- `SafetyContext` and `ToolDescriptor` enforce dynamic checks for MCP and A2A calls
- **Approval Binding** -- plan/effect approvals are invalidated on drift
- **Prompt Guard Pipeline** -- pattern matching, classifier-style heuristics, input sanitization, and tool-call output validation
- **Protocol Support** -- MCP server/client with OAuth scopes and A2A task routing with peer checks
- **Reference Infrastructure Modules** -- sandbox policy/manager, secrets, repository, tenancy, plugins, task queues, observability, resilience

## Quick Start

```bash
# Install
pip install pylon-ai

# Create a project directory and initialize pylon.yaml in it
mkdir my-project
cd my-project
pylon init --name my-project

# Run the local CLI workflow flow
pylon run
```

`pylon init` writes `pylon.yaml` into the current directory.
`pylon run` currently uses the CLI's local persisted state in `$PYLON_HOME` / `~/.pylon`; it does not yet invoke the full programmatic workflow engine directly.

## Module Structure

| Area | Package | Description |
|------|---------|-------------|
| Core | `pylon.types`, `pylon.errors` | Shared enums, dataclasses, and error hierarchy |
| Workflow | `pylon.workflow` | Compiled DAG execution, conditions, patch commits, replay, structured node results |
| Safety | `pylon.safety` | Capability validation, autonomy gates, prompt guard, input/output validation, runtime safety context |
| Agents | `pylon.agents` | Agent lifecycle, registry, pool, supervisor |
| Protocols | `pylon.protocols.mcp`, `pylon.protocols.a2a` | MCP JSON-RPC surfaces, OAuth, A2A tasks, agent cards |
| API / CLI / SDK | `pylon.api`, `pylon.cli`, `pylon.sdk` | Lightweight API server, local CLI flows, in-memory SDK client/builder/decorators |
| Persistence | `pylon.repository`, `pylon.state`, `pylon.events` | Workflow runs, checkpoints, memory repository, state store, snapshots, event bus |
| Infra | `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy`, `pylon.resources`, `pylon.resilience` | Sandbox policy, secret storage, tenant context/isolation, limits, retry/circuit breaker |
| Extensibility | `pylon.plugins`, `pylon.control_plane`, `pylon.taskqueue`, `pylon.observability`, `pylon.config`, `pylon.coding` | Plugins, registries, schedulers, metrics, config, coding loop |
| DSL / Providers | `pylon.dsl`, `pylon.providers` | YAML/JSON workflow parser, LLM provider abstraction |
| Approval | `pylon.approval` | Approval manager with plan/effect binding verification |

Current source layout: 31 Python packages, 160 Python modules, 40 test files.

## Running Tests

```bash
PYTHONPATH=src python -m pytest -q
python -m ruff check src tests
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Getting Started Guide](docs/getting-started.md)
- [API Reference](docs/api-reference.md)
- [Implemented Specification](docs/SPECIFICATION.md)
- [ADR-007: Deterministic DAG Execution Semantics](docs/adr/007-deterministic-dag-execution-semantics.md)
- [ADR-008: Safety Context and Delegation Boundaries](docs/adr/008-safety-context-and-delegation-boundaries.md)
- [Workflow/Safety Implementation Plan](docs/architecture/workflow-safety-implementation-plan.md)

## Current Implementation Status

- The programmatic workflow engine implements compiled graphs, restricted condition compilation, `ALL_RESOLVED` / `ANY` / `FIRST` join policies, patch commits, node-scoped checkpoints, and replay with state hash verification.
- Runtime safety is enforced at MCP `tools/call`, A2A `tasks/send`, A2A `tasks/sendSubscribe`, and router pre-dispatch validation boundaries.
- Approval binding is implemented in both `pylon.approval` and `pylon.safety.autonomy`.
- Many subsystems intentionally ship as in-memory or local-first reference implementations today: repository backends, API route store, SDK client, CLI run state, sandbox manager, secret manager, and plugin loading surfaces.
- Public API/CLI/SDK terminology is not yet fully aligned with the richer runtime states of the workflow engine.

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

## License

MIT
