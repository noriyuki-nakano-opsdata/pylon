"""Observability helpers for API factory wiring."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.api.health import (
    HealthChecker,
    HealthCheckResult,
    build_default_checker,
    build_default_readiness_checker,
)
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


def build_api_observability_bundle(
    *,
    control_plane_store: WorkflowControlPlaneStore,
    auth_backend: str,
    rate_limit_backend: str | None,
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
        workflow_count = len(store.list_all_workflow_projects())
    except Exception as exc:  # pragma: no cover - defensive boundary
        return HealthCheckResult(
            name="control_plane",
            status="unhealthy",
            message=str(exc),
        )
    return HealthCheckResult(
        name="control_plane",
        status="healthy",
        message="reachable",
        details={"workflow_count": workflow_count},
    )


def _component_health(
    name: str,
    *,
    backend: str,
    enabled: bool,
) -> HealthCheckResult:
    if not enabled:
        return HealthCheckResult(
            name=name,
            status="healthy",
            message="disabled",
            details={"backend": backend},
        )
    return HealthCheckResult(
        name=name,
        status="healthy",
        message="configured",
        details={"backend": backend},
    )
