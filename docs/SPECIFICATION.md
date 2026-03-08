# Pylon Implemented Specification v1.5

**Scope:** this document describes the code that currently exists in `src/pylon`. It intentionally prefers implemented behavior over older roadmap or aspirational architecture text.

**Revision History**
- v1.0-v1.3 (2026-03-07): earlier platform and workflow/safety drafts
- v1.4 (2026-03-07): rewritten against the actual codebase after a full source review
- v1.5 (2026-03-08): updated for runtime state unification, approval-aware resume, replay/operator payload normalization, and bounded autonomy work

## 1. Package Layout

Pylon is a Python package with these major areas:

- `pylon.types`, `pylon.errors`
- `pylon.workflow`
- `pylon.safety`
- `pylon.agents`
- `pylon.protocols.mcp`
- `pylon.protocols.a2a`
- `pylon.api`, `pylon.cli`, `pylon.sdk`
- `pylon.repository`, `pylon.state`, `pylon.events`
- `pylon.sandbox`, `pylon.secrets`, `pylon.tenancy`
- `pylon.taskqueue`, `pylon.plugins`, `pylon.control_plane`
- `pylon.resources`, `pylon.resilience`, `pylon.observability`
- `pylon.config`, `pylon.dsl`, `pylon.coding`, `pylon.providers`

Many subsystems are intentionally shipped as in-memory or local-first reference implementations.

### 1.1 Responsibility Matrix

| Package | Primary responsibility | Current implementation style |
|---------|------------------------|------------------------------|
| `pylon.workflow` | compiled DAG runtime, commit, replay | relatively rich, deterministic runtime |
| `pylon.safety` | capability rules, runtime safety evaluation, guardrails | relatively rich, wired into protocol boundaries |
| `pylon.agents` | lifecycle, registry, pool, supervisor | in-memory manager layer |
| `pylon.protocols.mcp` | MCP JSON-RPC server/client/auth/types | functional reference implementation |
| `pylon.protocols.a2a` | peer tasks, agent cards, delegation checks | functional reference implementation |
| `pylon.api` | lightweight API server and routes | in-memory route store |
| `pylon.cli` | local project commands and persisted run state | local filesystem implementation |
| `pylon.sdk` | decorators, builder, in-memory client | local/in-memory convenience layer |
| `pylon.repository` | workflow/checkpoint/audit/memory repositories | in-memory implementations |
| `pylon.sandbox` | sandbox policy, lifecycle, execution helpers | policy-rich reference layer |
| `pylon.secrets` | versioned secret storage, vault abstraction | in-memory implementations |
| `pylon.tenancy` | tenant context, isolation, quota, lifecycle | in-memory/contextvar implementations |
| `pylon.plugins` | plugin discovery, manifests, lifecycle, hooks | local plugin infrastructure |
| `pylon.taskqueue` | queue, workers, retry, scheduler | in-memory queueing |
| `pylon.resources` | pools, quotas, monitors, limiters | utility layer |
| `pylon.resilience` | retry, fallback, circuit breaker, bulkhead | utility layer |
| `pylon.observability` | metrics, tracing, logging, exporters | in-memory/reference instrumentation |

## 2. Core Types

### 2.1 Agent Model

`AgentConfig` defines:

- `name`
- `model`
- `role`
- `autonomy`
- `tools`
- `sandbox`
- `input_trust`
- `capability`

`AgentState` transitions:

- `INIT -> READY -> RUNNING -> PAUSED -> COMPLETED | FAILED | KILLED`

`AgentCapability` contains:

- `can_read_untrusted`
- `can_access_secrets`
- `can_write_external`

Hard rules:

- all three are forbidden together
- `can_read_untrusted` and `can_access_secrets` are forbidden together

### 2.2 Workflow Primitives

Workflow graph primitives live in `pylon.types` and `pylon.workflow`:

- `WorkflowNodeType`: `AGENT`, `SUBGRAPH`, `ROUTER`
- `WorkflowJoinPolicy`: `ALL_RESOLVED`, `ANY`, `FIRST`
- `ConditionalEdge`
- `WorkflowNode`
- `WorkflowGraph`
- `CompiledWorkflow`, `CompiledNode`, `CompiledEdge`
- `NodeResult`
- `StatePatch`

`WorkflowJoinPolicy.ANY` and `WorkflowJoinPolicy.FIRST` are only valid for router nodes with at least two inbound edges.

### 2.3 Workflow Run Persistence

`WorkflowRun` fields:

- `id`
- `workflow_id`
- `tenant_id`
- `status`
- `event_log`
- `state`
- `state_version`
- `state_hash`

`RunStatus` values:

- `PENDING`
- `RUNNING`
- `WAITING_APPROVAL`
- `PAUSED`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

The same run status model is now exposed through the programmatic workflow engine and the public CLI/API/SDK workflow run surfaces.

### 2.4 Approval Types

`pylon.approval` defines:

- `ApprovalRequest`
- `ApprovalDecision`
- `ApprovalStatus`
- `ApprovalManager`
- `ApprovalStore`

Approvals can be bound to:

- `plan_hash`
- `effect_hash`

### 2.5 Safety Types

`SafetyContext` contains:

- `agent_name`
- `run_id`
- `held_capability`
- `data_taint`
- `effect_scopes`
- `secret_scopes`
- `call_chain`
- `approval_token`

`TrustLevel` values implemented in code:

- `TRUSTED`
- `INTERNAL`
- `UNTRUSTED`

`ToolDescriptor` contains:

- `name`
- `input_trust`
- `reads_untrusted_input`
- `accesses_secrets`
- `writes_external`
- `requires_approval`
- `deterministic`
- `secret_scopes`
- `effect_scopes`
- `network_egress_policy`

## 3. DSL Specification

`pylon.dsl.parser` loads `pylon.yaml`, `pylon.yml`, or `pylon.json`.

Top-level model:

- `version`
- `name`
- `description`
- `agents`
- `workflow`
- `policy`

### 3.1 Agent DSL

Per-agent fields:

- `model` default: `PYLON_DEFAULT_MODEL` or `anthropic/claude-sonnet-4-20250514`
- `role` default: `""`
- `autonomy` default: `A2`
- `tools` default: `[]`
- `sandbox` default: `gvisor`
- `input_trust` default: `untrusted`

### 3.2 Workflow DSL

Implemented workflow DSL supports:

- `workflow.type = "graph"`
- `workflow.nodes.<node_id>.agent`
- `workflow.nodes.<node_id>.next`

`next` may be:

- `null`
- a single string target
- a list of string targets
- a list of objects with `target` and optional `condition`

### 3.3 Policy DSL

Implemented policy fields:

- `max_cost_usd`
- `max_duration`
- `require_approval_above`
- `safety.blocked_actions`
- `safety.max_file_changes`
- `compliance.audit_log`

The DSL currently uses `max_duration`, not `max_duration_seconds`.

## 4. Workflow Engine

### 4.1 Graph Validation

`WorkflowGraph.validate()` checks:

- non-empty graph
- every target exists or is `END`
- at least one entry node exists
- nodes can reach `END` or emit warnings
- invalid join policy usage
- cycles via DFS

### 4.2 Graph Compilation

`WorkflowGraph.compile()` produces:

- stable edge keys `(source_node_id, outbound_index)`
- inbound edge indexes per node
- compiled conditions
- normalized node metadata for the executor

### 4.3 Condition Language

Conditions are compiled from a restricted Python AST subset. Supported constructs:

- constants: `int`, `float`, `str`, `bool`, `None`
- `state.<field>` attribute access
- comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`, `is`, `is not`, `in`, `not in`
- boolean ops: `and`, `or`
- unary ops: `not`, unary minus

Not supported:

- arbitrary function calls
- arbitrary names
- arbitrary attribute chains outside `state.<field>`

Invalid syntax or unsupported nodes fail compilation.
Missing state fields fail evaluation with `WorkflowError`.

### 4.4 Execution Semantics

`GraphExecutor.execute()`:

1. validates and compiles the graph
2. initializes node and edge status maps
3. computes runnable nodes
4. executes one superstep at a time
5. commits merged patches
6. appends event-log records
7. persists node-scoped checkpoints
8. resolves outbound edges
9. refreshes runnable/skipped nodes

Node handler signature:

```python
Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | NodeResult]]
```

### 4.5 Join Semantics

Implemented join behavior:

- `ALL_RESOLVED`: wait for every inbound edge to resolve; run if any inbound edge was taken, otherwise skip
- `ANY`: run as soon as one inbound edge is taken; block remaining pending inbound edges
- `FIRST`: deterministically select the smallest taken inbound edge key as the winner; block the rest

### 4.6 Node Result and State Commit

`NodeResult` fields:

- `state_patch`
- `artifacts`
- `edge_decisions`
- `llm_events`
- `tool_events`
- `metrics`

Legacy compatibility:

- a raw `dict` return value is treated as `NodeResult(state_patch=<dict>)`

`CommitEngine.apply_patches(...)`:

- rejects conflicting writes when multiple nodes update the same state key in the same superstep
- merges non-conflicting patches
- increments `state_version`
- recomputes `state_hash`

### 4.7 Pause, Resume, and Failure Behavior

If `max_steps` is reached:

- the run is marked `PAUSED`
- `state["pause_reason"] = "max_steps_exceeded"`

If approval is required:

- the run is marked `WAITING_APPROVAL`
- `approval_request_id` is set on the run
- `suspension_reason = "approval_required"`

If a paused or approval-waiting run is resumed:

- executor control-flow snapshot is restored
- node and edge status maps are reused
- loop counters, replan count, and verification state are restored
- approval-bound resumes validate `plan_hash` and `effect_hash` before continuing

If execution raises:

- the run is marked `FAILED`
- `state["error"]` is populated

### 4.8 Event Log Record Shape

Workflow run event records appended by `GraphExecutor` contain:

- `seq`
- `step`
- `attempt_id`
- `node_id`
- `agent`
- `input_state_version`
- `input_state_hash`
- `state_patch`
- `output`
- `artifacts`
- `edge_decisions`
- `edge_resolutions`
- `llm_events`
- `tool_events`
- `metrics`
- `state_version`
- `state_hash`
- `timestamp`

This run-level event log is separate from, but closely aligned with, checkpoint event records.

## 5. Checkpoints and Replay

Checkpoints are event logs, not snapshots.

`Checkpoint` fields:

- `workflow_run_id`
- `node_id`
- `state_version`
- `state_hash`
- `event_log`
- `state_ref`

Checkpoint event records include:

- `seq`
- `attempt_id`
- `node_id`
- `input`
- `input_state_version`
- `input_state_hash`
- `llm_response`
- `llm_events`
- `tool_results`
- `tool_events`
- `artifacts`
- `edge_decisions`
- `metrics`
- `state_patch`
- `output`
- `state_version`
- `state_hash`
- `timestamp`

Secret-bearing metadata is scrubbed before persistence, but `state_patch` remains intact for replay.

`ReplayEngine.replay_event_log(...)`:

- reconstructs state by applying `state_patch` or legacy `output`
- updates `state_version`
- recomputes `state_hash`
- rebuilds `execution_summary` from the event log and terminal run metadata
- raises on hash mismatch

## 6. Safety Model

### 6.1 Static Capability Validation

`CapabilityValidator` enforces:

1. agent config validation
2. dynamic tool grants
3. subgraph inheritance
4. A2A delegation validation

### 6.2 Prompt Guard and Input Sanitization

`PromptGuard`:

- bypasses trusted input
- uses regex matching for internal input
- uses regex plus heuristic classifier for untrusted input

`InputSanitizer`:

- trusted: no change
- internal: strip control characters
- untrusted: strip scripts, strip HTML tags, strip control chars, enforce max length

### 6.3 Output Validation

`OutputValidator` rejects:

- shell injection patterns
- path traversal patterns
- explicitly blocked tools

### 6.4 Runtime Safety Decisions

`SafetyEngine.evaluate_delegation(...)` evaluates:

- parent runtime context
- receiver capability
- data taint from the parent context

`SafetyEngine.evaluate_tool_use(...)` evaluates:

- current context
- tool descriptor
- merged untrusted/secrets/write capability union
- approval requirement on the descriptor

### 6.5 Enforcement Points

Implemented runtime enforcement exists at:

- MCP `tools/call`
- A2A `tasks/send`
- A2A `tasks/sendSubscribe`
- router pre-dispatch validation hooks

### 6.6 Secret Scrubbing

`scrub_secrets(...)` redacts:

- secret-like keys such as `password`, `token`, `api_key`, `private_key`
- secret-like values matching common token/key patterns

Safe key overrides such as `token_usage` and `max_tokens` are preserved.

## 7. Approval Semantics

There are two approval surfaces:

- `pylon.approval`: asynchronous approval manager/store/audit model
- `pylon.safety.autonomy`: local autonomy enforcer for action gating

Shared implemented rule:

- approved scope must continue to match its original `plan_hash` and `effect_hash`

If scope drifts, approval is invalidated.

The workflow executor and public runtime surfaces use the same approval request model for:

- node-level approval
- refinement exhaustion with `request_approval`
- goal verification with `request_approval`

Public run payloads expose:

- `active_approval`
- `approvals`
- `approval_summary`

## 8. Protocols

### 8.1 MCP

`pylon.protocols.mcp` implements:

- JSON-RPC request/response/error types
- DTO validation
- method router
- sessions
- OAuth 2.1 + PKCE support
- tool/resource/prompt/sampling handlers

Supported MCP protocol versions in the server:

- `2025-11-25`
- `2024-11-05`

`ToolDefinition` may expose safety annotations derived from `ToolDescriptor`.

### 8.2 A2A

`pylon.protocols.a2a` implements:

- `A2ATask`, `TaskEvent`, `AgentCard`, `AgentCapabilities`
- send/get/cancel/push-notification flows via JSON-RPC dispatch
- `tasks/sendSubscribe` as a separate streaming entry point (not routed through `handle_request`)
- push notification validation against private/internal IP targets
- allowed-peer checks
- basic sender rate limiting

Incoming task metadata may contribute safety hints, but local receiver policy remains authoritative.

### 8.3 Provider Interface

`pylon.providers.base` defines:

- `Message`
- `Response`
- `Chunk`
- `TokenUsage`
- `LLMProvider` protocol

Built-in concrete provider in the repository:

- `AnthropicProvider`

The provider layer is intentionally small and does not depend on a larger agent framework abstraction.

## 9. API, CLI, and SDK

### 9.1 API

`pylon.api` contains:

- `APIServer`
- route registration
- auth/tenant/rate-limit/security middlewares
- schema validation

Routes implemented today:

- `GET /health`
- `POST /agents`
- `GET /agents`
- `GET /agents/{id}`
- `DELETE /agents/{id}`
- `POST /workflows`
- `GET /workflows`
- `GET /workflows/{id}`
- `DELETE /workflows/{id}`
- `POST /workflows/{id}/run`
- `GET /workflows/{id}/runs/{run_id}`
- `GET /api/v1/workflow-runs/{run_id}`
- `POST /api/v1/workflow-runs/{run_id}/resume`
- `POST /api/v1/approvals/{approval_id}/approve`
- `POST /api/v1/approvals/{approval_id}/reject`
- `GET /api/v1/checkpoints/{checkpoint_id}/replay`
- `POST /kill-switch`

`RouteStore` now keeps:

- tenant-scoped workflow definitions as canonical `PylonProject` payloads
- normalized run payloads
- checkpoint payloads
- approval payloads

Workflow run routes and control-plane routes serialize the same normalized run payload used by the CLI helper layer.

### 9.2 CLI

The CLI is local-state-based today.

It persists:

- runs
- checkpoints
- approvals
- sandboxes

under `$PYLON_HOME/state.json`.

Current workflow-related CLI commands:

- `pylon init`
- `pylon run`
- `pylon inspect`
- `pylon logs`
- `pylon replay`
- `pylon approve`
- `pylon sandbox list`
- `pylon sandbox clean`
- `pylon agent list`
- `pylon agent status`
- `pylon agent kill`
- `pylon config get`
- `pylon config set`
- `pylon config list`
- `pylon login`
- `pylon doctor`
- `pylon dev`

CLI run state currently stores:

- `runs`
- `checkpoints`
- `approvals`
- `sandboxes`

in a single JSON document under `$PYLON_HOME/state.json`.

Workflow execution for `pylon run` and resume for `pylon approve` both go through the shared runtime helper path:

- `compile_project_graph(...)`
- `execute_project_sync(...)`
- `resume_project_sync(...)`
- `serialize_run(...)`

`pylon inspect` returns the normalized run payload.
`pylon replay` returns the same payload shape with `view_kind = "replay"` and a `replay` metadata block.

### 9.3 SDK

`pylon.sdk.PylonClient` is an in-memory client today:

- agent CRUD is local to the client instance
- canonical workflow definitions are locally registered as `PylonProject`
- ad hoc callable execution is still supported, but it is explicitly separated from workflow execution
- there is no HTTP transport yet

`pylon.sdk.WorkflowBuilder` is a separate immutable builder abstraction and is not the same type as `pylon.workflow.WorkflowGraph`.

SDK workflow authoring is normalized through
`pylon.sdk.project.materialize_workflow_definition(...)`.
That materializer accepts:

- `PylonProject`
- `dict`
- `str | Path`
- `WorkflowBuilder`
- `WorkflowGraph`
- `WorkflowInfo`
- `@workflow`-decorated factories

and returns:

- canonical `PylonProject`
- node-scoped handler registry
- agent-scoped handler registry

Execution still goes through the shared canonical runtime path:

1. materialize the SDK definition into `PylonProject`
2. compile the project into runtime `WorkflowGraph`
3. execute with `GraphExecutor`
4. apply custom node or agent handlers at runtime if registered
5. emit the same run payload shape as CLI/API

The SDK does not treat plain callables as workflows. Those belong to the
explicit ad hoc helper surface:

- `register_callable`
- `run_callable`
- `delete_callable`

Current canonicalization limit:

- `WorkflowBuilder` callable edge conditions cannot be converted to canonical
  workflow definitions and must raise `WorkflowBuilderError`

`WorkflowRun` snapshots in the SDK now expose the operator-facing runtime fields:

- `state`, `event_log`
- `goal`, `autonomy`, `verification`
- `runtime_metrics`
- `policy_resolution`
- `approval_summary`, `active_approval`, `approvals`
- `execution_summary`
- `checkpoint_ids`, `logs`
- `state_version`, `state_hash`

SDK control-plane methods now include:

- `register_project`, `list_workflows`, `get_workflow`, `delete_workflow`
- `register_workflow`
- `run_workflow`, `resume_run`
- `approve_request`, `reject_request`
- `replay_checkpoint`
- `register_callable`, `run_callable`, `delete_callable`

### 9.4 API Middleware Contract

`pylon.api.middleware` currently provides:

- `AuthMiddleware`
- `TenantMiddleware`
- `RateLimitMiddleware`
- `SecurityHeadersMiddleware`
- `MiddlewareChain`

The route layer assumes `tenant_id` has already been injected into request context.

## 10. Infrastructure and Supporting Modules

### 10.1 Sandbox

Implemented today:

- sandbox config and lifecycle manager
- policy defaults by tier
- command blocking
- resource and network policy checks
- in-memory registry and executor helpers

Not yet implemented:

- concrete gVisor runtime integration
- concrete Firecracker runtime integration

### 10.2 Secrets

Implemented today:

- in-memory secret manager with versioning and expiry
- Vault protocol abstraction plus in-memory provider
- secret access audit log
- rotation policy helper

### 10.3 Tenancy

There are two tenancy surfaces:

- `pylon.tenancy`: richer context, isolation, quota, lifecycle, config
- `pylon.control_plane.tenant`: simpler control-plane tenant manager and quota enforcer

### 10.4 State, Events, Observability, Resources, Resilience

Implemented modules include:

- generic state machine
- key-value store with TTL and transactions
- diff-based snapshots
- in-memory event bus and event filters
- metrics collector, tracing, structured logging, exporters
- rate limiting, quotas, pools, monitors
- retry, fallback, circuit breaker, bulkhead

### 10.5 Task Queue and Plugins

Task queue features:

- priority queue
- workers and worker pool
- retry policies and dead letter queue
- one-time and cron-like scheduling

Plugin features:

- plugin manifests and discovery
- dependency resolution
- lifecycle registry
- hook system
- extension protocols by plugin type

### 10.6 Config, Events, and Control Plane Helpers

Additional implemented support modules:

- `pylon.config.loader`: YAML/JSON/env merge helpers
- `pylon.config.resolver`: `${ENV_VAR}` and `${secret:key}` resolution
- `pylon.config.validator`: schema-style config validation
- `pylon.events`: in-memory bus, handlers, event filters, dead-letter tracking
- `pylon.control_plane.registry.tools`: async tool registry with trust levels
- `pylon.control_plane.registry.skills`: skill-to-tool dependency resolution
- `pylon.control_plane.scheduler`: priority scheduler for workflow tasks
- `pylon.control_plane.tenant`: simpler tenant/quota helper layer separate from `pylon.tenancy`
- `pylon.runtime.planning`: compiled-workflow to scheduler-wave projection for distributed planning views

## 11. Runtime Flow Contracts

### 11.1 Programmatic workflow path

The canonical runtime path in the repository is:

1. construct `WorkflowGraph`
2. compile to `CompiledWorkflow`
3. execute with `GraphExecutor`
4. commit patches
5. persist checkpoints
6. replay from event log if needed

### 11.2 MCP path

The canonical MCP request path is:

1. `JsonRpcRequest`
2. OAuth scope check if configured
3. DTO validation
4. router request validation
5. output validation for tools
6. runtime safety evaluation
7. tool/resource/prompt/sampling handler

### 11.3 A2A path

The canonical A2A task path is:

1. peer identity / allowlist checks
2. task DTO conversion
3. sender context derivation
4. delegation safety evaluation
5. task lifecycle transition
6. handler invocation or streaming events

### 11.4 CLI path

The canonical CLI run path is:

1. load `pylon.yaml`
2. compile the project to `WorkflowGraph` and optional `GoalSpec`
3. execute through the shared runtime helper and `GraphExecutor`
4. serialize the normalized run payload
5. write local run/checkpoint/approval/sandbox records
6. render output

### 11.5 Dispatch planning path

The scheduler-oriented planning path is:

1. compile `PylonProject` to `CompiledWorkflow`
2. project nodes into `WorkflowTask` instances
3. compute dependency waves with `WorkflowScheduler.compute_waves()`
4. expose a `distributed_wave_plan` through API/SDK/runtime helpers

This path is a planning/deployment view only. It does not execute nodes and does
not replace `GraphExecutor`.

## 12. Current Maturity and Known Gaps

Strongest areas today:

- deterministic workflow execution semantics
- runtime safety enforcement on protocol boundaries
- approval binding
- event-log-based checkpoint and replay model
- public run-state alignment across CLI/API/SDK for workflow runs

Main gaps today:

- many infrastructure modules are reference implementations backed by in-memory stores
- sandbox runtime integrations are not yet wired to real gVisor/Firecracker backends
- replay currently reconstructs state and operator summaries, but it is not yet a full general-purpose distributed durable execution substrate

## 13. Documentation Map

Related docs:

- `docs/architecture.md`
- `docs/architecture/runtime-flows.md`
- `docs/architecture/module-map.md`
- `docs/api-reference.md`
- `docs/getting-started.md`
- ADR-001 through ADR-008

## 14. Source of Truth

For implementation details, the source of truth is the code under:

- `src/pylon/workflow`
- `src/pylon/safety`
- `src/pylon/protocols`
- `src/pylon/repository`
- `src/pylon/api`
- `src/pylon/cli`
- `src/pylon/sdk`
