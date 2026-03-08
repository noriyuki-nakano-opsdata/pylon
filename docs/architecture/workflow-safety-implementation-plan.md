# Workflow and Safety Convergence Implementation Plan

## Purpose

This plan turns the workflow semantics in ADR-007 and the safety boundary model in ADR-008 into an incremental implementation sequence.

The target is a deterministic DAG engine with dynamic safety evaluation, without destabilizing unrelated modules.

## Goals

- Replace implicit frontier union with explicit DAG runtime semantics
- Replace string-inferred safety decisions with structured safety evaluation
- Make checkpoint replay reconstruct execution decisions, not just final state
- Preserve incremental delivery with passing tests at every phase

## Non-Goals

- General cyclic workflow support
- Distributed scheduler redesign
- Full policy pack system
- Multi-language SDK parity in the first pass

## Phase 0: Guardrail Tests First

Status: completed

Add failing tests before refactoring behavior.

### Test additions

- `tests/unit/test_executor.py`
  - join node executes exactly once in diamond graphs
  - `max_steps` does not mark run completed
  - condition evaluation failure raises workflow error
  - parallel write conflict fails deterministically
- `tests/unit/test_workflow.py`
  - explicit join policy validation
  - condition DSL validation rejects unsupported expressions
- `tests/unit/test_safety.py`
  - A2A delegation uses transitive union of sender, receiver, taint, and requested effects
  - remote peer declaration alone cannot authorize secret access or external write
  - approval invalidates on plan/effect expansion
- `tests/integration/test_workflow_safety.py`
  - replay reproduces node order and state hash
  - checkpoint records are node-scoped and secret-scrubbed

## Phase 1: Compile the Workflow Graph

Status: completed

### Deliverables

- Introduce `CompiledWorkflow`, `CompiledNode`, `CompiledEdge`
- Move validation and condition compilation out of ad hoc runtime paths
- Add join policy metadata and inbound/outbound edge indexes

### File targets

- `src/pylon/workflow/graph.py`
- new `src/pylon/workflow/compiled.py`
- new `src/pylon/workflow/conditions.py`

### Acceptance criteria

- Graph compilation rejects invalid joins and unsupported condition syntax
- Runtime no longer calls Python `eval`

## Phase 2: Replace Mutable Dict Execution with Patch Commit Semantics

Status: completed

### Deliverables

- Introduce `NodeResult` and `StatePatch`
- Add commit engine with namespace and reducer policies
- Add node/edge runtime status tracking

### File targets

- `src/pylon/workflow/executor.py`
- new `src/pylon/workflow/state.py`
- new `src/pylon/workflow/commit.py`
- `src/pylon/repository/workflow.py`

### Acceptance criteria

- Diamond joins execute once
- Parallel conflicting writes fail before commit
- `paused` and `failed(limit_exceeded)` statuses are represented explicitly

## Phase 3: Rebuild Checkpoint and Replay

Status: completed

### Deliverables

- Persist node-attempt scoped checkpoint records
- Store state version/hash, edge decisions, and side-effect refs
- Replay from event log as the source of truth

### File targets

- `src/pylon/repository/checkpoint.py`
- `src/pylon/workflow/executor.py`
- new `src/pylon/workflow/replay.py`

### Acceptance criteria

- Replay reconstructs final state and execution order from logs
- Checkpoints no longer flatten multi-node frontiers into a shared `node_id`
- Secret scrubbing is enforced before persistence

## Phase 4: Introduce SafetyContext and SafetyEngine

Status: completed

### Deliverables

- Define `SafetyContext`, `ApprovalToken`, `DelegationRequest`, `SafetyDecision`
- Centralize runtime checks in `SafetyEngine`
- Keep `AgentCapability` as a static envelope, but not the only enforcement point

### File targets

- `src/pylon/safety/capability.py`
- `src/pylon/safety/policy.py`
- new `src/pylon/safety/context.py`
- new `src/pylon/safety/engine.py`
- `src/pylon/types.py`

### Acceptance criteria

- Dynamic tool grants use structured safety metadata
- Hard denials are enforced even with approval
- Sender and child capability union is evaluated transitively

## Phase 5: Wire Safety Through A2A, MCP, and Approval Flow

Status: mostly completed

### Deliverables

- Add structured tool descriptors
- Add local-policy-first A2A delegation checks
- Bind approvals to plan hash and effect envelope

### File targets

- `src/pylon/protocols/a2a/card.py`
- `src/pylon/protocols/a2a/server.py`
- `src/pylon/protocols/mcp/router.py`
- `src/pylon/safety/autonomy.py`
- `src/pylon/approval/manager.py`

### Acceptance criteria

- Peer cards cannot expand authority
- Approval invalidates on scope drift
- Workflow pause/resume integrates with approval wait states

Implemented now:

- local-policy-first A2A delegation checks at `tasks/send` and `tasks/sendSubscribe`
- MCP `tools/call` safety enforcement via `ToolDescriptor`, `SafetyContext`, and output validation
- router pre-dispatch safety validation hooks
- approval drift detection via `plan_hash` and `effect_hash`

Remaining from this phase:

- broader registry/discovery propagation of structured tool descriptors

## Phase 6: Cleanup and API Surface Alignment

Status: mostly completed

### Deliverables

- Align CLI/API run statuses with runtime states
- Update docs and SDK terminology
- Add observability for node attempts, joins, replays, and safety denials

### File targets

- `src/pylon/api/routes.py`
- `src/pylon/cli/commands/run.py`
- `src/pylon/sdk/client.py`
- `src/pylon/observability/metrics.py`
- `docs/api-reference.md`
- `docs/getting-started.md`

### Acceptance criteria

- Public API can report `waiting_approval`, `paused`, `failed(limit_exceeded)`, `failed(state_conflict)`
- Metrics include node attempt count, join wait time, replay count, safety denial count

Implemented now:

- README, architecture, specification, getting-started, API reference, and ADR notes have been refreshed against the actual codebase
- CLI/API/SDK workflow run surfaces now use the same runtime state model for status, stop reason, suspension reason, execution summary, and approval summary
- replay and inspect expose aligned operator-facing payloads

Remaining from this phase:

- expose richer metrics and runtime statuses through public surfaces

## Cross-Cutting Rules

- No phase may rely on silent fallback for invalid workflow conditions
- No phase may reintroduce last-write-wins state merging
- No phase may trust remote peer capability claims as authorization
- Each phase must land with tests and documentation in the same change set

## Recommended Delivery Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6

## Review Checklist

- Does every node transition and edge resolution have an explicit status?
- Can replay reconstruct the same decisions without LLM/tool calls?
- Is every secret-bearing boundary scrubbed before persistence or delegation?
- Can any approval be reused after plan or effect expansion?
- Can any parent-child delegation combine into an unsafe union without being denied?

## Current Snapshot

The implementation has reached a coherent midpoint:

- deterministic DAG execution semantics are live
- replay and checkpoint persistence are event-log based
- secret-scrubbed persistence is live
- approval binding and drift invalidation are live
- A2A/MCP/router safety enforcement is live

The next clean boundary is Phase 6: public API/CLI/runtime observability alignment.
