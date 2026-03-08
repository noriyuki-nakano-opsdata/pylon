from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest

from pylon.api.factory import (
    APIMiddlewareConfig,
    APIServerConfig,
    AuthBackend,
    AuthMiddlewareConfig,
    RateLimitBackend,
    RateLimitMiddlewareConfig,
    TenantMiddlewareConfig,
    build_api_server,
)
from pylon.dsl.parser import PylonProject
from pylon.errors import ConfigError


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


def test_build_api_server_with_default_stack() -> None:
    server, _ = build_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                tenant=TenantMiddlewareConfig(require_tenant=False),
            )
        )
    )

    resp = server.handle_request("GET", "/health")
    assert resp.status_code == 200

    agent = server.handle_request("POST", "/agents", body={"name": "coder"})
    assert agent.status_code == 201
    assert agent.headers["x-frame-options"] == "DENY"


def test_build_api_server_with_token_bound_tenant_and_sqlite_rate_limit(tmp_path: Path) -> None:
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        '{"tokens":[{"token":"svc-token","subject":"svc-api","tenant_id":"tenant-a","scopes":["workflows:write","workflows:read"]}]}',
        encoding="utf-8",
    )
    server, _ = build_api_server(
        APIServerConfig(
            middleware=APIMiddlewareConfig(
                auth=AuthMiddlewareConfig(
                    backend=AuthBackend.JSON_FILE,
                    token_path=str(token_path),
                ),
                tenant=TenantMiddlewareConfig(require_tenant=True),
                rate_limit=RateLimitMiddlewareConfig(
                    enabled=True,
                    backend=RateLimitBackend.SQLITE,
                    path=str(tmp_path / "rate-limit.db"),
                    requests_per_second=100.0,
                    burst=5,
                ),
            ),
        )
    )

    create = server.handle_request(
        "POST",
        "/workflows",
        headers={"Authorization": "Bearer svc-token"},
        body={"id": "wf-http", "project": _workflow_project("wf-http").model_dump(mode="json")},
    )
    assert create.status_code == 201
    assert create.body["tenant_id"] == "tenant-a"
    assert create.headers["x-ratelimit-limit"] == "5"

    listed = server.handle_request(
        "GET",
        "/workflows",
        headers={"Authorization": "Bearer svc-token"},
    )
    assert listed.status_code == 200
    assert [item["tenant_id"] for item in listed.body["workflows"]] == ["tenant-a"]


def test_auth_config_rejects_invalid_backend() -> None:
    with pytest.raises(ConfigError, match="Unsupported auth backend"):
        AuthMiddlewareConfig.from_mapping({"backend": "invalid"})


def test_rate_limit_config_rejects_invalid_rps() -> None:
    with pytest.raises(ConfigError, match="requests_per_second must be > 0"):
        RateLimitMiddlewareConfig.from_mapping({"enabled": True, "requests_per_second": 0})


def test_api_server_config_from_mapping_round_trips() -> None:
    config = APIServerConfig.from_mapping(
        {
            "control_plane": {"backend": "sqlite", "path": ".pylon/control-plane.db"},
            "middleware": {
                "request_context": {
                    "enabled": True,
                    "request_id_header": "x-request-id",
                    "correlation_id_header": "x-correlation-id",
                },
                "auth": {
                    "backend": "memory",
                    "tokens": [
                        {
                            "token": "svc-token",
                            "subject": "svc-api",
                            "tenant_id": "tenant-a",
                        }
                    ],
                },
                "tenant": {"require_tenant": True},
                "rate_limit": {
                    "enabled": True,
                    "backend": "sqlite",
                    "path": ".pylon/rate-limit.db",
                    "requests_per_second": 5,
                    "burst": 10,
                },
                "security_headers": True,
            },
        }
    )

    assert config.control_plane.backend.value == "sqlite"
    assert config.middleware.request_context.enabled is True
    assert config.middleware.auth.backend.value == "memory"
    assert config.middleware.auth.tokens[0].tenant_id == "tenant-a"
    assert config.middleware.rate_limit.backend.value == "sqlite"
    assert config.middleware.rate_limit.burst == 10


def test_build_api_server_with_jwt_auth_backend() -> None:
    token = _make_jwt(
        {
            "sub": "svc-jwt",
            "tenant_id": "tenant-a",
            "scope": "agents:write",
            "iss": "https://issuer.example",
            "aud": "pylon-api",
            "exp": int(time.time()) + 60,
        },
        "shared-secret",
    )
    server, _ = build_api_server(
        APIServerConfig.from_mapping(
            {
                "middleware": {
                    "auth": {
                        "backend": "jwt_hs256",
                        "jwt_secret": "shared-secret",
                        "jwt_issuer": "https://issuer.example",
                        "jwt_audience": "pylon-api",
                    },
                    "tenant": {"require_tenant": True},
                }
            }
        )
    )

    resp = server.handle_request(
        "GET",
        "/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    create = server.handle_request(
        "POST",
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": "coder"},
    )
    assert create.status_code == 201
    assert create.body["tenant_id"] == "tenant-a"
    assert create.headers["x-request-id"]
    assert create.headers["x-correlation-id"]
