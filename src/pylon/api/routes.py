"""Route definitions for the Pylon API.

Each route handler follows HandlerFunc protocol: (Request) -> Response.
Routes use in-memory stores for demonstration.
"""

from __future__ import annotations

import time
import uuid

from pylon.api.schemas import (
    CREATE_AGENT_SCHEMA,
    KILL_SWITCH_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    validate,
)
from pylon.api.server import APIServer, Request, Response


class RouteStore:
    """In-memory data store for route handlers."""

    def __init__(self) -> None:
        self.agents: dict[str, dict] = {}
        self.workflow_runs: dict[str, dict[str, dict]] = {}  # workflow_id -> {run_id -> run}
        self.workflow_runs_by_id: dict[str, dict] = {}
        self.kill_switches: dict[str, dict] = {}  # scope -> event


def _require_tenant_id(request: Request) -> str | None:
    """Extract tenant_id from request context; return None if missing."""
    return request.context.get("tenant_id")


def _tenant_required_response() -> Response:
    return Response(status_code=401, body={"error": "Tenant context required"})


def register_routes(server: APIServer, store: RouteStore | None = None) -> RouteStore:
    """Register all API routes on the server. Returns the store."""
    s = store or RouteStore()

    def health(request: Request) -> Response:
        return Response(body={"status": "ok", "timestamp": time.time()})

    def create_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        body = request.body or {}
        valid, errors = validate(body, CREATE_AGENT_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        agent_id = uuid.uuid4().hex[:12]
        agent = {
            "id": agent_id,
            "name": body["name"],
            "model": body.get("model", ""),
            "role": body.get("role", ""),
            "autonomy": body.get("autonomy", "A2"),
            "tools": body.get("tools", []),
            "sandbox": body.get("sandbox", "gvisor"),
            "status": "ready",
            "tenant_id": tenant_id,
        }
        s.agents[agent_id] = agent
        return Response(status_code=201, body=agent)

    def list_agents(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agents = [a for a in s.agents.values() if a.get("tenant_id") == tenant_id]
        return Response(body={"agents": agents, "count": len(agents)})

    def get_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=agent)

    def delete_agent(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        agent_id = request.path_params.get("id", "")
        agent = s.agents.get(agent_id)
        if agent is None:
            return Response(status_code=404, body={"error": f"Agent not found: {agent_id}"})
        if agent.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        del s.agents[agent_id]
        return Response(status_code=204, body=None)

    def start_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        body = request.body or {}
        valid, errors = validate(body, WORKFLOW_RUN_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        run_id = uuid.uuid4().hex[:12]
        run = {
            "id": run_id,
            "workflow_id": workflow_id,
            "status": "pending",
            "input": body.get("input", {}),
            "parameters": body.get("parameters", {}),
            "started_at": time.time(),
            "tenant_id": tenant_id,
        }
        s.workflow_runs.setdefault(workflow_id, {})[run_id] = run
        s.workflow_runs_by_id[run_id] = run
        location = f"/api/v1/workflow-runs/{run_id}"
        return Response(
            status_code=202,
            headers={"content-type": "application/json", "location": location},
            body=run,
        )

    def get_workflow_run(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        workflow_id = request.path_params.get("id", "")
        run_id = request.path_params.get("run_id", "")
        runs = s.workflow_runs.get(workflow_id, {})
        run = runs.get(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=run)

    def get_workflow_run_by_id(request: Request) -> Response:
        tenant_id = _require_tenant_id(request)
        if tenant_id is None:
            return _tenant_required_response()
        run_id = request.path_params.get("run_id", "")
        run = s.workflow_runs_by_id.get(run_id)
        if run is None:
            return Response(status_code=404, body={"error": f"Run not found: {run_id}"})
        if run.get("tenant_id") != tenant_id:
            return Response(status_code=403, body={"error": "Forbidden"})
        return Response(body=run)

    def activate_kill_switch(request: Request) -> Response:
        body = request.body or {}
        valid, errors = validate(body, KILL_SWITCH_SCHEMA)
        if not valid:
            return Response(status_code=422, body={"errors": errors})
        event = {
            "scope": body["scope"],
            "reason": body["reason"],
            "issued_by": body["issued_by"],
            "activated_at": time.time(),
        }
        s.kill_switches[body["scope"]] = event
        return Response(status_code=201, body=event)

    server.add_route("GET", "/health", health)
    server.add_route("POST", "/agents", create_agent)
    server.add_route("GET", "/agents", list_agents)
    server.add_route("GET", "/agents/{id}", get_agent)
    server.add_route("DELETE", "/agents/{id}", delete_agent)
    server.add_route("POST", "/workflows/{id}/run", start_workflow_run)
    server.add_route("POST", "/workflows/{id}/runs", start_workflow_run)
    server.add_route("GET", "/workflows/{id}/runs/{run_id}", get_workflow_run)
    server.add_route("GET", "/api/v1/workflow-runs/{run_id}", get_workflow_run_by_id)
    server.add_route("POST", "/kill-switch", activate_kill_switch)

    return s
