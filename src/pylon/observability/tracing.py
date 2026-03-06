from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpanStatus(Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass
class SpanEvent:
    """An event attached to a span at a specific point in time."""

    name: str
    timestamp: float = field(default_factory=time.time)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """Represents a unit of work within a distributed trace."""

    trace_id: str
    span_id: str
    name: str
    parent_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: SpanStatus = SpanStatus.UNSET
    events: list[SpanEvent] = field(default_factory=list)

    @property
    def duration(self) -> float | None:
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append(SpanEvent(name=name, attributes=attributes or {}))

    def set_status(self, status: SpanStatus) -> None:
        self.status = status

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


class Tracer:
    """Distributed tracing with span management.

    Thread-safe. Spans are stored in memory keyed by trace_id for retrieval.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {trace_id: [Span, ...]}
        self._traces: dict[str, list[Span]] = {}
        # {span_id: Span}
        self._spans: dict[str, Span] = {}

    def start_span(
        self,
        name: str,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> Span:
        """Create and register a new span.

        If *parent_id* is given and *trace_id* is ``None``, the trace_id is
        inherited from the parent span.  If neither is given a new trace is
        started.
        """
        resolved_trace_id = trace_id

        if resolved_trace_id is None and parent_id is not None:
            with self._lock:
                parent = self._spans.get(parent_id)
            if parent is not None:
                resolved_trace_id = parent.trace_id
            else:
                raise ValueError(f"Parent span {parent_id!r} not found")

        if resolved_trace_id is None:
            resolved_trace_id = uuid.uuid4().hex

        span = Span(
            trace_id=resolved_trace_id,
            span_id=uuid.uuid4().hex,
            name=name,
            parent_id=parent_id,
            attributes=attributes or {},
        )

        with self._lock:
            self._spans[span.span_id] = span
            self._traces.setdefault(span.trace_id, []).append(span)

        return span

    def end_span(self, span_id: str, status: SpanStatus = SpanStatus.OK) -> None:
        """Mark a span as ended with the given status."""
        with self._lock:
            span = self._spans.get(span_id)
        if span is None:
            raise ValueError(f"Span {span_id!r} not found")
        if span.end_time is not None:
            raise ValueError(f"Span {span_id!r} already ended")
        span.end_time = time.time()
        span.status = status

    def get_span(self, span_id: str) -> Span | None:
        with self._lock:
            return self._spans.get(span_id)

    def get_trace(self, trace_id: str) -> list[Span]:
        """Return all spans belonging to a trace, ordered by start time."""
        with self._lock:
            spans = list(self._traces.get(trace_id, []))
        spans.sort(key=lambda s: s.start_time)
        return spans
