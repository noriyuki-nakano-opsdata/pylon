# ADR-009: Runtime-Centered Bounded Autonomy

## Status
Accepted

## Context

Pylon already has a relatively strong execution kernel:

- deterministic DAG execution
- compiled workflow conditions
- explicit join policies
- node-scoped checkpoints
- replay with state hash verification
- runtime safety enforcement at MCP and A2A boundaries
- approval binding with plan/effect drift detection

What it does not yet have is a coherent autonomy layer that can:

- express goals and success criteria explicitly
- stop for reasons richer than simple graph exhaustion
- choose models and strategies based on budget and task complexity
- evaluate intermediate and final outputs during execution
- replan safely after failure without collapsing into open-ended agent loops

External frameworks show a convergence pattern:

- deterministic workflow control remains valuable
- dynamic reasoning is introduced in bounded decision points
- evaluation moves closer to the runtime
- cost and safety governance become first-class

Pylon should evolve in that direction without discarding its existing deterministic and auditable runtime.

## Decision

Pylon vNext adopts a three-layer runtime-centered architecture:

1. `Execution Kernel`
2. `Cognitive Layer`
3. `Governance Layer`

The execution kernel remains the source of truth for ordering, persistence, and replay.
LLMs and planners do not control the runtime directly; they operate within bounded decision surfaces defined by the kernel and enforced by governance.

### Core principles

#### 1. Deterministic workflow kernel

The kernel remains DAG-based in the near-to-medium term.

- compiled workflow topology remains authoritative
- node scheduling remains deterministic
- replay remains event-log based
- implicit open-ended agent loops are not allowed in the kernel

General cyclic workflow support is explicitly deferred.

#### 2. Dynamic but bounded autonomy

Autonomy is allowed only inside declared limits.

- model-driven routing may choose among finite, prevalidated options
- replanning may only produce actions that still fit the approved safety and effect envelope
- iterative refinement must be bounded by explicit termination policy
- every autonomous run must have resource ceilings

#### 3. Evaluation-native runtime

Evaluation becomes a first-class runtime concern rather than an external convenience.

- runtime may score tool trajectories
- runtime may score final and intermediate outputs
- runtime may stop on quality satisfaction or safety failure
- runtime may trigger refinement or escalation from evaluator output

#### 4. Local-policy-first protocol boundaries

External protocols remain integration layers, not sources of authority.

- MCP tool annotations are advisory only
- A2A agent cards are advisory only
- local policy and runtime safety stay authoritative
- remote metadata may influence UX and routing but not authorization

#### 5. Cost-aware model routing

Model selection becomes a runtime responsibility.

- routing must account for task complexity, latency target, and remaining budget
- caching and batching are part of the orchestration strategy
- token, cost, and cache metrics must become visible runtime state

## Architectural shape

### Execution Kernel

Owned primarily by:

- `pylon.workflow`
- `pylon.repository`
- `pylon.approval`

Responsibilities:

- compiled workflow execution
- patch commit semantics
- checkpointing and replay
- pause/resume
- approval-aware waiting states
- protocol bridge handoff into tools and remote agents

### Cognitive Layer

Introduced primarily as a new package:

- `pylon.autonomy`

Responsibilities:

- `GoalSpec`
- `TerminationPolicy`
- `Planner`
- `Critic`
- `Verifier`
- `ReplanEngine`
- `ModelRouter`
- `ContextManager`

This layer may use LLMs, but it does not own workflow ordering or policy enforcement.

### Governance Layer

Owned primarily by:

- `pylon.safety`
- `pylon.approval`
- `pylon.tenancy`
- `pylon.control_plane`

Responsibilities:

- hard safety denials
- approval gates
- token/cost/time/iteration quotas
- auditability
- kill switches
- externally visible execution status

## Scope boundaries

### In scope for vNext

- goal-conditioned execution on top of the existing DAG kernel
- composable termination policies
- bounded refinement loops
- runtime-native evaluators
- model routing and cost controls
- protocol bridge maturity for MCP and A2A

### Explicitly out of scope for the first pass

- unrestricted cyclic workflows
- unconstrained autonomous planning
- trust in remote protocol declarations as authority
- full distributed durable execution redesign

## Consequences

- Pylon keeps its strongest property: auditable deterministic execution
- autonomy becomes compositional instead of ad hoc
- evaluation and cost governance can influence runtime decisions directly
- the codebase gains a clearer separation between runtime control and model reasoning
- API, CLI, and SDK expose richer run state and stop reasons for workflow runs, and that surface now needs to stay aligned as the cognitive layer grows
