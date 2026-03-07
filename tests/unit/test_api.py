"""Tests for Pylon HTTP API server."""


from pylon.api.middleware import (
    AuthMiddleware,
    MiddlewareChain,
    RateLimitMiddleware,
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _server_with_routes() -> tuple[APIServer, RouteStore]:
    """Create a server with all routes registered and default tenant context."""
    server = APIServer()
    server.add_middleware(TenantMiddleware(require_tenant=False))
    store = register_routes(server)
    return server, store


def _authed_server() -> tuple[APIServer, RouteStore]:
    """Create a server with auth + tenant middleware."""
    server = APIServer()
    auth = AuthMiddleware(valid_tokens={"test-token"})
    tenant = TenantMiddleware(require_tenant=False)
    server.add_middleware(auth)
    server.add_middleware(tenant)
    store = register_routes(server)
    return server, store


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

    def test_non_dict_body(self):
        ok, errors = validate("not a dict", CREATE_AGENT_SCHEMA)  # type: ignore[arg-type]
        assert ok is False
        assert any("JSON object" in e for e in errors)

    def test_workflow_run_schema_optional(self):
        ok, errors = validate({}, WORKFLOW_RUN_SCHEMA)
        assert ok is True


# ---------------------------------------------------------------------------
# Server routing
# ---------------------------------------------------------------------------

class TestServerRouting:
    def test_health_endpoint(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/health")
        assert resp.status_code == 200
        assert resp.body["status"] == "ok"

    def test_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/nonexistent")
        assert resp.status_code == 404

    def test_method_not_allowed(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("PATCH", "/agents")
        assert resp.status_code == 405

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


# ---------------------------------------------------------------------------
# Workflow routes
# ---------------------------------------------------------------------------

class TestWorkflowRoutes:
    def test_start_workflow_run(self):
        server, _ = _server_with_routes()
        resp = server.handle_request(
            "POST", "/workflows/wf1/run", body={"input": {"task": "build"}}
        )
        assert resp.status_code == 202
        assert resp.body["workflow_id"] == "wf1"
        assert resp.body["status"] == "pending"
        assert resp.headers["location"].startswith("/api/v1/workflow-runs/")

    def test_get_workflow_run(self):
        server, _ = _server_with_routes()
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        run_id = create_resp.body["id"]
        resp = server.handle_request("GET", f"/workflows/wf1/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.body["id"] == run_id

    def test_get_workflow_run_by_location_route(self):
        server, _ = _server_with_routes()
        create_resp = server.handle_request("POST", "/workflows/wf1/run", body={})
        location = create_resp.headers["location"]
        resp = server.handle_request("GET", location)
        assert resp.status_code == 200
        assert resp.body["id"] == create_resp.body["id"]

    def test_get_workflow_run_not_found(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("GET", "/workflows/wf1/runs/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Kill switch route
# ---------------------------------------------------------------------------

class TestKillSwitchRoute:
    def test_activate(self):
        server, store = _server_with_routes()
        resp = server.handle_request(
            "POST",
            "/kill-switch",
            body={"scope": "global", "reason": "emergency", "issued_by": "admin"},
        )
        assert resp.status_code == 201
        assert "global" in store.kill_switches

    def test_activate_validation_error(self):
        server, _ = _server_with_routes()
        resp = server.handle_request("POST", "/kill-switch", body={"scope": "global"})
        assert resp.status_code == 422


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
        register_routes(server)

        create = server.handle_request(
            "POST", "/workflows/wf1/run", headers={"X-Tenant-ID": "tenant-a"}, body={}
        )
        run_id = create.body["id"]

        cross = server.handle_request(
            "GET", f"/workflows/wf1/runs/{run_id}", headers={"X-Tenant-ID": "tenant-b"}
        )
        assert cross.status_code == 403


class TestRateLimitMiddleware:
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


class TestMiddlewareChain:
    def test_chain_builder(self):
        chain = MiddlewareChain()
        chain.add(AuthMiddleware()).add(TenantMiddleware())
        assert len(chain.middlewares) == 2


class TestResponse:
    def test_json_body(self):
        resp = Response(body={"key": "val"})
        assert '"key"' in resp.json_body()

    def test_json_body_none(self):
        resp = Response(body=None)
        assert resp.json_body() == ""
