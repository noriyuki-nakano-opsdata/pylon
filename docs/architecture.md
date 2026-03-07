# Architecture Overview

## What Exists Today

Pylon is a Python codebase composed of reference implementations plus a richer programmatic workflow runtime.

The important architectural split is:

- **Developer surfaces**: `pylon.cli`, `pylon.sdk`, `pylon.api`
- **Execution core**: `pylon.workflow`, `pylon.agents`, `pylon.safety`
- **Protocol boundaries**: `pylon.protocols.mcp`, `pylon.protocols.a2a`, `pylon.providers`
- **State and infrastructure**: `pylon.repository`, `pylon.state`, `pylon.events`, `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy`
- **Supporting subsystems**: `pylon.taskqueue`, `pylon.plugins`, `pylon.control_plane`, `pylon.resources`, `pylon.resilience`, `pylon.observability`, `pylon.config`, `pylon.coding`

## Layered View

```text
+------------------------------------------------------------------+
| Developer Surfaces                                                |
| cli/ | sdk/ | api/                                                |
| Local CLI state, in-memory SDK client, lightweight API routes     |
+------------------------------------------------------------------+
| Execution Core                                                    |
| workflow/ | agents/ | dsl/ | coding/                              |
| Compiled DAG runtime, agent lifecycle, pylon.yaml, coding loop    |
+------------------------------------------------------------------+
| Safety and Protocol Boundaries                                    |
| safety/ | protocols/mcp/ | protocols/a2a/ | providers/            |
| Capability rules, runtime safety, MCP/A2A servers, LLM providers  |
+------------------------------------------------------------------+
| State and Infrastructure                                          |
| repository/ | state/ | events/ | sandbox/ | secrets/ | tenancy/  |
| Runs, checkpoints, snapshots, event bus, sandbox policy, tenancy  |
+------------------------------------------------------------------+
| Cross-Cutting Support                                             |
| taskqueue/ | plugins/ | control_plane/ | observability/           |
| resources/ | resilience/ | config/                                |
+------------------------------------------------------------------+
```

## Current Execution Model

### Programmatic Workflow Runtime

The most developed runtime is the programmatic workflow engine in `pylon.workflow`:

1. `WorkflowGraph` defines nodes and edges
2. `compile()` validates the DAG and produces `CompiledWorkflow`
3. `GraphExecutor` executes runnable nodes under explicit join semantics
4. node handlers return either a raw `dict` or a structured `NodeResult`
5. `CommitEngine` applies `StatePatch` updates deterministically
6. `CheckpointRepository` stores node-scoped event logs
7. `ReplayEngine` reconstructs state and verifies `state_hash`

This runtime is deterministic in the sense that:

- graph topology is validated before execution
- conditions are compiled from a restricted AST, not `eval`
- parallel writes to the same state key fail fast
- join policies are explicit: `ALL_RESOLVED`, `ANY`, `FIRST`

### CLI / API / SDK Surfaces

These surfaces are intentionally lighter than the workflow core:

- `pylon.cli` stores local state in `$PYLON_HOME` / `~/.pylon`
- `pylon.api` uses an in-memory `RouteStore`
- `pylon.sdk.PylonClient` is an in-memory client, not an HTTP transport

That means the public surfaces do not yet expose every runtime nuance of `pylon.workflow`.

## Safety Architecture

### Static Capability Envelope

`AgentCapability` expresses three dangerous capabilities:

- `can_read_untrusted`
- `can_access_secrets`
- `can_write_external`

Rule-of-Two+ forbids:

- all three together
- the pair `untrusted + secrets`

### Runtime Safety Context

Static capability is not the full decision point. `SafetyContext` adds:

- current data taint
- effect scopes
- secret scopes
- delegation ancestry
- optional approval token

`ToolDescriptor` describes dynamic effects of tool usage:

- untrusted input handling
- secret access
- external writes
- effect and secret scopes
- approval requirement

### Enforcement Points

Safety is currently enforced in code at:

1. agent creation and dynamic tool grants via `CapabilityValidator`
2. workflow and autonomy approval checks
3. MCP `tools/call` request validation
4. A2A `tasks/send` and `tasks/sendSubscribe`
5. router pre-dispatch validation hooks

## Protocol Boundaries

### MCP

`pylon.protocols.mcp` implements:

- JSON-RPC request/response types
- a method router
- session management
- OAuth 2.1 + PKCE scoped access control
- tools, resources, prompts, and sampling handlers

The MCP server validates:

- DTO shape
- output-validator safety on tool arguments
- `SafetyEngine.evaluate_tool_use(...)`

before invoking a tool handler.

### A2A

`pylon.protocols.a2a` implements:

- task lifecycle state machine
- agent cards and peer registry
- async server handling for send/get/cancel/push-notification
- optional allowed-peer and rate-limit checks

The A2A server derives sender context from local policy or task metadata, then evaluates delegation safety before accepting work.

## Persistence and Replay

Workflow persistence is event-log oriented:

```text
WorkflowRun
  status
  state
  state_version
  state_hash
  event_log[]

Checkpoint
  workflow_run_id
  node_id
  state_version
  state_hash
  event_log[]
```

Checkpoint event records currently include:

- `seq`
- `attempt_id`
- `node_id`
- `input`
- `input_state_version`
- `input_state_hash`
- `state_patch`
- `edge_decisions`
- `llm_events`
- `tool_events`
- `artifacts`
- `metrics`
- `state_version`
- `state_hash`

Persisted metadata is secret-scrubbed before storage. Replay recomputes state hashes and raises on mismatch.

## Sandbox, Secrets, and Tenancy

These subsystems are present as reference implementations:

- `sandbox/`: sandbox manager, executor, registry, policy defaults, resource/network checks
- `secrets/`: in-memory versioned secret manager, Vault protocol, audit, rotation helpers
- `tenancy/`: tenant context propagation, lifecycle manager, quota manager, isolation enforcement

Important current constraint:

- concrete gVisor / Firecracker runtime integrations are not implemented yet
- current sandbox lifecycle is an in-memory manager plus policy model

## Observability and Supporting Systems

Supporting modules already exist and are usable independently:

- `events/`: in-memory pub/sub and dead letters
- `observability/`: metrics, tracing, structured logging, exporters
- `taskqueue/`: priority queue, workers, retry, scheduler
- `plugins/`: plugin manifests, loader, registry, hook system, extension protocols
- `resources/`: rate limiting, quotas, pools, monitoring
- `resilience/`: retry, fallback, circuit breaker, bulkhead
- `state/`: key-value store, generic state machine, snapshots, diffs

## Architectural Reality

The codebase is strongest today in:

- deterministic workflow execution
- safety evaluation at runtime boundaries
- local/in-memory reference implementations for surrounding systems

The main gap is not absence of modules, but uneven maturity between:

- the rich programmatic workflow engine
- the simpler public API / CLI / SDK surfaces
