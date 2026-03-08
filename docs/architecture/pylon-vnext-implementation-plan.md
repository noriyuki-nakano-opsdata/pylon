# Pylon vNext Implementation Plan

## Purpose

This plan turns the vNext architecture into an ordered delivery sequence that
fits the current repository rather than an idealized rewrite.

It assumes the current state described in:

- `docs/SPECIFICATION.md`
- `docs/architecture/workflow-safety-implementation-plan.md`
- `docs/adr/009-runtime-centered-bounded-autonomy.md`

## Guiding Rules

- preserve deterministic workflow semantics
- do not regress replay fidelity
- do not bypass local-policy-first safety checks
- add public-surface alignment early enough to avoid another model split
- land every phase with tests, docs, and observable runtime behavior

## Phase 0: Normalize Runtime State And Stop Reasons

Status: completed

### Why first

The current code already has richer internal semantics than the CLI, API, and
SDK expose. Before adding autonomy, the repository needs one shared projection
of run state.

### Deliverables

- shared run phase / stop reason types
- approval wait-state integration in the workflow executor
- API/CLI/SDK mapping to the same runtime states
- event log fields for stop reason and suspension reason

### Primary file targets

- `src/pylon/types.py`
- `src/pylon/workflow/executor.py`
- `src/pylon/repository/workflow.py`
- `src/pylon/cli/commands/run.py`
- `src/pylon/api/routes.py`
- `src/pylon/sdk/client.py`

### Acceptance criteria

- one run state model is used across runtime, CLI, API, and SDK
- approval waits are represented as runtime state, not only side records
- `paused` carries a machine-readable reason

## Phase 1: Add Composable Termination Policy

Status: completed

### Deliverables

- new `pylon.autonomy.termination`
- primitive termination conditions
- composable `all` / `any` policies
- executor hook to evaluate termination after each node attempt

### Initial termination conditions

- max iterations
- timeout
- token budget
- cost budget
- external stop

### Primary file targets

- new `src/pylon/autonomy/termination.py`
- new `src/pylon/autonomy/context.py`
- `src/pylon/workflow/executor.py`
- `src/pylon/safety/policy.py`
- `src/pylon/control_plane/tenant/quota.py`

### Acceptance criteria

- runs can stop for reasons other than graph exhaustion
- stop reason is visible in replay and public status
- at least one `all` and one `any` composed policy are tested

## Phase 2: Introduce GoalSpec And Bounded Autonomy Context

Status: completed

### Deliverables

- `GoalSpec`, `GoalConstraints`, `SuccessCriterion`
- `AutonomyContext`
- DSL and programmatic constructors for goal-aware runs
- bounded effect/secret scope declaration at goal level

### Primary file targets

- new `src/pylon/autonomy/goals.py`
- `src/pylon/dsl/parser.py`
- `src/pylon/workflow/executor.py`
- `src/pylon/safety/context.py`
- `docs/getting-started.md`

### Acceptance criteria

- a run may start with a `GoalSpec`
- success criteria and resource ceilings are visible at runtime
- goal scope cannot silently expand beyond approval or policy bounds

## Phase 3: Add Model Router And Cost Telemetry

Status: completed

### Deliverables

- `ModelRouter`
- provider/model tier abstraction
- per-run token and cost accounting
- cache strategy decision surface
- optional batch eligibility hints

### Primary file targets

- new `src/pylon/autonomy/routing.py`
- `src/pylon/providers/base.py`
- `src/pylon/providers/anthropic.py`
- new provider adapters as needed
- `src/pylon/observability/metrics.py`
- `src/pylon/control_plane/tenant/quota.py`

### Acceptance criteria

- routing can choose among at least three model tiers
- provider usage is accumulated into run-level telemetry
- cache strategy is recorded in event logs for routed model calls

## Phase 4: Add Evaluation-Native Runtime

Status: completed

### Deliverables

- `Critic`
- `Verifier`
- evaluation result types
- runtime hooks for response, trajectory, hallucination, and safety scoring
- `EvalSet` fixtures for repeatable tests

### Primary file targets

- new `src/pylon/autonomy/evaluation.py`
- new `src/pylon/autonomy/planner.py`
- `src/pylon/workflow/result.py`
- `src/pylon/workflow/executor.py`
- new `tests/evals` fixtures or equivalent

### Acceptance criteria

- evaluation can run during workflow execution, not only offline
- verification can return `success`, `refine`, `escalate`, or `fail`
- event log records evaluation results or durable references to them

## Phase 5: Add Bounded Refinement Loop

Status: completed

### Deliverables

- `LoopNode` or `RefinementNode`
- writer/critic/refine execution pattern
- bounded iteration semantics
- explicit exhaustion behavior

### Primary file targets

- `src/pylon/types.py`
- `src/pylon/workflow/graph.py`
- `src/pylon/workflow/compiled.py`
- `src/pylon/workflow/executor.py`
- new `src/pylon/autonomy/replan.py`

### Acceptance criteria

- refinement loops remain replayable
- loop iterations are visible in checkpoints and event logs
- loop exhaustion yields a structured terminal or escalation decision

## Phase 6: Add Stuck Detection And Replanning

Status: in progress

### Deliverables

- `StuckDetector`
- bounded `ReplanEngine`
- failure recovery hooks that remain inside approved branch space

### Primary file targets

- new `src/pylon/autonomy/replan.py`
- new `src/pylon/autonomy/context.py`
- `src/pylon/workflow/executor.py`
- `src/pylon/observability/metrics.py`

### Acceptance criteria

- repeated low-value behavior can be detected and surfaced
- replanning does not create arbitrary new effect scopes
- stuck detection can terminate or escalate deterministically

## Phase 7: Mature MCP And A2A As Kernel Bridges

Status: in progress

### Deliverables

- MCP client integration for external tools
- A2A workflow bridge nodes
- protocol event normalization into workflow event logs
- stronger public status projection for remote tasks

### Primary file targets

- `src/pylon/protocols/mcp/client.py`
- `src/pylon/protocols/mcp/server.py`
- `src/pylon/protocols/a2a/client.py`
- `src/pylon/protocols/a2a/server.py`
- `src/pylon/workflow/executor.py`

### Acceptance criteria

- workflow nodes can call MCP tools through a normalized bridge
- workflow nodes can delegate to A2A peers through a normalized bridge
- remote metadata never overrides local safety policy

## Phase 8: Public Surface And Operator Experience

Status: in progress

### Deliverables

- `pylon inspect` richer runtime views
- `pylon replay` and `pylon eval` operator-grade output
- governance and cost dashboards
- plugin extension points for evaluators, routers, and critics

### Primary file targets

- `src/pylon/cli/commands/*`
- `src/pylon/api/routes.py`
- `src/pylon/sdk/client.py`
- `src/pylon/plugins/types.py`
- `src/pylon/plugins/hooks.py`
- `src/pylon/observability/*`

### Acceptance criteria

- operators can inspect why a run stopped or escalated
- CLI/API/SDK expose the same stop reasons and evaluation summaries
- custom routing/evaluation plugins can be registered without patching the core

Current implemented subset:

- `pylon inspect` exposes `execution_summary`, `approval_summary`, `policy_resolution`, and state hashes
- `pylon replay` returns the same normalized payload shape with `view_kind = "replay"`
- API and SDK workflow run views expose the same runtime-oriented stop reasons and summaries

## Recommended Delivery Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7
9. Phase 8

## Testing Strategy

Every phase should land with:

- unit tests for the new type system and decision logic
- integration tests for workflow execution behavior
- replay tests covering new event shapes
- protocol-boundary tests for MCP and A2A interactions
- documentation updates in the same change set

## Review Checklist

- Does the new feature preserve deterministic replay?
- Is every autonomy decision bounded by explicit policy or topology?
- Is every stop reason machine-readable and externally visible?
- Can the same run be inspected from CLI, API, and SDK without semantic drift?
- Can remote metadata influence behavior without becoming authorization?
- Is cost visibility present before cost automation becomes more aggressive?
