"""Tests for Pylon HTTP API server."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from pylon.api.health import HealthChecker, HealthCheckResult
from pylon.api.middleware import (
    AuthMiddleware,
    InMemoryRateLimitStore,
    InMemoryTokenVerifier,
    JsonFileTokenVerifier,
    JWTTokenVerifier,
    MiddlewareChain,
    RateLimitMiddleware,
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
from pylon.control_plane import InMemoryWorkflowControlPlaneStore
from pylon.dsl.parser import PylonProject

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
        assert resp.headers["location"].startswith("/api/v1/workflow-runs/")

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
        global_runs = server.handle_request("GET", "/api/v1/workflow-runs")

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
        run = second_server.handle_request("GET", f"/api/v1/workflow-runs/{run_id}")

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
            f"/api/v1/workflow-runs/{run_id}/resume",
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
            f"/api/v1/workflow-runs/{run_id}/resume",
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
            f"/api/v1/workflow-runs/{run_id}/approvals",
        )
        checkpoints = server.handle_request("GET", "/api/v1/checkpoints")
        run_checkpoints = server.handle_request(
            "GET",
            f"/api/v1/workflow-runs/{run_id}/checkpoints",
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

        get_by_id = server.handle_request("GET", f"/api/v1/workflow-runs/{run_id}")
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
        assert "tenant:tenant-a" in store.kill_switches

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
        assert "agent:123" in store.kill_switches

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
        assert store.kill_switches["workflow:wf-1"]["parent_scope"] == "tenant:tenant-a"

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
