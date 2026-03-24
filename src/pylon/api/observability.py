"""Observability helpers for API factory wiring."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.api.health import (
    HealthChecker,
    HealthCheckResult,
    build_default_checker,
    build_default_readiness_checker,
)
from pylon.control_plane.file_store import JsonFileWorkflowControlPlaneStore
from pylon.control_plane.in_memory_store import InMemoryWorkflowControlPlaneStore
from pylon.control_plane.sqlite_store import SQLiteWorkflowControlPlaneStore
from pylon.control_plane.workflow_service import WorkflowControlPlaneStore
from pylon.observability.exporters import (
    ExporterLogSink,
    ExporterProtocol,
    JSONLinesExporter,
    PrometheusExporter,
)
from pylon.observability.logging import StructuredLogger
from pylon.observability.metrics import MetricsCollector
from pylon.observability.otel import OpenTelemetryConfig, build_open_telemetry_bridge
from pylon.observability.tracing import Tracer


@dataclass(frozen=True)
class APIObservabilityBundle:
    """Runtime observability primitives shared by the API surface."""

    metrics: MetricsCollector
    tracer: Tracer
    logger: StructuredLogger
    health_checker: HealthChecker
    readiness_checker: HealthChecker
    prometheus_exporter: PrometheusExporter | None = None
    telemetry_exporters: tuple[ExporterProtocol, ...] = ()


@dataclass(frozen=True)
class _ReadinessProfile:
    status: str
    message: str
    backend: str
    readiness_tier: str
    production_capable: bool


def build_api_observability_bundle(
    *,
    control_plane_store: WorkflowControlPlaneStore,
    auth_backend: str,
    rate_limit_backend: str | None,
    secrets_backend: str | None = None,
    secret_audit_backend: str | None = None,
    sandbox_backend: str | None = None,
    metrics_namespace: str,
    enable_prometheus_exporter: bool,
    telemetry_export_path: str | None = None,
    open_telemetry: OpenTelemetryConfig = OpenTelemetryConfig(),
) -> APIObservabilityBundle:
    metrics = MetricsCollector()
    tracer = Tracer(bridge=build_open_telemetry_bridge(open_telemetry))
    logger = StructuredLogger()
    health_checker = build_default_checker()
    readiness_checker = build_default_readiness_checker()
    readiness_checker.register(
        "control_plane",
        lambda: _control_plane_readiness(control_plane_store),
    )
    readiness_checker.register(
        "auth",
        lambda: _component_health(
            "auth",
            backend=auth_backend,
            enabled=auth_backend != "none",
        ),
    )
    readiness_checker.register(
        "rate_limit",
        lambda: _component_health(
            "rate_limit",
            backend=rate_limit_backend or "none",
            enabled=bool(rate_limit_backend and rate_limit_backend != "memory-disabled"),
        ),
    )
    if secrets_backend is not None:
        readiness_checker.register(
            "secrets",
            lambda: _component_health(
                "secrets",
                backend=secrets_backend,
                enabled=bool(str(secrets_backend).strip()),
            ),
        )
    if secret_audit_backend is not None:
        readiness_checker.register(
            "secret_audit",
            lambda: _component_health(
                "secret_audit",
                backend=secret_audit_backend,
                enabled=bool(str(secret_audit_backend).strip()),
            ),
        )
    if sandbox_backend is not None:
        readiness_checker.register(
            "sandbox",
            lambda: _component_health(
                "sandbox",
                backend=sandbox_backend,
                enabled=bool(str(sandbox_backend).strip()),
            ),
        )
    exporter = (
        PrometheusExporter(namespace=metrics_namespace)
        if enable_prometheus_exporter
        else None
    )
    telemetry_exporters: list[ExporterProtocol] = []
    if exporter is not None:
        telemetry_exporters.append(exporter)
    if telemetry_export_path:
        telemetry_exporters.append(JSONLinesExporter(telemetry_export_path))
    if telemetry_exporters:
        logger.register_sink(ExporterLogSink(telemetry_exporters))
    return APIObservabilityBundle(
        metrics=metrics,
        tracer=tracer,
        logger=logger,
        health_checker=health_checker,
        readiness_checker=readiness_checker,
        prometheus_exporter=exporter,
        telemetry_exporters=tuple(telemetry_exporters),
    )


def _control_plane_readiness(
    store: WorkflowControlPlaneStore,
) -> HealthCheckResult:
    try:
        workflow_count = store.count_workflow_projects()
    except Exception as exc:  # pragma: no cover - defensive boundary
        return HealthCheckResult(
            name="control_plane",
            status="unhealthy",
            message=str(exc),
        )
    profile = _control_plane_profile(store)
    return HealthCheckResult(
        name="control_plane",
        status=profile.status,
        message=profile.message,
        details={
            "backend": profile.backend,
            "readiness_tier": profile.readiness_tier,
            "production_capable": profile.production_capable,
            "workflow_count": workflow_count,
        },
    )


def _component_health(
    name: str,
    *,
    backend: str,
    enabled: bool,
) -> HealthCheckResult:
    profile = _component_readiness_profile(name, backend=backend, enabled=enabled)
    return HealthCheckResult(
        name=name,
        status=profile.status,
        message=profile.message,
        details={
            "backend": profile.backend,
            "readiness_tier": profile.readiness_tier,
            "production_capable": profile.production_capable,
        },
    )


def _control_plane_profile(store: WorkflowControlPlaneStore) -> _ReadinessProfile:
    if isinstance(store, InMemoryWorkflowControlPlaneStore):
        return _ReadinessProfile(
            status="degraded",
            message="in-memory control plane is reference-only",
            backend="memory",
            readiness_tier="reference",
            production_capable=False,
        )
    if isinstance(store, JsonFileWorkflowControlPlaneStore):
        return _ReadinessProfile(
            status="degraded",
            message="json-file control plane is suitable for bootstrap only",
            backend="json_file",
            readiness_tier="bootstrap",
            production_capable=False,
        )
    if isinstance(store, SQLiteWorkflowControlPlaneStore):
        return _ReadinessProfile(
            status="healthy",
            message="sqlite control plane is ready for single-node operation",
            backend="sqlite",
            readiness_tier="single-node",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized control plane backend {store.__class__.__name__}",
        backend=store.__class__.__name__,
        readiness_tier="unknown",
        production_capable=False,
    )


def _component_readiness_profile(
    name: str,
    *,
    backend: str,
    enabled: bool,
) -> _ReadinessProfile:
    normalized_backend = str(backend or "none")
    if name == "auth":
        return _auth_readiness_profile(normalized_backend, enabled=enabled)
    if name == "rate_limit":
        return _rate_limit_readiness_profile(normalized_backend, enabled=enabled)
    if name == "secrets":
        return _secrets_readiness_profile(normalized_backend, enabled=enabled)
    if name == "secret_audit":
        return _secret_audit_readiness_profile(normalized_backend, enabled=enabled)
    if name == "sandbox":
        return _sandbox_readiness_profile(normalized_backend, enabled=enabled)
    if not enabled:
        return _ReadinessProfile(
            status="degraded",
            message="component disabled",
            backend=normalized_backend,
            readiness_tier="disabled",
            production_capable=False,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized component {normalized_backend}",
        backend=normalized_backend,
        readiness_tier="unknown",
        production_capable=False,
    )


def _auth_readiness_profile(
    backend: str,
    *,
    enabled: bool,
) -> _ReadinessProfile:
    if not enabled or backend == "none":
        return _ReadinessProfile(
            status="degraded",
            message="authentication is disabled",
            backend="none",
            readiness_tier="disabled",
            production_capable=False,
        )
    if backend in {"memory", "json_file"}:
        return _ReadinessProfile(
            status="degraded",
            message=f"{backend} auth backend is suitable for local/reference use only",
            backend=backend,
            readiness_tier="reference",
            production_capable=False,
        )
    if backend == "jwt_hs256":
        return _ReadinessProfile(
            status="healthy",
            message="jwt_hs256 auth is ready for managed single-node deployments",
            backend=backend,
            readiness_tier="single-node",
            production_capable=True,
        )
    if backend in {"jwt_jwks", "jwt_oidc"}:
        return _ReadinessProfile(
            status="healthy",
            message="federated auth backend configured",
            backend=backend,
            readiness_tier="production",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized auth backend {backend}",
        backend=backend,
        readiness_tier="unknown",
        production_capable=False,
    )


def _rate_limit_readiness_profile(
    backend: str,
    *,
    enabled: bool,
) -> _ReadinessProfile:
    if not enabled or backend == "none":
        return _ReadinessProfile(
            status="degraded",
            message="rate limiting is disabled",
            backend="none",
            readiness_tier="disabled",
            production_capable=False,
        )
    if backend == "memory":
        return _ReadinessProfile(
            status="degraded",
            message="in-memory rate limiting is suitable for reference use only",
            backend=backend,
            readiness_tier="reference",
            production_capable=False,
        )
    if backend == "sqlite":
        return _ReadinessProfile(
            status="healthy",
            message="sqlite rate limiting is ready for single-node operation",
            backend=backend,
            readiness_tier="single-node",
            production_capable=True,
        )
    if backend == "redis":
        return _ReadinessProfile(
            status="healthy",
            message="redis rate limiting is ready for production traffic",
            backend=backend,
            readiness_tier="production",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized rate limit backend {backend}",
        backend=backend,
        readiness_tier="unknown",
        production_capable=False,
    )


def _secrets_readiness_profile(
    backend: str,
    *,
    enabled: bool,
) -> _ReadinessProfile:
    if not enabled or backend == "none":
        return _ReadinessProfile(
            status="degraded",
            message="secrets backend is disabled",
            backend="none",
            readiness_tier="disabled",
            production_capable=False,
        )
    if backend in {"memory", "in_memory"}:
        return _ReadinessProfile(
            status="degraded",
            message="in-memory secrets backend is suitable for reference use only",
            backend=backend,
            readiness_tier="reference",
            production_capable=False,
        )
    if backend in {"file", "file_vault", "encrypted_file"}:
        return _ReadinessProfile(
            status="healthy",
            message="encrypted file-backed secrets are ready for managed single-node operation",
            backend=backend,
            readiness_tier="single-node",
            production_capable=True,
        )
    if backend in {"vault", "hashicorp_vault", "aws_secrets_manager", "gcp_secret_manager"}:
        return _ReadinessProfile(
            status="healthy",
            message="managed secrets backend configured",
            backend=backend,
            readiness_tier="production",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized secrets backend {backend}",
        backend=backend,
        readiness_tier="unknown",
        production_capable=False,
    )


def _secret_audit_readiness_profile(
    backend: str,
    *,
    enabled: bool,
) -> _ReadinessProfile:
    if not enabled or backend == "none":
        return _ReadinessProfile(
            status="degraded",
            message="secret audit backend is disabled",
            backend="none",
            readiness_tier="disabled",
            production_capable=False,
        )
    if backend == "memory":
        return _ReadinessProfile(
            status="degraded",
            message="in-memory secret audit is suitable for reference use only",
            backend=backend,
            readiness_tier="reference",
            production_capable=False,
        )
    if backend in {"jsonl", "sqlite"}:
        return _ReadinessProfile(
            status="healthy",
            message="durable secret audit backend is ready for single-node operation",
            backend=backend,
            readiness_tier="single-node",
            production_capable=True,
        )
    if backend in {"otlp", "siem", "cloud"}:
        return _ReadinessProfile(
            status="healthy",
            message="centralized secret audit backend configured",
            backend=backend,
            readiness_tier="production",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized secret audit backend {backend}",
        backend=backend,
        readiness_tier="unknown",
        production_capable=False,
    )


def _sandbox_readiness_profile(
    backend: str,
    *,
    enabled: bool,
) -> _ReadinessProfile:
    if not enabled or backend == "none":
        return _ReadinessProfile(
            status="degraded",
            message="sandbox backend is disabled",
            backend="none",
            readiness_tier="disabled",
            production_capable=False,
        )
    if backend in {"memory", "local", "process"}:
        return _ReadinessProfile(
            status="degraded",
            message="local-process sandbox backend is suitable for reference use only",
            backend=backend,
            readiness_tier="reference",
            production_capable=False,
        )
    if backend == "docker":
        return _ReadinessProfile(
            status="healthy",
            message="docker sandbox backend is ready for managed single-node operation",
            backend=backend,
            readiness_tier="single-node",
            production_capable=True,
        )
    if backend in {"firecracker", "gvisor"}:
        return _ReadinessProfile(
            status="healthy",
            message="isolated sandbox backend configured",
            backend=backend,
            readiness_tier="production",
            production_capable=True,
        )
    return _ReadinessProfile(
        status="degraded",
        message=f"unrecognized sandbox backend {backend}",
        backend=backend,
        readiness_tier="unknown",
        production_capable=False,
    )
