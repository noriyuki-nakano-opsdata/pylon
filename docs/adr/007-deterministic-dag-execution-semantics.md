# ADR-007: Deterministic DAG Execution Semantics

## Status
Accepted

## Implementation Status
Implemented in the current codebase:

- compiled graph structures and restricted condition compilation
- explicit join policies: `ALL_RESOLVED`, `ANY`, `FIRST`
- structured `NodeResult` with `state_patch`, `edge_decisions`, `artifacts`, and tool/LLM events
- node-scoped checkpoints with state version/hash
- replay that reconstructs state from event logs and verifies state hashes

## Context
The current graph engine intent is strong, but the semantics are underspecified in the places that matter most:

- Fan-out/fan-in behavior is not formally defined
- Join readiness is ambiguous
- Parallel state writes have no deterministic merge contract
- Conditional edge failures can be silently ignored
- `max_steps` and similar limits do not clearly map to run terminal states
- Replay is described as event-sourced, but the event shape is not rich enough to reconstruct execution decisions

For a workflow engine to be auditable, replayable, and safe, it must be more than "async nodes over a dict state". It needs a precise execution model.

## Decision
Pylon workflow runs are defined as deterministic execution of a compiled DAG.

### Core invariants

1. A node executes at most once per workflow run unless an explicit retry policy creates a new attempt.
2. Every edge resolves to one terminal runtime value: `taken`, `not_taken`, or `blocked`.
3. A node is runnable only when all inbound edges are resolved and its join policy is satisfied.
4. Default join policy is `ALL_RESOLVED`.
5. `ANY` and `FIRST` join policies are opt-in and valid only for explicitly marked router/gateway patterns.
6. Conditional evaluation errors are terminal workflow failures, not implicit false branches.
7. Parallel state writes must be merged by an explicit reducer or disjoint namespace policy.
8. A workflow run is `COMPLETED` only when no runnable nodes remain, all reachable nodes are terminal, and no approvals are pending.
9. `max_steps`, deadline expiration, or administrative pause transitions the run to `PAUSED` or `FAILED(limit_exceeded)`, never `COMPLETED`.

### Compilation model

Workflow definitions are compiled into an immutable `CompiledWorkflow` containing:

- validated nodes
- validated edges
- inbound and outbound adjacency indexes
- join policy metadata
- condition bytecode / validated expression AST
- state write policy for each node

Compilation rejects:

- undefined targets
- cycles for DAG workflows
- ambiguous joins
- duplicate node IDs
- condition expressions outside the allowed DSL

### Runtime model

The executor maintains a `WorkflowRuntimeState` with:

- run status
- node status map
- edge status map
- frontier queue
- state version
- state hash
- pending approval wait set

Node statuses are:

- `pending`
- `runnable`
- `running`
- `succeeded`
- `skipped`
- `failed`
- `blocked`

Edge statuses are:

- `pending`
- `taken`
- `not_taken`
- `blocked`

### State update model

Nodes return a `NodeResult`, not a fully merged state object.

`NodeResult` includes:

- `state_patch`
- `artifacts`
- `edge_decisions`
- `llm_events`
- `tool_events`
- `metrics`

The engine commits patches only after conflict detection.

Supported write policies:

- `namespace`: node may write only under its assigned namespace
- `reducer`: writes to shared keys require a named reducer
- `exclusive`: node is sole owner of declared keys

Implicit last-write-wins is forbidden.

### Checkpoint and replay model

Checkpoints are append-only node-attempt records. Each record contains:

- `seq`
- `node_id`
- `attempt_id`
- `input_state_version`
- `input_state_hash`
- `output_patch`
- `artifacts`
- `edge_decisions`
- `llm_call_refs`
- `tool_call_refs`
- `approval_state`
- `state_hash_after_commit`
- secret-scrubbed metadata

Replay reconstructs execution by reapplying recorded decisions and outputs in event order.

Snapshots may exist for acceleration, but correctness is defined solely by replay from the event log.

## Consequences

- Fan-in semantics become explicit and testable
- Replay becomes meaningful for audits, debugging, and recovery
- Parallel execution stays deterministic under load
- Condition bugs fail fast instead of silently changing control flow
- The executor implementation is more structured, but the design is robust enough for multi-tenant and regulated environments
