from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pylon.observability.otel import OpenTelemetryBridge


class SpanStatus(Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TraceContext:
    """Serializable trace context used for propagation and span parenting."""

    trace_id: str
    span_id: str | None = None
    trace_flags: str = "01"
    is_remote: bool = False
    native_context: Any | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_span(cls, span: Span) -> TraceContext:
        return cls(
            trace_id=span.trace_id,
            span_id=span.span_id,
            trace_flags=span.trace_flags,
            native_context=span.native_context,
        )

    @classmethod
    def from_traceparent(cls, value: str) -> TraceContext | None:
        parts = value.strip().split("-")
        if len(parts) != 4:
            return None
        version, trace_id, span_id, trace_flags = parts
        if version != "00":
            return None
        if not _is_hex(trace_id, length=32) or trace_id == "0" * 32:
            return None
        if not _is_hex(span_id, length=16) or span_id == "0" * 16:
            return None
        if not _is_hex(trace_flags, length=2):
            return None
        return cls(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=trace_flags,
            is_remote=True,
        )

    def to_traceparent(self) -> str | None:
        if self.span_id is None:
            return None
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"


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
    trace_flags: str = "01"
    native_span: Any | None = field(default=None, repr=False, compare=False)
    native_context: Any | None = field(default=None, repr=False, compare=False)

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


_CURRENT_TRACE_CONTEXT: contextvars.ContextVar[tuple[str, TraceContext] | None] = (
    contextvars.ContextVar("pylon_current_trace_context", default=None)
)


class _SpanScope:
    def __init__(self, tracer: Tracer, span: Span) -> None:
        self._tracer = tracer
        self._span = span
        self._context_token: contextvars.Token[tuple[str, TraceContext] | None] | None = None
        self._native_scope: Any | None = None

    def __enter__(self) -> Span:
        self._context_token = self._tracer._bind_context(TraceContext.from_span(self._span))
        self._native_scope = self._tracer._enter_native_scope(self._span)
        if self._native_scope is not None:
            self._native_scope.__enter__()
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self._span.end_time is None:
                if exc is not None:
                    self._span.set_attribute("error.type", exc.__class__.__name__)
                    self._span.add_event("exception", {"message": str(exc)})
                self._tracer.end_span(
                    self._span.span_id,
                    status=SpanStatus.ERROR if exc is not None else SpanStatus.OK,
                )
        finally:
            if self._native_scope is not None:
                self._native_scope.__exit__(exc_type, exc, tb)
            if self._context_token is not None:
                _CURRENT_TRACE_CONTEXT.reset(self._context_token)


class Tracer:
    """Distributed tracing with optional OpenTelemetry export integration."""

    def __init__(
        self,
        *,
        bridge: OpenTelemetryBridge | None = None,
    ) -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        self._instance_id = uuid.uuid4().hex
        self._traces: dict[str, list[Span]] = {}
        self._spans: dict[str, Span] = {}

    def start_span(
        self,
        name: str,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_context: TraceContext | None = None,
    ) -> Span:
        """Create and register a new span."""
        parent = None
        resolved_parent = parent_context

        if resolved_parent is None and parent_id is not None:
            with self._lock:
                parent = self._spans.get(parent_id)
            if parent is None:
                raise ValueError(f"Parent span {parent_id!r} not found")
            resolved_parent = TraceContext.from_span(parent)

        if resolved_parent is None and trace_id is None:
            resolved_parent = self.current_context()

        resolved_trace_id = trace_id or (
            resolved_parent.trace_id if resolved_parent is not None else None
        )
        parent_span_id = (
            resolved_parent.span_id
            if resolved_parent is not None and resolved_parent.span_id
            else parent_id
        )

        native_span = None
        native_context = None
        trace_flags = resolved_parent.trace_flags if resolved_parent is not None else "01"

        if self._bridge is not None:
            bridge_parent_context = (
                resolved_parent.native_context
                if resolved_parent is not None and resolved_parent.native_context is not None
                else None
            )
            if bridge_parent_context is None and parent is not None and parent.native_span is not None:
                bridge_parent_context = self._bridge.context_from_span(parent.native_span)
            if bridge_parent_context is None and resolved_parent is not None:
                bridge_parent_context = self._bridge.remote_parent_context(
                    trace_id=resolved_parent.trace_id,
                    span_id=resolved_parent.span_id,
                    trace_flags=resolved_parent.trace_flags,
                )
            native_span, resolved_trace_id, span_id, trace_flags = self._bridge.start_span(
                name,
                parent_context=bridge_parent_context,
                attributes=attributes or {},
            )
            native_context = self._bridge.context_from_span(native_span)
        else:
            if resolved_trace_id is None:
                resolved_trace_id = uuid.uuid4().hex
            span_id = uuid.uuid4().hex[:16]

        span = Span(
            trace_id=resolved_trace_id or uuid.uuid4().hex,
            span_id=span_id,
            name=name,
            parent_id=parent_span_id,
            attributes=dict(attributes or {}),
            trace_flags=trace_flags,
            native_span=native_span,
            native_context=native_context,
        )

        with self._lock:
            self._spans[span.span_id] = span
            self._traces.setdefault(span.trace_id, []).append(span)

        return span

    def start_as_current_span(
        self,
        name: str,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_context: TraceContext | None = None,
    ) -> _SpanScope:
        """Create a span and bind it as the current span for the scope."""
        return _SpanScope(
            self,
            self.start_span(
                name,
                parent_id=parent_id,
                attributes=attributes,
                trace_id=trace_id,
                parent_context=parent_context,
            ),
        )

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
        if self._bridge is not None and span.native_span is not None:
            self._bridge.end_span(
                span.native_span,
                attributes=span.attributes,
                events=span.events,
                status=status.value,
            )

    def get_span(self, span_id: str) -> Span | None:
        with self._lock:
            return self._spans.get(span_id)

    def get_trace(self, trace_id: str) -> list[Span]:
        """Return all spans belonging to a trace, ordered by start time."""
        with self._lock:
            spans = list(self._traces.get(trace_id, []))
        spans.sort(key=lambda s: s.start_time)
        return spans

    def current_context(self) -> TraceContext | None:
        current = _CURRENT_TRACE_CONTEXT.get()
        if current is None or current[0] != self._instance_id:
            return None
        return current[1]

    def current_span(self) -> Span | None:
        context = self.current_context()
        if context is None or context.span_id is None:
            return None
        return self.get_span(context.span_id)

    def extract_context(
        self,
        headers: Mapping[str, str],
        *,
        trace_id_header: str = "x-trace-id",
        span_id_header: str = "x-span-id",
    ) -> TraceContext | None:
        normalized = {
            str(key).lower(): str(value)
            for key, value in headers.items()
        }
        if self._bridge is not None:
            extracted = self._bridge.extract(normalized)
            if extracted is not None:
                return TraceContext(
                    trace_id=extracted.trace_id,
                    span_id=extracted.span_id,
                    trace_flags=extracted.trace_flags,
                    is_remote=True,
                    native_context=extracted.context,
                )

        traceparent = normalized.get("traceparent")
        if traceparent:
            parsed = TraceContext.from_traceparent(traceparent)
            if parsed is not None:
                return parsed

        trace_id = normalized.get(trace_id_header.lower())
        if not trace_id:
            return None
        span_id = normalized.get(span_id_header.lower())
        return TraceContext(
            trace_id=trace_id,
            span_id=span_id or None,
            is_remote=True,
        )

    def format_traceparent(self, context: TraceContext | None = None) -> str | None:
        effective = context or self.current_context()
        if effective is None:
            return None
        return effective.to_traceparent()

    def _bind_context(
        self,
        context: TraceContext,
    ) -> contextvars.Token[tuple[str, TraceContext] | None]:
        return _CURRENT_TRACE_CONTEXT.set((self._instance_id, context))

    def _enter_native_scope(self, span: Span) -> Any | None:
        if self._bridge is None or span.native_span is None:
            return None
        return self._bridge.use_span(span.native_span)


def _is_hex(value: str, *, length: int) -> bool:
    if len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
