# Production Readiness Implementation Plan

> **Created**: 2026-03-08
> **Project**: Pylon
> **Scope**: Non-optional work required to move Pylon from a local-first reference platform to a production-capable runtime
> **Status**: Planning baseline

## Goal

Make Pylon operable as a real multi-tenant workflow runtime with:

- durable control-plane state
- resumable and replayable distributed execution
- real API transport
- real operator query surfaces
- real secrets and sandbox backends
- production-grade authentication, rate limiting, and observability

This plan is intentionally narrower than the broader `vNext` autonomy roadmap.
It focuses on what must exist before production deployment is defensible.

## Current Baseline

Pylon already has strong runtime semantics:

- deterministic compiled DAG execution
- explicit join policies
- checkpointing and replay with state hash verification
- goal, termination, refinement, and approval semantics
- shared control-plane service
- canonical public workflow execution across CLI, API, and SDK

The remaining gaps are mostly infrastructure and control-plane hardening:

- local JSON-backed control-plane storage
- lightweight in-process API server
- in-memory SDK transport
- in-memory queue and workers
- reference sandbox lifecycle manager
- in-memory secrets manager and Vault protocol stub
- in-memory auth, rate limit, metrics, and exporters

## Design Principles

1. One runtime model

All public surfaces must continue to project the same canonical run model.
No transport or deployment mode may introduce a second workflow semantics.

2. Storage before distribution

Queued/distributed execution must be built on durable state. Stateless dispatch
over in-memory run records is not acceptable.

3. Write-side and read-side stay separate

Raw run records remain the command source of truth.
Operator payloads remain derived query projections.

4. Safety invariants do not weaken in production

Real transports and real backends must preserve approval, replay, audit, and
policy-first guarantees. Infrastructure work must not bypass runtime controls.

5. Roll out by mode, not by rewrite

Introduce production backends behind existing protocols and services.
Do not replace the runtime kernel.

## Out of Scope

- new agent cognition features
- dashboard UI
- plugin marketplace
- generalized cyclic workflow execution
- memory retrieval redesign
- nonessential CLI ergonomics

## Target Production Architecture

```text
+------------------------------------------------------------------+
| Public Surfaces                                                  |
| CLI | HTTP API | HTTP SDK                                        |
+------------------------------------------------------------------+
| Shared Control Plane                                             |
| WorkflowRunService | ValidationPipeline | QueryService           |
+------------------------------------------------------------------+
| Execution Modes                                                  |
| Inline GraphExecutor | Queued Wave Runner                        |
+------------------------------------------------------------------+
| Durable State                                                    |
| PostgreSQL: workflows, runs, checkpoints, approvals, audit       |
| Queue backend: Redis/NATS/Postgres-backed work dispatch          |
+------------------------------------------------------------------+
| Secure Infrastructure                                            |
| Real sandbox backend | Real secrets backend | Tenant authz       |
+------------------------------------------------------------------+
| Operations                                                       |
| Metrics exporter | Tracing exporter | Structured logs | Alerts    |
+------------------------------------------------------------------+
```

## Workstreams

### WS1. Durable Control-Plane Storage

#### Why

The current [JsonFileWorkflowControlPlaneStore](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/control_plane/file_store.py) is a correct reference implementation, not a multi-process production backend.

#### Deliverables

- `PostgresWorkflowControlPlaneStore`
- durable `ApprovalStore`
- durable `AuditRepository`
- migration scripts and schema versioning
- optimistic concurrency or transactional update strategy

#### Data Model

Required tables:

- `workflow_definitions`
- `workflow_runs`
- `workflow_run_logs` or embedded event-log strategy
- `workflow_checkpoints`
- `approval_requests`
- `audit_entries`

Required indexes:

- `(tenant_id, workflow_id)`
- `(tenant_id, run_id)`
- `(tenant_id, status, created_at)`
- `(run_id, checkpoint_seq)`
- `(run_id, approval_status)`

#### Acceptance Criteria

- process restart does not lose workflow definitions, runs, approvals, or checkpoints
- `resume`, `replay`, `approve`, and `reject` work across processes
- all control-plane writes happen transactionally
- tenant-scoped uniqueness is enforced in storage, not only in memory

### WS2. WorkflowRunService Hardening

#### Why

[WorkflowRunService](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/control_plane/workflow_service.py) is now the correct write-side boundary. The reference implementation no longer rebuilds approval/audit state in-memory during service transitions; the remaining production work is durable backend hardening, locking, and distributed execution semantics.

#### Deliverables

- service constructors that accept durable stores directly
- durable adapters for approval and audit stores
- idempotent `start`, `resume`, `approve`, `reject`, `replay`
- explicit conflict and retry semantics

#### Required Changes

- persist approval decisions directly through durable store
- persist audit entries directly through durable repository adapters
- make replay/read operations side-effect free
- add service-level locking or compare-and-swap on mutable run transitions

#### Acceptance Criteria

- duplicate approve/reject calls are safe
- concurrent resume attempts on the same run are rejected deterministically
- service methods are transport-agnostic and free of surface-specific branching

### WS3. Real HTTP Transport

#### Why

[APIServer](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/api/server.py) and the current SDK client are suitable for embedded/reference use, not for real remote operation.

#### Deliverables

- ASGI app adapter for the existing route contract
- production HTTP server wiring
- HTTP SDK client preserving current payload shapes
- correlation/request IDs
- network timeout and cancellation semantics

#### Authentication and Authorization

- reference HTTP middleware now supports pluggable token verification and
  tenant-bound service tokens
- reference auth now also supports HS256 JWT verification with issuer/audience
  validation, but production still needs a managed verifier backend or key
  rotation story
- reference API server wiring now supports config-driven middleware/backend
  composition through `pylon.api.factory`
- registered routes now enforce scope-based authorization whenever an
  authenticated principal is present
- reference transport now has stable request/correlation ID propagation, which
  is the minimum contract required before adding structured logs and tracing
- bearer tokens still need a production verifier backend beyond in-memory / JSON
  file adapters
- tenant identity must continue to bind to the authenticated principal, not only
  header input
- support at least service tokens or JWT validation in the production backend

#### Acceptance Criteria

- SDK can execute runs against a remote HTTP endpoint with no semantic drift
- authn/authz failures are enforced server-side
- request/response contracts match existing query payloads

### WS4. Operator Query Surfaces

#### Why

The query model is now coherent, but production operations need searchable list endpoints and stable filtering.

#### Deliverables

- query service backed by durable read access
- paginated run list
- paginated approval list
- paginated checkpoint list
- tenant/workflow/run scoped filters
- stable sort order and cursor or offset semantics

#### Acceptance Criteria

- operators can enumerate active, paused, failed, and approval-pending runs
- replay and inspect can be driven entirely from stored state
- list APIs do not require loading all runs into memory

### WS5. Queued Wave Runner

#### Why

[plan_project_dispatch](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/runtime/planning.py) and [QueuedWorkflowDispatchRunner](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/runtime/queued_runner.py) now cover the local planning-to-queue bridge and persist canonical run/checkpoint records for supported queued workflows. The remaining production work is leases, retries, worker crash recovery semantics, and lifting the current queued-mode restrictions around conditional control flow and approval-governed execution.

#### Deliverables

- durable task queue backend
- workflow wave dispatcher
- worker lease / heartbeat model
- idempotent node execution contract
- dead-letter and retry policy

Current reference status:

- local queued mode now supports durable lease ownership, retry policy, and dead-letter tracking
- local queued mode also supports heartbeat-based lease renewal for long-running handlers
- the remaining production work is distributed worker coordination, real transport, and real infrastructure backends

#### Deployment Model

The queued runner is an execution mode, not a second runtime.

- inline mode continues to use `GraphExecutor`
- queued mode dispatches node work derived from the same compiled workflow
- both modes update the same run/checkpoint/approval model
- queue ownership is lease-based; worker heartbeats extend task visibility and recovery only reclaims expired or legacy unleased work

#### Acceptance Criteria

- queued mode preserves checkpoint/replay semantics
- worker crash does not lose leased work permanently
- duplicate delivery cannot commit the same node twice
- approval waits and kill switch pauses propagate correctly

### WS6. Real Secrets Backend

#### Why

[SecretManager](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/secrets/manager.py) explicitly states it is not production-grade.

#### Deliverables

- Vault/KMS/Secret Manager adapter
- tenant/path isolation policy
- key rotation hooks
- bootstrap credential loading strategy
- audit integration for secret access

#### Acceptance Criteria

- no plaintext secret material is persisted in local reference stores
- secret access is attributable in audit logs
- secret backend failure modes are explicit and recoverable

### WS7. Real Sandbox Backend

#### Why

[SandboxManager](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/sandbox/manager.py) is lifecycle-only and does not provide real isolation.

#### Deliverables

- real backend adapter for gVisor, Firecracker, or equivalent container isolation
- network egress enforcement
- resource enforcement
- sandbox cleanup and orphan reaping
- execution metadata and health reporting

#### Acceptance Criteria

- sandbox tier selection maps to a real isolation backend
- network/resource policy is enforced by the execution environment
- sandbox IDs in run records correspond to real instances

### WS8. Production Observability

#### Why

[metrics.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/observability/metrics.py), [tracing.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/observability/tracing.py), and [exporters.py](/Users/noriyuki.nakano/Documents/99_work/pylon/src/pylon/observability/exporters.py) are in-memory or console-oriented.

#### Deliverables

- Prometheus or OpenTelemetry metrics exporter
- OTLP or equivalent tracing exporter
- structured log correlation with run/request/task IDs
- health/readiness probes
- SLO-focused metrics

#### Required Metrics

- run start/completion/failure counts
- active paused approval-pending run counts
- queue depth and lease age
- checkpoint write latency
- approval latency
- LLM token and cost metrics
- sandbox create/destroy latency

#### Acceptance Criteria

- a single run can be traced across API, control plane, worker, and provider call
- operators can alert on stuck queue, replay failures, approval backlog, and sandbox failures

## Phase Plan

### Phase 0. Schema and Contracts

#### Objectives

- freeze storage schema
- freeze run state transition contract
- freeze HTTP payload contract

#### Tasks

- define relational schema
- define versioned migration strategy
- define service-level concurrency semantics
- define API error contract for production transport

#### Exit Criteria

- schema ADR accepted
- initial migrations generated
- service contract tests written before backend swap

### Phase 1. Durable Storage Cutover

#### Objectives

- replace JSON control-plane store in production path
- persist approvals and audit durably

#### Tasks

- implement PostgreSQL store adapters
- wire `WorkflowRunService` to durable stores
- keep JSON file store as reference/test backend
- add migration/bootstrap path for local development

#### Exit Criteria

- `start/resume/approve/reject/replay` pass against PostgreSQL-backed service
- restart-safe integration tests exist

#### Current progress

- command-side run records already carry `record_version`
- the store contract already includes compare-and-swap and idempotency-key hooks
- `SQLiteWorkflowControlPlaneStore` now exists as a relational bootstrap backend for local and CI validation before PostgreSQL cutover

### Phase 2. HTTP Transport

#### Objectives

- make API and SDK real remote surfaces

#### Tasks

- add ASGI adapter
- add HTTP SDK client
- integrate authn/authz
- add request IDs, timeout handling, error mapping

#### Exit Criteria

- remote SDK tests pass against HTTP server
- no in-memory-only assumptions remain in workflow API paths

### Phase 3. Operator Read Model

#### Objectives

- make inspect/list/replay operationally sufficient

#### Tasks

- add pagination/filtering/sorting
- optimize query service for durable backends
- add list/search APIs to CLI/API/SDK

#### Exit Criteria

- operators can answer “what is running, blocked, failed, and why?” from stored state

### Phase 4. Queued Wave Runner

#### Objectives

- add distributed execution mode without changing runtime semantics

#### Tasks

- implement queue backend abstraction
- implement dispatcher and worker lease model
- persist worker heartbeats and retry state
- connect completion callbacks to canonical run state

#### Exit Criteria

- the same workflow can run inline or queued and produce equivalent run semantics

### Phase 5. Secrets and Sandbox Hardening

#### Objectives

- close the two largest infrastructure security gaps

#### Tasks

- add real secret backend adapter
- add real sandbox backend adapter
- connect safety and audit to those backends

#### Exit Criteria

- production deployment no longer depends on in-memory secret or sandbox managers

### Phase 6. Observability and Operations

#### Objectives

- make production diagnosis and alerting possible

#### Tasks

- exporter integration
- run/request/task trace correlation
- metrics dashboards and alert thresholds
- operational runbooks

#### Exit Criteria

- operators can detect and triage failures without local introspection

## Cross-Cutting Requirements

### Backward Compatibility

- keep JSON file store for local development and tests
- keep embedded API server for lightweight/test use
- keep in-memory SDK mode only as explicit local mode

### Idempotency

The following operations must be safe under retry:

- run creation with client idempotency key
- resume
- approve/reject
- checkpoint write
- worker completion callback

### Multi-Tenancy

All durable storage and transport layers must enforce:

- tenant-scoped identifiers
- tenant-bound authz
- tenant-aware rate limits
- tenant-aware audit trails

### Security

- no fallback secret material in production mode
- no unsigned or unverifiable audit mode in production mode
- no bypass path around approval and safety for queued workers

## Test Strategy

### Required Test Layers

1. unit tests for stores, adapters, and service transitions
2. integration tests with PostgreSQL-backed control plane
3. HTTP contract tests for API and SDK
4. worker crash/retry tests for queued mode
5. replay/resume tests across process restart
6. authz and tenant isolation tests
7. secret and sandbox backend contract tests

### Failure Scenarios That Must Be Tested

- process crash after checkpoint write but before run update
- duplicate approval decision submission
- concurrent resume attempts
- worker crash after lease acquire
- queue redelivery of completed node work
- replay of scrubbed checkpoints
- tenant A attempting to read tenant B run
- secret backend outage
- sandbox backend launch failure

## Risks and Mitigations

### Risk: Semantics drift between inline and queued modes

Mitigation:

- queued mode must consume compiled workflow artifacts
- run model stays canonical
- equivalence tests compare inline vs queued outcomes

### Risk: Durable store introduces hidden state coupling

Mitigation:

- keep write-side in `WorkflowRunService`
- keep read-side in query service
- avoid ad hoc mutations outside service boundary

### Risk: Production auth retrofits too late

Mitigation:

- require auth contract in Phase 2, not after transport is already public

### Risk: Secrets and sandbox remain “temporary”

Mitigation:

- treat WS6 and WS7 as production gate blockers, not backlog items

## Production Readiness Gate

Pylon should not be described as production-ready until all of the following are true:

- workflow lifecycle state is durably stored
- runs can resume and replay across process restart
- API and SDK work over real HTTP transport
- queued execution mode exists or inline-only mode is explicitly documented as the only supported deployment mode
- secrets and sandbox use real backends in production mode
- metrics, tracing, and logs are exportable to external systems
- tenant/auth boundaries are enforced by storage and transport, not just in memory

## Recommended Immediate Next Step

Begin with **Phase 0 + Phase 1 together**:

- freeze the relational schema
- implement PostgreSQL-backed control-plane stores
- cut `WorkflowRunService` over to durable storage

That is the highest-leverage move. It unlocks transport, queued execution, and real operator workflows without changing the runtime kernel.
