from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pylon.observability.logging import LEVEL_NAMES, LogEntry
from pylon.observability.tracing import Span


@runtime_checkable
class ExporterProtocol(Protocol):
    """Protocol that all exporters must satisfy (runtime-checkable)."""

    def export_metrics(self, metrics: dict[str, Any]) -> None: ...
    def export_span(self, span: Span) -> None: ...
    def export_log(self, entry: LogEntry) -> None: ...


class ConsoleExporter:
    """Prints telemetry data to stdout in JSON-lines format."""

    def __init__(self, *, stream: Any = None) -> None:
        self._stream = stream or sys.stdout

    def export_metrics(self, metrics: dict[str, Any]) -> None:
        line = json.dumps({"type": "metrics", "data": metrics}, default=str)
        self._stream.write(line + "\n")
        self._stream.flush()

    def export_span(self, span: Span) -> None:
        payload = {
            "type": "span",
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_id": span.parent_id,
            "name": span.name,
            "start_time": span.start_time,
            "end_time": span.end_time,
            "status": span.status.value,
            "attributes": span.attributes,
            "events": [
                {
                    "name": e.name,
                    "timestamp": e.timestamp,
                    "attributes": e.attributes,
                }
                for e in span.events
            ],
        }
        line = json.dumps({"type": "span", "data": payload}, default=str)
        self._stream.write(line + "\n")
        self._stream.flush()

    def export_log(self, entry: LogEntry) -> None:
        payload = {
            "type": "log",
            "timestamp": entry.timestamp,
            "level": LEVEL_NAMES.get(entry.level, str(entry.level)),
            "message": entry.message,
            "context": entry.context,
        }
        line = json.dumps({"type": "log", "data": payload}, default=str)
        self._stream.write(line + "\n")
        self._stream.flush()


class InMemoryExporter:
    """Stores exported telemetry in memory for testing and inspection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.metrics: list[dict[str, Any]] = []
        self.spans: list[Span] = []
        self.logs: list[LogEntry] = []

    def export_metrics(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            self.metrics.append(metrics)

    def export_span(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    def export_log(self, entry: LogEntry) -> None:
        with self._lock:
            self.logs.append(entry)

    def clear(self) -> None:
        with self._lock:
            self.metrics.clear()
            self.spans.clear()
            self.logs.clear()


class JSONLinesExporter:
    """Writes metrics, spans, and logs as JSON lines to a durable file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def export_metrics(self, metrics: dict[str, Any]) -> None:
        self._write_line({"type": "metrics", "data": metrics})

    def export_span(self, span: Span) -> None:
        self._write_line(
            {
                "type": "span",
                "data": {
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "parent_id": span.parent_id,
                    "name": span.name,
                    "start_time": span.start_time,
                    "end_time": span.end_time,
                    "status": span.status.value,
                    "attributes": span.attributes,
                    "events": [
                        {
                            "name": event.name,
                            "timestamp": event.timestamp,
                            "attributes": event.attributes,
                        }
                        for event in span.events
                    ],
                },
            }
        )

    def export_log(self, entry: LogEntry) -> None:
        self._write_line(
            {
                "type": "log",
                "data": {
                    "timestamp": entry.timestamp,
                    "level": LEVEL_NAMES.get(entry.level, str(entry.level)),
                    "message": entry.message,
                    "context": entry.context,
                },
            }
        )

    def _write_line(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class ExporterLogSink:
    """Log sink adapter that forwards structured logs to exporters."""

    def __init__(self, exporters: list[ExporterProtocol] | tuple[ExporterProtocol, ...]) -> None:
        self._exporters = tuple(exporters)

    def emit(self, entry: LogEntry) -> None:
        for exporter in self._exporters:
            exporter.export_log(entry)


def _sanitize_prometheus_name(name: str) -> str:
    sanitized = [
        ch if ch.isalnum() or ch in {"_", ":"} else "_"
        for ch in name
    ]
    rendered = "".join(sanitized).strip("_")
    return rendered or "pylon_metric"


def _format_prometheus_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = []
    for key, value in sorted(labels.items()):
        safe_key = _sanitize_prometheus_name(key)
        safe_value = (
            str(value)
            .replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace('"', '\\"')
        )
        parts.append(f'{safe_key}="{safe_value}"')
    return "{" + ",".join(parts) + "}"


class PrometheusExporter:
    """Renders metric snapshots using Prometheus text exposition format."""

    def __init__(self, *, namespace: str = "pylon") -> None:
        self._namespace = _sanitize_prometheus_name(namespace)
        self._lock = threading.Lock()
        self._latest_metrics: dict[str, Any] = {
            "counters": [],
            "histograms": [],
            "gauges": [],
        }

    def export_metrics(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            self._latest_metrics = json.loads(json.dumps(metrics))

    def export_span(self, span: Span) -> None:
        return None

    def export_log(self, entry: LogEntry) -> None:
        return None

    def render_latest(self) -> str:
        with self._lock:
            snapshot = json.loads(json.dumps(self._latest_metrics))
        return self.render_metrics(snapshot)

    def render_metrics(self, metrics: dict[str, Any]) -> str:
        lines: list[str] = []
        emitted_types: set[str] = set()

        for counter in metrics.get("counters", []):
            name = self._metric_name(str(counter.get("name", "counter")))
            labels = _format_prometheus_labels(dict(counter.get("labels", {})))
            if name not in emitted_types:
                lines.append(f"# TYPE {name} counter")
                emitted_types.add(name)
            lines.append(f"{name}{labels} {float(counter.get('value', 0.0))}")

        for gauge in metrics.get("gauges", []):
            name = self._metric_name(str(gauge.get("name", "gauge")))
            labels = _format_prometheus_labels(dict(gauge.get("labels", {})))
            if name not in emitted_types:
                lines.append(f"# TYPE {name} gauge")
                emitted_types.add(name)
            lines.append(f"{name}{labels} {float(gauge.get('value', 0.0))}")

        for histogram in metrics.get("histograms", []):
            name = self._metric_name(str(histogram.get("name", "histogram")))
            labels = _format_prometheus_labels(dict(histogram.get("labels", {})))
            if name not in emitted_types:
                lines.append(f"# TYPE {name} untyped")
                emitted_types.add(name)
            lines.append(f"{name}_count{labels} {int(histogram.get('count', 0))}")
            lines.append(f"{name}_sum{labels} {float(histogram.get('total', 0.0))}")
            if histogram.get("min") is not None:
                lines.append(f"{name}_min{labels} {float(histogram['min'])}")
            if histogram.get("max") is not None:
                lines.append(f"{name}_max{labels} {float(histogram['max'])}")
            lines.append(f"{name}_mean{labels} {float(histogram.get('mean', 0.0))}")

        return "\n".join(lines) + ("\n" if lines else "")

    def _metric_name(self, name: str) -> str:
        rendered = _sanitize_prometheus_name(name)
        if rendered.startswith(f"{self._namespace}_"):
            return rendered
        return f"{self._namespace}_{rendered}"
