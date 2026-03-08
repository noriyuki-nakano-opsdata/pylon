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

- `pylon run` uses the shared workflow runtime and persists the resulting run/checkpoint/approval metadata under `$PYLON_HOME/state.json`
- `pylon inspect` returns the normalized run payload, including `execution_summary`, `approval_summary`, `policy_resolution`, and runtime metrics when present
- `pylon replay` reconstructs state from the checkpoint event log and returns the same run payload shape with `view_kind: replay`
- A3+ agents produce the runtime status `waiting_approval`, and `pylon approve` validates approval binding before resuming the workflow

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

The richer deterministic DAG runtime lives in `pylon.workflow` and also backs workflow execution through the shared CLI/API runtime helpers:

- `WorkflowGraph`
- `GraphExecutor`
- `NodeResult`
- `ReplayEngine`

That engine supports compiled conditions, join policies, patch-based state commits, node-scoped checkpoints, pause/resume, approval waits, and replay with state hash verification.

## Programmatic SDK Surface

`pylon.sdk.PylonClient` now separates canonical workflow execution from explicit ad hoc callable execution.

Canonical workflow path:

```python
from pylon.dsl.parser import PylonProject
from pylon.sdk.client import PylonClient

client = PylonClient()
project = PylonProject.model_validate({
    "version": "1",
    "name": "demo-project",
    "agents": {"researcher": {}, "writer": {}},
    "workflow": {
        "nodes": {
            "start": {"agent": "researcher", "next": "finish"},
            "finish": {"agent": "writer", "next": "END"},
        }
    },
})

client.register_project("demo", project)
result = client.run_workflow("demo", input_data={"topic": "distributed systems"})
run = client.get_run(result.run_id)
```

Explicit ad hoc helper path:

```python
client.register_callable("upper", lambda value: value.upper())
result = client.run_callable("upper", input_data="hello")
```

Current SDK control-plane methods include:

- `register_project`, `list_workflows`, `get_workflow`, `delete_workflow`
- `run_workflow`, `resume_run`
- `approve_request`, `reject_request`
- `replay_checkpoint`
- `register_callable`, `run_callable`, `delete_callable`

SDK workflow authoring also accepts `WorkflowBuilder`, `WorkflowGraph`, and
`@workflow`-decorated factories. These are materialized into a canonical
`PylonProject` before execution, so `run_workflow()` still goes through the same
compiled graph runtime as the DSL and API surfaces.

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
run_result = client.run_workflow("pipeline", input_data={"topic": "agents"})
run = client.get_run(run_result.run_id)
```

Notes:

- `register_workflow()` only accepts canonical workflow definitions and SDK
  workflow authoring objects
- plain functions belong to `register_callable()` / `run_callable()`
- `WorkflowBuilder` callable edge conditions are not materialized into the
  canonical runtime; use string conditions in the DSL/runtime graph for those
  cases

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
