"""Factory helpers for composing API server middleware and route wiring."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pylon.autonomy.explainability import DecisionExplainer
from pylon.api.http_server import PylonHTTPServer, create_http_server
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
    RequestTelemetryMiddleware,
    SecurityHeadersMiddleware,
    ServiceToken,
    SQLiteRateLimitStore,
    TenantMiddleware,
)
from pylon.api.observability import APIObservabilityBundle, build_api_observability_bundle
from pylon.api.routes import RouteStore, register_routes
from pylon.api.server import APIServer
from pylon.approval import ApprovalManager
from pylon.control_plane import ControlPlaneStoreConfig, WorkflowControlPlaneStore
from pylon.control_plane.adapters import (
    StoreBackedApprovalStore,
    StoreBackedAuditRepository,
)
from pylon.control_plane.workflow_service import WorkflowRunService
from pylon.di import ServiceContainer
from pylon.errors import ConfigError
from pylon.observability.logging import StructuredLogger
from pylon.observability.metrics import MetricsCollector
from pylon.observability.otel import OpenTelemetryConfig
from pylon.observability.tracing import Tracer
from pylon.repository.audit import default_hmac_key
from pylon.runtime.llm import LLMRuntime, ProviderRegistry


class AuthBackend(enum.StrEnum):
    NONE = "none"
    MEMORY = "memory"
    JSON_FILE = "json_file"
    JWT_HS256 = "jwt_hs256"
    JWT_JWKS = "jwt_jwks"
    JWT_OIDC = "jwt_oidc"


class RateLimitBackend(enum.StrEnum):
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class ObservabilityExporterBackend(enum.StrEnum):
    NONE = "none"
    PROMETHEUS = "prometheus"


class TelemetrySinkBackend(enum.StrEnum):
    NONE = "none"
    JSONL = "jsonl"


@dataclass(frozen=True)
class RequestContextMiddlewareConfig:
    """Configuration for request/correlation ID propagation."""

    enabled: bool = True
    request_id_header: str = "x-request-id"
    correlation_id_header: str = "x-correlation-id"
    trace_id_header: str = "x-trace-id"
    span_id_header: str = "x-span-id"

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
            trace_id_header=str(raw.get("trace_id_header", "x-trace-id")),
            span_id_header=str(raw.get("span_id_header", "x-span-id")),
        )


@dataclass(frozen=True)
class AuthMiddlewareConfig:
    """Configuration for API bearer-token authentication."""

    backend: AuthBackend = AuthBackend.NONE
    token_path: str | None = None
    tokens: tuple[ServiceToken, ...] = field(default_factory=tuple)
    jwt_secret: str | None = None
    jwt_secret_path: str | None = None
    jwks_path: str | None = None
    jwks_url: str | None = None
    oidc_discovery_path: str | None = None
    oidc_discovery_url: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: tuple[str, ...] = field(default_factory=tuple)
    jwt_tenant_claim: str = "tenant_id"
    jwt_subject_claim: str = "sub"
    jwt_scopes_claim: str = "scope"
    jwt_leeway_seconds: float = 0.0
    jwks_cache_ttl_seconds: float = 300.0
    bootstrap_validate: bool = True
    allow_insecure_http: bool = False

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
        jwks_path = raw.get("jwks_path")
        jwks_url = raw.get("jwks_url")
        oidc_discovery_path = raw.get("oidc_discovery_path")
        oidc_discovery_url = raw.get("oidc_discovery_url")
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
        if jwks_path is not None and not isinstance(jwks_path, str):
            raise ConfigError(
                "auth.jwks_path must be a string",
                details={"jwks_path": jwks_path},
            )
        if jwks_url is not None and not isinstance(jwks_url, str):
            raise ConfigError(
                "auth.jwks_url must be a string",
                details={"jwks_url": jwks_url},
            )
        if oidc_discovery_path is not None and not isinstance(oidc_discovery_path, str):
            raise ConfigError(
                "auth.oidc_discovery_path must be a string",
                details={"oidc_discovery_path": oidc_discovery_path},
            )
        if oidc_discovery_url is not None and not isinstance(oidc_discovery_url, str):
            raise ConfigError(
                "auth.oidc_discovery_url must be a string",
                details={"oidc_discovery_url": oidc_discovery_url},
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
        jwks_cache_ttl_seconds = float(raw.get("jwks_cache_ttl_seconds", 300.0))
        bootstrap_validate = raw.get("bootstrap_validate", True)
        if not isinstance(bootstrap_validate, bool):
            raise ConfigError(
                "auth.bootstrap_validate must be a boolean",
                details={"bootstrap_validate": bootstrap_validate},
            )
        allow_insecure_http = raw.get("allow_insecure_http", False)
        if not isinstance(allow_insecure_http, bool):
            raise ConfigError(
                "auth.allow_insecure_http must be a boolean",
                details={"allow_insecure_http": allow_insecure_http},
            )
        return cls(
            backend=backend,
            token_path=token_path,
            tokens=tokens,
            jwt_secret=jwt_secret,
            jwt_secret_path=jwt_secret_path,
            jwks_path=jwks_path,
            jwks_url=jwks_url,
            oidc_discovery_path=oidc_discovery_path,
            oidc_discovery_url=oidc_discovery_url,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwt_tenant_claim=jwt_tenant_claim,
            jwt_subject_claim=jwt_subject_claim,
            jwt_scopes_claim=jwt_scopes_claim,
            jwt_leeway_seconds=jwt_leeway_seconds,
            jwks_cache_ttl_seconds=jwks_cache_ttl_seconds,
            bootstrap_validate=bootstrap_validate,
            allow_insecure_http=allow_insecure_http,
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
    url: str | None = None
    key_prefix: str = "pylon:rate_limit"
    requests_per_second: float = 10.0
    burst: int = 20
    bucket_scope: RateLimitBucketScope = RateLimitBucketScope.TENANT

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
        url = raw.get("url")
        key_prefix = raw.get("key_prefix", "pylon:rate_limit")
        if path is not None and not isinstance(path, str):
            raise ConfigError(
                "rate_limit.path must be a string",
                details={"path": path},
            )
        if url is not None and not isinstance(url, str):
            raise ConfigError(
                "rate_limit.url must be a string",
                details={"url": url},
            )
        if not isinstance(key_prefix, str) or not key_prefix:
            raise ConfigError(
                "rate_limit.key_prefix must be a non-empty string",
                details={"key_prefix": key_prefix},
            )
        rps = float(raw.get("requests_per_second", 10.0))
        burst = int(raw.get("burst", 20))
        bucket_scope_value = str(raw.get("bucket_scope", RateLimitBucketScope.TENANT.value))
        try:
            bucket_scope = RateLimitBucketScope(bucket_scope_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported rate_limit bucket_scope: {bucket_scope_value}",
                details={"bucket_scope": bucket_scope_value},
            ) from exc
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
            url=url,
            key_prefix=key_prefix,
            requests_per_second=rps,
            burst=burst,
            bucket_scope=bucket_scope,
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
class APIObservabilityConfig:
    """Configuration for API metrics export and readiness probes."""

    enabled: bool = True
    request_metrics_enabled: bool = True
    readiness_route_enabled: bool = True
    metrics_route_enabled: bool = True
    exporter_backend: ObservabilityExporterBackend = ObservabilityExporterBackend.PROMETHEUS
    telemetry_sink_backend: TelemetrySinkBackend = TelemetrySinkBackend.NONE
    telemetry_export_path: str | None = None
    metrics_namespace: str = "pylon"
    open_telemetry: OpenTelemetryConfig = field(default_factory=OpenTelemetryConfig)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> APIObservabilityConfig:
        raw = dict(payload or {})
        enabled = raw.get("enabled", True)
        request_metrics_enabled = raw.get("request_metrics_enabled", True)
        readiness_route_enabled = raw.get("readiness_route_enabled", True)
        metrics_route_enabled = raw.get("metrics_route_enabled", True)
        for field_name, value in (
            ("enabled", enabled),
            ("request_metrics_enabled", request_metrics_enabled),
            ("readiness_route_enabled", readiness_route_enabled),
            ("metrics_route_enabled", metrics_route_enabled),
        ):
            if not isinstance(value, bool):
                raise ConfigError(
                    f"observability.{field_name} must be a boolean",
                    details={field_name: value},
                )
        exporter_backend_value = str(
            raw.get("exporter_backend", ObservabilityExporterBackend.PROMETHEUS.value)
        )
        try:
            exporter_backend = ObservabilityExporterBackend(exporter_backend_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported observability exporter backend: {exporter_backend_value}",
                details={"exporter_backend": exporter_backend_value},
            ) from exc
        telemetry_sink_backend_value = str(
            raw.get("telemetry_sink_backend", TelemetrySinkBackend.NONE.value)
        )
        try:
            telemetry_sink_backend = TelemetrySinkBackend(telemetry_sink_backend_value)
        except ValueError as exc:
            raise ConfigError(
                f"Unsupported observability telemetry sink backend: {telemetry_sink_backend_value}",
                details={"telemetry_sink_backend": telemetry_sink_backend_value},
            ) from exc
        telemetry_export_path = raw.get("telemetry_export_path")
        if telemetry_export_path is not None and not isinstance(telemetry_export_path, str):
            raise ConfigError(
                "observability.telemetry_export_path must be a string",
                details={"telemetry_export_path": telemetry_export_path},
            )
        if telemetry_sink_backend is TelemetrySinkBackend.JSONL and not telemetry_export_path:
            raise ConfigError(
                "observability.telemetry_export_path is required for jsonl telemetry sink",
                details={"telemetry_sink_backend": telemetry_sink_backend.value},
            )
        metrics_namespace = str(raw.get("metrics_namespace", "pylon")).strip()
        if not metrics_namespace:
            raise ConfigError(
                "observability.metrics_namespace must be a non-empty string",
                details={"metrics_namespace": metrics_namespace},
            )
        try:
            open_telemetry = OpenTelemetryConfig.from_mapping(raw.get("open_telemetry"))
        except ValueError as exc:
            raise ConfigError(
                str(exc),
                details={"open_telemetry": raw.get("open_telemetry")},
            ) from exc
        return cls(
            enabled=enabled,
            request_metrics_enabled=request_metrics_enabled,
            readiness_route_enabled=readiness_route_enabled,
            metrics_route_enabled=metrics_route_enabled,
            exporter_backend=exporter_backend,
            telemetry_sink_backend=telemetry_sink_backend,
            telemetry_export_path=telemetry_export_path,
            metrics_namespace=metrics_namespace,
            open_telemetry=open_telemetry,
        )


@dataclass(frozen=True)
class APIServerConfig:
    """Configuration for building a reference API server."""

    control_plane: ControlPlaneStoreConfig = field(default_factory=ControlPlaneStoreConfig)
    middleware: APIMiddlewareConfig = field(default_factory=APIMiddlewareConfig)
    observability: APIObservabilityConfig = field(default_factory=APIObservabilityConfig)

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
            observability=APIObservabilityConfig.from_mapping(raw.get("observability")),
        )


def build_auth_middleware(config: AuthMiddlewareConfig) -> AuthMiddleware | None:
    """Build bearer-token auth middleware from config."""

    def _validate_url_policy(source: str, *, label: str) -> None:
        if source.startswith("http://") and not config.allow_insecure_http:
            raise ConfigError(
                f"{label} must use https unless auth.allow_insecure_http=true",
                details={label.lower().replace(" ", "_"): source},
            )

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
    if config.backend is AuthBackend.JWT_JWKS:
        jwks_source = config.jwks_url or config.jwks_path
        if not jwks_source:
            raise ConfigError(
                "auth.jwks_url or auth.jwks_path is required for jwt_jwks backend"
            )
        _validate_url_policy(str(jwks_source), label="JWKS source")
        verifier = JWKSTokenVerifier(
            jwks=jwks_source,
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            tenant_claim=config.jwt_tenant_claim,
            subject_claim=config.jwt_subject_claim,
            scopes_claim=config.jwt_scopes_claim,
            leeway_seconds=config.jwt_leeway_seconds,
            cache_ttl_seconds=config.jwks_cache_ttl_seconds,
            allow_insecure_http=config.allow_insecure_http,
        )
        if config.bootstrap_validate:
            try:
                verifier.prime()
            except (OSError, ValueError) as exc:
                raise ConfigError(
                    f"Failed to bootstrap JWKS verifier: {exc}",
                    details={"backend": config.backend.value},
                ) from exc
        return AuthMiddleware(verifier=verifier)
    if config.backend is AuthBackend.JWT_OIDC:
        discovery_source = config.oidc_discovery_url or config.oidc_discovery_path
        if not discovery_source:
            raise ConfigError(
                "auth.oidc_discovery_url or auth.oidc_discovery_path "
                "is required for jwt_oidc backend"
            )
        _validate_url_policy(str(discovery_source), label="OIDC discovery source")
        verifier = JWKSTokenVerifier(
            oidc_discovery=discovery_source,
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            tenant_claim=config.jwt_tenant_claim,
            subject_claim=config.jwt_subject_claim,
            scopes_claim=config.jwt_scopes_claim,
            leeway_seconds=config.jwt_leeway_seconds,
            cache_ttl_seconds=config.jwks_cache_ttl_seconds,
            allow_insecure_http=config.allow_insecure_http,
        )
        if config.bootstrap_validate:
            try:
                verifier.prime()
            except (OSError, ValueError) as exc:
                raise ConfigError(
                    f"Failed to bootstrap OIDC verifier: {exc}",
                    details={"backend": config.backend.value},
                ) from exc
        return AuthMiddleware(verifier=verifier)
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
    elif config.backend is RateLimitBackend.REDIS:
        if not config.url:
            raise ConfigError(
                "rate_limit.url is required for redis backend",
                details={"backend": config.backend.value},
            )
        try:
            store = RedisRateLimitStore(
                config.url,
                key_prefix=config.key_prefix,
            )
        except RuntimeError as exc:
            raise ConfigError(
                str(exc),
                details={"backend": config.backend.value},
            ) from exc
    else:
        raise ConfigError(
            f"Unsupported rate_limit backend: {config.backend.value}",
            details={"backend": config.backend.value},
        )
    return RateLimitMiddleware(
        requests_per_second=config.requests_per_second,
        burst=config.burst,
        store=store,
        bucket_scope=config.bucket_scope,
    )


def build_middleware_chain(
    config: APIMiddlewareConfig,
    *,
    observability: APIObservabilityBundle | None = None,
    request_metrics_enabled: bool = True,
) -> MiddlewareChain:
    """Build the standard API middleware chain."""

    chain = MiddlewareChain()
    if config.request_context.enabled:
        chain.add(RequestContextMiddleware(
            request_id_header=config.request_context.request_id_header,
            correlation_id_header=config.request_context.correlation_id_header,
            trace_id_header=config.request_context.trace_id_header,
            span_id_header=config.request_context.span_id_header,
        ))
    if observability is not None and request_metrics_enabled:
        chain.add(RequestTelemetryMiddleware(
            metrics=observability.metrics,
            tracer=observability.tracer,
            logger=observability.logger,
            exporters=observability.telemetry_exporters,
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


def build_api_container(
    config: APIServerConfig,
    *,
    store: RouteStore | None = None,
    control_plane_store: WorkflowControlPlaneStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability: APIObservabilityBundle | None = None,
    container: ServiceContainer | None = None,
) -> ServiceContainer:
    """Build the default DI container used by the API surface."""
    services = container or ServiceContainer()

    route_store = store or services.resolve_optional(RouteStore)
    if route_store is None:
        route_store = RouteStore(
            control_plane_store=control_plane_store,
            control_plane_backend=config.control_plane.backend,
            control_plane_path=config.control_plane.path,
        )
    services.override(RouteStore, route_store)

    if provider_registry is not None:
        services.override(ProviderRegistry, provider_registry)

    if observability is not None:
        services.override(APIObservabilityBundle, observability)
        services.override(MetricsCollector, observability.metrics)
        services.override(Tracer, observability.tracer)
        services.override(StructuredLogger, observability.logger)

    if not services.has(DecisionExplainer):
        services.register_singleton(
            DecisionExplainer,
            lambda _resolver: DecisionExplainer(),
        )

    if not services.has(ApprovalManager):
        services.register_factory(
            ApprovalManager,
            lambda resolver: ApprovalManager(
                StoreBackedApprovalStore(resolver.resolve(RouteStore)),
                StoreBackedAuditRepository(
                    resolver.resolve(RouteStore),
                    hmac_key=default_hmac_key(),
                ),
            ),
        )

    if not services.has(WorkflowRunService):
        services.register_singleton(
            WorkflowRunService,
            lambda resolver: WorkflowRunService(
                resolver.resolve(RouteStore),
                provider_registry=resolver.resolve_optional(ProviderRegistry),
                llm_runtime=resolver.resolve_optional(LLMRuntime),
                tracer=resolver.resolve_optional(Tracer),
                decision_explainer=resolver.resolve_optional(DecisionExplainer),
            ),
        )

    return services


def build_api_server(
    config: APIServerConfig,
    *,
    store: RouteStore | None = None,
    control_plane_store: WorkflowControlPlaneStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    container: ServiceContainer | None = None,
) -> tuple[APIServer, RouteStore]:
    """Build an APIServer with the standard middleware stack and routes."""

    server = APIServer()
    route_store = store or (
        container.resolve_optional(RouteStore)
        if container is not None
        else None
    )
    if route_store is None:
        route_store = RouteStore(
            control_plane_store=control_plane_store,
            control_plane_backend=config.control_plane.backend,
            control_plane_path=config.control_plane.path,
        )
    observability = (
        build_api_observability_bundle(
            control_plane_store=route_store.control_plane_store,
            auth_backend=config.middleware.auth.backend.value,
            rate_limit_backend=(
                config.middleware.rate_limit.backend.value
                if config.middleware.rate_limit.enabled
                else None
            ),
            metrics_namespace=config.observability.metrics_namespace,
            enable_prometheus_exporter=(
                config.observability.exporter_backend
                is ObservabilityExporterBackend.PROMETHEUS
            ),
            telemetry_export_path=(
                config.observability.telemetry_export_path
                if config.observability.telemetry_sink_backend
                is TelemetrySinkBackend.JSONL
                else None
            ),
            open_telemetry=config.observability.open_telemetry,
        )
        if config.observability.enabled
        else None
    )
    services = build_api_container(
        config,
        store=route_store,
        control_plane_store=control_plane_store,
        provider_registry=provider_registry,
        observability=observability,
        container=container,
    )
    route_store = services.resolve(RouteStore)
    setattr(server, "container", services)
    route_store = register_routes(
        server,
        store=route_store,
        control_plane_backend=config.control_plane.backend,
        control_plane_path=config.control_plane.path,
        observability=observability,
        container=services,
        readiness_route_enabled=(
            config.observability.enabled
            and config.observability.readiness_route_enabled
        ),
        metrics_route_enabled=(
            config.observability.enabled
            and config.observability.metrics_route_enabled
            and observability is not None
            and observability.prometheus_exporter is not None
        ),
    )
    for middleware in build_middleware_chain(
        config.middleware,
        observability=observability,
        request_metrics_enabled=config.observability.request_metrics_enabled,
    ).middlewares:
        server.add_middleware(middleware)
    return server, route_store


def build_http_api_server(
    config: APIServerConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    store: RouteStore | None = None,
    control_plane_store: WorkflowControlPlaneStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    container: ServiceContainer | None = None,
) -> tuple[PylonHTTPServer, RouteStore]:
    """Build an HTTP server around the standard APIServer wiring."""

    api_server, route_store = build_api_server(
        config,
        store=store,
        control_plane_store=control_plane_store,
        provider_registry=provider_registry,
        container=container,
    )
    return create_http_server(api_server, host=host, port=port), route_store
