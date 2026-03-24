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
- `APIObservabilityConfig`
- `build_api_server(...)`
- `build_http_api_server(...)`

Auth backend choices in the reference wiring are:

- `none`
- `memory`
- `json_file`
- `jwt_hs256`
- `jwt_jwks`
- `jwt_oidc`

## Typical Middleware Stack

The common stack is:

1. `RequestContextMiddleware`
2. `RequestTelemetryMiddleware`
3. `AuthMiddleware`
4. `TenantMiddleware`
5. `RateLimitMiddleware`
6. `SecurityHeadersMiddleware`

Important details:

- authentication is optional and only enforced if `AuthMiddleware` is installed
- route handlers expect `tenant_id` in `request.context`
- `TenantMiddleware` can source tenant context either from `X-Tenant-ID` or from
  an authenticated principal bound to a tenant
- `RequestContextMiddleware` injects `request_id` and `correlation_id` into
  request context, and echoes `request_id`, `correlation_id`, and `trace_id`
  back on responses when available
- `/health` and `/ready` bypass auth and tenant checks
- `/metrics` bypasses tenant and rate-limit checks, but still requires auth when auth is enabled

## Request Context Expectations

When the standard middlewares are installed:

- `Authorization: Bearer <token>` is required for non-health/non-ready routes when auth is enabled
- `X-Tenant-ID: <tenant-id>` is required unless either:
  - `TenantMiddleware(require_tenant=False)` is used, or
  - the authenticated principal already carries a tenant binding
- `X-Request-ID` is optional; when omitted, the server generates one
- `X-Correlation-ID` is optional; when omitted, it defaults to the request ID
- rate limits are applied through a pluggable token-bucket store and default to
  tenant-scoped buckets

## Routes

Public contract policy:

- canonical public routes live under `/api/v1`
- selected versionless routes remain available as compatibility aliases
- compatibility aliases emit `Deprecation`, `Sunset`, `Link`, and
  `X-Pylon-Canonical-Path` response headers
- `GET /api/v1/contract` is the machine-readable contract manifest for
  canonical routes, scopes, and alias policy
- new clients should target `/api/v1` and treat aliases as migration-only

### `GET /health`

Always available.

Response `200 OK`

```json
{
  "status": "healthy",
  "checks": [
    {"name": "system", "status": "healthy", "message": "operational"}
  ],
  "timestamp": 1709827200.0
}
```

### `GET /ready`

Available when both `observability.enabled=true` **and**
`observability.readiness_route_enabled=true` (both default to `true`). When
either setting is `false`, the route is not registered and requests return `404`.
Returns `200` when the API is ready to serve traffic and `503` when a required
dependency is unavailable.

```json
{
  "status": "ready",
  "ready": true,
  "checks": [
    {"name": "system", "status": "healthy", "message": "operational"},
    {"name": "control_plane", "status": "healthy", "message": "reachable"}
  ],
  "timestamp": 1709827200.0
}
```

### `GET /metrics`

Available when observability is enabled and a Prometheus exporter is configured.
When auth is enabled, the caller must hold `observability:read` (or a wildcard
covering it).

Response `200 OK`

Content type: `text/plain; version=0.0.4; charset=utf-8`

Example:

```text
# TYPE pylon_api_request_count counter
pylon_api_request_count{method="POST",route="/api/v1/agents",status_class="2xx"} 1.0
```

> **Note:** The `pylon_` prefix shown above is the default `metrics_namespace`.
> If `observability.metrics_namespace` is set to a different value, the prefix
> changes accordingly (e.g., `metrics_namespace: "myapp"` produces
> `myapp_api_request_count`).

If `observability.telemetry_sink_backend=jsonl` is configured, the same API
request flow also emits structured log and span records to the configured JSONL
path. This sink uses the same `request_id`, `correlation_id`, and `trace_id`
values that appear in HTTP responses.

### `POST /api/v1/agents`

Create an agent record for the current tenant.

Compatibility aliases:

- `POST /agents`

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

### `GET /api/v1/agents`

List agents for the current tenant.

Compatibility aliases:

- `GET /agents`

Response `200 OK`

```json
{
  "agents": [],
  "count": 0
}
```

### `GET /api/v1/agents/{id}`

Fetch a tenant-scoped agent by ID.

Compatibility aliases:

- `GET /agents/{id}`

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `PATCH /api/v1/agents/{id}`

Update mutable agent fields for a tenant-scoped agent.

Compatibility aliases:

- `PATCH /agents/{id}`

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | No | 1-128 chars |
| `model` | string | No | provider/model identifier |
| `role` | string | No | free-form agent role |
| `autonomy` | string or int | No | `A0`-`A4` or `0`-`4` |
| `tools` | array | No | full replacement when supplied |
| `sandbox` | string | No | `gvisor`, `firecracker`, `docker`, `none` |
| `status` | string | No | lightweight compatibility field for operator UI |

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `DELETE /api/v1/agents/{id}`

Delete a tenant-scoped agent.

Compatibility aliases:

- `DELETE /agents/{id}`

Responses:

- `204 No Content`
- `403 Forbidden`
- `404 Not Found`

### `POST /api/v1/workflows`

Register a canonical workflow definition for the current tenant.

Compatibility aliases:

- `POST /workflows`

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

### `GET /api/v1/workflows`

List workflow definitions visible to the current tenant.

Compatibility aliases:

- `GET /workflows`

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

### `GET /api/v1/workflows/{id}`

Fetch one tenant-scoped workflow definition.

Compatibility aliases:

- `GET /workflows/{id}`

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `GET /api/v1/workflows/{id}/plan`

Return the scheduler-oriented dispatch plan for a canonical workflow definition.

Compatibility aliases:

- `GET /workflows/{id}/plan`

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

### `DELETE /api/v1/workflows/{id}`

Delete one tenant-scoped workflow definition.

Compatibility aliases:

- `DELETE /workflows/{id}`

Responses:

- `204 No Content`
- `403 Forbidden`
- `404 Not Found`

### `POST /api/v1/workflows/{id}/runs`

Create a workflow run for the current tenant from a registered canonical workflow definition.

Compatibility aliases:

- `POST /workflows/{id}/run`

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

- `Location: /api/v1/runs/{run_id}`

### `GET /api/v1/workflows/{id}/runs`

List normalized run views for one workflow definition.

Compatibility aliases:

- `GET /workflows/{id}/runs`

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

### `POST /api/v1/runs/{run_id}/resume`

Resume a previously paused workflow run through the same shared runtime.

Compatibility aliases:

- `POST /api/v1/workflow-runs/{run_id}/resume`

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `input` | object | No | overrides the stored run input when provided |

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`
- `422 Validation Error`

### `GET /api/v1/workflows/{id}/runs/{run_id}`

Fetch a workflow run by workflow ID plus run ID.

Compatibility aliases:

- `GET /workflows/{id}/runs/{run_id}`

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

### `GET /api/v1/runs/{run_id}`

Fetch a workflow run by run ID only.

Compatibility aliases:

- `GET /api/v1/workflow-runs/{run_id}`

Responses:

- `200 OK`
- `403 Forbidden`
- `404 Not Found`

Returned payload shape matches `POST /api/v1/workflows/{id}/runs` and includes:

- `execution_summary`
- `approval_summary`
- `policy_resolution`
- `runtime_metrics`
- `state_version`
- `state_hash`

### `GET /api/v1/runs`

List all run views for the current tenant.

Compatibility aliases:

- `GET /api/v1/workflow-runs`

### `GET /api/v1/runs/{run_id}/approvals`

List approval records associated with one run.

Compatibility aliases:

- `GET /api/v1/workflow-runs/{run_id}/approvals`

### `GET /api/v1/runs/{run_id}/checkpoints`

List checkpoint records associated with one run.

Compatibility aliases:

- `GET /api/v1/workflow-runs/{run_id}/checkpoints`

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

### `GET /api/v1/agents/{id}/skills`

List the skills assigned to one agent.

### `PATCH /api/v1/agents/{id}/skills`

Replace the set of skill IDs assigned to one agent.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `skills` | array | Yes | list of skill IDs |

### `GET /api/v1/agents/activity`

Return tenant-scoped operational views of agents, including the currently
assigned mission-control task when one matches the agent `id` or `name`.

### `GET /api/v1/agents/{id}/activity`

Return one tenant-scoped operational agent payload.

### `GET /api/v1/tasks`

List mission-control tasks for the current tenant.
These project-operation records persist in the selected control-plane backend
(`memory`, `json_file`, or `sqlite`) rather than living only in API process
memory.

Query params:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `status` | string | No | `backlog`, `in_progress`, `review`, `done` |

### `POST /api/v1/tasks`

Create a task on the mission-control board.

Required fields:

- `title`
- `description`
- `status`
- `priority`
- `assignee`
- `assigneeType`

### `GET /api/v1/tasks/{task_id}`

Fetch one task by ID.

### `PATCH /api/v1/tasks/{task_id}`

Update mutable task fields such as `status`, `priority`, `assignee`, and
`payload`.

### `DELETE /api/v1/tasks/{task_id}`

Delete one task.

### `GET /api/v1/memories`

List mission-control memory entries for the current tenant.

### `POST /api/v1/memories`

Create one memory entry.

Request body supports:

- `title`
- `content`
- `category`
- `actor`
- optional `tags`
- optional `details`

### `DELETE /api/v1/memories/{entry_id}`

Delete one memory entry.

### `GET /api/v1/events`

List scheduled calendar events for the current tenant.

### `POST /api/v1/events`

Create one scheduled event. When `end` is omitted, the reference backend
defaults it to one hour after `start`.

### `DELETE /api/v1/events/{event_id}`

Delete one scheduled event.

### `GET /api/v1/content`

List content-pipeline items for the current tenant.

### `POST /api/v1/content`

Create one content-pipeline item.

### `PATCH /api/v1/content/{content_id}`

Update mutable content fields such as `stage`, `assignee`, and `description`.

### `DELETE /api/v1/content/{content_id}`

Delete one content item.

### `GET /api/v1/teams`

List tenant-scoped team definitions. The reference backend seeds the default
product teams on first access so the UI can render immediately.

### `POST /api/v1/teams`

Create one team definition.

### `PATCH /api/v1/teams/{id}`

Update one team definition.

### `DELETE /api/v1/teams/{id}`

Delete one team definition. Agents assigned to that team are moved to the
tenant's default fallback team.

### `GET /api/v1/skills`

Return a compatibility payload for the UI skills catalog. The current
implementation is intentionally lightweight and may return an empty catalog.

### `POST /api/v1/skills/scan`

Return a compatibility scan summary for the UI skills page.

### `POST /api/v1/skills/{id}/execute`

Execute one skill through a configured provider runtime when available. If the
backend has no provider runtime or no default model for the chosen provider,
the reference implementation returns a deterministic local preview payload
instead of failing the UI flow.

Request body:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `input` | string | No | defaults to empty string |
| `context` | object | No | string map passed as execution context |
| `provider` | string | No | preferred provider name |
| `model` | string | No | preferred model ID |

### `GET /api/v1/models`

Return a compatibility provider/model catalog for the UI model management page.

### `GET /api/v1/models/health`

Return per-provider health summaries for the current model catalog.

### `POST /api/v1/models/refresh`

Refresh the compatibility provider/model catalog and return the same payload
shape as `GET /api/v1/models`.

### `POST /api/v1/models/policy`

Store a lightweight provider policy override.

### `POST /api/v1/ads/audit`

Create one ads audit run and return a `run_id`. The reference backend computes
the final report deterministically from the supplied platforms, industry, and
optional budget/account exports, then exposes progressive status through the
polling endpoint below. Audit runs and reports are stored in the shared
control-plane backend so they survive API restarts when a durable backend is
configured.

### `GET /api/v1/ads/audit/{run_id}`

Poll audit status. Returns:

- `status`
- `progress`
- `report` once the run reaches `completed`

### `GET /api/v1/ads/reports`

List tenant-scoped ads audit reports, newest first.

### `GET /api/v1/ads/reports/{report_id}`

Fetch one ads audit report.

### `POST /api/v1/ads/plan`

Generate one deterministic media plan from an industry template and optional
budget.

### `POST /api/v1/ads/budget/optimize`

Return a reference allocation using a 70/20/10 split plus a
benchmark-informed per-platform mix.

### `GET /api/v1/ads/benchmarks/{platform}`

Return built-in benchmark metadata for one ads platform.

### `GET /api/v1/ads/templates`

Return the built-in industry templates used by the ads planning flow.

### `GET /api/v1/gtm/overview`

Return one project-scoped GTM operating summary derived from current agents,
tasks, events, content items, ads reports, and available skills. The payload
includes:

- `summary`
- `teams`
- `motions`
- `capabilities`
- `recommendations`

### `GET /api/v1/costs/summary`

Return a tenant-scoped cost aggregate for the requested period.

Compatibility aliases:

- `GET /api/v1/costs/realtime`

Query params:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `period` | string | No | defaults to `mtd` |

Example response:

```json
{
  "period": "mtd",
  "total_usd": 1.245,
  "budget_usd": 5.0,
  "run_count": 3,
  "total_tokens_in": 12000,
  "total_tokens_out": 4800,
  "by_provider": {"anthropic": 1.245},
  "by_model": {"anthropic/claude-sonnet-4-20250514": 1.245}
}
```

### `GET /api/v1/features`

Return the product surface manifest for the current tenant. This allows UI and
SDK clients to hide unimplemented surfaces instead of probing routes ad hoc.

Example response:

```json
{
  "contract_version": "2026-03-11",
  "canonical_prefix": "/api/v1",
  "legacy_aliases_enabled": true,
  "legacy_alias_policy": {
    "deprecated_on": "2026-03-11",
    "sunset_on": "2026-09-30"
  },
  "contract_path": "/api/v1/contract",
  "tenant_id": "default",
  "surfaces": {
    "admin": {
      "dashboard": true,
      "workflows": true,
      "agents": true
    },
    "project": {
      "runs": true,
      "approvals": true,
      "lifecycle": true,
      "tasks": true,
      "team": true,
      "memory": true,
      "calendar": true,
      "content": true,
      "ads": true,
      "studio": false
    }
  }
}
```

### `GET /api/v1/contract`

Return the canonical public contract manifest for the current tenant.

Use this when you need machine-readable route discovery, alias migration policy,
or authorization scope metadata for generated clients and contract tests.

Example response:

```json
{
  "contract_version": "2026-03-11",
  "canonical_prefix": "/api/v1",
  "legacy_alias_policy": {
    "deprecated_on": "2026-03-11",
    "sunset_on": "2026-09-30"
  },
  "routes": [
    {
      "method": "POST",
      "path": "/api/v1/agents",
      "aliases": [
        {
          "path": "/agents",
          "deprecated": true,
          "deprecated_on": "2026-03-11",
          "sunset_on": "2026-09-30"
        }
      ],
      "authorization": {
        "any_of_scopes": [],
        "all_of_scopes": ["agents:write"]
      }
    }
  ]
}
```

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

- skips `/health` and `/ready`
- expects `Authorization: Bearer <token>`
- accepts a pluggable `TokenVerifier`
- supports the reference `InMemoryTokenVerifier`, `JsonFileTokenVerifier`,
  `JWTTokenVerifier`, and `JWKSTokenVerifier`
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

`JWKSTokenVerifier` validates RSA-signed JWTs against a JWKS document and supports:

- `RS256`, `RS384`, `RS512`
- JWKS loaded from file path or URL
- `kid` selection from multi-key JWKS documents
- configurable JWKS cache TTL
- configurable tenant/subject/scopes claim names
- refresh-on-key-miss and refresh-on-signature-failure retry once before failing

OIDC discovery support:

- `jwt_oidc` auth backend resolves `jwks_uri` from an OpenID Connect discovery
  document
- discovery documents may be loaded from file path or URL
- discovery issuer is used for claim validation when `jwt_issuer` is not set
- if both discovery issuer and configured issuer are present, they must match

Trust bootstrap defaults:

- `bootstrap_validate=true` by default for `jwt_jwks` and `jwt_oidc`
- startup bootstrap loads discovery/JWKS documents eagerly and fails server
  construction on invalid metadata or empty keysets
- `allow_insecure_http=false` by default
- `http://` JWKS and OIDC discovery sources are rejected unless explicitly
  enabled with `allow_insecure_http=true`

Route scope taxonomy:

- `agents:read`, `agents:write`
- `workflows:read`, `workflows:write`
- `runs:read`, `runs:write`
- `approvals:read`, `approvals:write`
- `checkpoints:read`
- `observability:read`
- `kill-switch:write`

Compatibility note:

- if authentication is disabled and no `AuthPrincipal` is present, route scope checks are skipped
- if authentication is enabled and a principal is authenticated, route scope checks are enforced

### `TenantMiddleware`

- skips `/health`, `/ready`, and `/metrics`
- injects `tenant_id` into `request.context`
- prefers tenant binding from the authenticated principal when available
- rejects `X-Tenant-ID` that conflicts with the authenticated principal
- validates tenant IDs against `^[a-z0-9][a-z0-9_-]{0,63}$`

### `RateLimitMiddleware`

- skips `/health`, `/ready`, and `/metrics`
- default rate: `10` requests/sec
- default burst: `20`
- accepts a pluggable `RateLimitStore`
- supports the reference `InMemoryRateLimitStore`, `SQLiteRateLimitStore`, and
  `RedisRateLimitStore`
- emits `retry-after` header on `429`
- emits `x-ratelimit-scope` on successful responses

Backend options:

- `memory`
- `sqlite`
- `redis`

Redis backend notes:

- configured through `rate_limit.url`
- uses the same token-bucket contract as the in-memory and SQLite stores
- supports shared rate-limit state across processes or hosts

Bucket scope options:

- `tenant` (default)
- `subject`
- `token`
- `tenant_subject`
- `global`

Fallback behavior:

- `tenant` falls back to `subject`, then `default`
- `subject` falls back to `tenant`, then `default`
- `token` falls back to `subject`, then `tenant`, then `default`
- `tenant_subject` falls back to `tenant`, then `subject`, then `default`

### `SecurityHeadersMiddleware`

Adds:

- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `content-security-policy: default-src 'none'`
- `x-xss-protection: 0`
