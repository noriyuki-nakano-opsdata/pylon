# Experiment Campaigns Epics and Tickets

## Planning Assumptions

- Ticket IDs use the `EC-###` format.
- Estimates use `S`, `M`, `L`, `XL`.
- Dependencies are strict sequencing hints, not a substitute for engineering judgment.
- Every ticket must end with tests or explicit test debt tracking.
- No ticket may introduce a second source of truth for campaign state.

## Delivery Waves

- **Wave 0**: architecture and contracts
- **Wave 1**: persistence and control-plane foundation
- **Wave 2**: runner, workspace isolation, benchmark execution
- **Wave 3**: API, streaming, UI
- **Wave 4**: governance, observability, launch

---

## EPIC EC-01: Architecture and Domain Contracts

**Outcome:** Experiment Campaigns have a stable domain language, explicit invariants, and an ADR-quality contract before implementation spreads across backend and UI.

### EC-001 ADR for Experiment Campaigns

- Estimate: `M`
- Dependencies: none
- Deliverables:
  - architecture decision record
  - design invariants
  - runner vs workflow rationale
  - promotion model
- Acceptance criteria:
  - explains why direct `pi-autoresearch` port is rejected
  - locks canonical source of truth
  - locks isolation strategy and stop semantics

### EC-002 Define campaign and iteration domain models

- Estimate: `M`
- Dependencies: `EC-001`
- Deliverables:
  - typed backend models
  - payload schemas for campaign, iteration, metrics, gates
  - lifecycle state diagrams
- Acceptance criteria:
  - all public states are explicit and machine-checkable
  - no overloaded status field mixes campaign and promotion semantics

### EC-003 Define metric extraction and comparison contract

- Estimate: `S`
- Dependencies: `EC-002`
- Deliverables:
  - metric spec schema
  - extractor types
  - primary/secondary comparison semantics
- Acceptance criteria:
  - supports `stdout_metric`, `json_path`, `regex`
  - codifies `lower` vs `higher`
  - rejects ambiguous or missing primary metric extraction

### EC-004 Define quality gate and promotion contract

- Estimate: `S`
- Dependencies: `EC-002`
- Deliverables:
  - gate schema
  - promotion states
  - approval trigger rules
- Acceptance criteria:
  - benchmark success and promotion eligibility are distinct states
  - checks failure cannot silently promote a candidate

---

## EPIC EC-02: Control-Plane Persistence and Services

**Outcome:** Campaigns and iterations become durable, concurrency-safe control-plane records with a single service boundary.

### EC-101 Create experiment service package

- Estimate: `M`
- Dependencies: `EC-002`
- Deliverables:
  - `src/pylon/experiments/service.py`
  - CRUD service methods
  - validation and normalization logic
- Acceptance criteria:
  - create/get/list/update actions are unit tested
  - service has no UI-specific branching

### EC-102 Add control-plane namespaces and CAS helpers

- Estimate: `M`
- Dependencies: `EC-101`
- Deliverables:
  - namespace conventions for campaigns, iterations, worker leases, artifacts
  - compare-and-set update helpers
- Acceptance criteria:
  - concurrent update conflicts raise deterministic errors
  - both file and SQLite stores pass tests

### EC-103 Add query projection builders

- Estimate: `M`
- Dependencies: `EC-101`
- Deliverables:
  - campaign list summary projection
  - campaign detail projection
  - live telemetry projection
- Acceptance criteria:
  - query payloads are derived, not hand-built ad hoc in routes
  - list ordering and filtering are stable

### EC-104 Add restart reconciliation and orphan detection

- Estimate: `M`
- Dependencies: `EC-102`
- Deliverables:
  - reconciliation routine for running/paused campaigns
  - orphan worker lease detection
  - stale iteration recovery markers
- Acceptance criteria:
  - process restart does not strand campaigns in fake `running`
  - reconciliation is idempotent

---

## EPIC EC-03: Campaign Runner and Bounded Autonomy

**Outcome:** Experiment Campaigns execute through a bounded, restartable orchestration loop that is native to Pylon.

### EC-201 Implement campaign runner state machine

- Estimate: `L`
- Dependencies: `EC-101`, `EC-104`
- Deliverables:
  - runner orchestration loop
  - campaign state transitions
  - iteration sequencing
- Acceptance criteria:
  - runner can start, pause, resume, cancel, and complete
  - state transitions are persisted after each meaningful step

### EC-202 Integrate bounded stop policies

- Estimate: `M`
- Dependencies: `EC-201`
- Deliverables:
  - max iterations
  - timeout
  - cost budget
  - stuck detection
  - external stop support
- Acceptance criteria:
  - stop reason is explicit in campaign record
  - loop termination uses existing autonomy concepts where possible

### EC-203 Add child run orchestration

- Estimate: `L`
- Dependencies: `EC-201`
- Deliverables:
  - create and link child workflow runs where appropriate
  - campaign/iteration/run correlation IDs
  - artifact lineage
- Acceptance criteria:
  - operator can navigate campaign -> iteration -> run
  - failures propagate with preserved context

### EC-204 Add planner/coder bridge contract

- Estimate: `M`
- Dependencies: `EC-201`
- Deliverables:
  - adapter for agent-driven candidate generation
  - workspace-aware execution contract
  - prompt/skill inputs for experiment planning
- Acceptance criteria:
  - runner can request next candidate change from a bridge/runtime
  - planner input includes campaign brief, history, and constraints

---

## EPIC EC-04: Workspace Isolation and Git Operations

**Outcome:** Every iteration is isolated, auditable, and recoverable without corrupting the base repository.

### EC-301 Implement workspace eligibility and repo validation

- Estimate: `M`
- Dependencies: `EC-002`
- Deliverables:
  - validate repo path, branch, cleanliness policy, and permissions
  - workspace contract validator
- Acceptance criteria:
  - invalid repos fail before campaign start
  - protected branch policy is enforceable

### EC-302 Build iteration worktree manager

- Estimate: `L`
- Dependencies: `EC-301`
- Deliverables:
  - worktree create/list/destroy helpers
  - per-iteration directory conventions
  - recovery hooks
- Acceptance criteria:
  - each iteration gets isolated workspace context
  - discard destroys the isolated worktree cleanly

### EC-303 Implement keep/promote/discard git lifecycle

- Estimate: `L`
- Dependencies: `EC-302`
- Deliverables:
  - baseline branch handling
  - candidate branch persistence
  - promote merge strategy
- Acceptance criteria:
  - discard never mutates the base branch
  - kept candidate lineage is visible and reproducible

### EC-304 Add cleanup and orphan recovery

- Estimate: `M`
- Dependencies: `EC-302`
- Deliverables:
  - stale worktree cleanup
  - interrupted iteration recovery rules
  - TTL and janitor hooks
- Acceptance criteria:
  - restart can identify orphaned iteration worktrees
  - cleanup does not remove active iteration state

---

## EPIC EC-05: Sandbox Execution, Metrics, and Gates

**Outcome:** Campaigns can run real benchmarks and checks through production-capable execution backends.

### EC-401 Implement benchmark execution adapter

- Estimate: `L`
- Dependencies: `EC-201`, `EC-302`
- Deliverables:
  - sandbox backend adapter for benchmark commands
  - timeout and exit-code handling
  - stdout/stderr capture
- Acceptance criteria:
  - execution result includes duration, timeout, exit code, output
  - simulated executor is not used in production code path

### EC-402 Implement metric extractor registry

- Estimate: `M`
- Dependencies: `EC-003`, `EC-401`
- Deliverables:
  - extractor registry
  - parser implementations
  - extraction errors and validation
- Acceptance criteria:
  - campaign fails safely on missing required primary metric
  - extractors are unit tested independently

### EC-403 Implement quality gate executor

- Estimate: `M`
- Dependencies: `EC-004`, `EC-401`
- Deliverables:
  - gate command runner
  - blocking/non-blocking results
  - checks timeout contract
- Acceptance criteria:
  - `checks_failed` is a first-class result
  - gate time does not overwrite primary metric semantics

### EC-404 Implement artifact capture and retention

- Estimate: `M`
- Dependencies: `EC-401`, `EC-403`
- Deliverables:
  - artifact descriptors for logs, scripts, patches, summaries
  - retention rules
  - artifact download contract
- Acceptance criteria:
  - operator can inspect benchmark and gate output after completion
  - artifact metadata survives restart

---

## EPIC EC-06: REST API and Live Streaming

**Outcome:** Experiment Campaigns become proper public surfaces in the same style as workflows and lifecycle.

### EC-501 Add campaign REST routes

- Estimate: `M`
- Dependencies: `EC-101`, `EC-103`
- Deliverables:
  - create/list/get/start/pause/resume/cancel/promote routes
  - request/response schema validation
- Acceptance criteria:
  - routes are tenant-scoped and scope-checked
  - invalid transitions return consistent 4xx errors

### EC-502 Add iteration list and detail routes

- Estimate: `S`
- Dependencies: `EC-501`
- Deliverables:
  - iteration list endpoint
  - iteration detail payload
  - artifact access route
- Acceptance criteria:
  - operator can inspect full iteration history without raw store access

### EC-503 Add live SSE campaign stream

- Estimate: `M`
- Dependencies: `EC-201`, `EC-103`
- Deliverables:
  - `/events` stream
  - campaign snapshot and terminal events
  - keep-alive behavior
- Acceptance criteria:
  - UI can observe active campaign progress without polling drift
  - stream terminates correctly on completion/failure/cancel

### EC-504 Extend API reference and contract tests

- Estimate: `S`
- Dependencies: `EC-501`, `EC-503`
- Deliverables:
  - API reference documentation
  - route contract tests
- Acceptance criteria:
  - new routes are fully documented
  - contract tests cover success and failure cases

---

## EPIC EC-07: Operator UI Workspace

**Outcome:** Operators can create, monitor, and govern campaigns from a production-grade UI, not a temporary dev console.

### EC-601 Add frontend API client and types

- Estimate: `S`
- Dependencies: `EC-501`, `EC-502`
- Deliverables:
  - `ui/src/api/experiments.ts`
  - `ui/src/types/experiments.ts`
  - contract tests
- Acceptance criteria:
  - frontend types match public payloads
  - API client supports live streaming and action routes

### EC-602 Build Experiments list page

- Estimate: `M`
- Dependencies: `EC-601`
- Deliverables:
  - campaign list view
  - filters and statuses
  - empty and error states
- Acceptance criteria:
  - operator can locate active, paused, failed, and completed campaigns quickly

### EC-603 Build Experiment detail live dashboard

- Estimate: `L`
- Dependencies: `EC-601`, `EC-503`
- Deliverables:
  - baseline/best cards
  - iteration timeline
  - metrics comparison
  - gate results
  - artifacts/logs panel
- Acceptance criteria:
  - detail page updates live during execution
  - operator can explain campaign state from one screen

### EC-604 Integrate with Runs and lifecycle surfaces

- Estimate: `M`
- Dependencies: `EC-603`
- Deliverables:
  - runs cross-links
  - optional lifecycle summary card
  - campaign references from related runs
- Acceptance criteria:
  - operator can navigate between campaign and child run history
  - related surfaces stay consistent

---

## EPIC EC-08: Governance, Approvals, and Observability

**Outcome:** The feature is safe, auditable, rate-bounded, and operable in production.

### EC-701 Add approval and promotion bindings

- Estimate: `M`
- Dependencies: `EC-303`, `EC-501`
- Deliverables:
  - approval rules for promotion and policy escape
  - binding context for approved action
- Acceptance criteria:
  - protected promotions cannot bypass approval
  - approval decisions are replayable and auditable

### EC-702 Add quotas, concurrency limits, and kill-switch integration

- Estimate: `M`
- Dependencies: `EC-201`, `EC-501`
- Deliverables:
  - tenant campaign quotas
  - active iteration concurrency policy
  - kill-switch and external stop hooks
- Acceptance criteria:
  - runaway campaigns can be stopped centrally
  - tenant isolation is preserved under load

### EC-703 Add metrics, tracing, and alerts

- Estimate: `M`
- Dependencies: `EC-201`, `EC-404`
- Deliverables:
  - campaign-level observability metrics
  - traces linking campaign/iteration/run/sandbox
  - alertable conditions
- Acceptance criteria:
  - stuck campaigns, sandbox failures, and promotion backlog are observable

### EC-704 Add launch documentation and recipes

- Estimate: `S`
- Dependencies: `EC-603`, `EC-701`, `EC-703`
- Deliverables:
  - operator guide
  - benchmark recipe templates
  - launch checklist
- Acceptance criteria:
  - a new operator can create and run a campaign without tribal knowledge
  - at least four starter recipes are documented

---

## Recommended Execution Order

1. `EC-001` -> `EC-004`
2. `EC-101` -> `EC-104`
3. `EC-201` -> `EC-204`
4. `EC-301` -> `EC-304`
5. `EC-401` -> `EC-404`
6. `EC-501` -> `EC-504`
7. `EC-601` -> `EC-604`
8. `EC-701` -> `EC-704`

## Production Exit Criteria

The feature is not production-ready until all of the following are true:

- campaign state is durable and reconciles on restart
- iteration isolation is structural and tested
- promotion is approval-aware
- benchmark and gate execution use real sandbox backends
- live operator view exists
- quotas and kill-switch controls exist
- API and UI contract tests pass
- operator documentation and recipes exist
