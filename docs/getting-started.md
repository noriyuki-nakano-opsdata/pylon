# Getting Started

## Prerequisites

- Python 3.12 or later
- `pip` or `uv`

## Installation

```bash
pip install pylon-ai
```

Development install:

```bash
git clone https://github.com/noriyuki-nakano-opsdata/pylon.git
cd pylon
pip install -e ".[dev]"
```

## Initialize a Project

`pylon init` writes files into the current directory. Create a project folder first:

```bash
mkdir my-project
cd my-project
pylon init --name my-project
```

Optional quickstart mode also writes `docker-compose.yaml`:

```bash
pylon init --name my-project --quickstart
```

What gets created today:

```text
my-project/
  pylon.yaml
  docker-compose.yaml   # only with --quickstart
```

CLI runtime state is stored separately under `$PYLON_HOME` or `~/.pylon`.

## Configure `pylon.yaml`

```yaml
version: "1"
name: my-project

agents:
  researcher:
    model: anthropic/claude-sonnet-4-20250514
    role: "Research topics and gather information"
    autonomy: A2
    tools: [web-search, file-read]
    sandbox: docker
    input_trust: untrusted

  writer:
    model: anthropic/claude-sonnet-4-20250514
    role: "Write clear documentation"
    autonomy: A3
    tools: [file-read, file-write]
    sandbox: docker

workflow:
  type: graph
  nodes:
    research:
      agent: researcher
      next: [write]
    write:
      agent: writer
      next: END

policy:
  max_cost_usd: 5.0
  max_duration: 30m
  require_approval_above: A3
  safety:
    blocked_actions: [git-push]
    max_file_changes: 20
  compliance:
    audit_log: required
```

Notes:

- `policy.max_duration` accepts values like `30m`, `1h`, or integer seconds.
- `workflow.nodes.*.next` accepts `END`, a list of target names, or conditional edges with `target` and `condition`.
- The DSL validates that every workflow node references a defined agent and every edge target references a defined node or `END`.

## Run a Workflow

```bash
# Default workflow from the current directory
pylon run

# With JSON input
pylon run --input '{"topic": "distributed systems"}'

# Inspect local run state
pylon inspect <run_id>
pylon logs <run_id>
```

Current CLI behavior:

- `pylon run` is a local CLI flow backed by `$PYLON_HOME/state.json`
- it records runs, checkpoints, approvals, and sandboxes in that local state file
- A3+ agents produce a `waiting_approval` CLI run status

Approve or deny a pending CLI approval:

```bash
pylon approve <approval_id>
pylon approve <approval_id> --deny --reason "policy violation"
```

Replay a stored CLI checkpoint:

```bash
pylon replay <checkpoint_id>
```

## Programmatic Workflow Engine

The richer deterministic DAG runtime lives in `pylon.workflow` and is used programmatically:

- `WorkflowGraph`
- `GraphExecutor`
- `NodeResult`
- `ReplayEngine`

That engine supports compiled conditions, join policies, patch-based state commits, node-scoped checkpoints, and replay with state hash verification.

## Safety Features

Pylon currently enforces safety in several layers:

1. Rule-of-Two+ capability checks for static agent envelopes and dynamic tool/delegation unions
2. Prompt guard pattern matching plus heuristic classifier for untrusted input
3. Input sanitization by trust level
4. Output validation for tool calls
5. Approval binding by `plan_hash` and `effect_hash`
6. Runtime safety decisions for MCP `tools/call` and A2A task submission

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYLON_DEFAULT_MODEL` | Default DSL model when not specified | `anthropic/claude-sonnet-4-20250514` |
| `PYLON_HOME` | CLI state/config directory | `~/.pylon` |
| `PYLON_VAULT_ADDR` | Vault address for external integrations | `http://127.0.0.1:8200` |
| `PYLON_VAULT_TOKEN` | Vault auth token | unset |

## Next Steps

- Read the [Architecture Overview](architecture.md)
- Read the [Implemented Specification](SPECIFICATION.md)
- See the [API Reference](api-reference.md) for the lightweight API route contract
