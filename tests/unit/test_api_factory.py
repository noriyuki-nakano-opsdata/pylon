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
    ready = server.handle_request("GET", "/ready")
    assert ready.status_code == 200
    metrics = server.handle_request("GET", "/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")

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


def test_auth_config_rejects_non_boolean_bootstrap_validate() -> None:
    with pytest.raises(ConfigError, match="bootstrap_validate must be a boolean"):
        AuthMiddlewareConfig.from_mapping(
            {"backend": "jwt_jwks", "bootstrap_validate": "yes"}
        )


def test_auth_config_rejects_non_boolean_allow_insecure_http() -> None:
    with pytest.raises(ConfigError, match="allow_insecure_http must be a boolean"):
        AuthMiddlewareConfig.from_mapping(
            {"backend": "jwt_jwks", "allow_insecure_http": "yes"}
        )


def test_rate_limit_config_rejects_invalid_rps() -> None:
    with pytest.raises(ConfigError, match="requests_per_second must be > 0"):
        RateLimitMiddlewareConfig.from_mapping({"enabled": True, "requests_per_second": 0})


def test_rate_limit_config_rejects_invalid_bucket_scope() -> None:
    with pytest.raises(ConfigError, match="Unsupported rate_limit bucket_scope"):
        RateLimitMiddlewareConfig.from_mapping(
            {"enabled": True, "bucket_scope": "invalid"}
        )


def test_rate_limit_config_rejects_missing_redis_url() -> None:
    with pytest.raises(ConfigError, match="rate_limit.url is required for redis backend"):
        build_api_server(
            APIServerConfig.from_mapping(
                {
                    "middleware": {
                        "rate_limit": {
                            "enabled": True,
                            "backend": "redis",
                        },
                        "tenant": {"require_tenant": False},
                    }
                }
            )
        )


def test_observability_config_rejects_invalid_exporter_backend() -> None:
    with pytest.raises(ConfigError, match="Unsupported observability exporter backend"):
        APIServerConfig.from_mapping(
            {
                "observability": {"exporter_backend": "invalid"},
            }
        )


def test_observability_config_rejects_missing_jsonl_path() -> None:
    with pytest.raises(ConfigError, match="telemetry_export_path is required"):
        APIServerConfig.from_mapping(
            {
                "observability": {
                    "telemetry_sink_backend": "jsonl",
                }
            }
        )


def test_api_server_config_from_mapping_round_trips() -> None:
    config = APIServerConfig.from_mapping(
        {
            "control_plane": {"backend": "sqlite", "path": ".pylon/control-plane.db"},
            "middleware": {
                "request_context": {
                    "enabled": True,
                    "request_id_header": "x-request-id",
                    "correlation_id_header": "x-correlation-id",
                    "trace_id_header": "x-trace-id",
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
                    "url": "redis://localhost:6379/0",
                    "key_prefix": "pylon:test",
                    "requests_per_second": 5,
                    "burst": 10,
                    "bucket_scope": "subject",
                },
                "security_headers": True,
            },
            "observability": {
                "enabled": True,
                "request_metrics_enabled": True,
                "readiness_route_enabled": True,
                "metrics_route_enabled": True,
                "exporter_backend": "prometheus",
                "telemetry_sink_backend": "jsonl",
                "telemetry_export_path": ".pylon/api-telemetry.jsonl",
                "metrics_namespace": "pylon_api",
            },
        }
    )

    assert config.control_plane.backend.value == "sqlite"
    assert config.middleware.request_context.enabled is True
    assert config.middleware.request_context.trace_id_header == "x-trace-id"
    assert config.middleware.auth.backend.value == "memory"
    assert config.middleware.auth.tokens[0].tenant_id == "tenant-a"
    assert config.middleware.rate_limit.backend.value == "sqlite"
    assert config.middleware.rate_limit.burst == 10
    assert config.middleware.rate_limit.bucket_scope.value == "subject"
    assert config.middleware.rate_limit.url == "redis://localhost:6379/0"
    assert config.middleware.rate_limit.key_prefix == "pylon:test"
    assert config.observability.exporter_backend.value == "prometheus"
    assert config.observability.telemetry_sink_backend.value == "jsonl"
    assert config.observability.telemetry_export_path == ".pylon/api-telemetry.jsonl"
    assert config.observability.metrics_namespace == "pylon_api"


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


def test_build_api_server_with_jwks_auth_backend(tmp_path: Path) -> None:
    token, jwks = _make_rs256_jwt(
        {
            "sub": "svc-jwks",
            "tenant_id": "tenant-a",
            "scope": "agents:write",
            "iss": "https://issuer.example",
            "aud": "pylon-api",
            "exp": int(time.time()) + 60,
        }
    )
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
    server, _ = build_api_server(
        APIServerConfig.from_mapping(
            {
                "middleware": {
                    "auth": {
                        "backend": "jwt_jwks",
                        "jwks_path": str(jwks_path),
                        "jwt_issuer": "https://issuer.example",
                        "jwt_audience": "pylon-api",
                    },
                    "tenant": {"require_tenant": True},
                }
            }
        )
    )

    create = server.handle_request(
        "POST",
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": "coder"},
    )
    assert create.status_code == 201
    assert create.body["tenant_id"] == "tenant-a"


def test_build_api_server_rejects_insecure_jwks_url_by_default() -> None:
    with pytest.raises(
        ConfigError, match="JWKS source must use https unless auth.allow_insecure_http=true"
    ):
        build_api_server(
            APIServerConfig.from_mapping(
                {
                    "middleware": {
                        "auth": {
                            "backend": "jwt_jwks",
                            "jwks_url": "http://issuer.example/jwks.json",
                        }
                    }
                }
            )
        )


def test_build_api_server_rejects_insecure_oidc_jwks_uri_by_default(tmp_path: Path) -> None:
    discovery_path = tmp_path / "openid-configuration.json"
    discovery_path.write_text(
        json.dumps(
            {
                "issuer": "https://issuer.example",
                "jwks_uri": "http://issuer.example/jwks.json",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="Failed to bootstrap OIDC verifier"
    ):
        build_api_server(
            APIServerConfig.from_mapping(
                {
                    "middleware": {
                        "auth": {
                            "backend": "jwt_oidc",
                            "oidc_discovery_path": str(discovery_path),
                            "jwt_audience": "pylon-api",
                        }
                    }
                }
            )
        )


def test_build_api_server_allows_insecure_jwks_url_when_explicitly_enabled() -> None:
    server, _ = build_api_server(
        APIServerConfig.from_mapping(
            {
                "middleware": {
                    "auth": {
                        "backend": "jwt_jwks",
                        "jwks_url": "http://issuer.example/jwks.json",
                        "allow_insecure_http": True,
                        "bootstrap_validate": False,
                    },
                    "tenant": {"require_tenant": False},
                }
            }
        )
    )
    health = server.handle_request("GET", "/health")
    assert health.status_code == 200


def test_build_api_server_with_oidc_auth_backend(tmp_path: Path) -> None:
    token, jwks = _make_rs256_jwt(
        {
            "sub": "svc-oidc",
            "tenant_id": "tenant-a",
            "scope": "agents:write",
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
    server, _ = build_api_server(
        APIServerConfig.from_mapping(
            {
                "middleware": {
                    "auth": {
                        "backend": "jwt_oidc",
                        "oidc_discovery_path": str(discovery_path),
                        "jwt_audience": "pylon-api",
                    },
                    "tenant": {"require_tenant": True},
                }
            }
        )
    )

    create = server.handle_request(
        "POST",
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
        body={"name": "coder"},
    )
    assert create.status_code == 201
    assert create.body["tenant_id"] == "tenant-a"


def test_build_api_server_rejects_oidc_bootstrap_without_jwks_uri(tmp_path: Path) -> None:
    discovery_path = tmp_path / "openid-configuration.json"
    discovery_path.write_text(
        json.dumps({"issuer": "https://issuer.example"}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Failed to bootstrap OIDC verifier"):
        build_api_server(
            APIServerConfig.from_mapping(
                {
                    "middleware": {
                        "auth": {
                            "backend": "jwt_oidc",
                            "oidc_discovery_path": str(discovery_path),
                            "jwt_audience": "pylon-api",
                        }
                    }
                }
            )
        )
