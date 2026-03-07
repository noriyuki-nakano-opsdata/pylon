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

### `POST /workflows/{id}/run`

Create a workflow run request record for the current tenant.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `input` | object | No | defaults to `{}` |
| `parameters` | object | No | defaults to `{}` |

Response `202 Accepted`

Headers:

- `Location: /api/v1/workflow-runs/{run_id}`

Example body:

```json
{
  "id": "r1a2b3c4d5e6",
  "workflow_id": "build-pipeline",
  "status": "pending",
  "input": {"repo": "my-app", "branch": "main"},
  "parameters": {"max_retries": 3},
  "started_at": 1709827200.0,
  "tenant_id": "default"
}
```

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
