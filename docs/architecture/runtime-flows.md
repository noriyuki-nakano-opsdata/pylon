# Runtime Flows

This document describes the main runtime paths that actually exist in the repository today.

## 1. Programmatic Workflow Execution

This is the most mature execution path in the codebase.

### Components

- `pylon.workflow.graph.WorkflowGraph`
- `pylon.workflow.compiled.CompiledWorkflow`
- `pylon.workflow.executor.GraphExecutor`
- `pylon.workflow.result.NodeResult`
- `pylon.workflow.commit.CommitEngine`
- `pylon.repository.workflow.WorkflowRun`
- `pylon.repository.checkpoint.CheckpointRepository`
- `pylon.workflow.replay.ReplayEngine`

### Flow

```text
WorkflowGraph
  -> validate()
  -> compile()
  -> GraphExecutor.execute(...)
    -> compute runnable nodes
    -> invoke node handlers
    -> normalize to NodeResult
    -> apply StatePatch objects
    -> update state_version/state_hash
    -> append run event log
    -> create node-scoped checkpoints
    -> resolve edges
    -> compute next runnable frontier
```

### Important guarantees

- conditions are compiled from a restricted AST subset
- conflicting parallel writes fail before commit
- join semantics are explicit
- replay verifies `state_hash`
- run snapshots retain stop/suspension reasons plus operator-facing summaries

### Important non-guarantees

- no cyclic workflow support
- no distributed execution
- no arbitrary open-ended replanning outside declared refinement policy

## 2. MCP Tool Call Flow

### Components

- `pylon.protocols.mcp.server.McpServer`
- `pylon.protocols.mcp.router.MethodRouter`
- `pylon.protocols.mcp.dto.*`
- `pylon.protocols.mcp.auth.OAuthProvider`
- `pylon.safety.output_validator.OutputValidator`
- `pylon.safety.engine.SafetyEngine`
- `pylon.safety.tools.ToolDescriptor`

### Flow

```text
JsonRpcRequest
  -> optional OAuth token validation
  -> router validator
    -> DTO parsing
    -> OutputValidator on tool args
    -> resolve ToolDescriptor
    -> SafetyEngine.evaluate_tool_use(...)
  -> handler dispatch
  -> JsonRpcResponse
```

### Boundary decisions

- unsafe arguments are rejected before handler invocation
- tools that require approval are rejected before handler invocation
- local descriptor policy overrides default or remote assumptions

## 3. A2A Delegation Flow

### Components

- `pylon.protocols.a2a.server.A2AServer`
- `pylon.protocols.a2a.types.A2ATask`
- `pylon.safety.context.SafetyContext`
- `pylon.safety.engine.SafetyEngine`

### `tasks/send`

```text
JsonRpcRequest
  -> optional authenticated sender match
  -> allowed-peer check
  -> rate-limit check
  -> A2ATask.from_dict(...)
  -> sender SafetyContext resolution
  -> SafetyEngine.evaluate_delegation(...)
  -> task transition SUBMITTED -> WORKING
  -> task handler
```

### `tasks/sendSubscribe`

`sendSubscribe` is modeled separately from normal JSON-RPC dispatch.

```text
request
  -> DTO validation
  -> peer/rate-limit checks
  -> task conversion
  -> safety evaluation
  -> stream TaskEvent values
```

### Boundary decisions

- peer metadata can influence derived context
- local receiver capability remains authoritative
- message-bearing tasks are treated as untrusted by default

## 4. CLI Local Run Flow

### Components

- `pylon.cli.commands.run`
- `pylon.cli.state`
- `pylon.dsl.parser`
- `pylon.runtime.execution`
- `pylon.workflow.executor.GraphExecutor`

### Flow

```text
pylon run
  -> load_project(".")
  -> compile_project_graph(...)
  -> execute_project_sync(...)
    -> GraphExecutor.execute(...)
    -> CheckpointRepository / ApprovalManager
  -> serialize_run(...)
  -> create local run/checkpoint/approval/sandbox records
  -> persist to $PYLON_HOME/state.json
```

### Important note

The CLI is still local-state-based, but workflow execution now uses the same runtime core as the API and SDK helpers.

## 5. SDK Workflow Authoring Flow

### Components

- `pylon.sdk.project.materialize_workflow_definition`
- `pylon.runtime.execution.execute_project_sync`
- `pylon.workflow.executor.GraphExecutor`

### Flow

```text
WorkflowBuilder | WorkflowGraph | @workflow factory | PylonProject
  -> materialize_workflow_definition(...)
    -> canonical PylonProject + handler registries
  -> compile_project_graph(...)
  -> execute_project_sync(...)
    -> GraphExecutor.execute(...)
  -> serialize_run(...)
  -> WorkflowRun snapshot / public run payload
```

### Important note

SDK builder/decorator authoring is normalized before execution rather than
introducing a second runtime. Plain callables remain outside this path and must
use `register_callable()` / `run_callable()`.

## 6. API Route Flow

### Components

- `pylon.api.server.APIServer`
- `pylon.api.middleware.*`
- `pylon.api.routes.register_routes`

### Flow

```text
Request
  -> optional AuthMiddleware
  -> optional TenantMiddleware
  -> optional RateLimitMiddleware
  -> optional SecurityHeadersMiddleware
  -> route handler
  -> Response
```

### Important note

The route handlers still operate over an in-memory `RouteStore`, but that store now holds canonical workflow definitions, persisted run/checkpoint/approval payloads, and shared-runtime control-plane operations for resume, approval, and replay.

## 7. Approval Flow

There are two distinct approval paths.

### Managed approval path

- `pylon.approval.manager.ApprovalManager`
- `pylon.approval.store.ApprovalStore`
- `pylon.repository.audit.AuditRepository`

This path supports submission, approval/rejection, expiry, and binding validation.

### Local autonomy path

- `pylon.safety.autonomy.AutonomyEnforcer`

This path is simpler and oriented around action gating plus `plan_hash` / `effect_hash` verification.

## 8. How To Read The Repository

If you want the most representative implementation path, read in this order:

1. `pylon.types`
2. `pylon.workflow`
3. `pylon.repository.workflow`
4. `pylon.repository.checkpoint`
5. `pylon.safety`
6. `pylon.protocols.mcp`
7. `pylon.protocols.a2a`
8. `pylon.cli`, `pylon.api`, `pylon.sdk`
