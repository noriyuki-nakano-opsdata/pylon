# Pylon

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

**Pylon** is an autonomous AI agent orchestration platform that enables safe, multi-agent workflows with built-in safety guardrails, sandbox isolation, and secret management.

## Key Features

- **5-Layer Architecture** -- API, Safety, Orchestration, Protocols, Infrastructure
- **Rule-of-Two+ Enforcement** -- No agent can simultaneously read untrusted input, access secrets, and write externally
- **Autonomy Ladder (A0-A4)** -- Graduated autonomy with human approval gates
- **Prompt Guard Pipeline** -- Pattern matching + classifier LLM for injection detection
- **Multi-path Kill Switch** -- Emergency halt via NATS, ConfigMap poll, or namespace delete
- **Sandbox Isolation** -- gVisor, Firecracker, Docker, or host-process tiers
- **Secret Management** -- Versioned secrets with rotation, Vault integration, and audit logging
- **MCP + A2A Protocols** -- JSON-RPC 2.0 tool server and agent-to-agent communication
- **Workflow Engine** -- DAG-based execution with conditional routing and checkpoints

## Quick Start

```bash
# Install
pip install pylon

# Initialize a project
pylon init my-project
cd my-project

# Run the default workflow
pylon run
```

## Module Structure

| Layer | Package | Modules | Description |
|-------|---------|---------|-------------|
| **API** | `pylon.api` | server, routes, middleware, schemas | HTTP API server with auth and rate limiting |
| **Safety** | `pylon.safety` | capability, autonomy, prompt_guard, input_sanitizer, output_validator, kill_switch, policy | Rule-of-Two+, prompt guard, kill switch, policy engine |
| **Agents** | `pylon.agents` | runtime, lifecycle, pool, registry, supervisor | Agent lifecycle, pooling, and supervision |
| **Workflow** | `pylon.workflow` | graph, executor | DAG workflow definition and execution |
| **DSL** | `pylon.dsl` | parser | pylon.yaml configuration parser |
| **Protocols** | `pylon.protocols.mcp` | types | MCP JSON-RPC 2.0 protocol types |
| | `pylon.protocols.a2a` | card, client, server, types | Agent-to-Agent communication |
| **Providers** | `pylon.providers` | base, anthropic | LLM provider abstraction |
| **Sandbox** | `pylon.sandbox` | manager, executor, policy, registry | Sandbox isolation and resource limits |
| **Secrets** | `pylon.secrets` | manager, vault, rotation, audit | Secret storage, Vault, rotation, audit |
| **Repository** | `pylon.repository` | base, memory, workflow, checkpoint, audit | Event sourcing and persistence |
| **Core** | `pylon` | types, errors | Shared types and error hierarchy |

**Total: 21 packages, 40+ modules**

## Running Tests

```bash
# Run all tests
PYTHONPATH=src python -m pytest tests/ -v

# Run specific module tests
PYTHONPATH=src python -m pytest tests/unit/test_prompt_guard.py -v
PYTHONPATH=src python -m pytest tests/unit/test_sandbox.py -v
PYTHONPATH=src python -m pytest tests/unit/test_secrets.py -v
PYTHONPATH=src python -m pytest tests/unit/test_api.py -v
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Getting Started Guide](docs/getting-started.md)
- [API Reference](docs/api-reference.md)

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
    tools: [file-read, file-write, shell]
    sandbox: gvisor

  reviewer:
    model: anthropic/claude-sonnet-4-20250514
    role: "Review code for quality and security"
    autonomy: A1
    tools: [file-read]

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
          condition: "needs_revision"
        - target: END

policy:
  max_cost_usd: 10.0
  max_duration_seconds: 3600
  max_file_changes: 50
  blocked_actions: [git-push, db-write]
```

## License

MIT
