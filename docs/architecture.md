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

## Package Map

At a coarse level, the packages line up like this:

| Concern | Primary Packages | Notes |
|---------|------------------|-------|
| Config and bootstrapping | `pylon.dsl`, `pylon.config`, `pylon.cli` | DSL parsing, local config/state, project bootstrap |
| Execution runtime | `pylon.workflow`, `pylon.agents` | The most mature runtime path in the repository |
| Safety | `pylon.safety`, `pylon.approval` | Static capability rules plus runtime boundary enforcement |
| External protocol boundaries | `pylon.protocols.mcp`, `pylon.protocols.a2a`, `pylon.providers` | JSON-RPC surfaces, OAuth, peer/task routing, LLM abstraction |
| Persistence and replay | `pylon.repository`, `pylon.state`, `pylon.events` | Workflow runs, checkpoints, memory repository, state machine/snapshots, event bus |
| Operational infrastructure | `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy` | Mostly reference implementations with real policy models |
| Cross-cutting utilities | `pylon.resources`, `pylon.resilience`, `pylon.observability` | Limits, retries, metrics, tracing, exporters |
| Extension and scheduling | `pylon.plugins`, `pylon.taskqueue`, `pylon.control_plane`, `pylon.coding` | Plugin system, queues, registry/scheduler helpers, coding loop |

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

These surfaces are still local-first and in-memory, but workflow execution now aligns through the shared runtime helpers in `pylon.runtime.execution`:

- `pylon.cli` stores local state in `$PYLON_HOME` / `~/.pylon`
- `pylon.api` still uses an in-memory `RouteStore`, but it now registers canonical workflow definitions, executes workflow runs through the shared runtime, and exposes resume/approve/replay control-plane routes
- `pylon.sdk.PylonClient` remains an in-memory client, but workflow execution now uses registered canonical definitions and SDK authoring surfaces (`WorkflowBuilder`, `WorkflowGraph`, `@workflow`) that materialize into `PylonProject`, while ad hoc callables remain on a separate explicit helper surface

That means the public surfaces are still not distributed transports, but they now expose the same workflow run-state model.

## Runtime Flow Summary

There are four important execution paths in the current codebase.

### 1. Programmatic workflow execution

```text
WorkflowGraph
  -> validate()
  -> compile()
  -> GraphExecutor.execute(...)
  -> node handler returns dict | NodeResult
  -> CommitEngine.apply_patches(...)
  -> WorkflowRun.event_log append
  -> CheckpointRepository.create(...)
  -> ReplayEngine.replay_event_log(...)
```

This is the path where deterministic execution semantics are strongest.

### 2. MCP tool invocation

```text
JsonRpcRequest
  -> MethodRouter request validator
  -> DTO validation
  -> OutputValidator.validate_tool_call_detailed(...)
  -> resolve ToolDescriptor
  -> SafetyEngine.evaluate_tool_use(...)
  -> tool handler invocation
```

The safety decision happens before the handler is called.

### 3. A2A delegation

```text
incoming task/send or sendSubscribe
  -> peer allowlist / authenticated sender checks
  -> rate-limit check
  -> build or load sender SafetyContext
  -> SafetyEngine.evaluate_delegation(...)
  -> accept task and transition lifecycle
```

Remote metadata can contribute hints, but local policy stays authoritative.

### 4. CLI local run flow

```text
pylon run
  -> load_project(".")
  -> compile_project_graph(...)
  -> execute_project_sync(...)
    -> GraphExecutor.execute(...)
    -> checkpoint / approval / metrics collection
  -> serialize_run(...)
  -> write local run/checkpoint/sandbox/approval records
  -> render CLI output
```

This is now a thin local-state wrapper around the shared workflow runtime.

### 5. SDK workflow authoring flow

```text
WorkflowBuilder | WorkflowGraph | @workflow factory | PylonProject
  -> materialize_workflow_definition(...)
  -> canonical PylonProject + handler registries
  -> execute_project_sync(...)
    -> GraphExecutor.execute(...)
  -> serialize_run(...)
  -> WorkflowRun snapshot
```

This keeps SDK-defined workflows on the same runtime semantics as DSL and API
workflow runs instead of introducing a second execution engine.

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

## Public Surface Boundaries

The repository currently exposes three user-facing surfaces with different maturity levels:

| Surface | Backing implementation | Current character |
|---------|------------------------|-------------------|
| CLI | `pylon.cli` + local JSON/YAML state | local developer workflow and demos |
| API | `pylon.api` + in-memory `RouteStore` | lightweight embedded HTTP-style contract |
| SDK | `pylon.sdk` | in-memory client/builder/decorator convenience layer |

The workflow core lives behind those surfaces rather than being uniformly wired through them.

## Sandbox, Secrets, and Tenancy

These subsystems are present as reference implementations:

- `sandbox/`: sandbox manager, executor, registry, policy defaults, resource/network checks
- `secrets/`: in-memory versioned secret manager, Vault protocol, audit, rotation helpers
- `tenancy/`: tenant context propagation, lifecycle manager, quota manager, isolation enforcement

Important current constraint:

- concrete gVisor / Firecracker runtime integrations are not implemented yet
- current sandbox lifecycle is an in-memory manager plus policy model

## Maturity Boundaries

The cleanest way to reason about the system today is to split it into three maturity bands.

### Mature and internally coherent

- compiled workflow execution
- join semantics
- checkpoint and replay model
- runtime safety evaluation at MCP/A2A boundaries
- approval binding and drift detection

### Useful reference implementations

- sandbox lifecycle and policy
- secret management
- event bus
- API route store
- SDK client
- CLI persisted state model
- tenancy, plugins, taskqueue, coding loop

### Designed but not fully wired end-to-end

- public API/CLI/SDK exposure of workflow runtime richness
- workflow approval wait-state integration in the executor
- non-memory infrastructure backends
- concrete high-isolation sandbox backends

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

## Further Reading

- [Runtime Flows](architecture/runtime-flows.md)
- [Module Map](architecture/module-map.md)
- [Workflow/Safety Implementation Plan](architecture/workflow-safety-implementation-plan.md)
- [Pylon vNext Target Architecture](architecture/pylon-vnext-target-architecture.md)
- [Pylon vNext Type Design](architecture/pylon-vnext-type-design.md)
- [Pylon vNext Implementation Plan](architecture/pylon-vnext-implementation-plan.md)
- [ADR-009: Runtime-Centered Bounded Autonomy](adr/009-runtime-centered-bounded-autonomy.md)
