# API Reference

## Authentication

All endpoints except `/health` require a Bearer token:

```
Authorization: Bearer <token>
```

Multi-tenant requests include a tenant header:

```
X-Tenant-ID: <tenant-id>
```

Rate limiting is applied per tenant using a token bucket algorithm.

## Endpoints

### Health

#### `GET /health`

Returns server health status. No authentication required.

**Response** `200 OK`

```json
{
  "status": "ok",
  "timestamp": 1709827200.0
}
```

---

### Agents

#### `POST /agents`

Create a new agent.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Agent name (1-128 chars) |
| `model` | string | No | LLM model identifier |
| `role` | string | No | Agent role description |
| `autonomy` | string | No | Autonomy level: A0-A4 (default: A2) |
| `tools` | array | No | List of tool names |
| `sandbox` | string | No | Sandbox tier: gvisor, firecracker, docker, none (default: gvisor) |

**Example**

```bash
curl -X POST http://localhost:8080/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "coder",
    "model": "anthropic/claude-sonnet-4-20250514",
    "role": "Write production-quality code",
    "autonomy": "A2",
    "tools": ["file-read", "file-write", "shell"],
    "sandbox": "gvisor"
  }'
```

**Response** `201 Created`

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "coder",
  "model": "anthropic/claude-sonnet-4-20250514",
  "role": "Write production-quality code",
  "autonomy": "A2",
  "tools": ["file-read", "file-write", "shell"],
  "sandbox": "gvisor",
  "status": "ready",
  "tenant_id": "default"
}
```

#### `GET /agents`

List all agents for the current tenant.

**Response** `200 OK`

```json
{
  "agents": [...],
  "count": 2
}
```

#### `GET /agents/{id}`

Get a specific agent by ID.

**Response** `200 OK` or `404 Not Found`

#### `DELETE /agents/{id}`

Delete an agent.

**Response** `204 No Content` or `404 Not Found`

---

### Workflows

#### `POST /workflows/{id}/runs`

Start a new workflow run.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | object | No | Input data for the workflow |
| `parameters` | object | No | Runtime parameters |

**Example**

```bash
curl -X POST http://localhost:8080/workflows/build-pipeline/runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"repo": "my-app", "branch": "main"},
    "parameters": {"max_retries": 3}
  }'
```

**Response** `201 Created`

```json
{
  "id": "r1a2b3c4d5e6",
  "workflow_id": "build-pipeline",
  "status": "running",
  "input": {"repo": "my-app", "branch": "main"},
  "parameters": {"max_retries": 3},
  "started_at": 1709827200.0
}
```

#### `GET /workflows/{id}/runs/{run_id}`

Get the status of a workflow run.

**Response** `200 OK` or `404 Not Found`

---

### Kill Switch

#### `POST /kill-switch`

Activate the emergency kill switch.

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scope` | string | Yes | Scope: global, tenant:{id}, workflow:{id}, agent:{id} |
| `reason` | string | Yes | Reason for activation |
| `issued_by` | string | Yes | Identity of the person activating |

**Example**

```bash
curl -X POST http://localhost:8080/kill-switch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "agent:coder-123",
    "reason": "Agent producing unsafe output",
    "issued_by": "admin@example.com"
  }'
```

**Response** `201 Created`

```json
{
  "scope": "agent:coder-123",
  "reason": "Agent producing unsafe output",
  "issued_by": "admin@example.com",
  "activated_at": 1709827200.0
}
```

---

## Error Responses

All errors follow a consistent format:

```json
{
  "error": "Description of the error"
}
```

Validation errors include a list:

```json
{
  "errors": [
    "Field 'name' is required",
    "Field 'sandbox' must be one of ['gvisor', 'firecracker', 'docker', 'none']"
  ]
}
```

### Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (successful delete) |
| 400 | Bad Request (missing headers) |
| 401 | Unauthorized (invalid or missing token) |
| 404 | Not Found |
| 405 | Method Not Allowed |
| 422 | Validation Error |
| 429 | Rate Limit Exceeded |

## Rate Limiting

Requests are rate-limited per tenant using a token bucket algorithm:

- **Default rate**: 10 requests/second
- **Burst capacity**: 20 requests

When rate-limited, the response includes a `Retry-After` header.

## Middleware Stack

Requests pass through middleware in order:

1. **AuthMiddleware** -- Validates Bearer token
2. **TenantMiddleware** -- Extracts X-Tenant-ID
3. **RateLimitMiddleware** -- Per-tenant rate limiting
4. **Route Handler** -- Business logic
