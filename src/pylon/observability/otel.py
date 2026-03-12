"""Optional OpenTelemetry bridge for exporting Pylon trace spans."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from enum import StrEnum
import uuid
from typing import Any


class OpenTelemetryExporter(StrEnum):
    """Supported OpenTelemetry exporter backends."""

    OTLP_HTTP = "otlp_http"
    CONSOLE = "console"


@dataclass(frozen=True)
class OpenTelemetryConfig:
    """Configuration for optional OpenTelemetry span export."""

    enabled: bool = False
    exporter: OpenTelemetryExporter = OpenTelemetryExporter.OTLP_HTTP
    service_name: str = "pylon"
    service_namespace: str | None = None
    service_version: str | None = None
    endpoint: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    timeout_millis: int = 10_000

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> OpenTelemetryConfig:
        raw = dict(payload or {})
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("open_telemetry.enabled must be a boolean")
        exporter_raw = str(raw.get("exporter", OpenTelemetryExporter.OTLP_HTTP.value))
        try:
            exporter = OpenTelemetryExporter(exporter_raw)
        except ValueError as exc:
            raise ValueError(f"Unsupported OpenTelemetry exporter: {exporter_raw}") from exc

        headers_raw = raw.get("headers", {})
        if headers_raw is None:
            headers = ()
        elif isinstance(headers_raw, Mapping):
            headers = tuple(
                (str(key), str(value))
                for key, value in headers_raw.items()
            )
        else:
            raise ValueError("open_telemetry.headers must be an object")

        timeout_millis = int(raw.get("timeout_millis", 10_000))
        if timeout_millis <= 0:
            raise ValueError("open_telemetry.timeout_millis must be > 0")

        return cls(
            enabled=enabled,
            exporter=exporter,
            service_name=str(raw.get("service_name", "pylon")),
            service_namespace=(
                str(raw["service_namespace"])
                if raw.get("service_namespace") is not None
                else None
            ),
            service_version=(
                str(raw["service_version"])
                if raw.get("service_version") is not None
                else None
            ),
            endpoint=(
                str(raw["endpoint"])
                if raw.get("endpoint") is not None
                else None
            ),
            headers=headers,
            timeout_millis=timeout_millis,
        )


@dataclass(frozen=True)
class ExtractedOpenTelemetryContext:
    """Extracted upstream OpenTelemetry trace context."""

    context: Any
    trace_id: str
    span_id: str
    trace_flags: str = "01"


@dataclass
class OpenTelemetryBridge:
    """Mirrors custom Pylon spans into OpenTelemetry spans."""

    tracer: Any
    trace_api: Any
    propagator: Any
    status_factory: Any
    status_code: Any
    non_recording_span_factory: Any | None = None
    span_context_factory: Any | None = None
    trace_flags_factory: Any | None = None

    def extract(self, headers: Mapping[str, str]) -> ExtractedOpenTelemetryContext | None:
        normalized = {str(key).lower(): str(value) for key, value in headers.items()}
        context = self.propagator.extract(carrier=normalized)
        span = self.trace_api.get_current_span(context)
        span_context = span.get_span_context()
        if not getattr(span_context, "is_valid", False):
            return None
        return ExtractedOpenTelemetryContext(
            context=context,
            trace_id=f"{span_context.trace_id:032x}",
            span_id=f"{span_context.span_id:016x}",
            trace_flags=f"{int(span_context.trace_flags):02x}",
        )

    def context_from_span(self, native_span: Any) -> Any:
        return self.trace_api.set_span_in_context(native_span)

    def remote_parent_context(
        self,
        *,
        trace_id: str,
        span_id: str | None,
        trace_flags: str = "01",
    ) -> Any | None:
        if (
            self.non_recording_span_factory is None
            or self.span_context_factory is None
            or self.trace_flags_factory is None
        ):
            return None
        effective_span_id = span_id or uuid.uuid4().hex[:16]
        try:
            span_context = self.span_context_factory(
                trace_id=int(trace_id, 16),
                span_id=int(effective_span_id, 16),
                is_remote=True,
                trace_flags=self.trace_flags_factory(int(trace_flags, 16)),
            )
        except ValueError:
            return None
        return self.trace_api.set_span_in_context(
            self.non_recording_span_factory(span_context)
        )

    def start_span(
        self,
        name: str,
        *,
        parent_context: Any | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> tuple[Any, str, str, str]:
        native_span = self.tracer.start_span(
            name,
            context=parent_context,
            attributes=_coerce_attributes(attributes or {}),
        )
        native_context = native_span.get_span_context()
        return (
            native_span,
            f"{native_context.trace_id:032x}",
            f"{native_context.span_id:016x}",
            f"{int(native_context.trace_flags):02x}",
        )

    def use_span(self, native_span: Any) -> Any:
        if native_span is None:
            return nullcontext()
        return self.trace_api.use_span(native_span, end_on_exit=False)

    def end_span(
        self,
        native_span: Any,
        *,
        attributes: Mapping[str, Any],
        events: Iterable[Any],
        status: str,
    ) -> None:
        if native_span is None:
            return
        for key, value in _coerce_attributes(attributes).items():
            native_span.set_attribute(key, value)
        for event in events:
            native_span.add_event(
                str(getattr(event, "name", "event")),
                attributes=_coerce_attributes(getattr(event, "attributes", {})),
            )
        native_span.set_status(self.status_factory(self.status_code[status]))
        native_span.end()


def build_open_telemetry_bridge(
    config: OpenTelemetryConfig,
) -> OpenTelemetryBridge | None:
    """Build an OpenTelemetry bridge when support is configured."""
    if not config.enabled:
        return None
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.propagate import get_global_textmap
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import (
            NonRecordingSpan,
            SpanContext,
            Status,
            StatusCode,
            TraceFlags,
        )
    except ImportError as exc:  # pragma: no cover - import path depends on extras
        raise RuntimeError(
            "OpenTelemetry support requires the optional 'opentelemetry' dependencies"
        ) from exc

    resource_attributes: dict[str, str] = {"service.name": config.service_name}
    if config.service_namespace:
        resource_attributes["service.namespace"] = config.service_namespace
    if config.service_version:
        resource_attributes["service.version"] = config.service_version

    provider = TracerProvider(resource=Resource.create(resource_attributes))
    provider.add_span_processor(
        BatchSpanProcessor(_build_exporter(config))
    )
    tracer = provider.get_tracer(config.service_name)

    return OpenTelemetryBridge(
        tracer=tracer,
        trace_api=otel_trace,
        propagator=get_global_textmap(),
        status_factory=Status,
        status_code={
            "UNSET": StatusCode.UNSET,
            "OK": StatusCode.OK,
            "ERROR": StatusCode.ERROR,
        },
        non_recording_span_factory=NonRecordingSpan,
        span_context_factory=SpanContext,
        trace_flags_factory=TraceFlags,
    )


def _build_exporter(config: OpenTelemetryConfig) -> Any:
    if config.exporter is OpenTelemetryExporter.CONSOLE:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    headers = dict(config.headers)
    kwargs: dict[str, Any] = {
        "timeout": config.timeout_millis / 1000.0,
    }
    if config.endpoint:
        kwargs["endpoint"] = config.endpoint
    if headers:
        kwargs["headers"] = headers
    return OTLPSpanExporter(**kwargs)


def _coerce_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _coerce_attribute_value(value)
        for key, value in attributes.items()
        if value is not None
    }


def _coerce_attribute_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        coerced = [_coerce_attribute_value(item) for item in value]
        if all(isinstance(item, (bool, int, float, str)) for item in coerced):
            return coerced
    return str(value)
