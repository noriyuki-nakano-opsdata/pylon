# Experiment Campaigns Production Plan

## Goal

Add a production-grade autonomous experiment capability to Pylon that preserves
the useful operator experience of `pi-autoresearch` while conforming to
Pylon's existing runtime, control-plane, safety, approval, observability, and
multi-tenant architecture.

The resulting feature is called **Experiment Campaigns**.

It is not a direct port of a local extension. It is a governed, durable,
operator-facing control-plane feature for running bounded optimization loops
against real workspaces and repositories.

## Design Standard

"Beautiful" in this context means:

- one canonical source of truth for campaign state
- one explicit owner for each lifecycle concern
- no hidden local file becomes the authoritative system state
- exploration and promotion are separated
- iteration isolation is structural, not heuristic
- bounded autonomy is encoded in policy, not left to prompt folklore
- operator APIs expose durable state transitions, not incidental side effects
- restart, retry, approval, and audit semantics remain deterministic

## Problem Statement

`pi-autoresearch` proves that autonomous optimization loops are highly useful
for coding and benchmarking workflows. However, its architecture is intentionally
local-first:

- file-based state (`autoresearch.jsonl`, `autoresearch.md`)
- direct shell execution
- local git mutation and revert patterns
- unbounded auto-resume semantics
- TUI-only visibility

Those properties are acceptable for a trusted single-user agent environment.
They are not acceptable as the primary production architecture inside Pylon.

Pylon already has stronger primitives:

- durable control-plane state
- canonical run records and query projections
- bounded autonomy goals and termination policies
- approval and audit semantics
- SSE operator surfaces
- tenant isolation and scope-aware APIs

The correct design is to model autonomous experimentation as a Pylon-native
control-plane domain, not as a local extension bolted onto the side.

## Non-Goals

- reproducing the Pi widget or terminal overlay UX
- introducing generalized unbounded cyclic workflow execution
- allowing direct mutation of shared workspaces without isolation
- making benchmark scripts the primary system of record
- bypassing approval or safety rules for "faster experimentation"

## Product Definition

An **Experiment Campaign** is a tenant-scoped, durable optimization program
with:

- an objective
- a workspace or repository target
- a primary metric
- optional secondary metrics
- quality gates
- bounded budgets and stop conditions
- an iteration history
- candidate promotion semantics
- operator-facing live telemetry

Each campaign produces **Experiment Iterations**. An iteration is a single
attempted change set plus execution result, metrics, artifacts, gate results,
and promotion decision.

## Canonical Domain Model

### 1. ExperimentCampaign

Persistent command model for the campaign.

Required fields:

- `id`
- `tenant_id`
- `status`: `draft | running | paused | completed | failed | cancelled`
- `objective`
- `workspace`
- `repo`
- `base_branch`
- `campaign_branch`
- `metric_spec`
- `gate_spec`
- `budget_spec`
- `planner_spec`
- `record_version`
- `created_at`, `updated_at`, `started_at`, `completed_at`
- `best_iteration_id`
- `baseline_iteration_id`
- `latest_iteration_id`
- `stop_reason`
- `summary`

### 2. ExperimentIteration

Child record representing one concrete loop turn.

Required fields:

- `id`
- `campaign_id`
- `sequence`
- `status`: `pending | running | benchmark_failed | checks_failed | discarded | kept | promoted | failed`
- `workspace_ref`
- `candidate_branch`
- `commit_before`
- `commit_after`
- `description`
- `primary_metric`
- `secondary_metrics`
- `benchmark_result`
- `gate_results`
- `artifacts`
- `decision`
- `run_id`
- `created_at`, `started_at`, `completed_at`

### 3. ExperimentMetricSpec

Defines how a metric is extracted and compared.

Required fields:

- `name`
- `unit`
- `direction`: `lower` or `higher`
- `extractor`: `stdout_metric | json_path | regex | custom`
- `source`
- `required`

### 4. ExperimentGateSpec

Defines correctness and policy backpressure.

Required fields:

- `commands`
- `timeout_seconds`
- `blocking`
- `approval_on_failure`
- `artifact_capture`

### 5. PromotionDecision

Separates exploratory success from repository promotion.

States:

- `candidate_only`
- `eligible_for_promotion`
- `promotion_pending_approval`
- `promoted`
- `promotion_rejected`

This separation is a core invariant. A good benchmark result is not the same as
a safe production change.

## Persistence Strategy

### Command Side

Use control-plane `surface_records` first, with dedicated namespaces:

- `experiment_campaigns`
- `experiment_iterations`
- `experiment_worker_leases`
- `experiment_artifacts`
- `experiment_templates`

Why this is the right v1:

- it matches the existing lifecycle and skill-import patterns
- it already has optimistic concurrency via `record_version`
- it works across file and SQLite control-plane stores
- it preserves the current write-side architecture

### Query Side

Campaign detail and list payloads are derived projections.

Do not let UI pages read raw iteration storage directly. Build explicit query
builders for:

- campaign list summary
- campaign detail
- live campaign telemetry
- promotion queue view
- operator audit slice

### Optional Workspace Artifacts

For portability and agent continuity, campaigns may materialize workspace
artifacts under a Pylon-owned directory such as:

`.pylon/experiments/<campaign-id>/`

Examples:

- `brief.md`
- `benchmark.sh`
- `checks.sh`
- `iteration-summary.json`

These are operator aids, not the source of truth.

## Execution Architecture

### Runner Model

Implement a dedicated `ExperimentCampaignRunner`.

Do not overload generic `queued` workflow execution for this feature.
The runner is a control-plane orchestration loop that creates and supervises
normal workflow runs and benchmark executions as campaign children.

### Recommended Loop

1. Validate campaign inputs and workspace eligibility.
2. Create or attach isolated workspace context.
3. Establish baseline iteration.
4. Ask planner/coder agent for the next candidate change.
5. Apply the change in an isolated worktree.
6. Run benchmark.
7. Extract metrics.
8. Run quality gates.
9. Compare against baseline and current best.
10. Mark iteration as discarded, kept, or promotion-eligible.
11. Evaluate stop conditions.
12. Continue, pause, escalate, or complete.

### Bounded Autonomy

Every campaign must carry explicit stop conditions derived from Pylon's
termination model:

- max iterations
- timeout
- cost budget
- token budget
- external stop
- stuck detection
- optional quality threshold

The Pi-style "never stop" behavior is intentionally not a production default.

## Workspace and Git Isolation

### Invariant

Never mutate the shared repository working tree directly as the primary loop
mechanism.

### Recommended Strategy

- one campaign-level branch for durable lineage
- one ephemeral git worktree per iteration
- benchmark and gate execution inside sandboxed isolated workspace
- discard by destroying the worktree
- keep by persisting the candidate commit/branch
- promote by explicit merge or fast-forward policy after approval

### Why This Matters

This removes dependence on `git checkout -- .` and makes recovery,
cancellation, orphan cleanup, and audit structurally reliable.

## Sandbox and Benchmark Execution

The simulated `SandboxExecutor` is not sufficient for production experiment
execution. Experiment Campaigns must route benchmark and gate commands through a
real execution backend.

Supported backends at launch:

- Docker sandbox backend for self-hosted environments
- E2B-backed sandbox for managed isolation

The execution contract must capture:

- stdout/stderr
- exit code
- duration
- timeout
- backend identity
- retained artifacts
- resource usage where available

## Public API Shape

Recommended routes:

- `POST /api/v1/experiments`
- `GET /api/v1/experiments`
- `GET /api/v1/experiments/{id}`
- `POST /api/v1/experiments/{id}/start`
- `POST /api/v1/experiments/{id}/pause`
- `POST /api/v1/experiments/{id}/resume`
- `POST /api/v1/experiments/{id}/cancel`
- `POST /api/v1/experiments/{id}/promote`
- `GET /api/v1/experiments/{id}/iterations`
- `GET /api/v1/experiments/{id}/events`
- `GET /api/v1/experiments/{id}/artifacts/{artifact_id}`

Required scopes:

- `experiments:read`
- `experiments:write`
- `experiments:stop`
- `experiments:promote`

## UI Shape

Primary surface:

- top-level `Experiments` page
- list of campaigns
- live detail view
- baseline vs best comparison
- iteration timeline
- gate result visibility
- promotion queue
- live log and telemetry panels

Secondary integrations:

- show experiment-linked child runs in `Runs`
- expose campaign summary from lifecycle `Iterate` or `Development` when relevant

## Governance and Safety

### Hard Rules

- promotion is approval-aware
- policy exceptions are approval-aware
- network egress is backend-policy controlled
- experiment runner obeys tenant quotas
- kill switch can pause or cancel campaigns
- audit entries are emitted for start, pause, resume, cancel, promote, and approval decisions

### Approval Guidance

Require approval for:

- promotion into protected branches
- host-level execution
- non-default network egress
- quality gate bypass
- sandbox tier downgrade

## Observability

Add experiment-native telemetry:

- campaign counts by status
- active iterations
- gate failure rate
- average benchmark duration
- promotion conversion rate
- cost per campaign
- stuck campaign count
- orphan worktree count

Tracing should connect:

- campaign
- iteration
- child run
- sandbox execution
- promotion action

## Recommended Module Layout

Backend:

- `src/pylon/experiments/__init__.py`
- `src/pylon/experiments/models.py`
- `src/pylon/experiments/service.py`
- `src/pylon/experiments/runner.py`
- `src/pylon/experiments/evaluator.py`
- `src/pylon/experiments/gitops.py`
- `src/pylon/experiments/metrics.py`
- `src/pylon/experiments/gates.py`
- `src/pylon/experiments/query.py`
- `src/pylon/experiments/contracts.py`

API:

- extend `src/pylon/api/routes.py`
- extend `src/pylon/api/schemas.py`
- extend API reference docs

UI:

- `ui/src/api/experiments.ts`
- `ui/src/pages/Experiments.tsx`
- `ui/src/pages/ExperimentDetail.tsx`
- `ui/src/hooks/useExperimentCampaign.ts`
- `ui/src/types/experiments.ts`

Tests:

- `tests/unit/test_experiment_service.py`
- `tests/unit/test_experiment_runner.py`
- `tests/unit/test_experiment_query.py`
- `tests/unit/test_experiment_gitops.py`
- `tests/unit/test_experiment_api.py`
- `ui/src/api/__tests__/experiments.contract.test.ts`

## Delivery Phases

### Phase 0. Architecture Lock

- ADR
- domain contract
- storage namespaces
- promotion semantics
- metric extraction contract

### Phase 1. Backend Foundation

- campaign service
- persistence
- query builders
- list/detail APIs

### Phase 2. Runner and Isolation

- campaign runner
- worktree manager
- sandbox execution
- metric extraction
- quality gates

### Phase 3. Operator Experience

- SSE live stream
- experiments UI
- detail dashboard
- iteration drill-down

### Phase 4. Governance and GA

- approvals
- quotas
- audit and telemetry
- recovery and cleanup
- docs and recipes

## Success Criteria

- campaigns survive process restart with no state loss
- paused and running campaigns reconcile correctly after restart
- discarded iterations leave the base repo clean
- operator can explain why a candidate was kept, discarded, or blocked
- promotion requires the right level of approval and produces audit entries
- live detail view reflects campaign state without polling drift
- campaign state is tenant-scoped and concurrency-safe

## Launch Recommendation

Ship in two cuts:

1. **Internal beta**
   - Docker/E2B backend
   - single promotion policy
   - core API and UI
   - bounded runner

2. **GA**
   - quotas
   - richer analytics
   - approval escalation rules
   - lifecycle integration
   - recipe library
