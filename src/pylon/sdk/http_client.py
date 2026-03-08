from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from pylon.dsl.parser import PylonProject, load_project
from pylon.sdk.client import PylonClientError, WorkflowResult, WorkflowRun
from pylon.sdk.config import SDKConfig
from pylon.types import RunStatus, RunStopReason


def _build_workflow_run(payload: dict[str, Any]) -> WorkflowRun:
    status = RunStatus(str(payload.get("status", RunStatus.PENDING.value)))
    stop_reason = RunStopReason(
        str(payload.get("stop_reason", RunStopReason.NONE.value))
    )
    suspension_reason = RunStopReason(
        str(payload.get("suspension_reason", RunStopReason.NONE.value))
    )
    state = dict(payload.get("state", {}))
    return WorkflowRun(
        run_id=str(payload["id"]),
        workflow_id=str(payload.get("workflow_id", payload.get("workflow", ""))),
        workflow_name=str(payload.get("workflow", payload.get("workflow_id", ""))),
        status=status,
        project_name=payload.get("project"),
        view_kind=str(payload.get("view_kind", "run")),
        execution_mode=str(payload.get("execution_mode", "inline")),
        input_data=payload.get("input"),
        output=state.get("output"),
        error=payload.get("error"),
        stop_reason=stop_reason,
        suspension_reason=suspension_reason,
        state=state,
        event_log=list(payload.get("event_log", [])),
        goal=payload.get("goal"),
        autonomy=payload.get("autonomy"),
        verification=payload.get("verification"),
        runtime_metrics=payload.get("runtime_metrics"),
        policy_resolution=payload.get("policy_resolution"),
        refinement_context=payload.get("refinement_context"),
        approval_context=payload.get("approval_context"),
        termination_reason=payload.get("termination_reason"),
        approval_request_id=payload.get("approval_request_id"),
        active_approval=payload.get("active_approval"),
        approvals=list(payload.get("approvals", [])),
        approval_summary=payload.get("approval_summary"),
        execution_summary=payload.get("execution_summary"),
        checkpoint_ids=list(payload.get("checkpoint_ids", [])),
        queue_task_ids=list(payload.get("queue_task_ids", [])),
        logs=list(payload.get("logs", [])),
        state_version=int(payload.get("state_version", 0)),
        state_hash=str(payload.get("state_hash", "")),
    )


class PylonHTTPClient:
    """Remote workflow/control-plane client over HTTP.

    This client intentionally targets canonical workflow definitions and the
    shared run/approval/checkpoint control-plane API. It does not expose the
    local authoring conveniences of `PylonClient`.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: int = 30,
        *,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
        config: SDKConfig | None = None,
    ) -> None:
        self._config = config or SDKConfig(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self._tenant_id = tenant_id
        self._correlation_id = correlation_id
        self._last_request_id: str | None = None
        self._last_response_headers: dict[str, str] = {}

    @property
    def config(self) -> SDKConfig:
        return self._config

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @property
    def last_request_id(self) -> str | None:
        return self._last_request_id

    @property
    def last_response_headers(self) -> dict[str, str]:
        return dict(self._last_response_headers)

    def _resolve_project_definition(
        self,
        definition: PylonProject | dict[str, Any] | str | Path,
    ) -> PylonProject:
        if isinstance(definition, PylonProject):
            return definition
        if isinstance(definition, dict):
            return PylonProject.model_validate(definition)
        return load_project(definition)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
    ) -> tuple[int, dict[str, str], Any]:
        url = f"{self._config.base_url.rstrip('/')}{path}"
        request_id = uuid.uuid4().hex
        correlation_id = self._correlation_id or request_id
        headers = {
            "accept": "application/json",
            "x-request-id": request_id,
            "x-correlation-id": correlation_id,
        }
        if self._tenant_id:
            headers["x-tenant-id"] = self._tenant_id
        data: bytes | None = None
        if self._config.api_key:
            headers["authorization"] = f"Bearer {self._config.api_key}"
        if body is not None:
            headers["content-type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib_request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib_request.urlopen(request, timeout=self._config.timeout) as response:
                self._last_request_id = request_id
                self._last_response_headers = {
                    str(key).lower(): value for key, value in response.headers.items()
                }
                raw = response.read()
                parsed = (
                    json.loads(raw.decode("utf-8"))
                    if raw and "application/json" in response.headers.get("Content-Type", "")
                    else None
                )
                return int(response.status), dict(response.headers.items()), parsed
        except urllib_error.HTTPError as exc:
            raw = exc.read()
            payload: dict[str, Any] | None = None
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    payload = {"raw": raw.decode("utf-8", errors="replace")}
            self._last_request_id = request_id
            self._last_response_headers = {
                str(key).lower(): value for key, value in exc.headers.items()
            }
            message = (
                str(payload.get("error"))
                if isinstance(payload, dict) and payload.get("error")
                else (
                    "; ".join(str(item) for item in payload.get("errors", []))
                    if isinstance(payload, dict) and isinstance(payload.get("errors"), list)
                    else f"HTTP {exc.code}"
                )
            )
            details = dict(payload or {})
            details.setdefault("request_id", self._last_response_headers.get("x-request-id"))
            details.setdefault(
                "correlation_id",
                self._last_response_headers.get("x-correlation-id"),
            )
            raise PylonClientError(message, details=details) from exc
        except urllib_error.URLError as exc:
            self._last_request_id = request_id
            self._last_response_headers = {}
            raise PylonClientError(
                f"HTTP request failed: {exc.reason}",
                details={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            ) from exc

    def register_project(
        self,
        name: str,
        definition: PylonProject | dict[str, Any] | str | Path,
    ) -> dict[str, Any]:
        project = self._resolve_project_definition(definition)
        _, _, payload = self._request(
            "POST",
            "/workflows",
            body={"id": name, "project": project.model_dump(mode="json")},
        )
        assert isinstance(payload, dict)
        return payload

    def register_workflow(
        self,
        name: str,
        definition: PylonProject | dict[str, Any] | str | Path,
    ) -> dict[str, Any]:
        return self.register_project(name, definition)

    def list_workflows(self) -> list[dict[str, Any]]:
        _, _, payload = self._request("GET", "/workflows")
        assert isinstance(payload, dict)
        return list(payload.get("workflows", []))

    def get_workflow(self, name: str) -> PylonProject:
        _, _, payload = self._request("GET", f"/workflows/{name}")
        assert isinstance(payload, dict)
        return PylonProject.model_validate(payload["project"])

    def delete_workflow(self, name: str) -> None:
        self._request("DELETE", f"/workflows/{name}")

    def plan_workflow(self, name: str) -> dict[str, Any]:
        _, _, payload = self._request("GET", f"/workflows/{name}/plan")
        assert isinstance(payload, dict)
        return payload

    def run_workflow(
        self,
        name: str,
        input_data: Any = None,
        *,
        idempotency_key: str | None = None,
        execution_mode: str = "inline",
        parameters: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        body: dict[str, Any] = {
            "parameters": parameters or {},
            "execution_mode": execution_mode,
        }
        if input_data is not None:
            body["input"] = input_data
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        _, _, payload = self._request(
            "POST",
            f"/workflows/{name}/run",
            body=body,
        )
        assert isinstance(payload, dict)
        run = _build_workflow_run(payload)
        return WorkflowResult(
            run_id=run.run_id,
            status=run.status,
            output=run.output,
            error=run.error,
            stop_reason=run.stop_reason,
            suspension_reason=run.suspension_reason,
        )

    def get_run(self, run_id: str) -> WorkflowRun:
        _, _, payload = self._request("GET", f"/api/v1/workflow-runs/{run_id}")
        assert isinstance(payload, dict)
        return _build_workflow_run(payload)

    def list_runs(self, *, workflow_id: str | None = None) -> list[WorkflowRun]:
        path = (
            f"/workflows/{workflow_id}/runs"
            if workflow_id is not None
            else "/api/v1/workflow-runs"
        )
        _, _, payload = self._request("GET", path)
        assert isinstance(payload, dict)
        return [_build_workflow_run(item) for item in payload.get("runs", [])]

    def resume_run(self, run_id: str, input_data: Any = None) -> WorkflowRun:
        body: dict[str, Any] = {}
        if input_data is not None:
            body["input"] = input_data
        _, _, payload = self._request(
            "POST",
            f"/api/v1/workflow-runs/{run_id}/resume",
            body=body,
        )
        assert isinstance(payload, dict)
        return _build_workflow_run(payload)

    def approve_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        _, _, payload = self._request(
            "POST",
            f"/api/v1/approvals/{approval_id}/approve",
            body={"reason": reason or ""},
        )
        assert isinstance(payload, dict)
        return _build_workflow_run(payload)

    def reject_request(
        self,
        approval_id: str,
        *,
        reason: str | None = None,
    ) -> WorkflowRun:
        _, _, payload = self._request(
            "POST",
            f"/api/v1/approvals/{approval_id}/reject",
            body={"reason": reason or ""},
        )
        assert isinstance(payload, dict)
        return _build_workflow_run(payload)

    def replay_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        _, _, payload = self._request("GET", f"/api/v1/checkpoints/{checkpoint_id}/replay")
        assert isinstance(payload, dict)
        return payload

    def list_approvals(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        path = (
            f"/api/v1/workflow-runs/{run_id}/approvals"
            if run_id is not None
            else "/api/v1/approvals"
        )
        _, _, payload = self._request("GET", path)
        assert isinstance(payload, dict)
        return list(payload.get("approvals", []))

    def list_checkpoints(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        path = (
            f"/api/v1/workflow-runs/{run_id}/checkpoints"
            if run_id is not None
            else "/api/v1/checkpoints"
        )
        _, _, payload = self._request("GET", path)
        assert isinstance(payload, dict)
        return list(payload.get("checkpoints", []))
