from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from pathlib import Path

import pytest

from pylon.api import (
    APIMiddlewareConfig,
    APIServerConfig,
    AuthBackend,
    AuthMiddlewareConfig,
    TenantMiddlewareConfig,
    build_http_api_server,
)
from pylon.control_plane import ControlPlaneBackend, ControlPlaneStoreConfig
from pylon.dsl.parser import PylonProject
from pylon.sdk import PylonHTTPClient
from pylon.sdk.client import PylonClientError
from pylon.types import RunStatus


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
    public_numbers = private_key.public_key().public_numbers()

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
    return f"{header}.{body}.{signature_b64}", jwks


@pytest.fixture()
def http_client(tmp_path: Path) -> PylonHTTPClient:
    http_server, _ = build_http_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                tenant=TenantMiddlewareConfig(require_tenant=True),
            ),
            control_plane=ControlPlaneStoreConfig(
                backend=ControlPlaneBackend.SQLITE,
                path=str(tmp_path / "cp.db"),
            ),
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PylonHTTPClient(
            base_url=f"http://127.0.0.1:{http_server.server_port}",
            tenant_id="tenant-a",
        )
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2.0)


def test_http_client_registers_and_fetches_workflow(http_client: PylonHTTPClient) -> None:
    created = http_client.register_project("echo", _workflow_project("echo-project"))

    assert created["id"] == "echo"
    assert http_client.last_request_id
    assert http_client.last_response_headers["x-request-id"] == http_client.last_request_id
    assert http_client.last_response_headers["x-correlation-id"] == http_client.last_request_id
    assert http_client.last_trace_id
    assert http_client.last_response_headers["x-trace-id"] == http_client.last_trace_id

    listed = http_client.list_workflows()
    assert [item["id"] for item in listed] == ["echo"]

    project = http_client.get_workflow("echo")
    assert project.name == "echo-project"

    plan = http_client.plan_workflow("echo")
    assert plan["workflow_id"] == "echo"
    assert plan["execution_mode"] == "distributed_wave_plan"


def test_http_client_runs_and_replays_workflow(http_client: PylonHTTPClient) -> None:
    http_client.register_project("echo", _workflow_project())

    result = http_client.run_workflow("echo", input_data={"msg": "hi"}, execution_mode="queued")
    assert result.status == RunStatus.COMPLETED

    run = http_client.get_run(result.run_id)
    assert run.execution_mode == "queued"
    assert len(run.queue_task_ids) == 2

    runs = http_client.list_runs(workflow_id="echo")
    assert [item.run_id for item in runs] == [result.run_id]

    inline_result = http_client.run_workflow("echo", input_data={"msg": "hi"})
    inline_run = http_client.get_run(inline_result.run_id)

    checkpoints = http_client.list_checkpoints(run_id=inline_run.run_id)
    assert checkpoints

    replay = http_client.replay_checkpoint(str(checkpoints[0]["id"]))
    assert replay["view_kind"] == "replay"
    assert replay["checkpoint_id"] == str(checkpoints[0]["id"])


def test_http_client_reads_feature_manifest(http_client: PylonHTTPClient) -> None:
    manifest = http_client.get_features()

    assert manifest["canonical_prefix"] == "/api/v1"
    assert manifest["legacy_aliases_enabled"] is True
    assert manifest["legacy_alias_policy"]["sunset_on"] == "2026-09-30"
    assert manifest["contract_path"] == "/api/v1/contract"
    assert manifest["surfaces"]["project"]["runs"] is True


def test_http_client_reads_public_contract_manifest(http_client: PylonHTTPClient) -> None:
    manifest = http_client.get_contract()

    assert manifest["canonical_prefix"] == "/api/v1"
    assert manifest["legacy_alias_policy"]["deprecated_on"] == "2026-03-11"
    create_agent = next(
        route
        for route in manifest["routes"]
        if route["method"] == "POST" and route["path"] == "/api/v1/agents"
    )
    assert create_agent["aliases"][0]["path"] == "/agents"
    assert create_agent["authorization"]["all_of_scopes"] == ["agents:write"]


def test_http_client_approves_waiting_run(http_client: PylonHTTPClient) -> None:
    http_client.register_project("review", _approval_project())

    result = http_client.run_workflow("review")
    assert result.status == RunStatus.WAITING_APPROVAL

    run = http_client.get_run(result.run_id)
    assert run.approval_request_id is not None

    approvals = http_client.list_approvals(run_id=result.run_id)
    assert len(approvals) == 1

    resumed = http_client.approve_request(str(run.approval_request_id), reason="ship it")
    assert resumed.status == RunStatus.COMPLETED


def test_http_client_surfaces_http_errors(http_client: PylonHTTPClient) -> None:
    http_client.register_project("review", _approval_project())

    with pytest.raises(PylonClientError, match="queued execution mode currently supports only"):
        http_client.run_workflow("review", execution_mode="queued")


def test_http_client_can_use_token_bound_tenant_without_header(tmp_path: Path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        '{"tokens":[{"token":"svc-token","subject":"svc-http","tenant_id":"tenant-a","scopes":["workflows:write","workflows:read"]}]}',
        encoding="utf-8",
    )
    http_server, _ = build_http_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                auth=AuthMiddlewareConfig(
                    backend=AuthBackend.JSON_FILE,
                    token_path=str(token_path),
                ),
                tenant=TenantMiddlewareConfig(require_tenant=True),
            ),
            control_plane=ControlPlaneStoreConfig(
                backend=ControlPlaneBackend.SQLITE,
                path=str(tmp_path / "cp.db"),
            ),
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PylonHTTPClient(
            base_url=f"http://127.0.0.1:{http_server.server_port}",
            api_key="svc-token",
            tenant_id=None,
        )
        created = client.register_project("echo", _workflow_project("echo-project"))
        assert created["tenant_id"] == "tenant-a"
        listed = client.list_workflows()
        assert [item["tenant_id"] for item in listed] == ["tenant-a"]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2.0)


def test_http_client_can_use_jwt_bound_tenant_without_header(tmp_path: Path) -> None:
    http_server, _ = build_http_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                auth=AuthMiddlewareConfig(
                    backend=AuthBackend.JWT_HS256,
                    jwt_secret="shared-secret",
                    jwt_issuer="https://issuer.example",
                    jwt_audience=("pylon-api",),
                ),
                tenant=TenantMiddlewareConfig(require_tenant=True),
            ),
            control_plane=ControlPlaneStoreConfig(
                backend=ControlPlaneBackend.SQLITE,
                path=str(tmp_path / "cp.db"),
            ),
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        token = _make_jwt(
            {
                "sub": "svc-jwt",
                "tenant_id": "tenant-a",
                "scope": "workflows:write workflows:read",
                "iss": "https://issuer.example",
                "aud": "pylon-api",
                "exp": int(time.time()) + 60,
            },
            "shared-secret",
        )
        client = PylonHTTPClient(
            base_url=f"http://127.0.0.1:{http_server.server_port}",
            api_key=token,
            tenant_id=None,
            correlation_id="corr-http-jwt",
        )
        created = client.register_project("jwt-echo", _workflow_project("jwt-echo"))
        assert created["tenant_id"] == "tenant-a"
        assert client.last_response_headers["x-correlation-id"] == "corr-http-jwt"
        listed = client.list_workflows()
        assert [item["id"] for item in listed] == ["jwt-echo"]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2.0)


def test_http_client_can_use_jwks_bound_tenant_without_header(tmp_path: Path) -> None:
    token, jwks = _make_rs256_jwt(
        {
            "sub": "svc-jwks",
            "tenant_id": "tenant-a",
            "scope": "workflows:write workflows:read",
            "iss": "https://issuer.example",
            "aud": "pylon-api",
            "exp": int(time.time()) + 60,
        }
    )
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
    http_server, _ = build_http_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                auth=AuthMiddlewareConfig(
                    backend=AuthBackend.JWT_JWKS,
                    jwks_path=str(jwks_path),
                    jwt_issuer="https://issuer.example",
                    jwt_audience=("pylon-api",),
                ),
                tenant=TenantMiddlewareConfig(require_tenant=True),
            ),
            control_plane=ControlPlaneStoreConfig(
                backend=ControlPlaneBackend.SQLITE,
                path=str(tmp_path / "cp.db"),
            ),
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PylonHTTPClient(
            base_url=f"http://127.0.0.1:{http_server.server_port}",
            api_key=token,
            tenant_id=None,
        )
        created = client.register_project("jwks-echo", _workflow_project("jwks-echo"))
        assert created["tenant_id"] == "tenant-a"
        listed = client.list_workflows()
        assert [item["id"] for item in listed] == ["jwks-echo"]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2.0)


def test_http_client_can_use_oidc_bound_tenant_without_header(tmp_path: Path) -> None:
    token, jwks = _make_rs256_jwt(
        {
            "sub": "svc-oidc",
            "tenant_id": "tenant-a",
            "scope": "workflows:write workflows:read",
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
    http_server, _ = build_http_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                auth=AuthMiddlewareConfig(
                    backend=AuthBackend.JWT_OIDC,
                    oidc_discovery_path=str(discovery_path),
                    jwt_audience=("pylon-api",),
                ),
                tenant=TenantMiddlewareConfig(require_tenant=True),
            ),
            control_plane=ControlPlaneStoreConfig(
                backend=ControlPlaneBackend.SQLITE,
                path=str(tmp_path / "cp.db"),
            ),
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PylonHTTPClient(
            base_url=f"http://127.0.0.1:{http_server.server_port}",
            api_key=token,
            tenant_id=None,
        )
        created = client.register_project("oidc-echo", _workflow_project("oidc-echo"))
        assert created["tenant_id"] == "tenant-a"
        listed = client.list_workflows()
        assert [item["id"] for item in listed] == ["oidc-echo"]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=2.0)
