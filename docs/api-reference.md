# API Reference

This document describes the lightweight route contract implemented by `pylon.api`.

## Scope

`pylon.api.server.APIServer` is a small in-process HTTP-style router.
`pylon.api.routes.register_routes()` installs route handlers backed by an in-memory `RouteStore`.

There is no built-in network daemon in this package. You compose:

- `APIServer`
- optional middlewares from `pylon.api.middleware`
- route handlers from `pylon.api.routes`

## Typical Middleware Stack

The common stack is:

1. `AuthMiddleware`
2. `TenantMiddleware`
3. `RateLimitMiddleware`
4. `SecurityHeadersMiddleware`

Important details:

- authentication is optional and only enforced if `AuthMiddleware` is installed
- route handlers expect `tenant_id` in `request.context`
- `TenantMiddleware` normally provides that context from `X-Tenant-ID`
- `/health` bypasses auth and tenant checks

## Request Context Expectations

When the standard middlewares are installed:

- `Authorization: Bearer <token>` is required for non-health routes
- `X-Tenant-ID: <tenant-id>` is required unless `TenantMiddleware(require_tenant=False)` is used
- rate limits are applied per tenant via token bucket

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

The route compiles the registered `PylonProject`, executes it through the shared runtime, and returns the normalized public run payload.

Important persistence note:

- the server stores raw run records as the command-side source of truth
- public responses rebuild `execution_summary`, `approval_summary`, and replay metadata through the shared query service

Response `202 Accepted`

Headers:

- `Location: /api/v1/workflow-runs/{run_id}`

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

### `AuthMiddleware`

- skips `/health`
- expects `Authorization: Bearer <token>`
- validates tokens against an in-memory set

### `TenantMiddleware`

- skips `/health`
- injects `tenant_id` into `request.context`
- validates tenant IDs against `^[a-z0-9][a-z0-9_-]{0,63}$`

### `RateLimitMiddleware`

- default rate: `10` requests/sec
- default burst: `20`
- emits `retry-after` header on `429`

### `SecurityHeadersMiddleware`

Adds:

- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `content-security-policy: default-src 'none'`
- `x-xss-protection: 0`
