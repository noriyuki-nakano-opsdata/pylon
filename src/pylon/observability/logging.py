from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol, runtime_checkable


class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


LEVEL_NAMES: dict[int, str] = {v.value: v.name for v in LogLevel}


@dataclass
class LogEntry:
    """A single structured log record."""

    timestamp: float
    level: LogLevel
    message: str
    context: dict[str, Any] = field(default_factory=dict)


_sink_logger = logging.getLogger(__name__)


@runtime_checkable
class LogSink(Protocol):
    """Protocol for pluggable log sinks."""

    def emit(self, entry: LogEntry) -> None: ...


class StructuredLogger:
    """Structured logger with context propagation.

    Log entries are stored in a bounded deque and can be filtered by level on
    retrieval.  A child logger created with :meth:`with_context` inherits the
    parent's stored context and shares the same log storage.
    """

    def __init__(
        self,
        *,
        context: dict[str, Any] | None = None,
        max_entries: int = 10_000,
        _entries: deque[LogEntry] | None = None,
        _lock: threading.Lock | None = None,
        _sinks: list[LogSink] | None = None,
    ) -> None:
        if _entries is None and max_entries <= 0:
            raise ValueError(f"max_entries must be positive, got {max_entries}")
        self._base_context: dict[str, Any] = dict(context) if context else {}
        # Shared mutable state -- child loggers point to the same deque/lock/sinks.
        self._entries: deque[LogEntry] = (
            _entries if _entries is not None else deque(maxlen=max_entries)
        )
        self._lock = _lock or threading.Lock()
        self._sinks: list[LogSink] = _sinks if _sinks is not None else []

    def log(self, level: LogLevel, message: str, **context: Any) -> LogEntry:
        """Record a structured log entry.

        Extra keyword arguments are merged with the logger's base context.
        """
        merged = {**self._base_context, **context}
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            message=message,
            context=merged,
        )
        with self._lock:
            self._entries.append(entry)
            for sink in self._sinks:
                try:
                    sink.emit(entry)
                except Exception:
                    _sink_logger.exception("LogSink.emit failed")
        return entry

    # convenience shortcuts
    def debug(self, message: str, **ctx: Any) -> LogEntry:
        return self.log(LogLevel.DEBUG, message, **ctx)

    def info(self, message: str, **ctx: Any) -> LogEntry:
        return self.log(LogLevel.INFO, message, **ctx)

    def warning(self, message: str, **ctx: Any) -> LogEntry:
        return self.log(LogLevel.WARNING, message, **ctx)

    def error(self, message: str, **ctx: Any) -> LogEntry:
        return self.log(LogLevel.ERROR, message, **ctx)

    def critical(self, message: str, **ctx: Any) -> LogEntry:
        return self.log(LogLevel.CRITICAL, message, **ctx)

    def register_sink(self, sink: LogSink) -> None:
        """Register a pluggable sink that receives every emitted log entry."""
        with self._lock:
            self._sinks.append(sink)

    def with_context(self, **ctx: Any) -> StructuredLogger:
        """Return a new logger that inherits this logger's context plus *ctx*.

        The child shares the same log entry storage so :meth:`get_logs` on
        either logger sees all entries.
        """
        merged = {**self._base_context, **ctx}
        return StructuredLogger(
            context=merged,
            _entries=self._entries,
            _lock=self._lock,
            _sinks=self._sinks,
        )

    def get_logs(
        self,
        level: LogLevel | None = None,
        limit: int | None = None,
    ) -> list[LogEntry]:
        """Return recent log entries, optionally filtered by minimum *level*.

        Entries are returned newest-first. *limit* caps the number returned.
        """
        with self._lock:
            entries = list(self._entries)
        if level is not None:
            entries = [e for e in entries if e.level >= level]
        entries.reverse()
        if limit is not None:
            entries = entries[:limit]
        return entries
