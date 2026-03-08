"""Factory helpers for composing API server middleware and route wiring."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pylon.api.http_server import PylonHTTPServer, create_http_server
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
    ServiceToken,
    SQLiteRateLimitStore,
    TenantMiddleware,
)
from pylon.api.routes import RouteStore, register_routes
from pylon.api.server import APIServer
from pylon.control_plane import ControlPlaneStoreConfig, WorkflowControlPlaneStore
from pylon.errors import ConfigError


class AuthBackend(enum.StrEnum):
    NONE = "none"
    MEMORY = "memory"
    JSON_FILE = "json_file"
    JWT_HS256 = "jwt_hs256"


class RateLimitBackend(enum.StrEnum):
    MEMORY = "memory"
    SQLITE = "sqlite"


@dataclass(frozen=True)
class RequestContextMiddlewareConfig:
    """Configuration for request/correlation ID propagation."""

    enabled: bool = True
    request_id_header: str = "x-request-id"
    correlation_id_header: str = "x-correlation-id"

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> RequestContextMiddlewareConfig:
        raw = dict(payload or {})
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(
                "request_context.enabled must be a boolean",
                details={"enabled": enabled},
            )
        return cls(
            enabled=enabled,
            request_id_header=str(raw.get("request_id_header", "x-request-id")),
            correlation_id_header=str(
                raw.get("correlation_id_header", "x-correlation-id")
            ),
        )


@dataclass(frozen=True)
class AuthMiddlewareConfig:
    """Configuration for API bearer-token authentication."""

    backend: AuthBackend = AuthBackend.NONE
    token_path: str | None = None
    tokens: tuple[ServiceToken, ...] = field(default_factory=tuple)
    jwt_secret: str | None = None
    jwt_secret_path: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: tuple[str, ...] = field(default_factory=tuple)
    jwt_tenant_claim: str = "tenant_id"
    jwt_subject_claim: str = "sub"
    jwt_scopes_claim: str = "scope"
    jwt_leeway_seconds: float = 0.0

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> AuthMiddlewareConfig:
        raw = dict(payload or {})
        backend_value = str(raw.get("backend", AuthBackend.NONE.value))
        try:
            backend = AuthBackend(backend_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported auth backend: {backend_value}",
                details={"backend": backend_value},
            ) from exc
        token_path = raw.get("token_path")
        if token_path is not None and not isinstance(token_path, str):
            raise ConfigError(
                "auth.token_path must be a string",
                details={"token_path": token_path},
            )
        raw_tokens = raw.get("tokens", ())
        if (
            not isinstance(raw_tokens, Sequence)
            or isinstance(raw_tokens, (str, bytes, dict))
        ):
            raise ConfigError(
                "auth.tokens must be a list",
                details={"tokens": raw_tokens},
            )
        tokens = tuple(ServiceToken.from_value(value) for value in raw_tokens)
        jwt_secret = raw.get("jwt_secret")
        jwt_secret_path = raw.get("jwt_secret_path")
        jwt_issuer = raw.get("jwt_issuer")
        jwt_audience_raw = raw.get("jwt_audience", ())
        if jwt_secret is not None and not isinstance(jwt_secret, str):
            raise ConfigError(
                "auth.jwt_secret must be a string",
                details={"jwt_secret": jwt_secret},
            )
        if jwt_secret_path is not None and not isinstance(jwt_secret_path, str):
            raise ConfigError(
                "auth.jwt_secret_path must be a string",
                details={"jwt_secret_path": jwt_secret_path},
            )
        if jwt_issuer is not None and not isinstance(jwt_issuer, str):
            raise ConfigError(
                "auth.jwt_issuer must be a string",
                details={"jwt_issuer": jwt_issuer},
            )
        if isinstance(jwt_audience_raw, str):
            jwt_audience = (jwt_audience_raw,)
        elif (
            isinstance(jwt_audience_raw, Sequence)
            and not isinstance(jwt_audience_raw, (bytes, dict))
        ):
            jwt_audience = tuple(str(value) for value in jwt_audience_raw)
        else:
            raise ConfigError(
                "auth.jwt_audience must be a string or list of strings",
                details={"jwt_audience": jwt_audience_raw},
            )
        jwt_tenant_claim = str(raw.get("jwt_tenant_claim", "tenant_id"))
        jwt_subject_claim = str(raw.get("jwt_subject_claim", "sub"))
        jwt_scopes_claim = str(raw.get("jwt_scopes_claim", "scope"))
        jwt_leeway_seconds = float(raw.get("jwt_leeway_seconds", 0.0))
        return cls(
            backend=backend,
            token_path=token_path,
            tokens=tokens,
            jwt_secret=jwt_secret,
            jwt_secret_path=jwt_secret_path,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_tenant_claim=jwt_tenant_claim,
            jwt_subject_claim=jwt_subject_claim,
            jwt_scopes_claim=jwt_scopes_claim,
            jwt_leeway_seconds=jwt_leeway_seconds,
        )


@dataclass(frozen=True)
class TenantMiddlewareConfig:
    """Configuration for tenant extraction and enforcement."""

    require_tenant: bool = True

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> TenantMiddlewareConfig:
        raw = dict(payload or {})
        require_tenant = raw.get("require_tenant", True)
        if not isinstance(require_tenant, bool):
            raise ConfigError(
                "tenant.require_tenant must be a boolean",
                details={"require_tenant": require_tenant},
            )
        return cls(require_tenant=require_tenant)


@dataclass(frozen=True)
class RateLimitMiddlewareConfig:
    """Configuration for API rate limiting."""

    enabled: bool = False
    backend: RateLimitBackend = RateLimitBackend.MEMORY
    path: str | None = None
    requests_per_second: float = 10.0
    burst: int = 20

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> RateLimitMiddlewareConfig:
        raw = dict(payload or {})
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError(
                "rate_limit.enabled must be a boolean",
                details={"enabled": enabled},
            )
        backend_value = str(raw.get("backend", RateLimitBackend.MEMORY.value))
        try:
            backend = RateLimitBackend(backend_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported rate_limit backend: {backend_value}",
                details={"backend": backend_value},
            ) from exc
        path = raw.get("path")
        if path is not None and not isinstance(path, str):
            raise ConfigError(
                "rate_limit.path must be a string",
                details={"path": path},
            )
        rps = float(raw.get("requests_per_second", 10.0))
        burst = int(raw.get("burst", 20))
        if rps <= 0:
            raise ConfigError(
                "rate_limit.requests_per_second must be > 0",
                details={"requests_per_second": rps},
            )
        if burst <= 0:
            raise ConfigError(
                "rate_limit.burst must be > 0",
                details={"burst": burst},
            )
        return cls(
            enabled=enabled,
            backend=backend,
            path=path,
            requests_per_second=rps,
            burst=burst,
        )


@dataclass(frozen=True)
class APIMiddlewareConfig:
    """Configuration for the standard API middleware stack."""

    request_context: RequestContextMiddlewareConfig = field(
        default_factory=RequestContextMiddlewareConfig
    )
    auth: AuthMiddlewareConfig = field(default_factory=AuthMiddlewareConfig)
    tenant: TenantMiddlewareConfig = field(default_factory=TenantMiddlewareConfig)
    rate_limit: RateLimitMiddlewareConfig = field(default_factory=RateLimitMiddlewareConfig)
    security_headers: bool = True

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> APIMiddlewareConfig:
        raw = dict(payload or {})
        security_headers = raw.get("security_headers", True)
        if not isinstance(security_headers, bool):
            raise ConfigError(
                "middleware.security_headers must be a boolean",
                details={"security_headers": security_headers},
            )
        return cls(
            request_context=RequestContextMiddlewareConfig.from_mapping(
                raw.get("request_context")
            ),
            auth=AuthMiddlewareConfig.from_mapping(raw.get("auth")),
            tenant=TenantMiddlewareConfig.from_mapping(raw.get("tenant")),
            rate_limit=RateLimitMiddlewareConfig.from_mapping(raw.get("rate_limit")),
            security_headers=security_headers,
        )


@dataclass(frozen=True)
class APIServerConfig:
    """Configuration for building a reference API server."""

    control_plane: ControlPlaneStoreConfig = field(default_factory=ControlPlaneStoreConfig)
    middleware: APIMiddlewareConfig = field(default_factory=APIMiddlewareConfig)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> APIServerConfig:
        raw = dict(payload or {})
        return cls(
            control_plane=ControlPlaneStoreConfig.from_mapping(
                raw.get("control_plane"),
                default_backend=ControlPlaneStoreConfig().backend,
                default_path=ControlPlaneStoreConfig().path,
            ),
            middleware=APIMiddlewareConfig.from_mapping(raw.get("middleware")),
        )


def build_auth_middleware(config: AuthMiddlewareConfig) -> AuthMiddleware | None:
    """Build bearer-token auth middleware from config."""

    if config.backend is AuthBackend.NONE:
        return None
    if config.backend is AuthBackend.MEMORY:
        verifier = InMemoryTokenVerifier(config.tokens)
        return AuthMiddleware(verifier=verifier)
    if config.backend is AuthBackend.JSON_FILE:
        if not config.token_path:
            raise ConfigError("auth.token_path is required for json_file backend")
        return AuthMiddleware(verifier=JsonFileTokenVerifier(config.token_path))
    if config.backend is AuthBackend.JWT_HS256:
        secret = config.jwt_secret
        if config.jwt_secret_path:
            secret = Path(config.jwt_secret_path).read_text(encoding="utf-8").strip()
        if not secret:
            raise ConfigError(
                "auth.jwt_secret or auth.jwt_secret_path is required for jwt_hs256 backend"
            )
        return AuthMiddleware(
            verifier=JWTTokenVerifier(
                secret=secret,
                issuer=config.jwt_issuer,
                audience=config.jwt_audience,
                tenant_claim=config.jwt_tenant_claim,
                subject_claim=config.jwt_subject_claim,
                scopes_claim=config.jwt_scopes_claim,
                leeway_seconds=config.jwt_leeway_seconds,
            )
        )
    raise ConfigError(
        f"Unsupported auth backend: {config.backend.value}",
        details={"backend": config.backend.value},
    )


def build_rate_limit_middleware(
    config: RateLimitMiddlewareConfig,
) -> RateLimitMiddleware | None:
    """Build rate-limit middleware from config."""

    if not config.enabled:
        return None
    if config.backend is RateLimitBackend.MEMORY:
        store = InMemoryRateLimitStore()
    elif config.backend is RateLimitBackend.SQLITE:
        path = config.path or str(Path(".pylon") / "rate-limit.db")
        store = SQLiteRateLimitStore(path)
    else:
        raise ConfigError(
            f"Unsupported rate_limit backend: {config.backend.value}",
            details={"backend": config.backend.value},
        )
    return RateLimitMiddleware(
        requests_per_second=config.requests_per_second,
        burst=config.burst,
        store=store,
    )


def build_middleware_chain(config: APIMiddlewareConfig) -> MiddlewareChain:
    """Build the standard API middleware chain."""

    chain = MiddlewareChain()
    if config.request_context.enabled:
        chain.add(RequestContextMiddleware(
            request_id_header=config.request_context.request_id_header,
            correlation_id_header=config.request_context.correlation_id_header,
        ))
    auth = build_auth_middleware(config.auth)
    if auth is not None:
        chain.add(auth)
    chain.add(TenantMiddleware(require_tenant=config.tenant.require_tenant))
    rate_limit = build_rate_limit_middleware(config.rate_limit)
    if rate_limit is not None:
        chain.add(rate_limit)
    if config.security_headers:
        chain.add(SecurityHeadersMiddleware())
    return chain


def build_api_server(
    config: APIServerConfig,
    *,
    store: RouteStore | None = None,
    control_plane_store: WorkflowControlPlaneStore | None = None,
) -> tuple[APIServer, RouteStore]:
    """Build an APIServer with the standard middleware stack and routes."""

    server = APIServer()
    for middleware in build_middleware_chain(config.middleware).middlewares:
        server.add_middleware(middleware)
    route_store = register_routes(
        server,
        store=store,
        control_plane_store=control_plane_store,
        control_plane_backend=config.control_plane.backend,
        control_plane_path=config.control_plane.path,
    )
    return server, route_store


def build_http_api_server(
    config: APIServerConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    store: RouteStore | None = None,
    control_plane_store: WorkflowControlPlaneStore | None = None,
) -> tuple[PylonHTTPServer, RouteStore]:
    """Build an HTTP server around the standard APIServer wiring."""

    api_server, route_store = build_api_server(
        config,
        store=store,
        control_plane_store=control_plane_store,
    )
    return create_http_server(api_server, host=host, port=port), route_store
