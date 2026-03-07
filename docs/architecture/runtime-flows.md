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

### Important non-guarantees

- no cyclic workflow support
- no distributed execution
- no built-in retry/attempt management beyond the current fixed `attempt_id=1`
- workflow approval wait states are not yet integrated into executor control flow

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

### Flow

```text
pylon run
  -> load_project(".")
  -> inspect workflow nodes and referenced agents
  -> create local run record
  -> create local checkpoint records
  -> create local sandbox record
  -> optionally create pending approval record
  -> persist to $PYLON_HOME/state.json
```

### Important note

This is not a thin wrapper around `GraphExecutor`. It is a separate local state flow intended for CLI developer experience.

## 5. API Route Flow

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

The route handlers operate over an in-memory `RouteStore`. They do not currently orchestrate the full workflow runtime.

## 6. Approval Flow

There are two distinct approval paths.

### Managed approval path

- `pylon.approval.manager.ApprovalManager`
- `pylon.approval.store.ApprovalStore`
- `pylon.repository.audit.AuditRepository`

This path supports submission, approval/rejection, expiry, and binding validation.

### Local autonomy path

- `pylon.safety.autonomy.AutonomyEnforcer`

This path is simpler and oriented around action gating plus `plan_hash` / `effect_hash` verification.

## 7. How To Read The Repository

If you want the most representative implementation path, read in this order:

1. `pylon.types`
2. `pylon.workflow`
3. `pylon.repository.workflow`
4. `pylon.repository.checkpoint`
5. `pylon.safety`
6. `pylon.protocols.mcp`
7. `pylon.protocols.a2a`
8. `pylon.cli`, `pylon.api`, `pylon.sdk`
