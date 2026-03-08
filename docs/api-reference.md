# API Reference

This document describes the lightweight route contract implemented by `pylon.api`.

## Scope

`pylon.api.server.APIServer` is a small in-process HTTP-style router.
`pylon.api.routes.register_routes()` installs route handlers backed by a control-plane store.

The API package ships a lightweight stdlib HTTP adapter, but the route contract
itself remains transport-agnostic. You compose:

- `APIServer`
- `create_http_server(...)` when you want an embedded HTTP transport
- `build_api_server(...)` / `build_http_api_server(...)` when you want the
  standard middleware stack and route wiring from config
- optional middlewares from `pylon.api.middleware`
- route handlers from `pylon.api.routes`

The default reference wiring uses:

- `RouteStore` as an API facade over a pluggable control-plane store
- `WorkflowRunService` for workflow lifecycle transitions
- shared query builders for run/replay/operator views

`register_routes()` can either accept an already constructed `RouteStore` / control-plane store,
or build one from backend settings. The reference backends are `memory`, `json_file`, and `sqlite`.

`pylon.api.factory` provides:

- `APIServerConfig`
- `APIMiddlewareConfig`
- `AuthMiddlewareConfig`
- `TenantMiddlewareConfig`
- `RateLimitMiddlewareConfig`
- `build_api_server(...)`
- `build_http_api_server(...)`

Auth backend choices in the reference wiring are:

- `none`
- `memory`
- `json_file`
- `jwt_hs256`

## Typical Middleware Stack

The common stack is:

1. `RequestContextMiddleware`
2. `AuthMiddleware`
3. `TenantMiddleware`
4. `RateLimitMiddleware`
5. `SecurityHeadersMiddleware`

Important details:

- authentication is optional and only enforced if `AuthMiddleware` is installed
- route handlers expect `tenant_id` in `request.context`
- `TenantMiddleware` can source tenant context either from `X-Tenant-ID` or from
  an authenticated principal bound to a tenant
- `RequestContextMiddleware` injects `request_id` and `correlation_id` into
  request context and echoes them back on responses
- `/health` bypasses auth and tenant checks

## Request Context Expectations

When the standard middlewares are installed:

- `Authorization: Bearer <token>` is required for non-health routes when auth is enabled
- `X-Tenant-ID: <tenant-id>` is required unless either:
  - `TenantMiddleware(require_tenant=False)` is used, or
  - the authenticated principal already carries a tenant binding
- `X-Request-ID` is optional; when omitted, the server generates one
- `X-Correlation-ID` is optional; when omitted, it defaults to the request ID
- rate limits are applied through a pluggable token-bucket store and default to
  tenant-scoped buckets

## Routes

### `GET /health`

Always available.

Response `200 OK`

```json
{
  "status": "ok",
  "timestamp": 1709827200.0
}
```

### `POST /agents`

Create an agent record for the current tenant.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | Yes | 1-128 chars |
| `model` | string | No | defaults to empty string |
| `role` | string | No | defaults to empty string |
| `autonomy` | string or int | No | `A0`-`A4` or `0`-`4` |
| `tools` | array | No | defaults to `[]` |
| `sandbox` | string | No | `gvisor`, `firecracker`, `docker`, `none` |

Response `201 Created`

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "coder",
  "model": "anthropic/claude-sonnet-4-20250514",
  "role": "Write production-quality code",
  "autonomy": "A2",
  "tools": ["file-read", "file-write"],
  "sandbox": "docker",
  "status": "ready",
  "tenant_id": "default"
}
```

### `GET /agents`

List agents for the current tenant.

Response `200 OK`

```json
{
  "agents": [],
  "count": 0
}
```

### `GET /agents/{id}`

Fetch a tenant-scoped agent by ID.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `DELETE /agents/{id}`

Delete a tenant-scoped agent.

Responses:

- `204 No Content`
- `403 Forbidden`
- `404 Not Found`

### `POST /workflows`

Register a canonical workflow definition for the current tenant.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | Yes | workflow definition ID |
| `project` | object | Yes | `PylonProject`-compatible payload |

Response `201 Created`

The response includes workflow metadata plus the normalized `project` payload.

Important scope note:

- the HTTP API only accepts canonical `PylonProject`-compatible workflow definitions
- SDK-only authoring helpers such as `WorkflowBuilder` or `@workflow` factories
  must be materialized client-side before registration

### `GET /workflows`

List workflow definitions visible to the current tenant.

Response `200 OK`

```json
{
  "workflows": [
    {
      "id": "build-pipeline",
      "project_name": "my-project",
      "tenant_id": "default",
      "agent_count": 2,
      "node_count": 3,
      "goal_enabled": false
    }
  ],
  "count": 1
}
```

### `GET /workflows/{id}`

Fetch one tenant-scoped workflow definition.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `GET /workflows/{id}/plan`

Return the scheduler-oriented dispatch plan for a canonical workflow definition.

This is a planning view, not an execution endpoint. It projects the compiled DAG
into dependency waves suitable for queued or distributed runners while leaving
the canonical inline runtime unchanged.

Response `200 OK`

```json
{
  "workflow_id": "build-pipeline",
  "tenant_id": "default",
  "execution_mode": "distributed_wave_plan",
  "entry_nodes": ["start"],
  "task_count": 2,
  "wave_count": 2,
  "waves": [
    {"index": 0, "node_ids": ["start"], "task_ids": ["build-pipeline:start"]},
    {"index": 1, "node_ids": ["finish"], "task_ids": ["build-pipeline:finish"]}
  ],
  "tasks": [
    {
      "task_id": "build-pipeline:start",
      "node_id": "start",
      "wave_index": 0,
      "depends_on": [],
      "dependency_task_ids": [],
      "node_type": "agent",
      "join_policy": "all_resolved",
      "conditional_inbound": false,
      "conditional_outbound": false
    }
  ]
}
```

### `DELETE /workflows/{id}`

Delete one tenant-scoped workflow definition.

Responses:

- `204 No Content`
- `403 Forbidden`
- `404 Not Found`

### `POST /workflows/{id}/run`

Create a workflow run for the current tenant from a registered canonical workflow definition.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `input` | object | No | defaults to `{}` |
| `parameters` | object | No | defaults to `{}` |
| `idempotency_key` | string | No | write-side deduplication key |
| `execution_mode` | string | No | `inline` or `queued`, defaults to `inline` |

The route compiles the registered `PylonProject`, executes it through the shared runtime, and returns the normalized public run payload.

Queued mode notes:

- `execution_mode="queued"` persists the same run/checkpoint/query model as inline mode
- current support is intentionally limited to straight-line agent DAGs
- goals, approval-gated autonomy, loops, routers, conditional edges, and non-default join policies are rejected instead of silently degrading semantics
- optional queued retry configuration may be passed as `parameters.queued.retry`
- optional queued lease configuration may be passed as `parameters.queued`
  - `lease_timeout_seconds`: positive float, defaults to `30.0`
  - `heartbeat_interval_seconds`: positive float smaller than `lease_timeout_seconds`
- `policy`: `fixed` or `exponential_backoff`
  - `max_retries`: integer `>= 0`
  - delay fields:
    - `fixed`: `delay_seconds`
    - `exponential_backoff`: `base_delay_seconds`, `max_delay_seconds`
- queued run state and runtime metrics expose:
  - `retrying_task_ids`
  - `dead_letter_task_ids`
  - normalized `retry_policy`
  - `lease_timeout_seconds`
  - `heartbeat_interval_seconds`
  - `heartbeat_total`

Important persistence note:

- the server stores raw run records as the command-side source of truth
- public responses rebuild `execution_summary`, `approval_summary`, and replay metadata through the shared query service

Response `202 Accepted`

Headers:

- `Location: /api/v1/workflow-runs/{run_id}`

### `GET /workflows/{id}/runs`

List normalized run views for one workflow definition.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

Example body:

```json
{
  "id": "r1a2b3c4d5e6",
  "workflow_id": "build-pipeline",
  "project": "my-project",
  "status": "completed",
  "stop_reason": "none",
  "suspension_reason": "none",
  "input": {"repo": "my-app", "branch": "main"},
  "parameters": {"max_retries": 3},
  "execution_summary": {
    "total_events": 1,
    "last_node": "start",
    "pending_approval": false
  },
  "approval_summary": {
    "pending": false,
    "active_request_id": null
  },
  "started_at": "2026-03-08T00:00:00+00:00",
  "tenant_id": "default"
}
```

### `POST /api/v1/workflow-runs/{run_id}/resume`

Resume a previously paused workflow run through the same shared runtime.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `input` | object | No | overrides the stored run input when provided |

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`
- `422 Validation Error`

### `GET /workflows/{id}/runs/{run_id}`

Fetch a workflow run by workflow ID plus run ID.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `GET /api/v1/workflow-runs/{run_id}`

Fetch a workflow run by run ID only.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

Returned payload shape matches `POST /workflows/{id}/run` and includes:

- `execution_summary`
- `approval_summary`
- `policy_resolution`
- `runtime_metrics`
- `state_version`
- `state_hash`

### `GET /api/v1/workflow-runs`

List all run views for the current tenant.

### `GET /api/v1/workflow-runs/{run_id}/approvals`

List approval records associated with one run.

### `GET /api/v1/workflow-runs/{run_id}/checkpoints`

List checkpoint records associated with one run.

### `GET /api/v1/approvals`

List approval records visible to the current tenant.

### `POST /api/v1/approvals/{approval_id}/approve`

Approve a pending approval request and resume the owning run.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `reason` | string | No | optional operator comment |

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`
- `409 Conflict`

### `POST /api/v1/approvals/{approval_id}/reject`

Reject a pending approval request and cancel the owning run.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `reason` | string | No | optional operator comment |

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`
- `409 Conflict`

### `GET /api/v1/checkpoints`

List checkpoint records visible to the current tenant.

### `GET /api/v1/checkpoints/{checkpoint_id}/replay`

Replay a checkpoint from the stored event log and return a normalized payload with `view_kind = "replay"`.

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `POST /kill-switch`

Activate a kill switch event.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `scope` | string | Yes | `global`, `tenant:{id}`, `workflow:{id}`, `agent:{id}` |
| `reason` | string | Yes | human-readable reason |
| `issued_by` | string | Yes | actor identity |

Authorization logic in the route handler:

- `global` scope requires tenant `admin`
- `tenant:{id}` requires the current tenant to match `{id}`

Response `201 Created`

```json
{
  "scope": "agent:coder-123",
  "reason": "Agent producing unsafe output",
  "issued_by": "admin@example.com",
  "activated_at": 1709827200.0
}
```

## Errors

Error payloads are simple JSON objects.

Generic error:

```json
{
  "error": "Description of the error"
}
```

Validation error:

```json
{
  "errors": [
    "Field 'name' is required"
  ]
}
```

Common status codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted |
| 204 | No Content |
| 400 | Bad Request |
| 401 | Missing auth or tenant context depending on composition |
| 403 | Forbidden |
| 404 | Not Found |
| 405 | Method Not Allowed |
| 422 | Validation Error |
| 429 | Rate Limit Exceeded |

## Middleware Details

### `RequestContextMiddleware`

- injects `request_id`, `correlation_id`, and `request_started_at` into request context
- preserves incoming `X-Request-ID` / `X-Correlation-ID` when present
- generates a request ID when none is supplied
- echoes `x-request-id` and `x-correlation-id` on responses

### `AuthMiddleware`

- skips `/health`
- expects `Authorization: Bearer <token>`
- accepts a pluggable `TokenVerifier`
- supports the reference `InMemoryTokenVerifier`, `JsonFileTokenVerifier`, and `JWTTokenVerifier`
- projects an `AuthPrincipal` into `request.context["auth_principal"]`
- when an authenticated principal is present, registered API routes enforce scope-based authorization
- exact scopes, namespace wildcards like `workflows:*`, and global wildcard `*` are supported

`JWTTokenVerifier` validates HS256 bearer tokens and supports:

- `iss`
- `aud`
- `exp`
- `nbf`
- `iat`
- configurable tenant/subject/scopes claim names

Route scope taxonomy:

- `agents:read`, `agents:write`
- `workflows:read`, `workflows:write`
- `runs:read`, `runs:write`
- `approvals:read`, `approvals:write`
- `checkpoints:read`
- `kill-switch:write`

Compatibility note:

- if authentication is disabled and no `AuthPrincipal` is present, route scope checks are skipped
- if authentication is enabled and a principal is authenticated, route scope checks are enforced

### `TenantMiddleware`

- skips `/health`
- injects `tenant_id` into `request.context`
- prefers tenant binding from the authenticated principal when available
- rejects `X-Tenant-ID` that conflicts with the authenticated principal
- validates tenant IDs against `^[a-z0-9][a-z0-9_-]{0,63}$`

### `RateLimitMiddleware`

- default rate: `10` requests/sec
- default burst: `20`
- accepts a pluggable `RateLimitStore`
- supports the reference `InMemoryRateLimitStore` and `SQLiteRateLimitStore`
- emits `retry-after` header on `429`

### `SecurityHeadersMiddleware`

Adds:

- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `content-security-policy: default-src 'none'`
- `x-xss-protection: 0`
