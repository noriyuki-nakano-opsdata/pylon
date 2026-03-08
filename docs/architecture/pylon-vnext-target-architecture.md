# Pylon vNext Target Architecture

## Purpose

This document describes the target architecture for Pylon after the current
workflow/safety convergence work. It is intentionally future-facing and should
be read together with:

- `docs/SPECIFICATION.md` for implemented behavior
- `docs/adr/009-runtime-centered-bounded-autonomy.md` for architectural intent
- `docs/architecture/workflow-safety-implementation-plan.md` for the already active workflow/safety track

## Design Goal

Pylon should evolve into an evaluation-native autonomous runtime where:

- the runtime controls execution
- models provide bounded reasoning
- governance controls cost, risk, and escalation
- all important decisions remain auditable and replayable

The target is not a free-form chat agent framework. The target is a
runtime-centered system for safe, inspectable, goal-conditioned execution.

## Layered Model

```text
+---------------------------------------------------------------------+
| Layer 3: Governance Layer                                           |
| safety / approval / tenancy / control_plane / observability         |
| termination, approval, quotas, audit, kill switch, policy           |
+---------------------------------------------------------------------+
| Layer 2: Cognitive Layer                                            |
| autonomy/                                                           |
| GoalSpec, Planner, Critic, Verifier, ModelRouter, Replan, Context   |
+---------------------------------------------------------------------+
| Layer 1: Execution Kernel                                           |
| workflow / repository / protocols bridge                            |
| DAG runtime, commit, replay, checkpoint, node execution, streaming  |
+---------------------------------------------------------------------+
```

## Layer 1: Execution Kernel

This layer remains the center of the system.

### Responsibilities

- compile workflow graphs
- execute nodes under deterministic scheduling
- persist checkpoints and event logs
- replay and verify state hashes
- expose pause/resume semantics
- provide protocol bridge points for tool and agent delegation

### Required evolutions

#### Approval-aware pause/resume

The executor must move from simple `PAUSED` semantics to explicit suspension
reasons that include approval waits.

Target behavior:

- `PAUSED(limit_exceeded)`
- `PAUSED(external_stop)`
- `WAITING_APPROVAL`

#### Durability modes

Checkpoint persistence should become configurable:

- `exit`: flush at workflow exit or pause only
- `async`: enqueue checkpoint persistence out of band
- `sync`: persist before advancing runtime state

#### Stream engine

The kernel should expose streaming views of execution:

- state/value updates
- node progress updates
- model token stream
- custom runtime events

#### Protocol bridge

Protocol integration should become a formal kernel surface:

- MCP client bridge for tool discovery and tool calls
- A2A bridge nodes for remote task delegation
- normalized event records for protocol-originated actions

## Layer 2: Cognitive Layer

This is the major missing subsystem today.

The recommended package is:

- `src/pylon/autonomy`

This keeps cognitive orchestration separate from `pylon.workflow`,
`pylon.safety`, and the simpler `pylon.coding` helpers.

### Core concepts

#### GoalSpec

Declarative definition of:

- objective
- success criteria
- failure policy
- allowed side effects
- quality thresholds
- budget and time ceilings

#### Planner

Produces bounded plans inside a prevalidated action space.

The planner may:

- pick among finite branches
- propose refinement passes
- choose a model tier
- request escalation

The planner may not:

- create arbitrary new effect scopes
- bypass workflow topology
- bypass safety policy

#### Critic

Produces quality and process judgments.

Initial evaluation dimensions should be:

- response quality
- tool trajectory quality
- hallucination risk
- safety risk

#### Verifier

Aggregates critic and deterministic checks into a decision:

- success reached
- refine again
- escalate
- fail

#### Replan engine

Allows bounded recovery after:

- tool failure
- quality failure
- branch dead-end
- stuck detection

Replanning must remain within workflow-approved alternatives or explicitly
raise an escalation request.

#### Model router

Selects a provider/model tier based on:

- task complexity
- cost remaining
- latency target
- cacheability
- tool requirements

#### Context manager

Owns:

- cached static prefixes
- rolling context windows
- compression or summarization
- context provenance

## Layer 3: Governance Layer

This layer extends what already exists in `pylon.safety` and `pylon.approval`.

### Responsibilities

- hard policy denials
- composable termination
- approval gates
- quota enforcement
- audit and replay visibility
- protocol-facing trust boundaries

### Termination policy

Termination must be explicit and composable.

Target primitive conditions:

- `MaxIterations`
- `TokenBudget`
- `CostBudget`
- `Timeout`
- `ExternalStop`
- `QualityThreshold`
- `StuckDetected`
- `ApprovalDenied`

Target composition:

- `A | B`
- `A & B`
- grouped declarative policies

### Approval gate

Approval should support:

- pre-node gate
- post-node gate
- edit-and-resume
- reject-and-reroute
- bound plan/effect revalidation on resume

### Cost governance

Cost enforcement should combine:

- per-node token usage
- per-run cost accumulation
- tenant quota
- route-time model selection
- caching and batch eligibility

## Cross-Layer Interaction

### Kernel -> Cognitive

The kernel emits:

- node result
- state snapshot reference
- cost/timing usage
- tool trajectory
- errors and stop reasons

The cognitive layer returns:

- continue
- refine
- reroute within bounded options
- escalate
- terminate as success
- terminate as failure

### Cognitive -> Governance

Every requested action from the cognitive layer is checked before execution:

- model selection
- tool use
- approval-sensitive branch
- side-effecting action
- remote delegation

### Governance -> Kernel

Governance may:

- pause execution
- deny action
- require approval
- reduce available budget
- force termination

## Why DAG First Still Matters

Pylon should not rush into unrestricted cyclic graphs.

Reasons:

- replay and audit are easier to reason about
- effect envelopes and approval scopes stay tighter
- public status reporting stays simpler
- bounded refinement can be added with a dedicated loop construct first

The recommended path is:

1. keep DAG workflows
2. add bounded `LoopNode` or `RefinementNode`
3. revisit general cyclic graphs only after the autonomy layer matures

## Reference Influence Map

### LangGraph

Adopt:

- durability modes
- interrupt/resume thinking
- stronger streaming model

Do not adopt directly:

- unrestricted cyclic runtime as an early move

### Google ADK

Adopt:

- workflow plus dynamic reasoning split
- evaluation-native design
- context caching/compression patterns

### AutoGen

Adopt:

- composable termination conditions

### CrewAI

Adopt:

- approval and feedback routing concepts

### OpenHands

Adopt:

- bounded autonomy
- stuck detection
- iterative refinement patterns

### MCP and A2A

Adopt:

- standard external protocol surfaces
- clear separation between agent-to-tool and agent-to-agent paths

Preserve:

- local-policy-first enforcement

## Success Criteria For vNext

Pylon should be considered on-track when it can do all of the following
coherently:

- execute deterministic workflows with pause/resume and approval waits
- run bounded refinement loops against declared quality thresholds
- route tasks across model tiers under explicit budget ceilings
- evaluate outputs and trajectories during execution
- expose auditable stop reasons and replayable event logs
- integrate MCP and A2A without trusting remote metadata as authority
