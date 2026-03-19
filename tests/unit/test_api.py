"""Tests for Pylon HTTP API server."""

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest

import pylon.api.routes as routes_module
from pylon.api.factory import (
    APIMiddlewareConfig,
    APIServerConfig,
    AuthBackend,
    AuthMiddlewareConfig,
    TenantMiddlewareConfig,
    build_api_server,
)
from pylon.api.health import HealthChecker, HealthCheckResult
from pylon.api.observability import build_api_observability_bundle
from pylon.api.middleware import (
    AuthMiddleware,
    InMemoryRateLimitStore,
    InMemoryTokenVerifier,
    JsonFileTokenVerifier,
    JWKSTokenVerifier,
    JWTTokenVerifier,
    MiddlewareChain,
    RateLimitBucketScope,
    RateLimitMiddleware,
    RedisRateLimitStore,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    SQLiteRateLimitStore,
    TenantMiddleware,
)
from pylon.api.routes import RouteStore, register_routes
from pylon.api.schemas import (
    CREATE_AGENT_SCHEMA,
    KILL_SWITCH_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    validate,
)
from pylon.api.server import APIServer, Request, Response
from pylon.approval.types import compute_approval_binding_hash
from pylon.control_plane import ControlPlaneBackend, InMemoryWorkflowControlPlaneStore
from pylon.dsl.parser import PylonProject
from pylon.errors import ConcurrencyError
from pylon.lifecycle import build_lifecycle_approval_binding
from pylon.providers.base import Response as ProviderResponse
from pylon.providers.base import TokenUsage
from pylon.runtime.llm import ProviderRegistry
from pylon.skills.catalog import SkillCatalog
from pylon.skills.compat import SkillCompatibilityLayer
from pylon.skills.runtime import SkillRuntime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(payload: dict[str, object], secret: str) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{body}.{signature_b64}"


def _make_rs256_jwt(
    payload: dict[str, object],
    *,
    key_id: str = "test-key",
) -> tuple[str, dict[str, object]]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    def _b64_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": key_id,
                "use": "sig",
                "alg": "RS256",
                "n": _b64_uint(public_numbers.n),
                "e": _b64_uint(public_numbers.e),
            }
        ]
    }
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT", "kid": key_id}).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signing_input = f"{header}.{body}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    token = f"{header}.{body}.{signature_b64}"
    return token, jwks

def _server_with_routes(**route_kwargs: object) -> tuple[APIServer, RouteStore]:
    """Create a server with all routes registered and default tenant context."""
    server = APIServer()
    server.add_middleware(TenantMiddleware(require_tenant=False))
    store = register_routes(server, **route_kwargs)
    return server, store


def _authed_server() -> tuple[APIServer, RouteStore]:
    """Create a server with auth + tenant middleware."""
    server = APIServer()
    auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
    auth.add_token("test-token", scopes=("*",))
    tenant = TenantMiddleware(require_tenant=False)
    server.add_middleware(auth)
    server.add_middleware(tenant)
    store = register_routes(server)
    return server, store


def _workflow_project(name: str = "demo-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
        }
    )


def _wait_for_skill_import_job(
    server: APIServer,
    job_id: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_body: dict[str, object] | None = None
    while time.time() < deadline:
        response = server.handle_request("GET", f"/api/v1/skill-import-jobs/{job_id}")
        assert response.status_code == 200
        assert isinstance(response.body, dict)
        last_body = response.body
        if response.body.get("status") in {"completed", "failed"}:
            return response.body
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for skill import job {job_id}: {last_body}")


def _metric_series(
    snapshot: dict[str, object],
    group: str,
    name: str,
) -> list[dict[str, object]]:
    series = snapshot.get(group, [])
    assert isinstance(series, list)
    return [
        item
        for item in series
        if isinstance(item, dict) and str(item.get("name", "")) == name
    ]


class _FakeSkillProvider:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def chat(self, messages, **kwargs):
        user_messages = [message.content for message in messages if message.role == "user"]
        return ProviderResponse(
            content=" | ".join(user_messages),
            model=str(kwargs.get("model") or self._model_id),
            usage=TokenUsage(input_tokens=21, output_tokens=13),
        )

    async def stream(self, messages, **kwargs):
        if False:  # pragma: no cover
            yield messages, kwargs

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_name(self) -> str:
        return "fake"


def _write_external_skill_repo(base_dir: Path) -> Path:
    repo_root = base_dir / "marketingskills-like"
    analytics_dir = repo_root / "skills" / "analytics-tracking"
    context_dir = repo_root / "skills" / "product-marketing-context"
    (analytics_dir / "references").mkdir(parents=True)
    context_dir.mkdir(parents=True)
    (repo_root / "tools" / "integrations").mkdir(parents=True)
    (repo_root / "tools" / "clis").mkdir(parents=True)
    (repo_root / "VERSIONS.md").write_text("# Versions\n", encoding="utf-8")
    (repo_root / "tools" / "REGISTRY.md").write_text(
        "| Tool | Category | API | MCP | CLI | SDK | Guide |\n"
        "|---|---|---|---|---|---|---|\n"
        "| ga4 | Analytics | ✓ | ✓ | [✓](clis/ga4.js) | ✓ | [ga4.md](integrations/ga4.md) |\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "integrations" / "ga4.md").write_text(
        "# GA4\n\nUse GA4 for analytics tracking.\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "clis" / "ga4.js").write_text(
        "process.stdin.resume(); process.stdin.on('end', () => console.log('ga4 ok'));\n",
        encoding="utf-8",
    )
    (context_dir / "SKILL.md").write_text(
        "---\n"
        "name: product-marketing-context\n"
        "description: Create the shared product marketing context.\n"
        "metadata:\n"
        "  version: 1.1.0\n"
        "---\n\n"
        "Create `.agents/product-marketing-context.md` for the project.\n",
        encoding="utf-8",
    )
    (analytics_dir / "SKILL.md").write_text(
        "---\n"
        "name: analytics-tracking\n"
        "description: Set up and audit analytics tracking.\n"
        "metadata:\n"
        "  version: 1.1.0\n"
        "---\n\n"
        "If `.agents/product-marketing-context.md` exists, read it before asking questions.\n",
        encoding="utf-8",
    )
    (analytics_dir / "references" / "event-library.md").write_text(
        "# Event Library\n\nTrack the important events.\n",
        encoding="utf-8",
    )
    return repo_root


def _limited_workflow_project(name: str = "limited-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
            "goal": {
                "objective": "finish both steps",
                "constraints": {"max_iterations": 1},
            },
        }
    )


def _approval_project(name: str = "approval-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "reviewer": {"role": "review", "autonomy": "A4"},
            },
            "workflow": {
                "nodes": {
                    "review": {"agent": "reviewer", "next": "END"},
                }
            },
        }
    )


# ---------------------------------------------------------------------------
# Route store
# ---------------------------------------------------------------------------

class TestRouteStore:
    def test_surface_records_support_compare_and_set(self):
        store = RouteStore(control_plane_store=InMemoryWorkflowControlPlaneStore())

        created = store.put_surface_record(
            "skill_import_worker_leases",
            "primary",
            {"id": "primary", "owner": "worker-a"},
            expected_record_version=0,
        )
        assert created["record_version"] == 1

        updated = store.put_surface_record(
            "skill_import_worker_leases",
            "primary",
            {
                "id": "primary",
                "owner": "worker-a",
                "expires_at": "2026-03-13T00:00:00+00:00",
            },
            expected_record_version=1,
        )
        assert updated["record_version"] == 2

        with pytest.raises(ConcurrencyError):
            store.put_surface_record(
                "skill_import_worker_leases",
                "primary",
                {"id": "primary", "owner": "worker-b"},
                expected_record_version=1,
            )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_valid_create_agent(self):
        ok, errors = validate({"name": "coder"}, CREATE_AGENT_SCHEMA)
        assert ok is True
        assert errors == []

    def test_missing_required_field(self):
        ok, errors = validate({}, CREATE_AGENT_SCHEMA)
        assert ok is False
        assert any("name" in e for e in errors)

    def test_invalid_type(self):
        ok, errors = validate({"name": 123}, CREATE_AGENT_SCHEMA)
        assert ok is False
        assert any("type" in e for e in errors)

    def test_invalid_choice(self):
        ok, errors = validate({"name": "x", "sandbox": "invalid"}, CREATE_AGENT_SCHEMA)
        assert ok is False
        assert any("sandbox" in e for e in errors)

    def test_min_length(self):
        ok, errors = validate({"name": ""}, CREATE_AGENT_SCHEMA)
        assert ok is False
        assert any("at least" in e for e in errors)

    def test_valid_kill_switch(self):
        data = {"scope": "global", "reason": "test", "issued_by": "admin"}
        ok, errors = validate(data, KILL_SWITCH_SCHEMA)
        assert ok is True

    def test_valid_kill_switch_with_parent_scope(self):
        data = {
            "scope": "workflow:wf-1",
            "reason": "test",
            "issued_by": "admin",
            "parent_scope": "tenant:acme",
        }
        ok, errors = validate(data, KILL_SWITCH_SCHEMA)
        assert ok is True

    def test_non_dict_body(self):
        ok, errors = validate("not a dict", CREATE_AGENT_SCHEMA)  # type: ignore[arg-type]
        assert ok is False
        assert any("JSON object" in e for e in errors)

    def test_workflow_run_schema_optional(self):
        ok, errors = validate({}, WORKFLOW_RUN_SCHEMA)
        assert ok is True

    def test_workflow_run_schema_rejects_explicit_null_input(self):
        ok, errors = validate({"input": None}, WORKFLOW_RUN_SCHEMA)
        assert ok is False
        assert errors == ["Field 'input' must not be null"]

    def test_workflow_run_schema_accepts_idempotency_key(self):
        ok, errors = validate({"idempotency_key": "req-1"}, WORKFLOW_RUN_SCHEMA)
        assert ok is True
        assert errors == []

    def test_workflow_run_schema_accepts_queued_execution_mode(self):
        ok, errors = validate({"execution_mode": "queued"}, WORKFLOW_RUN_SCHEMA)
        assert ok is True
        assert errors == []


# ---------------------------------------------------------------------------
# Server routing
# ---------------------------------------------------------------------------

class TestServerRouting:
    def test_health_endpoint(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/health")
        assert resp.status_code == 200
        assert resp.body["status"] == "healthy"
        assert "checks" in resp.body
        assert "timestamp" in resp.body

    def test_ready_endpoint(self):
        server, _ = build_api_server(
            APIServerConfig(
                middleware=APIMiddlewareConfig(
                    tenant=TenantMiddlewareConfig(require_tenant=False),
                )
            )
        )

        resp = server.handle_request("GET", "/ready")

        assert resp.status_code == 200
        assert resp.body["status"] == "ready"
        assert resp.body["ready"] is True
        assert "checks" in resp.body

    def test_metrics_endpoint_renders_prometheus_text(self):
        server, _ = build_api_server(
            APIServerConfig(
                middleware=APIMiddlewareConfig(
                    auth=AuthMiddlewareConfig.from_mapping(
                        {
                            "backend": AuthBackend.MEMORY.value,
                            "tokens": [
                                {
                                    "token": "obs-token",
                                    "subject": "svc-observability",
                                    "scopes": ["observability:read", "agents:write"],
                                }
                            ],
                        }
                    ),
                    tenant=TenantMiddlewareConfig(require_tenant=False),
                )
            )
        )
        create = server.handle_request(
            "POST",
            "/agents",
            headers={"Authorization": "Bearer obs-token"},
            body={"name": "telemetry-agent"},
        )
        assert create.status_code == 201

        metrics = server.handle_request(
            "GET",
            "/metrics",
            headers={"Authorization": "Bearer obs-token"},
        )

        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain")
        assert "pylon_api_request_count" in metrics.body
        assert 'route="/agents"' in metrics.body
        assert create.headers["x-trace-id"]

    def test_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/nonexistent")
        assert resp.status_code == 404

    def test_method_not_allowed(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("PATCH", "/agents")
        assert resp.status_code == 405

    def test_method_not_allowed_has_allow_header(self):
        """M10: 405 responses must include Allow header per HTTP spec."""
        server, _ = _server_with_routes()
        resp = server.handle_request("PATCH", "/agents")
        assert resp.status_code == 405
        assert "allow" in resp.headers
        allowed = resp.headers["allow"]
        assert "GET" in allowed
        assert "POST" in allowed

    def test_duplicate_runs_route_removed(self):
        """M11: /workflows/{id}/runs POST should not be registered."""
        server, _ = _server_with_routes()
        resp = server.handle_request("POST", "/workflows/wf1/runs", body={})
        # GET exists for listing runs, but POST must remain unregistered.
        assert resp.status_code == 405
        assert resp.headers["allow"] == "GET"

    def test_path_param_extraction(self):
        server = APIServer()

        def handler(req: Request) -> Response:
            return Response(body={"id": req.path_params["id"]})

        server.add_route("GET", "/items/{id}", handler)
        resp = server.handle_request("GET", "/items/abc123")
        assert resp.body["id"] == "abc123"

    def test_multi_path_params(self):
        server = APIServer()

        def handler(req: Request) -> Response:
            return Response(body=req.path_params)

        server.add_route("GET", "/a/{x}/b/{y}", handler)
        resp = server.handle_request("GET", "/a/1/b/2")
        assert resp.body == {"x": "1", "y": "2"}

    def test_headers_normalized_to_lowercase(self):
        server = APIServer()
        captured = {}

        def handler(req: Request) -> Response:
            captured.update(req.headers)
            return Response()

        server.add_route("GET", "/test", handler)
        server.handle_request("GET", "/test", headers={"X-Custom": "val"})
        assert captured["x-custom"] == "val"

    def test_query_params_are_parsed(self):
        server = APIServer()

        def handler(req: Request) -> Response:
            return Response(body={"query": req.query_params})

        server.add_route("GET", "/search", handler)
        resp = server.handle_request("GET", "/search?q=pylon&tag=api&tag=v1")
        assert resp.body == {"query": {"q": "pylon", "tag": ["api", "v1"]}}


# ---------------------------------------------------------------------------
# Agent CRUD routes
# ---------------------------------------------------------------------------

class TestAgentRoutes:
    def test_create_agent(self):
        server, store = _server_with_routes()
        resp = server.handle_request("POST", "/agents", body={"name": "coder"})
        assert resp.status_code == 201
        assert resp.body["name"] == "coder"
        assert "id" in resp.body
        assert len(store.agents) == 1

    def test_create_agent_validation_error(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("POST", "/agents", body={})
        assert resp.status_code == 422

    def test_list_agents_empty(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/agents")
        assert resp.status_code == 200
        assert resp.body["count"] == 0

    def test_list_agents_after_create(self):
        server, _ = _server_with_routes()
        server.handle_request("POST", "/agents", body={"name": "a1"})
        server.handle_request("POST", "/agents", body={"name": "a2"})
        resp = server.handle_request("GET", "/agents")
        assert resp.body["count"] == 2

    def test_get_agent(self):
        server, _ = _server_with_routes()
        create_resp = server.handle_request("POST", "/agents", body={"name": "coder"})
        agent_id = create_resp.body["id"]
        resp = server.handle_request("GET", f"/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.body["name"] == "coder"

    def test_get_agent_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/agents/nonexistent")
        assert resp.status_code == 404

    def test_delete_agent(self):
        server, store = _server_with_routes()
        create_resp = server.handle_request("POST", "/agents", body={"name": "coder"})
        agent_id = create_resp.body["id"]
        resp = server.handle_request("DELETE", f"/agents/{agent_id}")
        assert resp.status_code == 204
        assert agent_id not in store.agents

    def test_delete_agent_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("DELETE", "/agents/nonexistent")
        assert resp.status_code == 404

    def test_versioned_agent_routes_support_patch_and_skills(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(tmp_path / "imports"))
        monkeypatch.setattr(routes_module, "build_lifecycle_skill_catalog", lambda: {})
        server, store = _server_with_routes(
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=tmp_path / "imports"),
        )
        store.skills["triage"] = {
            "id": "triage",
            "name": "triage",
            "description": "",
            "category": "uncategorized",
            "risk": "unknown",
            "source": "local",
            "tags": [],
        }
        create_resp = server.handle_request(
            "POST",
            "/api/v1/agents",
            body={"name": "coder", "skills": ["code-review"]},
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.body["id"]

        patch_resp = server.handle_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}",
            body={"team": "platform", "autonomy": 3},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.body["team"] == "platform"
        assert patch_resp.body["autonomy"] == "A3"

        skills_resp = server.handle_request("GET", f"/api/v1/agents/{agent_id}/skills")
        assert skills_resp.status_code == 200
        assert skills_resp.body["skills"] == [
            {
                "id": "code-review",
                "alias": "code-review",
                "skill_key": "code-review",
                "name": "code-review",
                "description": "",
                "category": "uncategorized",
                "risk": "unknown",
                "source": "local",
                "tags": [],
                "handle": {
                    "source_id": "",
                    "skill_key": "code-review",
                    "canonical_id": "code-review",
                },
                "version_ref": {
                    "source_id": "",
                    "skill_key": "code-review",
                    "revision": "",
                    "canonical_ref": "code-review",
                },
            }
        ]

        update_skills = server.handle_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/skills",
            body={"skills": ["triage"]},
        )
        assert update_skills.status_code == 200
        assert update_skills.body["skills"] == ["triage"]

    def test_skills_and_models_compatibility_routes_return_empty_payloads(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(tmp_path / "imports"))
        monkeypatch.setattr(routes_module, "build_lifecycle_skill_catalog", lambda: {})
        server, _ = _server_with_routes(
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=tmp_path / "imports"),
        )

        skills = server.handle_request("GET", "/api/v1/skills")
        assert skills.status_code == 200
        assert skills.body == {
            "skills": [],
            "total": 0,
            "categories": {},
            "sources": {},
        }

        scan = server.handle_request("POST", "/api/v1/skills/scan")
        assert scan.status_code == 200
        assert scan.body == {"total": 0, "new": 0, "removed": 0}

        categories = server.handle_request("GET", "/api/v1/skills/categories")
        assert categories.status_code == 200
        assert categories.body == {}

        models = server.handle_request("GET", "/api/v1/models")
        assert models.status_code == 200
        assert models.body == {
            "providers": {},
            "fallback_chain": [],
            "policies": {},
        }

        health = server.handle_request("GET", "/api/v1/models/health")
        assert health.status_code == 200
        assert health.body == {}

    def test_skill_execute_returns_local_preview_without_provider_runtime(self):
        server, store = _server_with_routes()
        store.skills["triage"] = {
            "id": "triage",
            "name": "Issue Triage",
            "description": "Summarize and prioritize new issues.",
            "content_preview": "Classify severity and propose the next action.",
            "category": "operations",
            "source": "local",
            "tags": ["triage"],
        }

        resp = server.handle_request(
            "POST",
            "/api/v1/skills/triage/execute",
            body={
                "input": "Customer reports login failures after deploy.",
                "context": {"repo": "pylon", "severity": "high"},
                "provider": "anthropic",
            },
        )

        assert resp.status_code == 200
        assert resp.body["skill_id"] == "triage"
        assert resp.body["provider"] == "local"
        assert resp.body["model"] == "builtin-skill-preview"
        assert "Customer reports login failures" in resp.body["result"]
        assert "deterministic local preview" in resp.body["result"]

    def test_skill_execute_uses_provider_runtime_when_available(self):
        registry = ProviderRegistry({"fake": lambda model_id: _FakeSkillProvider(model_id)})
        server, store = _server_with_routes(provider_registry=registry)
        store.skills["triage"] = {
            "id": "triage",
            "name": "Issue Triage",
            "description": "Summarize and prioritize new issues.",
            "category": "operations",
            "source": "local",
            "tags": ["triage"],
        }

        resp = server.handle_request(
            "POST",
            "/api/v1/skills/triage/execute",
            body={
                "input": "Login fails after deploy",
                "context": {"repo": "pylon"},
                "provider": "fake",
                "model": "triage-model",
            },
        )

        assert resp.status_code == 200
        assert resp.body == {
            "skill_id": "triage",
            "result": 'Execution context:\n{\n  "repo": "pylon"\n} | Login fails after deploy',
            "tokens_in": 21,
            "tokens_out": 13,
            "model": "triage-model",
            "provider": "fake",
        }

    def test_filesystem_skills_are_listed_and_assignable(self, tmp_path: Path, monkeypatch):
        skill_dir = tmp_path / "skills" / "triage"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "id: triage\n"
            "name: Issue Triage\n"
            "description: Summarize issues.\n"
            "category: operations\n"
            "tags: [triage]\n"
            "---\n\n"
            "Classify severity and next action.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            routes_module,
            "get_default_skill_runtime",
            lambda: SkillRuntime(
                SkillCatalog(skill_dirs=(str(tmp_path / "skills"),), refresh_ttl_seconds=0)
            ),
        )
        server, _ = _server_with_routes()
        create = server.handle_request(
            "POST",
            "/api/v1/agents",
            body={"name": "coder", "skills": []},
        )
        agent_id = create.body["id"]

        skills = server.handle_request("GET", "/api/v1/skills")
        assert skills.status_code == 200
        assert skills.body["skills"][0]["id"] == "triage"

        update = server.handle_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/skills",
            body={"skills": ["triage"]},
        )
        assert update.status_code == 200
        assigned = server.handle_request("GET", f"/api/v1/agents/{agent_id}/skills")
        assert assigned.body["skills"][0]["id"] == "triage"

    def test_external_skill_sources_import_agent_skills_repositories(self, tmp_path: Path, monkeypatch):
        repo_root = _write_external_skill_repo(tmp_path)
        import_root = tmp_path / "imports"
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
        server, _ = _server_with_routes(
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=import_root),
        )

        created = server.handle_request(
            "POST",
            "/api/v1/skill-sources",
            body={"location": str(repo_root), "kind": "local-dir"},
        )

        assert created.status_code == 201
        assert created.body["source_format"] == "agent-skills-spec"
        assert created.body["adapter_profile"] == "marketingskills"
        assert created.body["imported_skill_count"] == 2
        assert created.body["last_report"]["snapshot_id"]
        assert created.body["last_report"]["snapshot"]["snapshot_id"] == created.body["last_report"]["snapshot_id"]

        listed = server.handle_request("GET", "/api/v1/skill-sources")
        assert listed.status_code == 200
        assert listed.body["count"] == 1

        source_id = created.body["id"]
        imported = server.handle_request("GET", f"/api/v1/skill-sources/{source_id}/skills")
        assert imported.status_code == 200
        assert {item["id"] for item in imported.body["skills"]} == {
            f"{source_id}:analytics-tracking",
            f"{source_id}:product-marketing-context",
        }
        analytics_manifest = next(
            item for item in imported.body["skills"] if item["alias"] == "analytics-tracking"
        )
        assert analytics_manifest["handle"]["canonical_id"] == f"{source_id}:analytics-tracking"
        assert analytics_manifest["version_ref"]["canonical_ref"].startswith(
            f"{source_id}:analytics-tracking@"
        )
        assert analytics_manifest["tool_candidates"][0]["review"]["state"] == "pending"
        assert analytics_manifest["tool_candidates"][0]["review"]["promoted"] is False

        skills = server.handle_request("GET", "/api/v1/skills")
        assert skills.status_code == 200
        analytics = next(
            item for item in skills.body["skills"] if item["alias"] == "analytics-tracking"
        )
        assert analytics["id"] == f"{source_id}:analytics-tracking"
        assert analytics["source_kind"] == "imported"
        assert analytics["source_format"] == "agent-skills-spec"
        assert analytics["handle"]["canonical_id"] == f"{source_id}:analytics-tracking"
        assert analytics["version_ref"]["canonical_ref"].startswith(
            f"{source_id}:analytics-tracking@"
        )
        assert "tools" not in analytics

        references = server.handle_request(
            "GET",
            f"/api/v1/skills/{source_id}:analytics-tracking/references",
        )
        assert references.status_code == 200
        assert references.body["skill_id"] == f"{source_id}:analytics-tracking"
        assert references.body["references"][0]["path"] == "references/event-library.md"

        contracts = server.handle_request(
            "GET",
            f"/api/v1/skills/{source_id}:analytics-tracking/context-contracts",
        )
        assert contracts.status_code == 200
        assert contracts.body["skill_id"] == f"{source_id}:analytics-tracking"
        assert contracts.body["context_contracts"][0]["path_patterns"][0] == ".agents/product-marketing-context.md"

    def test_skill_source_tool_candidate_approval_promotes_executable_binding(self, tmp_path: Path, monkeypatch):
        repo_root = _write_external_skill_repo(tmp_path)
        import_root = tmp_path / "imports"
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
        server, _ = _server_with_routes(
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=import_root),
        )

        created = server.handle_request(
            "POST",
            "/api/v1/skill-sources",
            body={"location": str(repo_root), "kind": "local-dir"},
        )
        assert created.status_code == 201
        source_id = created.body["id"]

        listed_candidates = server.handle_request(
            "GET",
            f"/api/v1/skill-sources/{source_id}/tool-candidates",
        )
        assert listed_candidates.status_code == 200
        assert listed_candidates.body["count"] == 1
        candidate = listed_candidates.body["candidates"][0]
        assert candidate["candidate_id"] == "analytics-tracking:ga4:cli"
        assert candidate["review"]["state"] == "pending"
        assert listed_candidates.body["states"] == {"pending": 1}

        approved = server.handle_request(
            "PATCH",
            f"/api/v1/skill-sources/{source_id}/tool-candidates/analytics-tracking:ga4:cli",
            body={"state": "approved", "note": "Reviewed and allowed for runtime use"},
        )
        assert approved.status_code == 200
        assert approved.body["candidate"]["review"]["state"] == "approved"
        assert approved.body["candidate"]["review"]["promoted"] is True
        assert approved.body["candidate"]["review"]["note"] == "Reviewed and allowed for runtime use"
        assert approved.body["report"]["promoted_tool_count"] == 1
        assert approved.body["report"]["tool_candidate_states"] == {"approved": 1}
        assert not (import_root / source_id / "tool-candidate-decisions.json").exists()

        skills = server.handle_request("GET", "/api/v1/skills")
        assert skills.status_code == 200
        analytics = next(
            item for item in skills.body["skills"] if item["alias"] == "analytics-tracking"
        )
        assert analytics["tools"][0]["id"] == "ga4"

        rescanned = server.handle_request(
            "POST",
            f"/api/v1/skill-sources/{source_id}/scan",
        )
        assert rescanned.status_code == 200
        assert rescanned.body["report"]["promoted_tool_count"] == 1
        listed_again = server.handle_request(
            "GET",
            f"/api/v1/skill-sources/{source_id}/tool-candidates",
        )
        assert listed_again.body["candidates"][0]["review"]["state"] == "approved"

    def test_skill_source_import_jobs_run_async_and_update_source_state(self, tmp_path: Path, monkeypatch):
        repo_root = _write_external_skill_repo(tmp_path)
        import_root = tmp_path / "imports"
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=False))
        store = RouteStore(control_plane_store=InMemoryWorkflowControlPlaneStore())
        observability = build_api_observability_bundle(
            control_plane_store=store.control_plane_store,
            auth_backend="none",
            rate_limit_backend=None,
            metrics_namespace="pylon",
            enable_prometheus_exporter=False,
        )
        register_routes(
            server,
            store=store,
            observability=observability,
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=import_root),
        )

        created = server.handle_request(
            "POST",
            "/api/v1/skill-sources?async=1",
            body={"location": str(repo_root), "kind": "local-dir"},
        )
        assert created.status_code == 202
        assert created.body["source"]["status"] == "queued"
        queue_task_id = str(created.body["job"]["queue_task_id"])

        create_job = _wait_for_skill_import_job(server, str(created.body["job"]["id"]))
        assert create_job["status"] == "completed"
        assert create_job["operation"] == "create"
        source_id = str(create_job["source_id"])
        queue_record = store.get_surface_record("skill_import_queue_tasks", queue_task_id)
        assert queue_record is not None
        assert queue_record["status"] == "completed"
        assert queue_record["record_version"] >= 1
        assert queue_record["payload"]["source_id"] == source_id
        lease_record = store.get_surface_record("skill_import_worker_leases", "primary")
        assert lease_record is not None
        assert lease_record["record_version"] >= 1

        fetched_source = server.handle_request("GET", f"/api/v1/skill-sources/{source_id}")
        assert fetched_source.status_code == 200
        assert fetched_source.body["status"] == "ready"

        rescanned = server.handle_request(
            "POST",
            f"/api/v1/skill-sources/{source_id}/scan?async=1",
        )
        assert rescanned.status_code == 202
        assert rescanned.body["source"]["status"] == "queued"

        scan_job = _wait_for_skill_import_job(server, str(rescanned.body["job"]["id"]))
        assert scan_job["status"] == "completed"
        assert scan_job["operation"] == "scan"

        listed_jobs = server.handle_request("GET", f"/api/v1/skill-import-jobs?source_id={source_id}")
        assert listed_jobs.status_code == 200
        assert listed_jobs.body["count"] >= 2
        summary = server.handle_request("GET", f"/api/v1/skill-import/summary?source_id={source_id}")
        assert summary.status_code == 200
        assert summary.body["source_id"] == source_id
        assert summary.body["worker"]["record_version"] >= 1
        assert summary.body["jobs"]["counts"]["completed"] >= 2
        assert summary.body["sources"]["counts"]["ready"] == 1
        assert summary.body["sources"]["items"][0]["id"] == source_id
        assert summary.body["reviews"]["candidate_count"] == 1
        assert summary.body["reviews"]["states"]["pending"] == 1
        assert summary.body["queue"]["tasks"][0]["source_id"] == source_id
        metrics_snapshot = observability.metrics.get_metrics()
        completed_jobs = _metric_series(metrics_snapshot, "counters", "skill_import_job_count")
        assert any(
            series.get("labels") == {"operation": "create", "status": "completed"}
            and float(series.get("value", 0.0)) >= 1.0
            for series in completed_jobs
        )
        assert any(
            series.get("labels") == {"operation": "scan", "status": "completed"}
            and float(series.get("value", 0.0)) >= 1.0
            for series in completed_jobs
        )
        queue_depth = _metric_series(metrics_snapshot, "gauges", "skill_import_queue_depth")
        assert any(series.get("labels") == {"status": "pending"} for series in queue_depth)
        leader_state = _metric_series(metrics_snapshot, "gauges", "skill_import_worker_is_leader")
        assert any(float(series.get("value", 0.0)) >= 0.0 for series in leader_state)
        heartbeat = _metric_series(metrics_snapshot, "gauges", "skill_import_worker_heartbeat_unix")
        assert any(float(series.get("value", 0.0)) > 0.0 for series in heartbeat)

        server.shutdown()
        time.sleep(0.05)
        assert store.get_surface_record("skill_import_worker_leases", "primary") is None

    def test_ready_reports_skill_import_worker_backlog_without_active_lease(self, tmp_path: Path, monkeypatch):
        repo_root = _write_external_skill_repo(tmp_path)
        import_root = tmp_path / "imports"
        monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
        server, _ = _server_with_routes(
            skill_runtime=SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0)),
            compatibility_layer=SkillCompatibilityLayer(import_root=import_root),
        )

        server.shutdown()
        queued = server.handle_request(
            "POST",
            "/api/v1/skill-sources?async=1",
            body={"location": str(repo_root), "kind": "local-dir"},
        )
        assert queued.status_code == 202
        time.sleep(0.05)

        ready = server.handle_request("GET", "/ready")
        assert ready.status_code == 503
        check = next(
            item
            for item in ready.body["checks"]
            if item["name"] == "skill_import_worker"
        )
        assert check["status"] == "unhealthy"
        assert check["pending"] >= 1
        assert "backlog exists" in check["message"]

    def test_features_endpoint_returns_product_surface_manifest(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/api/v1/features")
        assert resp.status_code == 200
        assert resp.body["canonical_prefix"] == "/api/v1"
        assert resp.body["contract_path"] == "/api/v1/contract"
        assert resp.body["legacy_alias_policy"]["sunset_on"] == "2026-09-30"
        assert resp.body["surfaces"]["admin"]["agents"] is True
        assert resp.body["surfaces"]["project"]["ads"] is True
        assert resp.body["surfaces"]["project"]["tasks"] is True
        assert resp.body["surfaces"]["project"]["lifecycle"] is True

    def test_contract_endpoint_returns_canonical_route_manifest(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/api/v1/contract")

        assert resp.status_code == 200
        assert resp.body["canonical_prefix"] == "/api/v1"
        assert resp.body["legacy_alias_policy"]["deprecated_on"] == "2026-03-11"
        create_agent = next(
            route
            for route in resp.body["routes"]
            if route["method"] == "POST" and route["path"] == "/api/v1/agents"
        )
        assert create_agent["aliases"] == [
            {
                "path": "/agents",
                "deprecated": True,
                "deprecated_on": "2026-03-11",
                "sunset_on": "2026-09-30",
            }
        ]
        assert create_agent["authorization"]["all_of_scopes"] == ["agents:write"]

    def test_legacy_alias_routes_emit_deprecation_headers(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("POST", "/agents", body={"name": "coder"})

        assert resp.status_code == 201
        assert resp.headers["deprecation"] == "true"
        assert resp.headers["sunset"] == "2026-09-30"
        assert resp.headers["x-pylon-canonical-path"] == "/api/v1/agents"
        assert resp.headers["link"] == '</api/v1/agents>; rel="successor-version"'
        assert "Deprecated API alias /agents" in resp.headers["warning"]


# ---------------------------------------------------------------------------
# Mission control / ads routes
# ---------------------------------------------------------------------------

class TestProjectOperationsRoutes:
    def test_mission_control_crud_and_agent_activity(self):
        server, _ = _server_with_routes()
        agent = server.handle_request(
            "POST",
            "/api/v1/agents",
            body={
                "name": "ops-bot",
                "model": "openai/gpt-5-mini",
                "role": "Operations",
                "team": "product",
                "tools": ["http", "bash"],
            },
        )
        assert agent.status_code == 201
        agent_id = agent.body["id"]

        task = server.handle_request(
            "POST",
            "/api/v1/tasks",
            body={
                "title": "Investigate onboarding drop-off",
                "description": "Review activation funnel metrics and propose fixes.",
                "status": "in_progress",
                "priority": "high",
                "assignee": "ops-bot",
                "assigneeType": "ai",
                "payload": {"run_id": "run-123", "phase": "research"},
            },
        )
        assert task.status_code == 201
        task_id = task.body["id"]

        activity = server.handle_request("GET", "/api/v1/agents/activity")
        assert activity.status_code == 200
        assert activity.body[0]["id"] == agent_id
        assert activity.body[0]["current_task"]["id"] == task_id
        assert activity.body[0]["team"] == "product"
        assert activity.body[0]["uptime_seconds"] >= 0

        task_detail = server.handle_request("GET", f"/api/v1/tasks/{task_id}")
        assert task_detail.status_code == 200
        assert task_detail.body["payload"]["phase"] == "research"

        task_patch = server.handle_request(
            "PATCH",
            f"/api/v1/tasks/{task_id}",
            body={"status": "review", "priority": "critical"},
        )
        assert task_patch.status_code == 200
        assert task_patch.body["status"] == "review"
        assert task_patch.body["priority"] == "critical"

        memory = server.handle_request(
            "POST",
            "/api/v1/memories",
            body={
                "title": "Activation insight",
                "content": "Users stall before first integration.",
                "category": "learnings",
                "actor": "ops-bot",
                "tags": ["activation", "onboarding"],
            },
        )
        assert memory.status_code == 201
        memories = server.handle_request("GET", "/api/v1/memories")
        assert memories.status_code == 200
        assert memories.body[0]["details"]["tags"] == ["activation", "onboarding"]

        event = server.handle_request(
            "POST",
            "/api/v1/events",
            body={
                "title": "Weekly growth review",
                "description": "Review paid and product loops",
                "start": "2026-03-11T09:00:00Z",
                "type": "review",
                "agentId": agent_id,
            },
        )
        assert event.status_code == 201
        listed_events = server.handle_request("GET", "/api/v1/events")
        assert listed_events.status_code == 200
        assert listed_events.body[0]["end"] == "2026-03-11T10:00:00Z"

        content = server.handle_request(
            "POST",
            "/api/v1/content",
            body={
                "title": "Launch announcement",
                "description": "Draft the product launch post",
                "type": "article",
                "stage": "draft",
                "assignee": "ops-bot",
                "assigneeType": "ai",
            },
        )
        assert content.status_code == 201
        content_id = content.body["id"]
        content_patch = server.handle_request(
            "PATCH",
            f"/api/v1/content/{content_id}",
            body={"stage": "review"},
        )
        assert content_patch.status_code == 200
        assert content_patch.body["stage"] == "review"

        teams = server.handle_request("GET", "/api/v1/teams")
        assert teams.status_code == 200
        assert any(team["id"] == "product" for team in teams.body)

        created_team = server.handle_request(
            "POST",
            "/api/v1/teams",
            body={"name": "Growth", "nameJa": "グロース", "icon": "TrendingUp"},
        )
        assert created_team.status_code == 201
        updated_team = server.handle_request(
            "PATCH",
            f"/api/v1/teams/{created_team.body['id']}",
            body={"color": "text-lime-400"},
        )
        assert updated_team.status_code == 200
        assert updated_team.body["color"] == "text-lime-400"

        assert server.handle_request("DELETE", f"/api/v1/content/{content_id}").status_code == 204
        assert server.handle_request("DELETE", f"/api/v1/events/{event.body['id']}").status_code == 204
        assert server.handle_request("DELETE", f"/api/v1/memories/{memory.body['entry_id']}").status_code == 204
        assert server.handle_request("DELETE", f"/api/v1/tasks/{task_id}").status_code == 204
        assert server.handle_request("DELETE", f"/api/v1/teams/{created_team.body['id']}").status_code == 204

    def test_team_routes_seed_specialist_roster_for_empty_tenant(self):
        server, _ = _server_with_routes()

        teams = server.handle_request(
            "GET",
            "/api/v1/teams",
            headers={"X-Tenant-ID": "opp"},
        )
        assert teams.status_code == 200
        assert any(team["id"] == "platform" for team in teams.body)
        assert any(team["id"] == "operations" for team in teams.body)

        activity = server.handle_request(
            "GET",
            "/api/v1/agents/activity",
            headers={"X-Tenant-ID": "opp"},
        )
        assert activity.status_code == 200
        ids = [agent["id"] for agent in activity.body]
        assert len(ids) == len(set(ids))
        assert any(agent["name"] == "Product Orchestrator" for agent in activity.body)
        assert any(agent["team"] == "platform" for agent in activity.body)
        assert any(agent["team"] == "operations" for agent in activity.body)
        assert len(activity.body) >= 10

    def test_ads_routes_return_coherent_reference_payloads(self):
        server, store = _server_with_routes()

        templates = server.handle_request("GET", "/api/v1/ads/templates")
        assert templates.status_code == 200
        assert any(template["id"] == "saas" for template in templates.body)

        plan = server.handle_request(
            "POST",
            "/api/v1/ads/plan",
            body={"industry_type": "saas", "monthly_budget": 12000},
        )
        assert plan.status_code == 200
        assert plan.body["industry_type"] == "saas"
        assert plan.body["recommended_platforms"][0] == "google"
        assert plan.body["campaign_architecture"]

        budget = server.handle_request(
            "POST",
            "/api/v1/ads/budget/optimize",
            body={
                "current_spend": {
                    "google": 5000,
                    "meta": 3000,
                    "linkedin": 1000,
                    "tiktok": 500,
                    "microsoft": 500,
                },
                "target_mer": 3.2,
                "monthly_budget": 12000,
            },
        )
        assert budget.status_code == 200
        assert budget.body["monthly_budget"] == 12000
        assert sum(budget.body["platform_mix"].values()) == 12000

        benchmarks = server.handle_request("GET", "/api/v1/ads/benchmarks/google")
        assert benchmarks.status_code == 200
        assert benchmarks.body["platform"] == "google"
        assert benchmarks.body["benchmark_mer"] > 0

        run = server.handle_request(
            "POST",
            "/api/v1/ads/audit",
            body={
                "platforms": ["google", "meta"],
                "industry_type": "saas",
                "monthly_budget": 15000,
                "account_data": {"google": "campaign export", "meta": "ad set export"},
            },
        )
        assert run.status_code == 201
        run_id = run.body["run_id"]

        updated_run = dict(store.ads_audit_runs[run_id])
        updated_run["created_at_epoch"] = time.time() - 10
        store.ads_audit_runs[run_id] = updated_run
        status = server.handle_request("GET", f"/api/v1/ads/audit/{run_id}")
        assert status.status_code == 200
        assert status.body["status"] == "completed"
        assert status.body["report"]["aggregate_grade"] in {"A", "B", "C", "D", "F"}
        assert status.body["report"]["platforms"][0]["checks"]

        reports = server.handle_request("GET", "/api/v1/ads/reports")
        assert reports.status_code == 200
        report_id = reports.body[0]["id"]

        report = server.handle_request("GET", f"/api/v1/ads/reports/{report_id}")
        assert report.status_code == 200
        assert report.body["aggregate_score"] >= 0
        assert report.body["total_checks"] == len(report.body["platforms"]) * 5
        assert "tenant_id" not in report.body

    @pytest.mark.parametrize(
        ("backend", "filename"),
        [
            (ControlPlaneBackend.JSON_FILE, "control-plane.json"),
            (ControlPlaneBackend.SQLITE, "control-plane.db"),
        ],
    )
    def test_project_surfaces_persist_across_server_restarts(
        self,
        tmp_path: Path,
        backend: ControlPlaneBackend,
        filename: str,
    ):
        control_plane_path = str(tmp_path / filename)
        server, _ = _server_with_routes(
            control_plane_backend=backend,
            control_plane_path=control_plane_path,
        )

        agent = server.handle_request(
            "POST",
            "/api/v1/agents",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"name": "growth-bot", "model": "openai/gpt-5-mini", "role": "Growth"},
        )
        assert agent.status_code == 201

        task = server.handle_request(
            "POST",
            "/api/v1/tasks",
            headers={"X-Tenant-ID": "tenant-a"},
            body={
                "title": "Run weekly audit",
                "description": "Audit paid media changes",
                "status": "backlog",
                "priority": "medium",
                "assignee": "growth-bot",
                "assigneeType": "ai",
            },
        )
        assert task.status_code == 201

        team = server.handle_request(
            "POST",
            "/api/v1/teams",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"name": "Growth", "nameJa": "グロース"},
        )
        assert team.status_code == 201

        memory = server.handle_request(
            "POST",
            "/api/v1/memories",
            headers={"X-Tenant-ID": "tenant-a"},
            body={
                "title": "Offer insight",
                "content": "Pricing proof increases conversion.",
                "category": "patterns",
                "actor": "growth-bot",
            },
        )
        assert memory.status_code == 201

        audit_run = server.handle_request(
            "POST",
            "/api/v1/ads/audit",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"platforms": ["google"], "industry_type": "saas", "monthly_budget": 9000},
        )
        assert audit_run.status_code == 201
        run_id = audit_run.body["run_id"]

        server_after_restart, restarted_store = _server_with_routes(
            control_plane_backend=backend,
            control_plane_path=control_plane_path,
        )
        audit_record = dict(restarted_store.ads_audit_runs[run_id])
        audit_record["created_at_epoch"] = time.time() - 10
        restarted_store.ads_audit_runs[run_id] = audit_record

        listed_agents = server_after_restart.handle_request(
            "GET",
            "/api/v1/agents/activity",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert listed_agents.status_code == 200
        assert listed_agents.body[0]["name"] == "growth-bot"

        listed_tasks = server_after_restart.handle_request(
            "GET",
            "/api/v1/tasks",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert listed_tasks.status_code == 200
        assert listed_tasks.body[0]["title"] == "Run weekly audit"

        listed_teams = server_after_restart.handle_request(
            "GET",
            "/api/v1/teams",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert any(entry["id"] == team.body["id"] for entry in listed_teams.body)

        listed_memories = server_after_restart.handle_request(
            "GET",
            "/api/v1/memories",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert listed_memories.body[0]["entry_id"] == memory.body["entry_id"]

        audit_status = server_after_restart.handle_request(
            "GET",
            f"/api/v1/ads/audit/{run_id}",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert audit_status.status_code == 200
        assert audit_status.body["status"] == "completed"
        assert audit_status.body["report"]["platforms"][0]["platform"] == "google"

    def test_model_policies_are_tenant_scoped(self):
        server, _ = _server_with_routes()

        tenant_a = server.handle_request(
            "POST",
            "/api/v1/models/policy",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"provider": "anthropic", "policy": "quality", "pin": "claude-sonnet-4-6"},
        )
        tenant_b = server.handle_request(
            "POST",
            "/api/v1/models/policy",
            headers={"X-Tenant-ID": "tenant-b"},
            body={"provider": "anthropic", "policy": "cost", "pin": "claude-haiku-4-5"},
        )
        assert tenant_a.status_code == 200
        assert tenant_b.status_code == 200

        listed_a = server.handle_request("GET", "/api/v1/models", headers={"X-Tenant-ID": "tenant-a"})
        listed_b = server.handle_request("GET", "/api/v1/models", headers={"X-Tenant-ID": "tenant-b"})
        assert listed_a.body["providers"]["anthropic"]["policy"] == "quality"
        assert listed_b.body["providers"]["anthropic"]["policy"] == "cost"


# ---------------------------------------------------------------------------
# Lifecycle routes
# ---------------------------------------------------------------------------

class TestLifecycleRoutes:
    def test_lifecycle_project_routes_and_operational_surfaces(self):
        server, _ = _server_with_routes()

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/orbit")
        assert fetched.status_code == 200
        assert fetched.body["projectId"] == "orbit"
        assert fetched.body["phaseStatuses"][0]["phase"] == "research"

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/orbit",
            body={
                "spec": "Autonomous product lifecycle cockpit for operator-led multi-agent delivery.",
                "features": [
                    {"feature": "自律開発", "selected": True, "priority": "must", "category": "must-be"},
                    {"feature": "承認ゲート", "selected": True, "priority": "must", "category": "must-be"},
                ],
                "buildCode": (
                    "<!doctype html><html lang='ja'><head><meta name='viewport' "
                    "content='width=device-width, initial-scale=1' /></head>"
                    "<body><main><button aria-label='Launch'>Launch</button></main></body></html>"
                ),
                "selectedDesignId": "claude-designer",
            },
        )
        assert updated.status_code == 200
        assert updated.body["spec"].startswith("Autonomous product lifecycle cockpit")
        assert updated.body["recommendations"]

        blueprints = server.handle_request("GET", "/api/v1/lifecycle/projects/orbit/blueprint")
        assert blueprints.status_code == 200
        assert blueprints.body["blueprints"]["development"]["team"][0]["id"] == "planner"
        assert blueprints.body["blueprints"]["iterate"]["artifacts"][0]["id"] == "feedback-backlog"

        approval = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/approval/comments",
            body={"type": "approve", "text": "Ready for implementation"},
        )
        assert approval.status_code == 200
        assert approval.body["approvalStatus"] == "approved"
        assert approval.body["decisionLog"]
        assert approval.body["artifacts"]
        approval_phase = next(item for item in approval.body["phaseStatuses"] if item["phase"] == "approval")
        assert approval_phase["status"] == "completed"

        checks = server.handle_request("POST", "/api/v1/lifecycle/projects/orbit/deploy/checks", body={})
        assert checks.status_code == 200
        assert checks.body["summary"]["releaseReady"] is True
        assert checks.body["summary"]["failed"] == 0
        assert checks.body["project"]["artifacts"]

        release = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/releases",
            body={"note": "Initial operator preview"},
        )
        assert release.status_code == 201
        assert release.body["release"]["version"].startswith("v")
        assert release.body["release"]["qualitySummary"]["releaseReady"] is True
        assert release.body["project"]["decisionLog"]

        feedback = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/feedback",
            body={"text": "Mobile navigation needs a stronger hierarchy.", "type": "improvement", "impact": "medium"},
        )
        assert feedback.status_code == 201
        feedback_id = feedback.body["feedbackItems"][0]["id"]
        assert feedback.body["project"]["artifacts"]

        voted = server.handle_request(
            "POST",
            f"/api/v1/lifecycle/projects/orbit/feedback/{feedback_id}/vote",
            body={"delta": 2},
        )
        assert voted.status_code == 200
        assert voted.body["feedbackItems"][0]["votes"] == 2

        listed_feedback = server.handle_request("GET", "/api/v1/lifecycle/projects/orbit/feedback")
        assert listed_feedback.status_code == 200
        assert listed_feedback.body["feedbackItems"][0]["id"] == feedback_id

        recommendations = server.handle_request("GET", "/api/v1/lifecycle/projects/orbit/recommendations")
        assert recommendations.status_code == 200
        assert recommendations.body["recommendations"][0]["priority"] in {"medium", "high", "critical"}

        listed_projects = server.handle_request("GET", "/api/v1/lifecycle/projects")
        assert listed_projects.status_code == 200
        assert any(project["projectId"] == "orbit" for project in listed_projects.body["projects"])

    def test_lifecycle_project_events_stream_runtime_snapshot(self):
        server, _ = _server_with_routes()
        patched = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/orbit",
            body={"spec": "STREAM_SPEC_SENTINEL"},
        )
        assert patched.status_code == 200

        streamed = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/orbit/events?phase=research&once=1",
        )

        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("text/event-stream")
        chunks = list(streamed.body.chunks)
        assert any("event: project-runtime" in chunk for chunk in chunks)
        assert any("event: run-live" in chunk for chunk in chunks)
        project_runtime = next(chunk for chunk in chunks if "event: project-runtime" in chunk)
        run_live = next(chunk for chunk in chunks if "event: run-live" in chunk)
        assert '"phaseSummary"' in project_runtime
        assert '"phase": "research"' in project_runtime
        assert '"blockingSummary"' in project_runtime
        assert '"activePhaseSummary"' in project_runtime
        assert '"agents"' in project_runtime
        assert '"Competitor Scout"' in project_runtime
        assert "STREAM_SPEC_SENTINEL" not in project_runtime
        assert '"input"' not in project_runtime
        assert '"recentNodeIds"' in run_live or "data: null" in run_live
        assert '"activeFocusNodeId"' in run_live or "data: null" in run_live

    def test_lifecycle_project_events_stream_reports_active_phase_separately(self):
        server, _ = _server_with_routes()

        streamed = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/orbit/events?phase=planning&once=1",
        )

        assert streamed.status_code == 200
        chunks = list(streamed.body.chunks)
        project_runtime = next(chunk for chunk in chunks if "event: project-runtime" in chunk)
        assert '"observedPhase": "planning"' in project_runtime
        assert '"activePhase": "planning"' in project_runtime
        assert '"activePhaseSummary"' in project_runtime

    def test_lifecycle_project_events_stream_rehydrates_live_payload_from_state_node_status(self):
        server, store = _server_with_routes()
        patched = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/orbit",
            body={"spec": "DESIGN_STREAM_SENTINEL"},
        )
        assert patched.status_code == 200

        workflow_id = "lifecycle-design-orbit"
        store.put_run_record(
            {
                "id": "run_design_terminal",
                "workflow_id": workflow_id,
                "workflow": workflow_id,
                "tenant_id": "default",
                "status": "completed",
                "started_at": "2026-03-17T00:00:00Z",
                "completed_at": "2026-03-17T00:05:00Z",
                "state": {
                    "execution": {
                        "node_status": {
                            "claude-designer": "succeeded",
                            "design-evaluator": "succeeded",
                        },
                    },
                },
                "event_log": [
                    {"seq": 1, "node_id": "claude-designer", "agent": "claude-designer"},
                    {"seq": 2, "node_id": "design-evaluator", "agent": "design-evaluator"},
                ],
            },
            workflow_id=workflow_id,
            tenant_id="default",
            parameters={},
        )

        streamed = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/orbit/events?phase=design&once=1",
        )

        assert streamed.status_code == 200
        chunks = list(streamed.body.chunks)
        run_live = next(chunk for chunk in chunks if "event: run-live" in chunk)
        payload = json.loads(run_live.split("data: ", 1)[1])
        assert payload["completedNodeCount"] == 2
        assert payload["lastNodeId"] == "design-evaluator"
        assert payload["recentNodeIds"] == ["design-evaluator", "claude-designer"]

    def test_lifecycle_projects_support_project_metadata_for_selector_creation(self):
        server, _ = _server_with_routes()

        created = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/focus-board",
            headers={"X-Tenant-ID": "tenant-a"},
            body={
                "name": "Focus Board",
                "description": "AI-assisted task planning workspace",
                "githubRepo": "acme/focus-board",
            },
        )
        assert created.status_code == 200
        assert created.body["project"]["projectId"] == "focus-board"
        assert created.body["project"]["name"] == "Focus Board"
        assert created.body["project"]["description"] == "AI-assisted task planning workspace"
        assert created.body["project"]["githubRepo"] == "acme/focus-board"

        fetched = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/focus-board",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert fetched.status_code == 200
        assert fetched.body["name"] == "Focus Board"
        assert fetched.body["description"] == "AI-assisted task planning workspace"
        assert fetched.body["githubRepo"] == "acme/focus-board"

        listed = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert listed.status_code == 200
        assert listed.body["count"] == 1
        assert listed.body["projects"][0]["name"] == "Focus Board"

    def test_lifecycle_projects_round_trip_product_identity(self):
        server, _ = _server_with_routes()

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/identity-probe",
            body={
                "name": "Identity Probe",
                "spec": "identity probe spec",
                "productIdentity": {
                    "companyName": "Pylon Labs",
                    "productName": "Pylon",
                    "officialWebsite": "https://pylon.example.com",
                    "officialDomains": ["pylon.example.com"],
                    "aliases": ["Pylon Platform"],
                    "excludedEntityNames": ["Basler pylon"],
                },
            },
        )

        assert updated.status_code == 200
        assert updated.body["project"]["productIdentity"]["companyName"] == "Pylon Labs"
        assert updated.body["project"]["productIdentity"]["officialDomains"] == ["pylon.example.com"]

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/identity-probe")
        assert fetched.status_code == 200
        assert fetched.body["productIdentity"]["productName"] == "Pylon"
        assert fetched.body["productIdentity"]["excludedEntityNames"] == ["Basler pylon"]

    def test_lifecycle_projects_compact_storage_and_hydrate_response_fields(self):
        server, store = _server_with_routes()

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/storage-probe",
            body={
                "name": "Storage Probe",
                "spec": "Operator-led lifecycle workspace with governed approvals.",
                "research": {
                    "summary": "Initial research summary",
                    "readiness": "rework",
                    "view_model": {"hero": {"title": "Do not persist derived view state"}},
                },
                "features": [
                    {"feature": "approval gate", "selected": True},
                    {"feature": "artifact lineage", "selected": True},
                ],
                "analysis": {
                    "design_tokens": {
                        "colors": {"background": "#020617", "primary": "#2563eb", "cta": "#f59e0b"},
                    }
                },
                "milestones": [
                    {"id": "ms-alpha", "name": "Alpha", "criteria": "Reviewable operator workflow"}
                ],
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Control Deck",
                        "description": "Product shell for approvals and research recovery",
                        "preview_html": "<!doctype html><html><body>transient</body></html>",
                        "primary_color": "#2563eb",
                        "accent_color": "#f59e0b",
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "research", "label": "Research", "priority": "primary"}
                                ]
                            },
                            "screens": [
                                {
                                    "id": "research",
                                    "title": "Research",
                                    "headline": "Inspect evidence quality",
                                    "purpose": "Review the current research pass",
                                    "modules": [
                                        {"name": "Evidence", "type": "summary", "items": ["Signals", "Sources"]}
                                    ],
                                }
                            ],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:storage-probe")
        assert stored is not None
        assert "decision_context" not in stored
        assert "phaseContracts" not in stored
        assert "nextAction" not in stored
        assert "autonomyState" not in stored
        assert "view_model" not in stored["research"]
        assert stored["designVariants"][0]["preview_html"].startswith("<!doctype html>")
        assert stored["designVariants"][0]["preview_meta"]["source"] == "repaired"

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/storage-probe")

        assert fetched.status_code == 200
        assert fetched.body["research"]["view_model"] is not None
        assert fetched.body["designVariants"][0]["preview_html"].startswith("<!doctype html>")
        assert 'data-screen-id="research"' in fetched.body["designVariants"][0]["preview_html"]
        assert fetched.body["designVariants"][0]["preview_meta"]["fallback_reason"] == "stored_preview_invalid"
        assert fetched.body["designVariants"][0]["preview_meta"]["source"] == "repaired"
        assert fetched.body["designVariants"][0]["prototype_spec"]["framework_target"] == "nextjs-app-router"
        assert fetched.body["designVariants"][0]["prototype_app"]["framework"] == "nextjs"
        assert fetched.body["designVariants"][0]["prototype_app"]["artifact_summary"]["file_count"] >= 7
        assert fetched.body["designVariants"][0]["display_language"] == "ja"
        assert fetched.body["designVariants"][0]["localized"]["prototype"]["screens"][0]["title"] == "調査"
        assert fetched.body["designVariants"][0]["implementation_brief"]["technical_choices"]
        assert fetched.body["designVariants"][0]["artifact_completeness"]["status"] == "partial"
        assert fetched.body["designVariants"][0]["scorecard"]["dimensions"]
        assert fetched.body["designVariants"][0]["selection_rationale"]["summary"]
        assert fetched.body["designVariants"][0]["approval_packet"]["review_checklist"]

    def test_lifecycle_projects_preserve_valid_llm_preview_html(self):
        server, store = _server_with_routes()
        llm_preview = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8' />"
            "<meta name='viewport' content='width=device-width, initial-scale=1' />"
            "<style>body{font-family:sans-serif}nav{display:flex}table{width:100%}@media(max-width:768px){body{padding:8px}}"
            ".screen{display:none}.screen.active{display:block}.metric{padding:12px}.form{display:grid;gap:12px}.status{display:grid;gap:8px}"
            ".tabs button[aria-selected='true']{font-weight:700}.accordion{transition:all .2s ease}.card:hover{transform:translateY(-1px)}"
            "</style></head><body><nav aria-label='主要ナビゲーション'><button data-tab='overview'>概要</button><button data-tab='queue'>審査</button>"
            "<button data-tab='lineage'>系譜</button><button data-tab='settings'>設定</button></nav><main>"
            "<section class='screen active card' data-screen-id='overview'><div class='metric'>指標 12 件</div><table><tr><td>案件</td><td>状態</td></tr></table>"
            "<div class='status'>進行中 / 要承認 / 完了</div><form class='form'><label>担当者<input /></label></form></section>"
            "<section class='screen card' data-screen-id='queue'><div class='tabs'><button aria-selected='true'>審査</button></div><div class='accordion'>レビュー項目</div></section>"
            "<section class='screen card' data-screen-id='lineage'><table><tr><td>artifact lineage</td><td>最新</td></tr></table><div class='status'>同期済み</div></section>"
            "<section class='screen card' data-screen-id='settings'><form><label>通知<input /></label></form><div class='metric'>SLA 98%</div></section>"
            "<script>document.querySelectorAll('[data-tab]').forEach((button)=>button.addEventListener('click',()=>button.setAttribute('aria-selected','true')));</script>"
            "</main></body></html>"
        )
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-preview-preserve",
            body={
                "spec": "Operator-led lifecycle workspace",
                "features": [{"feature": "approval gate", "selected": True}],
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Preserve valid llm preview",
                        "preview_html": llm_preview,
                        "preview_meta": {"source": "llm", "extraction_ok": True, "fallback_reason": ""},
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {"primary_navigation": [{"id": "overview", "label": "Overview", "priority": "primary"}]},
                            "screens": [
                                {"id": "overview", "title": "Overview", "purpose": "Main overview", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "Queue", "purpose": "Review queue", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Artifact lineage", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Workspace settings", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval Gate", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:design-preview-preserve")
        assert stored is not None
        assert stored["designVariants"][0]["preview_html"] == llm_preview

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-preview-preserve")

        assert fetched.status_code == 200
        assert fetched.body["designVariants"][0]["preview_html"] == llm_preview
        assert fetched.body["designVariants"][0]["selection_rationale"]["reasons"]
        assert fetched.body["designVariants"][0]["approval_packet"]["guardrails"]
        assert fetched.body["designVariants"][0]["preview_meta"]["source"] == "llm"
        assert fetched.body["designVariants"][0]["preview_meta"]["validation_ok"] is True

    def test_lifecycle_projects_hydrate_selected_design_as_selected_verdict(self):
        server, _store = _server_with_routes()
        llm_preview = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8' />"
            "<meta name='viewport' content='width=device-width, initial-scale=1' />"
            "<style>body{font-family:sans-serif}nav{display:flex}@media(max-width:768px){body{padding:8px}}</style>"
            "</head><body><nav aria-label='主要ナビゲーション'><button data-tab='workspace'>判断レビュー</button></nav>"
            "<main><section data-screen-id='workspace'><table aria-label='判断テーブル'><tr><td>根拠</td></tr></table>"
            "<div class='status'>承認 / 根拠 / 系譜 / 復旧</div><form aria-label='承認フォーム'><label>判定<input /></label></form></section>"
            "<section data-screen-id='queue'>審査</section><section data-screen-id='lineage'>系譜</section><section data-screen-id='settings'>設定</section>"
            "<script>document.querySelectorAll('[data-tab]').forEach((button)=>button.addEventListener('click',()=>button.setAttribute('aria-selected','true')));</script>"
            "</main></body></html>"
        )
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-selected-verdict",
            body={
                "spec": "Operator-led lifecycle workspace",
                "selectedDesignId": "variant-a",
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Selected direction",
                        "preview_html": llm_preview,
                        "preview_meta": {"source": "llm", "extraction_ok": True, "fallback_reason": ""},
                        "prototype": {
                            "kind": "product-workspace",
                            "visual_direction": {"visual_style": "obsidian-atelier"},
                            "app_shell": {"primary_navigation": [{"id": "workspace", "label": "Workspace", "priority": "primary"}]},
                            "screens": [
                                {"id": "workspace", "title": "Workspace", "purpose": "Main overview", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "Queue", "purpose": "Review queue", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Artifact lineage", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Workspace settings", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval Gate", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-selected-verdict")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert variant["selection_rationale"]["verdict"] == "selected"
        assert variant["approval_packet"]["operator_promise"]
        assert variant["approval_packet"]["handoff_summary"]

    def test_lifecycle_projects_repair_invalid_llm_preview_html(self):
        server, store = _server_with_routes()
        invalid_llm_preview = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8' />"
            "<style>body{font-family:sans-serif}.card:hover{transform:translateY(-1px)}</style>"
            "</head><body><nav aria-label='主要ナビゲーション'><button>概要</button></nav>"
            "<main><section data-screen-id='overview'>概要</section><section data-screen-id='queue'>審査</section>"
            "<section data-screen-id='lineage'>系譜</section><section data-screen-id='settings'>設定</section></main></body></html>"
        )
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-preview-repair",
            body={
                "spec": "Operator-led lifecycle workspace",
                "features": [{"feature": "approval gate", "selected": True}],
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Repair invalid llm preview",
                        "preview_html": invalid_llm_preview,
                        "preview_meta": {
                            "source": "llm",
                            "extraction_ok": True,
                            "validation_ok": False,
                            "fallback_reason": "",
                            "validation_issues": ["missing_inline_script", "missing_viewport"],
                        },
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "overview", "label": "Overview", "priority": "primary"},
                                    {"id": "queue", "label": "Queue", "priority": "primary"},
                                ]
                            },
                            "screens": [
                                {"id": "overview", "title": "Overview", "purpose": "Main overview", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "Queue", "purpose": "Review queue", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Artifact lineage", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Workspace settings", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval Gate", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:design-preview-repair")
        assert stored is not None
        assert stored["designVariants"][0]["preview_html"] != invalid_llm_preview
        assert stored["designVariants"][0]["preview_meta"]["source"] == "repaired"

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-preview-repair")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert variant["preview_html"] != invalid_llm_preview
        assert "<script>" in variant["preview_html"]
        assert variant["preview_meta"]["source"] == "repaired"
        assert variant["preview_meta"]["repaired_from_source"] == "llm"
        assert variant["preview_meta"]["validation_ok"] is True
        assert "missing_inline_script" in variant["preview_meta"]["candidate_validation_issues"]

    def test_lifecycle_projects_refresh_invalid_template_preview_html(self):
        server, store = _server_with_routes()
        stale_template_preview = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8' />"
            "<meta name='viewport' content='width=device-width, initial-scale=1' />"
            "<style>body{font-family:sans-serif}.card:hover{transform:translateY(-1px)}@media(max-width:768px){body{padding:8px}}</style>"
            "</head><body><nav aria-label='主要ナビゲーション'><a href='#overview'>Overview</a></nav>"
            "<main><section data-screen-id='overview'>概要</section><section data-screen-id='queue'>審査</section>"
            "<section data-screen-id='lineage'>系譜</section><section data-screen-id='settings'>設定</section></main></body></html>"
        )
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-template-refresh",
            body={
                "spec": "Operator-led lifecycle workspace",
                "features": [{"feature": "approval gate", "selected": True}],
                "milestones": [{"id": "ms-alpha", "name": "Alpha", "criteria": "Reviewable operator workflow"}],
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Refresh invalid template preview",
                        "preview_html": stale_template_preview,
                        "preview_meta": {"source": "template", "validation_ok": False, "fallback_reason": "legacy_template"},
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "overview", "label": "Overview", "priority": "primary"},
                                    {"id": "queue", "label": "Queue", "priority": "primary"},
                                    {"id": "lineage", "label": "Lineage", "priority": "secondary"},
                                    {"id": "settings", "label": "Settings", "priority": "utility"},
                                ]
                            },
                            "screens": [
                                {"id": "overview", "title": "Overview", "purpose": "Main overview", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "Queue", "purpose": "Review queue", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Artifact lineage", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Workspace settings", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval Gate", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:design-template-refresh")
        assert stored is not None
        assert stored["designVariants"][0]["preview_html"] != stale_template_preview
        assert stored["designVariants"][0]["preview_meta"]["source"] == "repaired"

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-template-refresh")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert variant["preview_html"] != stale_template_preview
        assert "<script>" in variant["preview_html"]
        assert 'aria-label="承認フォーム"' in variant["preview_html"]
        assert variant["preview_meta"]["source"] == "repaired"
        assert variant["preview_meta"]["repaired_from_source"] == "template"
        assert variant["preview_meta"]["template_version"] >= 1
        assert variant["preview_meta"]["validation_ok"] is True

    def test_lifecycle_projects_backfill_native_artifacts(self):
        server, store = _server_with_routes()
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/native-artifacts",
            body={
                "spec": "Approval workspace that tracks delivery readiness and records every decision.",
                "research": {
                    "user_research": {
                        "segment": "delivery operator",
                        "pain_points": ["approval traceability is manual"],
                    },
                    "claims": [
                        {
                            "id": "claim-1",
                            "statement": "When approval is requested, the system shall persist the decision and notify the owner.",
                            "confidence": 0.88,
                            "status": "accepted",
                        }
                    ],
                },
                "features": [
                    {
                        "id": "feat-approval",
                        "feature": "Approval log",
                        "selected": True,
                        "priority": "must",
                        "implementation_cost": "high",
                        "rationale": "Keep every approval decision traceable.",
                    },
                    {
                        "id": "feat-audit",
                        "feature": "Audit timeline",
                        "selected": True,
                        "priority": "should",
                        "implementation_cost": "medium",
                        "rationale": "Show lineage for audits and rework.",
                        "depends_on": ["feat-approval"],
                    },
                ],
                "milestones": [
                    {"id": "ms-alpha", "name": "Alpha", "criteria": "Approval traceability works end to end"},
                ],
                "selectedDesignId": "variant-a",
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Approval Control Desk",
                        "description": "Operator-facing approval workspace",
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "workspace", "label": "Workspace", "priority": "primary"},
                                    {"id": "timeline", "label": "Timeline", "priority": "secondary"},
                                ]
                            },
                            "screens": [
                                {"id": "workspace", "title": "Workspace", "purpose": "Track approvals", "modules": [], "primary_actions": []},
                                {"id": "timeline", "title": "Timeline", "purpose": "Review lineage", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval handoff", "steps": ["request", "review", "approve"], "goal": "release"}],
                        },
                        "prototype_app": {
                            "framework": "nextjs",
                            "files": [
                                {
                                    "path": "server/routes/approval.ts",
                                    "kind": "ts",
                                    "content": "import express from 'express';\nconst app = express();\napp.get('/api/approvals', listApprovals);\napp.post('/api/approvals', createApproval);\n",
                                },
                                {
                                    "path": "src/types.ts",
                                    "kind": "ts",
                                    "content": "export interface ApprovalRecord { id: string; status: string; }\n",
                                },
                                {
                                    "path": "schema.sql",
                                    "kind": "sql",
                                    "content": "CREATE TABLE approvals (id uuid primary key, status text not null);\n",
                                },
                                {
                                    "path": "tests/approval.spec.ts",
                                    "kind": "ts",
                                    "content": "describe('test_approval_route', () => { it('should_store_decision', () => {}); });\n",
                                },
                            ],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:native-artifacts")
        assert stored is not None
        assert stored["requirements"]["requirements"][0]["sourceClaimIds"] == ["claim-1"]
        assert stored["taskDecomposition"]["tasks"]
        assert stored["dcsAnalysis"]["edgeCases"]["edgeCases"]
        assert stored["technicalDesign"]["apiSpecification"]
        assert stored["reverseEngineering"]["apiEndpoints"]

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/native-artifacts")

        assert fetched.status_code == 200
        assert fetched.body["requirements"]["requirements"][0]["acceptanceCriteria"]
        assert fetched.body["taskDecomposition"]["tasks"][0]["effortHours"] > 0
        assert fetched.body["dcsAnalysis"]["impactAnalysis"]["blastRadius"] >= 1
        assert fetched.body["technicalDesign"]["dataflowMermaid"].startswith("flowchart")
        assert fetched.body["reverseEngineering"]["coverageScore"] >= 0.7
        assert fetched.body["reverseEngineering"]["sourceType"] == "prototype_app"
        assert fetched.body["phaseContracts"]["planning"]["outputs"]["taskCount"] >= 1
        assert fetched.body["phaseContracts"]["design"]["outputs"]["technicalDesignPresent"] is True

    def test_lifecycle_projects_backfill_requirements_from_selected_features_without_claims(self):
        server, store = _server_with_routes()
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/native-feature-requirements",
            body={
                "spec": "Operator console that manages approval delivery, artifact lineage, and autonomous release readiness.",
                "research": {
                    "user_research": {
                        "segment": "delivery operator",
                        "pain_points": ["manual approval coordination"],
                    },
                    "claims": [],
                },
                "features": [
                    {
                        "id": "feat-console",
                        "feature": "operator console",
                        "selected": True,
                        "priority": "must",
                        "implementation_cost": "medium",
                        "rationale": "Give operators one governed console for approvals and lineage.",
                        "acceptance_criteria": ["operator console shows approval packets and lineage status"],
                    },
                    {
                        "id": "feat-lineage",
                        "feature": "artifact lineage",
                        "selected": True,
                        "priority": "should",
                        "implementation_cost": "medium",
                        "rationale": "Keep release decisions traceable across phases.",
                    },
                ],
                "milestones": [
                    {"id": "ms-alpha", "name": "Alpha", "criteria": "Approval operators can review packet and lineage"},
                ],
                "selectedDesignId": "variant-a",
                "designVariants": [
                    {
                        "id": "variant-a",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Operator Control Desk",
                        "description": "Operator-facing control plane",
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "workspace", "label": "Workspace", "priority": "primary"},
                                    {"id": "lineage", "label": "Lineage", "priority": "secondary"},
                                ]
                            },
                            "screens": [
                                {"id": "workspace", "title": "Workspace", "purpose": "Review approvals", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Inspect artifact trail", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval review", "steps": ["request", "review", "approve"], "goal": "release"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:native-feature-requirements")
        assert stored is not None
        assert len(stored["requirements"]["requirements"]) == 2
        assert all(
            value.startswith("synthetic-")
            for item in stored["requirements"]["requirements"]
            for value in item["sourceClaimIds"]
        )

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/native-feature-requirements")

        assert fetched.status_code == 200
        statements = [item["statement"].lower() for item in fetched.body["requirements"]["requirements"]]
        assert any("operator console" in statement for statement in statements)
        assert any("artifact lineage" in statement for statement in statements)
        assert fetched.body["phaseContracts"]["research"]["outputs"]["requirementCount"] == 2

    def test_lifecycle_projects_repair_preview_style_mismatch(self):
        server, store = _server_with_routes()
        mismatched_preview = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8' />"
            "<meta name='viewport' content='width=device-width, initial-scale=1' />"
            "<style>body{font-family:sans-serif}</style>"
            "</head><body class='preview-style-obsidian-atelier'>"
            "<nav aria-label='主要ナビゲーション'><button data-tab='workspace'>判断レビュー</button></nav>"
            "<main><section data-screen-id='workspace'><table aria-label='判断テーブル'><tr><td>根拠</td></tr></table>"
            "<form aria-label='承認フォーム'><label>判定<input /></label></form></section>"
            "<section data-screen-id='queue'>審査</section><section data-screen-id='lineage'>系譜</section><section data-screen-id='settings'>設定</section>"
            "<script>document.querySelectorAll('[data-tab]').forEach((button)=>button.addEventListener('click',()=>button.setAttribute('aria-selected','true')));</script>"
            "</main></body></html>"
        )
        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-style-refresh",
            body={
                "spec": "Operator-led lifecycle workspace",
                "designVariants": [
                    {
                        "id": "variant-b",
                        "model": "KIMI K2.5",
                        "pattern_name": "Ivory Signal Gallery",
                        "description": "Repair preview style mismatch",
                        "preview_html": mismatched_preview,
                        "preview_meta": {
                            "source": "repaired",
                            "template_version": 9,
                            "validation_ok": True,
                            "fallback_reason": "",
                        },
                        "prototype": {
                            "kind": "operations",
                            "visual_direction": {"visual_style": "ivory-signal"},
                            "app_shell": {
                                "layout": "top-nav",
                                "density": "medium",
                                "primary_navigation": [
                                    {"id": "workspace", "label": "フェーズワークスペース", "priority": "primary"},
                                    {"id": "queue", "label": "ラン台帳", "priority": "primary"},
                                ],
                            },
                            "screens": [
                                {"id": "workspace", "title": "フェーズワークスペース", "purpose": "判断レビュー", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "ラン台帳", "purpose": "審査", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "系譜タイムライン", "purpose": "系譜", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "判断レビュー", "purpose": "設定", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "構想から承認まで", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:design-style-refresh")
        assert stored is not None
        assert "preview-style-ivory-signal" in stored["designVariants"][0]["preview_html"]
        assert stored["designVariants"][0]["preview_meta"]["source"] == "repaired"

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-style-refresh")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert "preview-style-ivory-signal" in variant["preview_html"]
        assert variant["preview_meta"]["fallback_reason"] == "stored_preview_style_mismatch"
        assert variant["preview_meta"]["validation_ok"] is True

    def test_lifecycle_projects_hydrate_legacy_design_variants_for_decision_desk(self):
        server, _ = _server_with_routes()

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/design-legacy",
            body={
                "name": "Design Legacy",
                "spec": "Governed lifecycle workspace",
                "designVariants": [
                    {
                        "id": "gemini-designer",
                        "model": "Gemini 3 Pro",
                        "pattern_name": "Ivory Signal Gallery",
                        "description": "Legacy direction",
                        "tokens": {"in": 4200, "out": 3100},
                        "cost_usd": 0.280,
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "layout": "sidebar",
                                "density": "balanced",
                                "primary_navigation": [],
                                "status_badges": [],
                            },
                            "screens": [
                                {
                                    "id": "workspace",
                                    "title": "{'id': 'shell-lifecycle-workspace', 'label': 'Lifecycle Workspace — Primary Shell', 'description': 'The hub for operator decisions.', 'layout': 'three-column', 'components': ['LeftRail', 'PhaseCanvas', 'ContextPanel'], 'accessibility': 'aria-current on active navigation.'}",
                                    "headline": "Run discovery-to-build workflow",
                                    "purpose": "",
                                    "layout": "command-center",
                                    "modules": [],
                                    "primary_actions": [],
                                    "supporting_text": "",
                                    "success_state": "",
                                }
                            ],
                            "flows": [],
                            "interaction_principles": [],
                        },
                        "scores": {
                            "ux_quality": 0.94,
                            "code_quality": 0.89,
                            "performance": 0.88,
                            "accessibility": 0.93,
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/design-legacy")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert variant["model"] == "Gemini 3 Pro"
        assert variant["cost_usd"] == 0.036
        assert variant["prototype"]["screens"][0]["title"] == "調査ワークスペース"
        assert variant["localized"]["prototype"]["screens"][0]["purpose"] == "オペレーター判断の中心となる画面。"
        assert variant["canonical"]["prototype"]["screens"][0]["purpose"] == "The hub for operator decisions."
        assert variant["prototype"]["screens"][0]["modules"][0]["items"] == ["次の一手", "保留理由", "承認候補"]
        assert variant["display_language"] == "ja"
        assert variant["implementation_brief"]["architecture_thesis"]

    def test_lifecycle_project_get_normalizes_and_persists_stale_design_state(self):
        server, store = _server_with_routes()

        seeded = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/approval-phase-drift",
            body={
                "spec": "Operator-led lifecycle workspace",
                "selectedDesignId": "claude-designer",
                "designVariants": [
                    {
                        "id": "claude-designer",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Design baseline",
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {"primary_navigation": []},
                            "screens": [{"id": "workspace", "title": "Workspace", "purpose": "Main view", "modules": [], "primary_actions": []}],
                            "flows": [],
                        },
                    }
                ],
            },
        )

        assert seeded.status_code == 200

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/approval-phase-drift",
            body={
                "approvalStatus": "pending",
                "phaseStatuses": [
                    {"phase": "research", "status": "completed", "version": 1},
                    {"phase": "planning", "status": "completed", "version": 1},
                    {"phase": "design", "status": "completed", "version": 1},
                    {"phase": "approval", "status": "completed", "version": 1},
                    {"phase": "development", "status": "available", "version": 1},
                    {"phase": "deploy", "status": "locked", "version": 1},
                    {"phase": "iterate", "status": "locked", "version": 1},
                ],
            },
        )

        assert updated.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/approval-phase-drift")

        assert fetched.status_code == 200
        phase_lookup = {item["phase"]: item["status"] for item in fetched.body["phaseStatuses"]}
        assert fetched.body["approvalStatus"] == "pending"
        assert phase_lookup["design"] == "completed"
        assert phase_lookup["approval"] == "available"
        assert phase_lookup["development"] == "locked"
        assert fetched.body["designVariants"][0]["preview_meta"]["source"] == "repaired"
        assert fetched.body["designVariants"][0]["artifact_completeness"]["status"] == "partial"
        assert fetched.body["designVariants"][0]["freshness"]["status"] in {"fresh", "unknown"}

        stored = store.get_surface_record("lifecycle_projects", "default:approval-phase-drift")
        assert stored is not None
        stored_phase_lookup = {item["phase"]: item["status"] for item in stored["phaseStatuses"]}
        assert stored["approvalStatus"] == "pending"
        assert stored_phase_lookup["approval"] == "available"
        assert stored_phase_lookup["development"] == "locked"
        assert stored["designVariants"][0]["preview_meta"]["source"] == "repaired"
        assert stored["designVariants"][0]["artifact_completeness"]["status"] == "partial"

    def test_lifecycle_project_get_preserves_approved_state_for_expired_approval_record(self):
        server, store = _server_with_routes()

        seeded = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/approval-expiry-preserve",
            body={
                "spec": "Operator-led lifecycle workspace",
                "features": [
                    {"id": "feature-1", "name": "Research workspace", "selected": True},
                ],
                "milestones": [
                    {"id": "ms-alpha", "name": "Evidence loop", "criteria": "Traceability survives development"},
                ],
                "selectedDesignId": "claude-designer",
                "designVariants": [
                    {
                        "id": "claude-designer",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Design baseline",
                        "implementation_brief": {
                            "delivery_slices": [
                                {
                                    "slice": "S1",
                                    "title": "Shell",
                                    "milestone": "Alpha",
                                    "acceptance": ["Navigation stays intact"],
                                }
                            ],
                        },
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {"primary_navigation": []},
                            "screens": [
                                {
                                    "id": "workspace",
                                    "title": "Workspace",
                                    "purpose": "Main view",
                                    "modules": [],
                                    "primary_actions": [],
                                }
                            ],
                            "flows": [],
                        },
                    }
                ],
            },
        )

        assert seeded.status_code == 200
        canonical_before_approval = server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/approval-expiry-preserve",
        )
        assert canonical_before_approval.status_code == 200
        binding = build_lifecycle_approval_binding(canonical_before_approval.body)
        store.put_approval_record(
            {
                "id": "apr_expired",
                "agent_id": "lifecycle-coordinator",
                "action": binding["action"],
                "autonomy_level": "A3",
                "context": {
                    **binding["context"],
                    "project_id": "approval-expiry-preserve",
                    "tenant_id": "default",
                    "run_id": "lifecycle:approval-expiry-preserve",
                },
                "status": "expired",
                "plan_hash": compute_approval_binding_hash(binding["plan"]),
                "effect_hash": compute_approval_binding_hash(binding["effect_envelope"]),
                "created_at": "2026-03-17T00:00:00Z",
                "expires_at": "2026-03-17T00:05:00Z",
                "run_id": "lifecycle:approval-expiry-preserve",
            }
        )

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/approval-expiry-preserve",
            body={
                "approvalStatus": "approved",
                "approvalRequestId": "apr_expired",
                "phaseStatuses": [
                    {"phase": "research", "status": "completed", "version": 1},
                    {"phase": "planning", "status": "completed", "version": 1},
                    {"phase": "design", "status": "completed", "version": 1},
                    {"phase": "approval", "status": "completed", "version": 1},
                    {"phase": "development", "status": "in_progress", "version": 1},
                    {"phase": "deploy", "status": "locked", "version": 1},
                    {"phase": "iterate", "status": "locked", "version": 1},
                ],
            },
        )

        assert updated.status_code == 200
        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/approval-expiry-preserve")

        assert fetched.status_code == 200
        phase_lookup = {item["phase"]: item["status"] for item in fetched.body["phaseStatuses"]}
        assert fetched.body["approvalStatus"] == "approved"
        assert fetched.body["approvalRequestId"] == "apr_expired"
        assert fetched.body["approvalRequest"]["status"] == "approved"
        assert fetched.body["approvalRequest"]["approval_status_source"] == "expired_record_preserved"
        assert phase_lookup["approval"] == "completed"
        assert phase_lookup["development"] == "in_progress"

        stored = store.get_surface_record("lifecycle_projects", "default:approval-expiry-preserve")
        assert stored is not None
        stored_phase_lookup = {item["phase"]: item["status"] for item in stored["phaseStatuses"]}
        assert stored["approvalStatus"] == "approved"
        assert stored["approvalRequestId"] == "apr_expired"
        assert stored_phase_lookup["approval"] == "completed"
        assert stored_phase_lookup["development"] == "in_progress"

    def test_lifecycle_project_get_keeps_design_fresh_when_selected_design_matches_upstream_context(self):
        server, _ = _server_with_routes()

        seeded = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/fresh-design-context",
            body={
                "spec": "Operator-led lifecycle workspace",
                "research": {
                    "canonical": {
                        "winning_theses": ["Governed visibility is the leading wedge."],
                        "claims": [
                            {
                                "id": "claim-1",
                                "statement": "Governed visibility is the leading wedge.",
                                "status": "accepted",
                            }
                        ],
                        "research_context": {
                            "decision_stage": "conditional_handoff",
                            "segment": "Platform teams",
                            "thesis_headline": "Governed visibility is the leading wedge.",
                            "thesis_snapshot": ["Governed visibility is the leading wedge."],
                        },
                    }
                },
                "analysis": {
                    "canonical": {
                        "planning_context": {
                            "product_kind": "operations",
                            "segment": "Platform teams",
                            "north_star": "Operator trust",
                            "core_loop": "Carry evidence into governed delivery.",
                        },
                        "personas": [{"name": "Aiko", "role": "Platform Lead"}],
                        "use_cases": [
                            {"id": "uc-1", "title": "Trace artifact lineage", "priority": "must"},
                        ],
                        "traceability": [
                            {
                                "claim_id": "claim-1",
                                "claim": "Governed visibility is the leading wedge.",
                                "use_case_id": "uc-1",
                                "use_case": "Trace artifact lineage",
                                "feature": "artifact lineage",
                                "milestone_id": "ms-1",
                                "milestone": "Evidence loop",
                            }
                        ],
                    }
                },
                "features": [
                    {"feature": "artifact lineage", "selected": True, "priority": "must", "category": "must-be"},
                ],
                "milestones": [
                    {"id": "ms-1", "name": "Evidence loop", "phase": "alpha", "depends_on_use_cases": ["uc-1"]},
                ],
            },
        )

        assert seeded.status_code == 200
        decision_fingerprint = seeded.body["decision_context"]["fingerprint"]

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/fresh-design-context",
            body={
                "selectedDesignId": "claude-designer",
                "designVariants": [
                    {
                        "id": "claude-designer",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Design baseline",
                        "decision_context_fingerprint": decision_fingerprint,
                        "decision_scope": {
                            "phase": "design",
                            "fingerprint": decision_fingerprint,
                            "selected_feature_names": ["artifact lineage"],
                            "primary_use_case_ids": ["uc-1"],
                        },
                        "preview_html": (
                            "<!doctype html><html lang='ja'><head>"
                            "<meta name='viewport' content='width=device-width, initial-scale=1' />"
                            "<style>body{font-family:sans-serif} .tab{transition:all .2s ease} @media (max-width:768px){body{padding:8px}}</style>"
                            "</head><body>"
                            "<nav aria-label='主要ナビゲーション' role='tablist'>"
                            "<a class='tab' href='#workspace' data-screen-target='workspace' data-tab='true' role='tab' aria-selected='true' aria-controls='workspace'>Workspace</a>"
                            "</nav>"
                            "<main>"
                            "<section id='workspace' data-screen-id='workspace' role='tabpanel' aria-labelledby='workspace-tab'>"
                            "<form aria-label='承認フォーム'><input aria-label='comment' /></form>"
                            "</section>"
                            "<section id='review' data-screen-id='review' role='tabpanel' aria-labelledby='review-tab'></section>"
                            "<section id='lineage' data-screen-id='lineage' role='tabpanel' aria-labelledby='lineage-tab'></section>"
                            "<section id='settings' data-screen-id='settings' role='tabpanel' aria-labelledby='settings-tab'></section>"
                            "</main>"
                            "<script>document.addEventListener('click',()=>{});</script>"
                            "</body></html>"
                        ),
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "workspace", "label": "Workspace", "priority": "primary"},
                                ]
                            },
                            "screens": [
                                {"id": "workspace", "title": "Workspace", "purpose": "Main view", "modules": [], "primary_actions": []},
                                {"id": "review", "title": "Review", "purpose": "Review view", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Lineage view", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Settings view", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"name": "Approve phase", "goal": "Move to approval", "steps": ["Review", "Approve"]}],
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/fresh-design-context")

        assert fetched.status_code == 200
        variant = fetched.body["designVariants"][0]
        assert fetched.body["decision_context"]["fingerprint"] == decision_fingerprint
        assert variant["freshness"]["status"] == "fresh"
        assert variant["freshness"]["can_handoff"] is True

    def test_lifecycle_project_get_does_not_rewind_next_action_to_research_for_legacy_design_ready_project(self):
        server, _ = _server_with_routes()

        seeded = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/legacy-design-ready",
            body={
                "spec": "Operator-led lifecycle workspace",
                "analysis": {
                    "canonical": {
                        "personas": [{"name": "Aiko", "role": "Platform Lead"}],
                        "use_cases": [{"id": "uc-1", "title": "Trace artifact lineage", "priority": "must"}],
                        "recommended_milestones": [
                            {"id": "ms-alpha", "name": "Alpha", "criteria": "Reviewable operator workflow"}
                        ],
                    }
                },
                "features": [{"feature": "artifact lineage", "selected": True}],
                "milestones": [{"id": "ms-alpha", "name": "Alpha", "criteria": "Reviewable operator workflow"}],
                "designVariants": [
                    {
                        "id": "claude-designer",
                        "model": "Claude Sonnet 4.6",
                        "pattern_name": "Signal Canvas",
                        "description": "Legacy project with completed downstream phases",
                        "prototype": {
                            "kind": "product-workspace",
                            "app_shell": {
                                "primary_navigation": [
                                    {"id": "overview", "label": "Overview", "priority": "primary"},
                                    {"id": "queue", "label": "Queue", "priority": "primary"},
                                    {"id": "lineage", "label": "Lineage", "priority": "secondary"},
                                    {"id": "settings", "label": "Settings", "priority": "utility"},
                                ]
                            },
                            "screens": [
                                {"id": "overview", "title": "Overview", "purpose": "Main overview", "modules": [], "primary_actions": []},
                                {"id": "queue", "title": "Queue", "purpose": "Review queue", "modules": [], "primary_actions": []},
                                {"id": "lineage", "title": "Lineage", "purpose": "Artifact lineage", "modules": [], "primary_actions": []},
                                {"id": "settings", "title": "Settings", "purpose": "Workspace settings", "modules": [], "primary_actions": []},
                            ],
                            "flows": [{"id": "flow-1", "name": "Approval Gate", "steps": ["確認", "承認"], "goal": "handoff"}],
                        },
                    }
                ],
                "selectedDesignId": "claude-designer",
                "phaseStatuses": [
                    {"phase": "research", "status": "available", "version": 1},
                    {"phase": "planning", "status": "completed", "version": 1},
                    {"phase": "design", "status": "completed", "version": 1},
                    {"phase": "approval", "status": "available", "version": 1},
                    {"phase": "development", "status": "locked", "version": 1},
                    {"phase": "deploy", "status": "locked", "version": 1},
                    {"phase": "iterate", "status": "locked", "version": 1},
                ],
            },
        )

        assert seeded.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/legacy-design-ready")

        assert fetched.status_code == 200
        assert fetched.body["nextAction"]["phase"] != "research"
        assert fetched.body["nextAction"]["type"] in {"request_approval", "review_phase"}

    def test_lifecycle_project_preview_hydration_uses_short_title_not_full_spec_dump(self):
        server, _ = _server_with_routes()

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/meal-preview",
            body={
                "name": "うちメニュー",
                "spec": (
                    "# うちメニュー\n\n"
                    "## プロダクト概要\n"
                    "共働き家庭向けに、冷蔵庫在庫と家族の好みから3日分の献立と買い物リストを作るアプリ。"
                ),
                "designVariants": [
                    {
                        "id": "gemini-designer",
                        "model": "Gemini 3 Pro",
                        "pattern_name": "うちメニュー — ギャラリー型献立オペレーション",
                        "description": "明るい判断スタジオ。",
                        "primary_color": "#f5f0e8",
                        "accent_color": "#d4500a",
                        "prototype": {
                            "kind": "decision-studio",
                            "app_shell": {
                                "layout": "top-nav",
                                "density": "medium",
                                "primary_navigation": [
                                    {"id": "home", "label": "ホーム", "priority": "primary"},
                                    {"id": "workflow", "label": "主要導線", "priority": "primary"},
                                ],
                                "status_badges": ["在庫登録", "3日分献立", "買い物リスト"],
                            },
                            "screens": [
                                {
                                    "id": "home",
                                    "title": "今日の献立",
                                    "headline": "Complete guided onboarding",
                                    "purpose": "主要情報の要約",
                                    "layout": "product-workspace",
                                    "modules": [],
                                    "primary_actions": ["Open 今日の献立"],
                                    "supporting_text": "First-run success",
                                    "success_state": ["主要導線へ迷わず入れる"],
                                }
                            ],
                            "flows": [
                                {"id": "flow-1", "name": "First-run success", "steps": ["オンボーディング", "ホーム", "主要導線"]},
                            ],
                            "interaction_principles": [],
                            "visual_direction": {
                                "visual_style": "ivory-signal",
                            },
                        },
                    }
                ],
            },
        )

        assert updated.status_code == 200

        fetched = server.handle_request("GET", "/api/v1/lifecycle/projects/meal-preview")

        assert fetched.status_code == 200
        html = fetched.body["designVariants"][0]["preview_html"]
        assert "<title>うちメニュー</title>" in html
        assert '<p class="shell-title">うちメニュー</p>' in html
        assert "## プロダクト概要" not in html

    def test_lifecycle_projects_trim_large_operator_histories_before_storage(self):
        server, store = _server_with_routes()
        skill_invocations = [
            {"id": f"skill-{index}", "createdAt": f"2026-03-15T00:{index % 60:02d}:00Z", "title": f"Skill {index}"}
            for index in range(120)
        ]
        delegations = [
            {"id": f"delegation-{index}", "createdAt": f"2026-03-15T01:{index % 60:02d}:00Z", "title": f"Delegation {index}"}
            for index in range(120)
        ]

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/history-probe",
            body={
                "spec": "Governed lifecycle system",
                "skillInvocations": skill_invocations,
                "delegations": delegations,
            },
        )

        assert updated.status_code == 200
        stored = store.get_surface_record("lifecycle_projects", "default:history-probe")
        assert stored is not None
        assert len(stored["skillInvocations"]) == 80
        assert len(stored["delegations"]) == 80
        assert len(updated.body["project"]["skillInvocations"]) == 80
        assert len(updated.body["project"]["delegations"]) == 80

    def test_lifecycle_patch_can_run_full_autonomy_inline(self):
        server, _ = _server_with_routes()

        updated = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/api-service",
            body={
                "spec": "API lifecycle service for governed multi-agent delivery with approval-bound release gates.",
                "orchestrationMode": "autonomous",
                "autonomyLevel": "A4",
                "researchConfig": {
                    "competitorUrls": ["https://example.com"],
                    "depth": "deep",
                },
                "auto_run": True,
                "max_steps": 8,
            },
        )

        assert updated.status_code == 200
        assert updated.body["project"]["orchestrationMode"] == "autonomous"
        assert updated.body["project"]["autonomyLevel"] == "A4"
        assert updated.body["project"]["research"]["competitors"][0]["url"] == "https://example.com"
        assert updated.body["project"]["research"]["readiness"] == "rework"
        assert updated.body["project"]["analysis"] is None
        assert updated.body["project"]["buildCode"] is None
        assert updated.body["project"]["releases"] == []
        assert updated.body["project"]["approvalStatus"] == "pending"
        assert not any(action["action"]["type"] == "auto_approve" for action in updated.body["actions"])
        assert updated.body["nextAction"]["phase"] == "research"
        assert updated.body["nextAction"]["type"] == "review_phase"

    @pytest.mark.parametrize(
        ("phase", "input_data"),
        [
            (
                "research",
                {
                    "spec": "Autonomous multi-agent product lifecycle for AI platform teams.",
                    "competitor_urls": ["https://example.com", "https://acme.dev"],
                },
            ),
            (
                "planning",
                {
                    "spec": "Autonomous multi-agent product lifecycle for AI platform teams.",
                },
            ),
            (
                "design",
                {
                    "spec": "Autonomous multi-agent product lifecycle for AI platform teams.",
                    "selected_features": [
                        {"feature": "自律開発", "selected": True},
                        {"feature": "承認ゲート", "selected": True},
                    ],
                },
            ),
            (
                "development",
                {
                    "spec": "Autonomous multi-agent product lifecycle for AI platform teams.",
                    "selected_features": [
                        {"feature": "自律開発", "selected": True},
                        {"feature": "承認ゲート", "selected": True},
                    ],
                    "selected_design": {
                        "preview_html": (
                            "<!doctype html><html lang='ja'><head><meta name='viewport' "
                            "content='width=device-width, initial-scale=1' /></head>"
                            "<body><main><button aria-label='Start'>Start</button></main></body></html>"
                        )
                    },
                    "milestones": [
                        {
                            "id": "ms-alpha",
                            "name": "Alpha readiness",
                            "criteria": "previewable build with quality gates",
                        }
                    ],
                },
            ),
        ],
    )
    def test_prepare_lifecycle_phase_registers_workflow_and_runs_structured_reference_graph(
        self,
        phase: str,
        input_data: dict[str, object],
    ):
        server, store = _server_with_routes()

        prepared = server.handle_request(
            "POST",
            f"/api/v1/lifecycle/projects/orbit/phases/{phase}/prepare",
            body={},
        )

        assert prepared.status_code == 201
        workflow_id = prepared.body["workflow_id"]
        assert workflow_id == f"lifecycle-{phase}-orbit"
        assert store.get_workflow_project(workflow_id, tenant_id="default") is not None
        assert any(skill_id in store.skills for skill_id in prepared.body["blueprint"]["team"][0]["skills"])
        lifecycle_project = store.get_surface_record("lifecycle-project", "default:orbit")
        if lifecycle_project is not None and phase == "research":
            phase_lookup = {item["phase"]: item["status"] for item in lifecycle_project["phaseStatuses"]}
            assert phase_lookup["research"] == "in_progress"
            assert phase_lookup["planning"] == "locked"

        started = server.handle_request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/runs",
            body={"input": input_data},
        )

        assert started.status_code == 202
        assert started.body["status"] == "completed"
        state = started.body["state"]
        if phase == "research":
            assert state["research"]["competitors"]
            assert state["research"]["tech_feasibility"]["score"] > 0
        elif phase == "planning":
            assert state["analysis"]["personas"]
            assert state["features"]
            assert state["planEstimates"]
        elif phase == "design":
            assert len(state["variants"]) >= 2
            assert state["design"]["variants"][0]["preview_html"].startswith("<!doctype html>")
            assert state["design"]["variants"][0]["prototype"]["screens"]
            assert 'data-screen-id=' in state["design"]["variants"][0]["preview_html"]
        else:
            assert state["development"]["code"].startswith("<!doctype html>")
            assert 'data-prototype-kind=' in state["development"]["code"]
            assert state["development"]["review_summary"]["milestonesTotal"] >= 1
            assert state["_build_iteration"] in {1, 2}

        synced = server.handle_request(
            "POST",
            f"/api/v1/lifecycle/projects/orbit/phases/{phase}/sync",
            body={"run_id": started.body["id"]},
        )
        assert synced.status_code == 200
        project = synced.body["project"]
        assert project["phaseRuns"]
        assert project["artifacts"]
        assert project["decisionLog"]
        assert project["skillInvocations"]
        if phase in {"research", "design", "development"}:
            assert project["delegations"]

    @pytest.mark.parametrize(
        ("backend", "filename"),
        [
            (ControlPlaneBackend.JSON_FILE, "lifecycle-control-plane.json"),
            (ControlPlaneBackend.SQLITE, "lifecycle-control-plane.db"),
        ],
    )
    def test_lifecycle_projects_persist_across_server_restarts(
        self,
        tmp_path: Path,
        backend: ControlPlaneBackend,
        filename: str,
    ):
        control_plane_path = str(tmp_path / filename)
        headers = {"X-Tenant-ID": "tenant-a"}
        server, _ = _server_with_routes(
            control_plane_backend=backend,
            control_plane_path=control_plane_path,
        )

        patched = server.handle_request(
            "PATCH",
            "/api/v1/lifecycle/projects/orbit",
            headers=headers,
            body={
                "spec": "Durable lifecycle workspace",
                "features": [{"feature": "承認ゲート", "selected": True, "priority": "must", "category": "must-be"}],
                "buildCode": (
                    "<!doctype html><html lang='ja'><head><meta name='viewport' "
                    "content='width=device-width, initial-scale=1' /></head>"
                    "<body><main><button aria-label='Ship'>Ship</button></main></body></html>"
                ),
            },
        )
        assert patched.status_code == 200

        checks = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/deploy/checks",
            headers=headers,
            body={},
        )
        assert checks.status_code == 200

        release = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/releases",
            headers=headers,
            body={"note": "Persistent preview"},
        )
        assert release.status_code == 201

        feedback = server.handle_request(
            "POST",
            "/api/v1/lifecycle/projects/orbit/feedback",
            headers=headers,
            body={"text": "Preserve history across restarts", "type": "feature", "impact": "high"},
        )
        assert feedback.status_code == 201

        restarted_server, _ = _server_with_routes(
            control_plane_backend=backend,
            control_plane_path=control_plane_path,
        )
        persisted = restarted_server.handle_request(
            "GET",
            "/api/v1/lifecycle/projects/orbit",
            headers=headers,
        )

        assert persisted.status_code == 200
        assert persisted.body["tenant_id"] == "tenant-a"
        assert persisted.body["spec"] == "Durable lifecycle workspace"
        assert persisted.body["releases"][0]["note"] == "Persistent preview"
        assert persisted.body["feedbackItems"][0]["text"] == "Preserve history across restarts"
        assert persisted.body["decisionLog"]


# ---------------------------------------------------------------------------
# Workflow routes
# ---------------------------------------------------------------------------

class TestWorkflowRoutes:
    def test_create_workflow_definition(self):
        server, store = _server_with_routes()
        project = _workflow_project("wf1-project").model_dump(mode="json")
        resp = server.handle_request(
            "POST",
            "/workflows",
            body={"id": "wf1", "project": project},
        )
        assert resp.status_code == 201
        assert resp.body["id"] == "wf1"
        assert resp.body["project_name"] == "wf1-project"
        assert resp.body["agent_count"] == 2
        assert resp.body["node_count"] == 2
        assert store.get_workflow_project("wf1", tenant_id="default").name == "wf1-project"

    def test_versioned_workflow_routes_are_canonical(self):
        server, _ = _server_with_routes()
        project = _workflow_project("wf-v1-project").model_dump(mode="json")
        created = server.handle_request(
            "POST",
            "/api/v1/workflows",
            body={"id": "wf-v1", "project": project},
        )
        assert created.status_code == 201

        listed = server.handle_request("GET", "/api/v1/workflows")
        assert listed.status_code == 200
        assert listed.body["workflows"][0]["id"] == "wf-v1"

        started = server.handle_request("POST", "/api/v1/workflows/wf-v1/runs", body={})
        assert started.status_code == 202
        run_id = started.body["id"]

        fetched = server.handle_request("GET", f"/api/v1/workflows/wf-v1/runs/{run_id}")
        assert fetched.status_code == 200
        assert fetched.body["id"] == run_id

        global_runs = server.handle_request("GET", "/api/v1/runs")
        assert global_runs.status_code == 200
        assert global_runs.body["runs"][0]["id"] == run_id

    def test_create_workflow_definition_returns_structured_validation_issues(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/workflows",
            body={
                "id": "wf1",
                "project": {
                    "version": "1",
                    "name": "wf1-project",
                    "agents": {"writer": {"role": "write"}},
                    "workflow": {"nodes": {"start": {"agent": "missing", "next": "END"}}},
                },
            },
        )
        assert resp.status_code == 422
        assert resp.body["error"] == "Workflow project validation failed"
        assert resp.body["validation"]["valid"] is False
        assert resp.body["validation"]["source"] == "project_definition"
        assert resp.body["issues"][0]["stage"] == "referential"
        assert resp.body["issues"][0]["field"] == "workflow.nodes.start.agent"

    def test_create_workflow_definition_exposes_validation_warnings(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/workflows",
            body={
                "id": "wf1",
                "project": {
                    "version": "1",
                    "name": "wf1-project",
                    "agents": {"writer": {"role": "write"}},
                    "workflow": {
                        "nodes": {
                            "start": {"agent": "writer", "next": "END"},
                            "other": {"agent": "writer", "next": "END"},
                        }
                    },
                },
            },
        )
        assert resp.status_code == 201
        assert resp.body["validation"]["valid"] is True
        assert resp.body["validation"]["summary"]["warning_count"] == 1
        assert resp.body["validation_warnings"][0]["stage"] == "protocol"

    def test_create_workflow_definition_allows_same_id_across_tenants(self):
        server, store = _server_with_routes()
        project = _workflow_project("wf-project").model_dump(mode="json")

        tenant_a = server.handle_request(
            "POST",
            "/workflows",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"id": "wf1", "project": project},
        )
        tenant_b = server.handle_request(
            "POST",
            "/workflows",
            headers={"X-Tenant-ID": "tenant-b"},
            body={"id": "wf1", "project": project},
        )

        assert tenant_a.status_code == 201
        assert tenant_b.status_code == 201
        assert store.get_workflow_project("wf1", tenant_id="tenant-a") is not None
        assert store.get_workflow_project("wf1", tenant_id="tenant-b") is not None

    def test_list_workflows_filters_by_tenant(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf-default", _workflow_project("default-project"))
        store.register_workflow_project(
            "wf-tenant-a",
            _workflow_project("tenant-a-project"),
            tenant_id="tenant-a",
        )

        resp = server.handle_request(
            "GET",
            "/workflows",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert resp.status_code == 200
        assert resp.body["count"] == 1
        assert resp.body["workflows"][0]["id"] == "wf-tenant-a"

    def test_get_workflow_definition(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project("wf1-project"))

        resp = server.handle_request("GET", "/workflows/wf1")
        assert resp.status_code == 200
        assert resp.body["id"] == "wf1"
        assert resp.body["project"]["name"] == "wf1-project"
        assert resp.body["project"]["workflow"]["nodes"]["start"]["agent"] == "researcher"

    def test_get_workflow_plan(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project("wf1-project"))

        resp = server.handle_request("GET", "/workflows/wf1/plan")
        assert resp.status_code == 200
        assert resp.body["workflow_id"] == "wf1"
        assert resp.body["tenant_id"] == "default"
        assert resp.body["execution_mode"] == "distributed_wave_plan"
        assert resp.body["waves"] == [
            {"index": 0, "node_ids": ["start"], "task_ids": ["wf1:start"]},
            {"index": 1, "node_ids": ["finish"], "task_ids": ["wf1:finish"]},
        ]

    def test_delete_workflow_definition(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project("wf1-project"))

        resp = server.handle_request("DELETE", "/workflows/wf1")
        assert resp.status_code == 204
        assert store.get_workflow_project("wf1", tenant_id="default") is None

    def test_get_workflow_cross_tenant_forbidden(self):
        server, store = _server_with_routes()
        store.register_workflow_project(
            "wf1",
            _workflow_project("tenant-a-project"),
            tenant_id="tenant-a",
        )

        resp = server.handle_request(
            "GET",
            "/workflows/wf1",
            headers={"X-Tenant-ID": "tenant-b"},
        )
        assert resp.status_code == 403

    def test_start_workflow_run(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project("wf1-project"))
        resp = server.handle_request(
            "POST", "/workflows/wf1/run", body={"input": {"task": "build"}}
        )
        assert resp.status_code == 202
        stored_run = store.workflow_runs_by_id[resp.body["id"]]
        assert "approval_summary" not in stored_run
        assert "execution_summary" not in stored_run
        assert "approval_id" not in stored_run
        assert resp.body["workflow_id"] == "wf1"
        assert resp.body["project"] == "wf1-project"
        assert resp.body["status"] == "completed"
        assert resp.body["stop_reason"] == "none"
        assert resp.body["suspension_reason"] == "none"
        assert resp.body["input"] == {"task": "build"}
        assert resp.body["state"]["task"] == "build"
        assert resp.body["state"]["start_done"] is True
        assert resp.body["state"]["finish_done"] is True
        assert resp.body["runtime_metrics"]["iterations"] == 2
        assert resp.body["goal"] is None
        assert resp.body["policy_resolution"] is None
        assert resp.body["active_approval"] is None
        assert resp.body["approvals"] == []
        assert resp.body["execution_summary"]["node_sequence"] == ["start", "finish"]
        assert resp.body["execution_summary"]["total_events"] == 2
        assert resp.body["execution_summary"]["critical_path"] == [
            {"node_id": "start", "attempt_id": 1, "loop_iteration": 1},
            {"node_id": "finish", "attempt_id": 1, "loop_iteration": 1},
        ]
        assert resp.body["execution_summary"]["decision_points"][0] == {
            "type": "edge_decision",
            "source_node": "start",
            "edges": [
                {
                    "edge_key": "start:0",
                    "edge_index": 0,
                    "status": "taken",
                    "target": "finish",
                    "condition": None,
                    "decision_source": "default",
                    "reason": "default edge selected",
                }
            ],
        }
        assert resp.headers["location"].startswith("/api/v1/runs/")

    def test_get_workflow_run(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        run_id = create_resp.body["id"]
        resp = server.handle_request("GET", f"/workflows/wf1/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.body["runtime_metrics"]["iterations"] == 2
        assert isinstance(resp.body["event_log"], list)
        assert resp.body["id"] == run_id

    def test_stream_workflow_run_events_returns_sse_chunks(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())
        create_resp = server.handle_request("POST", "/api/v1/workflows/wf1/runs", body={})
        run_id = create_resp.body["id"]

        streamed = server.handle_request("GET", f"/api/v1/runs/{run_id}/events?once=1")

        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("text/event-stream")
        chunks = list(streamed.body.chunks)
        assert any("event: snapshot" in chunk for chunk in chunks)
        assert any("event: terminal" in chunk for chunk in chunks)
        snapshot = next(chunk for chunk in chunks if "event: snapshot" in chunk)
        assert '"event_log"' in snapshot
        assert '"node_status"' in snapshot

    def test_start_workflow_run_honors_idempotency_key(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())
        first = server.handle_request(
            "POST",
            "/workflows/wf1/run",
            body={"input": {"msg": "hi"}, "idempotency_key": "req-1"},
        )
        second = server.handle_request(
            "POST",
            "/workflows/wf1/run",
            body={"input": {"msg": "hi"}, "idempotency_key": "req-1"},
        )
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.body["id"] == second.body["id"]

    def test_start_workflow_run_supports_queued_execution_mode(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())

        resp = server.handle_request(
            "POST",
            "/workflows/wf1/run",
            body={"execution_mode": "queued"},
        )

        assert resp.status_code == 202
        assert resp.body["execution_mode"] == "queued"
        assert resp.body["status"] == "completed"
        assert len(resp.body["checkpoint_ids"]) == 2
        assert len(resp.body["queue_task_ids"]) == 2

    def test_start_workflow_run_rejects_unsupported_queued_workflow(self):
        server, store = _server_with_routes()
        store.register_workflow_project("approval", _approval_project())

        resp = server.handle_request(
            "POST",
            "/workflows/approval/run",
            body={"execution_mode": "queued"},
        )

        assert resp.status_code == 400
        assert "queued execution mode currently supports only" in resp.body["error"]

    def test_get_workflow_run_by_location_route(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        location = create_resp.headers["location"]
        resp = server.handle_request("GET", location)
        assert resp.status_code == 200
        assert resp.body["id"] == create_resp.body["id"]

    def test_list_workflow_runs_and_global_runs(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        run_id = create_resp.body["id"]

        workflow_runs = server.handle_request("GET", "/workflows/wf1/runs")
        global_runs = server.handle_request("GET", "/api/v1/runs")

        assert workflow_runs.status_code == 200
        assert workflow_runs.body["count"] == 1
        assert workflow_runs.body["runs"][0]["id"] == run_id
        assert global_runs.status_code == 200
        assert global_runs.body["count"] == 1
        assert global_runs.body["runs"][0]["id"] == run_id

    def test_register_routes_uses_injected_control_plane_store(self):
        backend = InMemoryWorkflowControlPlaneStore()
        server, store = _server_with_routes(control_plane_store=backend)
        assert store.control_plane_store is backend

        store.register_workflow_project("wf1", _workflow_project())
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})

        assert create_resp.status_code == 202
        assert backend.get_run_record(create_resp.body["id"]) is not None

    def test_route_store_supports_sqlite_backend(self, tmp_path):
        db_path = tmp_path / "api-control-plane.db"
        server, store = _server_with_routes(
            control_plane_backend="sqlite",
            control_plane_path=str(db_path),
        )
        store.register_workflow_project("wf1", _workflow_project())
        create = server.handle_request("POST", "/workflows/wf1/run", body={})
        run_id = create.body["id"]

        second_server, _ = _server_with_routes(
            control_plane_backend="sqlite",
            control_plane_path=str(db_path),
        )
        workflow = second_server.handle_request("GET", "/workflows/wf1")
        run = second_server.handle_request("GET", f"/api/v1/runs/{run_id}")

        assert workflow.status_code == 200
        assert workflow.body["project_name"] == "demo-project"
        assert run.status_code == 200
        assert run.body["id"] == run_id

    def test_start_workflow_run_requires_registered_definition(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        assert resp.status_code == 404
        assert resp.body["error"] == "Workflow not found: wf1"

    def test_get_workflow_run_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/workflows/wf1/runs/nope")
        assert resp.status_code == 404

    def test_resume_workflow_run(self):
        server, store = _server_with_routes()
        store.register_workflow_project("limited", _limited_workflow_project())

        create = server.handle_request(
            "POST",
            "/workflows/limited/run",
            body={"input": {"task": "x"}},
        )
        run_id = create.body["id"]
        assert create.body["status"] == "paused"
        assert create.body["suspension_reason"] == "limit_exceeded"

        resumed = server.handle_request(
            "POST",
            f"/api/v1/runs/{run_id}/resume",
            body={},
        )
        assert resumed.status_code == 200
        assert resumed.body["status"] == "paused"
        assert resumed.body["state"]["finish_done"] is True
        assert resumed.body["state"]["task"] == "x"

    def test_resume_workflow_run_rejects_input_mismatch(self):
        server, store = _server_with_routes()
        store.register_workflow_project("limited", _limited_workflow_project())

        create = server.handle_request(
            "POST",
            "/workflows/limited/run",
            body={"input": {"task": "x"}},
        )
        run_id = create.body["id"]

        resumed = server.handle_request(
            "POST",
            f"/api/v1/runs/{run_id}/resume",
            body={"input": {"task": "y"}},
        )
        assert resumed.status_code == 409
        assert "resume input_data must match" in resumed.body["error"]

    def test_approve_request_resumes_waiting_run(self):
        server, store = _server_with_routes()
        store.register_workflow_project("approval", _approval_project())

        create = server.handle_request("POST", "/workflows/approval/run", body={})
        run_id = create.body["id"]
        approval_id = create.body["approval_request_id"]
        assert create.body["status"] == "waiting_approval"

        approved = server.handle_request(
            "POST",
            f"/api/v1/approvals/{approval_id}/approve",
            body={"reason": "ok"},
        )
        assert approved.status_code == 200
        assert approved.body["id"] == run_id
        assert approved.body["status"] == "completed"
        assert approved.body["approval_summary"]["approved_request_ids"] == [approval_id]

    def test_reject_request_cancels_waiting_run(self):
        server, store = _server_with_routes()
        store.register_workflow_project("approval", _approval_project())

        create = server.handle_request("POST", "/workflows/approval/run", body={})
        approval_id = create.body["approval_request_id"]

        rejected = server.handle_request(
            "POST",
            f"/api/v1/approvals/{approval_id}/reject",
            body={"reason": "no"},
        )
        assert rejected.status_code == 200
        assert rejected.body["status"] == "cancelled"
        assert rejected.body["stop_reason"] == "approval_denied"
        assert rejected.body["active_approval"] is None

    def test_list_approvals_and_checkpoints(self):
        server, store = _server_with_routes()
        store.register_workflow_project("approval", _approval_project())

        create = server.handle_request("POST", "/workflows/approval/run", body={})
        run_id = create.body["id"]
        approval_id = create.body["approval_request_id"]

        approvals = server.handle_request("GET", "/api/v1/approvals")
        run_approvals = server.handle_request(
            "GET",
            f"/api/v1/runs/{run_id}/approvals",
        )
        checkpoints = server.handle_request("GET", "/api/v1/checkpoints")
        run_checkpoints = server.handle_request(
            "GET",
            f"/api/v1/runs/{run_id}/checkpoints",
        )

        assert approvals.status_code == 200
        assert approvals.body["count"] == 1
        assert approvals.body["approvals"][0]["id"] == approval_id
        assert run_approvals.status_code == 200
        assert run_approvals.body["approvals"][0]["run_id"] == run_id
        assert checkpoints.status_code == 200
        assert checkpoints.body["count"] == 1
        assert run_checkpoints.status_code == 200
        assert run_checkpoints.body["count"] == 1
        assert run_checkpoints.body["checkpoints"][0]["run_id"] == run_id

    def test_replay_checkpoint(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())

        create = server.handle_request("POST", "/workflows/wf1/run", body={})
        checkpoint_id = create.body["checkpoint_ids"][-1]

        replay = server.handle_request(
            "GET",
            f"/api/v1/checkpoints/{checkpoint_id}/replay",
        )
        assert replay.status_code == 200
        assert replay.body["view_kind"] == "replay"
        assert replay.body["source_run"] == create.body["id"]
        assert replay.body["state_hash"]

    def test_replay_intermediate_checkpoint_uses_reconstructed_status(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())

        create = server.handle_request("POST", "/workflows/wf1/run", body={})
        checkpoint_id = create.body["checkpoint_ids"][0]

        replay = server.handle_request(
            "GET",
            f"/api/v1/checkpoints/{checkpoint_id}/replay",
        )
        assert replay.status_code == 200
        assert replay.body["status"] == "running"
        assert replay.body["stop_reason"] == "none"
        assert replay.body["execution_summary"]["node_sequence"] == ["start"]

    def test_delete_workflow_keeps_historical_runs_accessible(self):
        server, store = _server_with_routes()
        store.register_workflow_project("wf1", _workflow_project())

        create = server.handle_request("POST", "/workflows/wf1/run", body={})
        run_id = create.body["id"]
        deleted = server.handle_request("DELETE", "/workflows/wf1")
        assert deleted.status_code == 204

        get_by_id = server.handle_request("GET", f"/api/v1/runs/{run_id}")
        get_by_workflow = server.handle_request("GET", f"/workflows/wf1/runs/{run_id}")
        assert get_by_id.status_code == 200
        assert get_by_workflow.status_code == 200


# ---------------------------------------------------------------------------
# Kill switch route
# ---------------------------------------------------------------------------

class TestKillSwitchRoute:
    def test_activate_global_as_admin(self):
        server, store = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "admin"},
            body={"scope": "global", "reason": "emergency", "issued_by": "admin"},
        )
        assert resp.status_code == 201
        assert "global" in store.kill_switches

    def test_activate_global_non_admin_forbidden(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"scope": "global", "reason": "test", "issued_by": "user"},
        )
        assert resp.status_code == 403

    def test_activate_own_tenant_scope(self):
        server, store = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"scope": "tenant:tenant-a", "reason": "test", "issued_by": "user"},
        )
        assert resp.status_code == 201
        assert "tenant-a:tenant:tenant-a" in store.kill_switches

    def test_activate_other_tenant_scope_forbidden(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"scope": "tenant:tenant-b", "reason": "test", "issued_by": "user"},
        )
        assert resp.status_code == 403

    def test_activate_agent_scope_allowed(self):
        """Non-tenant, non-global scopes (e.g. agent:xxx) are allowed."""
        server, store = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "tenant-a"},
            body={"scope": "agent:123", "reason": "test", "issued_by": "user"},
        )
        assert resp.status_code == 201
        assert "tenant-a:agent:123" in store.kill_switches

    def test_activate_with_parent_scope_persists_metadata(self):
        server, store = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "tenant-a"},
            body={
                "scope": "workflow:wf-1",
                "reason": "test",
                "issued_by": "user",
                "parent_scope": "tenant:tenant-a",
            },
        )
        assert resp.status_code == 201
        assert store.kill_switches["tenant-a:workflow:wf-1"]["parent_scope"] == "tenant:tenant-a"

    def test_activate_validation_error(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            headers={"X-Tenant-ID": "admin"},
            body={"scope": "global"},
        )
        assert resp.status_code == 422

    def test_activate_without_tenant_returns_401(self):
        server = APIServer()
        register_routes(server)
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            body={"scope": "global", "reason": "test", "issued_by": "admin"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    def test_valid_token_passes(self):
        server, _ = _authed_server()
        resp = server.handle_request(
            "POST",
            "/agents",
            headers={"Authorization": "Bearer test-token"},
            body={"name": "x"},
        )
        assert resp.status_code == 201

    def test_missing_auth_rejected(self):
        server, _ = _authed_server()
        resp = server.handle_request("POST", "/agents", body={"name": "x"})
        assert resp.status_code == 401

    def test_invalid_token_rejected(self):
        server, _ = _authed_server()
        resp = server.handle_request(
            "POST",
            "/agents",
            headers={"Authorization": "Bearer wrong"},
            body={"name": "x"},
        )
        assert resp.status_code == 401

    def test_health_skips_auth(self):
        server, _ = _authed_server()
        resp = server.handle_request("GET", "/health")
        assert resp.status_code == 200

    def test_ready_skips_auth(self):
        server, _ = _authed_server()
        resp = server.handle_request("GET", "/ready")
        assert resp.status_code == 200

    def test_trace_id_header_is_emitted(self):
        server = APIServer()
        server.add_middleware(RequestContextMiddleware())
        server.add_middleware(TenantMiddleware(require_tenant=False))

        def handler(request: Request) -> Response:
            request.context["trace_id"] = "trace-123"
            return Response(body={"ok": True})

        server.add_route("GET", "/trace", handler)

        resp = server.handle_request("GET", "/trace")

        assert resp.status_code == 200
        assert resp.headers["x-trace-id"] == "trace-123"

    def test_metrics_requires_observability_scope(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token("limited-token", scopes=("runs:read",))
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=False))
        register_routes(server)

        resp = server.handle_request(
            "GET",
            "/metrics",
            headers={"Authorization": "Bearer limited-token"},
        )

        assert resp.status_code == 403

    def test_jwt_verifier_accepts_valid_hs256_token(self):
        now = int(time.time())
        token = _make_jwt(
            {
                "sub": "svc-jwt",
                "tenant_id": "tenant-a",
                "scope": "runs:read runs:write",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "jti": "tok-123",
                "exp": now + 60,
            },
            "shared-secret",
        )
        verifier = JWTTokenVerifier(
            secret="shared-secret",
            issuer="https://issuer.example",
            audience=("pylon-api",),
        )

        principal = verifier.verify(token)

        assert principal.subject == "svc-jwt"
        assert principal.tenant_id == "tenant-a"
        assert principal.scopes == ("runs:read", "runs:write")
        assert principal.token_id == "tok-123"

    def test_jwt_verifier_rejects_wrong_audience(self):
        now = int(time.time())
        token = _make_jwt(
            {
                "sub": "svc-jwt",
                "tenant_id": "tenant-a",
                "iss": "https://issuer.example",
                "aud": "other-api",
                "exp": now + 60,
            },
            "shared-secret",
        )
        verifier = JWTTokenVerifier(
            secret="shared-secret",
            issuer="https://issuer.example",
            audience=("pylon-api",),
        )

        with pytest.raises(ValueError, match="audience"):
            verifier.verify(token)

    def test_jwt_verifier_rejects_expired_token(self):
        token = _make_jwt(
            {
                "sub": "svc-jwt",
                "tenant_id": "tenant-a",
                "exp": int(time.time()) - 5,
            },
            "shared-secret",
        )
        verifier = JWTTokenVerifier(secret="shared-secret")

        with pytest.raises(ValueError, match="expired"):
            verifier.verify(token)

    def test_jwks_verifier_accepts_valid_rs256_token(self):
        token, jwks = _make_rs256_jwt(
            {
                "sub": "svc-jwks",
                "tenant_id": "tenant-a",
                "scope": "runs:read approvals:write",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "jti": "tok-rs256",
                "exp": int(time.time()) + 60,
            }
        )
        verifier = JWKSTokenVerifier(
            jwks=jwks,
            issuer="https://issuer.example",
            audience=("pylon-api",),
        )

        principal = verifier.verify(token)

        assert principal.subject == "svc-jwks"
        assert principal.tenant_id == "tenant-a"
        assert principal.scopes == ("runs:read", "approvals:write")
        assert principal.token_id == "tok-rs256"

    def test_jwks_verifier_accepts_oidc_discovery_source(self, tmp_path):
        token, jwks = _make_rs256_jwt(
            {
                "sub": "svc-oidc",
                "tenant_id": "tenant-a",
                "scope": "runs:read",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "exp": int(time.time()) + 60,
            }
        )
        jwks_path = tmp_path / "jwks.json"
        jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
        discovery_path = tmp_path / "openid-configuration.json"
        discovery_path.write_text(
            json.dumps(
                {
                    "issuer": "https://issuer.example",
                    "jwks_uri": str(jwks_path),
                }
            ),
            encoding="utf-8",
        )
        verifier = JWKSTokenVerifier(
            oidc_discovery=discovery_path,
            audience=("pylon-api",),
        )

        principal = verifier.verify(token)

        assert principal.subject == "svc-oidc"
        assert principal.tenant_id == "tenant-a"

    def test_jwks_verifier_refreshes_after_key_rotation(self, tmp_path):
        token1, jwks1 = _make_rs256_jwt(
            {
                "sub": "svc-rotate-1",
                "tenant_id": "tenant-a",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "exp": int(time.time()) + 60,
            },
            key_id="key-1",
        )
        token2, jwks2 = _make_rs256_jwt(
            {
                "sub": "svc-rotate-2",
                "tenant_id": "tenant-a",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "exp": int(time.time()) + 60,
            },
            key_id="key-2",
        )
        jwks_path = tmp_path / "jwks.json"
        jwks_path.write_text(json.dumps(jwks1), encoding="utf-8")
        verifier = JWKSTokenVerifier(
            jwks=jwks_path,
            issuer="https://issuer.example",
            audience=("pylon-api",),
            cache_ttl_seconds=300.0,
        )

        first = verifier.verify(token1)
        assert first.subject == "svc-rotate-1"

        jwks_path.write_text(json.dumps(jwks2), encoding="utf-8")
        second = verifier.verify(token2)
        assert second.subject == "svc-rotate-2"

    def test_token_bound_principal_exposed_in_context(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token(
            "bound-token",
            subject="svc-build",
            tenant_id="tenant-a",
            scopes=("runs:write",),
        )
        server.add_middleware(auth)
        captured = {}

        def handler(req: Request) -> Response:
            captured["principal"] = req.context["auth_principal"]
            captured["claims"] = req.context["auth_principal_claims"]
            return Response(body={"ok": True})

        server.add_route("GET", "/test", handler)
        resp = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer bound-token"},
        )
        assert resp.status_code == 200
        assert captured["principal"].subject == "svc-build"
        assert captured["principal"].tenant_id == "tenant-a"
        assert captured["claims"]["scopes"] == ["runs:write"]

    def test_registered_route_rejects_missing_required_scope(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token(
            "read-only-token",
            subject="svc-read",
            tenant_id="tenant-a",
            scopes=("workflows:read",),
        )
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        register_routes(server)

        resp = server.handle_request(
            "POST",
            "/workflows",
            headers={"Authorization": "Bearer read-only-token"},
            body={
                "id": "wf-authz",
                "project": _workflow_project("wf-authz").model_dump(mode="json"),
            },
        )
        assert resp.status_code == 403
        assert resp.body["error"] == "Insufficient scope"
        assert resp.body["required_scopes"] == ["workflows:write"]
        assert resp.body["principal_scopes"] == ["workflows:read"]

    def test_registered_route_accepts_namespace_wildcard_scope(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token(
            "workflow-admin-token",
            subject="svc-workflows",
            tenant_id="tenant-a",
            scopes=("workflows:*",),
        )
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        register_routes(server)

        resp = server.handle_request(
            "POST",
            "/workflows",
            headers={"Authorization": "Bearer workflow-admin-token"},
            body={
                "id": "wf-authz",
                "project": _workflow_project("wf-authz").model_dump(mode="json"),
            },
        )
        assert resp.status_code == 201

    def test_json_file_token_verifier_rejects_invalid_token(self, tmp_path):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(
            '{"tokens":[{"token":"valid-token","subject":"svc","tenant_id":"tenant-a"}]}',
            encoding="utf-8",
        )
        server = APIServer()
        server.add_middleware(AuthMiddleware(verifier=JsonFileTokenVerifier(token_path)))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        resp = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_jwt_auth_middleware_accepts_valid_token(self):
        server = APIServer()
        server.add_middleware(AuthMiddleware(
            verifier=JWTTokenVerifier(
                secret="shared-secret",
                issuer="https://issuer.example",
                audience=("pylon-api",),
            )
        ))
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route(
            "GET",
            "/test",
            lambda r: Response(body={"tenant": r.context["tenant_id"]}),
        )
        token = _make_jwt(
            {
                "sub": "svc-jwt",
                "tenant_id": "tenant-a",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "exp": int(time.time()) + 60,
            },
            "shared-secret",
        )

        resp = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.body["tenant"] == "tenant-a"


class TestTenantMiddleware:
    def test_tenant_id_injected(self):
        server = APIServer()
        tenant_mw = TenantMiddleware(require_tenant=True)
        server.add_middleware(tenant_mw)
        captured = {}

        def handler(req: Request) -> Response:
            captured["tenant_id"] = req.context.get("tenant_id")
            return Response()

        server.add_route("GET", "/test", handler)
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": "acme"})
        assert resp.status_code == 200
        assert captured["tenant_id"] == "acme"

    def test_missing_tenant_rejected(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response())
        resp = server.handle_request("GET", "/test")
        assert resp.status_code == 400

    def test_authenticated_tenant_binding_satisfies_requirement(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token("tenant-bound", subject="svc", tenant_id="tenant-a")
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        captured = {}

        def handler(req: Request) -> Response:
            captured["tenant_id"] = req.context["tenant_id"]
            captured["tenant_source"] = req.context["tenant_source"]
            return Response(body={"ok": True})

        server.add_route("GET", "/test", handler)
        resp = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer tenant-bound"},
        )
        assert resp.status_code == 200
        assert captured["tenant_id"] == "tenant-a"
        assert captured["tenant_source"] == "principal"

    def test_authenticated_tenant_binding_rejects_mismatched_header(self):
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token("tenant-bound", subject="svc", tenant_id="tenant-a")
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        resp = server.handle_request(
            "GET",
            "/test",
            headers={
                "Authorization": "Bearer tenant-bound",
                "X-Tenant-ID": "tenant-b",
            },
        )
        assert resp.status_code == 403
        assert "not authorized" in resp.body["error"]


class TestTenantRequired:
    def test_create_agent_without_tenant_returns_401(self):
        server = APIServer()
        register_routes(server)
        resp = server.handle_request("POST", "/agents", body={"name": "x"})
        assert resp.status_code == 401
        assert resp.body["error"] == "Tenant context required"

    def test_list_agents_without_tenant_returns_401(self):
        server = APIServer()
        register_routes(server)
        resp = server.handle_request("GET", "/agents")
        assert resp.status_code == 401

    def test_workflow_run_without_tenant_returns_401(self):
        server = APIServer()
        register_routes(server)
        resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        assert resp.status_code == 401


class TestTenantIsolationOnRoutes:
    def test_get_agent_cross_tenant_forbidden(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        register_routes(server)

        create = server.handle_request(
            "POST", "/agents", headers={"X-Tenant-ID": "tenant-a"}, body={"name": "agent-a"}
        )
        agent_id = create.body["id"]

        cross = server.handle_request(
            "GET", f"/agents/{agent_id}", headers={"X-Tenant-ID": "tenant-b"}
        )
        assert cross.status_code == 403

    def test_get_workflow_run_cross_tenant_forbidden(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        store = register_routes(server)
        store.register_workflow_project("wf1", _workflow_project(), tenant_id="tenant-a")

        create = server.handle_request(
            "POST", "/workflows/wf1/run", headers={"X-Tenant-ID": "tenant-a"}, body={}
        )
        run_id = create.body["id"]

        cross = server.handle_request(
            "GET", f"/workflows/wf1/runs/{run_id}", headers={"X-Tenant-ID": "tenant-b"}
        )
        assert cross.status_code == 403


class TestRateLimitMiddleware:
    class _FakeRedisPipeline:
        def __init__(self, buckets: dict[str, dict[str, str]]) -> None:
            self._buckets = buckets

        def watch(self, key: str) -> None:
            self._key = key

        def hgetall(self, key: str) -> dict[str, str]:
            return dict(self._buckets.get(key, {}))

        def multi(self) -> None:
            return None

        def hset(self, key: str, mapping: dict[str, float]) -> None:
            self._buckets[key] = {name: str(value) for name, value in mapping.items()}

        def execute(self) -> None:
            return None

        def reset(self) -> None:
            return None

    class _FakeRedisClient:
        def __init__(self) -> None:
            self._buckets: dict[str, dict[str, str]] = {}

        def pipeline(self) -> "TestRateLimitMiddleware._FakeRedisPipeline":
            return TestRateLimitMiddleware._FakeRedisPipeline(self._buckets)

    def test_allows_within_burst(self):
        server = APIServer()
        rl = RateLimitMiddleware(requests_per_second=100, burst=5)
        server.add_middleware(rl)
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        for _ in range(5):
            resp = server.handle_request("GET", "/test")
            assert resp.status_code == 200

    def test_rejects_over_burst(self):
        server = APIServer()
        rl = RateLimitMiddleware(requests_per_second=0.001, burst=1)
        server.add_middleware(rl)
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        server.handle_request("GET", "/test")  # consumes the 1 token
        resp = server.handle_request("GET", "/test")
        assert resp.status_code == 429
        assert "retry-after" in resp.headers

    def test_shared_in_memory_store_applies_across_instances(self):
        store = InMemoryRateLimitStore()
        server_a = APIServer()
        server_a.add_middleware(TenantMiddleware(require_tenant=True))
        server_a.add_middleware(
            RateLimitMiddleware(requests_per_second=0.001, burst=1, store=store)
        )
        server_a.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        server_b = APIServer()
        server_b.add_middleware(TenantMiddleware(require_tenant=True))
        server_b.add_middleware(
            RateLimitMiddleware(requests_per_second=0.001, burst=1, store=store)
        )
        server_b.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        first = server_a.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})
        second = server_b.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})

        assert first.status_code == 200
        assert second.status_code == 429

    def test_sqlite_store_shares_bucket_state(self, tmp_path):
        store = SQLiteRateLimitStore(tmp_path / "rate-limit.db")
        server_a = APIServer()
        server_a.add_middleware(TenantMiddleware(require_tenant=True))
        server_a.add_middleware(
            RateLimitMiddleware(requests_per_second=0.001, burst=1, store=store)
        )
        server_a.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        server_b = APIServer()
        server_b.add_middleware(TenantMiddleware(require_tenant=True))
        server_b.add_middleware(
            RateLimitMiddleware(
                requests_per_second=0.001,
                burst=1,
                store=SQLiteRateLimitStore(tmp_path / "rate-limit.db"),
            )
        )
        server_b.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        first = server_a.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})
        second = server_b.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})

        assert first.status_code == 200
        assert second.status_code == 429

    def test_subject_bucket_scope_isolates_different_principals(self):
        store = InMemoryRateLimitStore()
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token("token-a", subject="svc-a", tenant_id="tenant-a")
        auth.add_token("token-b", subject="svc-b", tenant_id="tenant-a")
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_middleware(
            RateLimitMiddleware(
                requests_per_second=0.001,
                burst=1,
                store=store,
                bucket_scope=RateLimitBucketScope.SUBJECT,
            )
        )
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        first = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer token-a"},
        )
        second = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer token-b"},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.headers["x-ratelimit-scope"] == "subject"

    def test_token_bucket_scope_isolates_same_subject_with_different_tokens(self):
        store = InMemoryRateLimitStore()
        server = APIServer()
        auth = AuthMiddleware(verifier=InMemoryTokenVerifier())
        auth.add_token("token-a", subject="svc-a", tenant_id="tenant-a")
        auth.add_token("token-b", subject="svc-a", tenant_id="tenant-a")
        server.add_middleware(auth)
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_middleware(
            RateLimitMiddleware(
                requests_per_second=0.001,
                burst=1,
                store=store,
                bucket_scope=RateLimitBucketScope.TOKEN,
            )
        )
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        first = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer token-a"},
        )
        second = server.handle_request(
            "GET",
            "/test",
            headers={"Authorization": "Bearer token-b"},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.headers["x-ratelimit-scope"] == "token"

    def test_redis_store_shares_bucket_state(self):
        fake_client = self._FakeRedisClient()
        store = RedisRateLimitStore(client=fake_client, key_prefix="pylon:test")
        server_a = APIServer()
        server_a.add_middleware(TenantMiddleware(require_tenant=True))
        server_a.add_middleware(
            RateLimitMiddleware(requests_per_second=0.001, burst=1, store=store)
        )
        server_a.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        server_b = APIServer()
        server_b.add_middleware(TenantMiddleware(require_tenant=True))
        server_b.add_middleware(
            RateLimitMiddleware(
                requests_per_second=0.001,
                burst=1,
                store=RedisRateLimitStore(client=fake_client, key_prefix="pylon:test"),
            )
        )
        server_b.add_route("GET", "/test", lambda r: Response(body={"ok": True}))

        first = server_a.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})
        second = server_b.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant-a"})

        assert first.status_code == 200
        assert second.status_code == 429


class TestMiddlewareChain:
    def test_chain_builder(self):
        chain = MiddlewareChain()
        chain.add(RequestContextMiddleware()).add(AuthMiddleware()).add(TenantMiddleware())
        assert len(chain.middlewares) == 3


class TestRequestContextMiddleware:
    def test_generates_request_and_correlation_ids(self):
        server = APIServer()
        server.add_middleware(RequestContextMiddleware())

        def handler(req: Request) -> Response:
            return Response(
                body={
                    "request_id": req.context["request_id"],
                    "correlation_id": req.context["correlation_id"],
                }
            )

        server.add_route("GET", "/test", handler)
        resp = server.handle_request("GET", "/test")
        assert resp.status_code == 200
        assert resp.body["request_id"]
        assert resp.body["correlation_id"] == resp.body["request_id"]
        assert resp.headers["x-request-id"] == resp.body["request_id"]
        assert resp.headers["x-correlation-id"] == resp.body["correlation_id"]

    def test_preserves_incoming_correlation_id(self):
        server = APIServer()
        server.add_middleware(RequestContextMiddleware())
        server.add_route("GET", "/test", lambda r: Response(body=r.context))

        resp = server.handle_request(
            "GET",
            "/test",
            headers={"X-Correlation-ID": "corr-123"},
        )
        assert resp.status_code == 200
        assert resp.body["correlation_id"] == "corr-123"
        assert resp.headers["x-correlation-id"] == "corr-123"


class TestTenantIdValidation:
    """M15: tenant_id format validation."""

    def test_valid_tenant_id(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": "acme-corp"})
        assert resp.status_code == 200

    def test_valid_tenant_id_with_underscores(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": "tenant_01"})
        assert resp.status_code == 200

    def test_invalid_tenant_id_sql_injection(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request(
            "GET", "/test", headers={"X-Tenant-ID": "'; DROP TABLE tenants;--"}
        )
        assert resp.status_code == 400
        assert "Invalid tenant ID" in resp.body["error"]

    def test_invalid_tenant_id_uppercase(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": "ACME"})
        assert resp.status_code == 400

    def test_invalid_tenant_id_starts_with_hyphen(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": "-bad"})
        assert resp.status_code == 400

    def test_invalid_tenant_id_too_long(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        long_id = "a" * 65
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": long_id})
        assert resp.status_code == 400

    def test_invalid_tenant_id_empty_string(self):
        server = APIServer()
        server.add_middleware(TenantMiddleware(require_tenant=True))
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test", headers={"X-Tenant-ID": ""})
        assert resp.status_code == 400


class TestSecurityHeadersMiddleware:
    """M16: security response headers."""

    def test_headers_present(self):
        server = APIServer()
        server.add_middleware(SecurityHeadersMiddleware())
        server.add_route("GET", "/test", lambda r: Response(body={"ok": True}))
        resp = server.handle_request("GET", "/test")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["content-security-policy"] == "default-src 'none'"
        assert resp.headers["x-xss-protection"] == "0"

    def test_does_not_overwrite_existing_headers(self):
        server = APIServer()
        server.add_middleware(SecurityHeadersMiddleware())

        def handler(r: Request) -> Response:
            return Response(
                body={"ok": True},
                headers={"content-type": "application/json", "x-frame-options": "SAMEORIGIN"},
            )

        server.add_route("GET", "/test", handler)
        resp = server.handle_request("GET", "/test")
        assert resp.headers["x-frame-options"] == "SAMEORIGIN"
        assert resp.headers["x-content-type-options"] == "nosniff"


class TestResponse:
    def test_json_body(self):
        resp = Response(body={"key": "val"})
        assert '"key"' in resp.json_body()

    def test_json_body_none(self):
        resp = Response(body=None)
        assert resp.json_body() == ""


# ---------------------------------------------------------------------------
# Health check system
# ---------------------------------------------------------------------------


class TestHealthChecker:
    def test_all_healthy(self):
        checker = HealthChecker()
        checker.register("db", lambda: HealthCheckResult(name="db", status="healthy"))
        checker.register("cache", lambda: HealthCheckResult(name="cache", status="healthy"))
        report = checker.run_all_sync()
        assert report["status"] == "healthy"
        assert len(report["checks"]) == 2
        assert all(c["status"] == "healthy" for c in report["checks"])

    def test_one_unhealthy_makes_overall_unhealthy(self):
        checker = HealthChecker()
        checker.register("db", lambda: HealthCheckResult(name="db", status="healthy"))
        checker.register(
            "cache",
            lambda: HealthCheckResult(name="cache", status="unhealthy", message="down"),
        )
        report = checker.run_all_sync()
        assert report["status"] == "unhealthy"

    def test_degraded_status(self):
        checker = HealthChecker()
        checker.register("db", lambda: HealthCheckResult(name="db", status="healthy"))
        checker.register(
            "cache",
            lambda: HealthCheckResult(name="cache", status="degraded", message="slow"),
        )
        report = checker.run_all_sync()
        assert report["status"] == "degraded"

    def test_exception_caught_as_unhealthy(self):
        def failing_check() -> HealthCheckResult:
            raise RuntimeError("connection refused")

        checker = HealthChecker()
        checker.register("db", failing_check)
        report = checker.run_all_sync()
        assert report["status"] == "unhealthy"
        assert report["checks"][0]["name"] == "db"
        assert report["checks"][0]["status"] == "unhealthy"
        assert "connection refused" in report["checks"][0]["message"]

    def test_health_endpoint_returns_proper_structure(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/health")
        assert resp.status_code == 200
        body = resp.body
        assert body["status"] == "healthy"
        assert isinstance(body["checks"], list)
        assert len(body["checks"]) >= 1
        system_check = body["checks"][0]
        assert system_check["name"] == "system"
        assert system_check["status"] == "healthy"
        assert "timestamp" in body
