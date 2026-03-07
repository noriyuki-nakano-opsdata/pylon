from __future__ import annotations

import json
import sys
import threading
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
