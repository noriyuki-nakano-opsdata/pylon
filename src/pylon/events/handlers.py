"""Event handler base classes and utilities."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

from pylon.events.types import Event, EventFilter

logger = logging.getLogger(__name__)


class EventHandler(Protocol):
    """Protocol for event handlers."""

    def handle(self, event: Event) -> None: ...


class FunctionHandler:
    """Wraps a plain function as an EventHandler."""

    def __init__(self, fn: Callable[[Event], None]) -> None:
        self._fn = fn

    def handle(self, event: Event) -> None:
        self._fn(event)


class FilteredHandler:
    """Handler that only processes events matching a filter."""

    def __init__(self, handler: EventHandler, event_filter: EventFilter) -> None:
        self._handler = handler
        self._filter = event_filter

    @property
    def filter(self) -> EventFilter:
        return self._filter

    def handle(self, event: Event) -> None:
        if self._filter.matches(event):
            self._handler.handle(event)


class RetryHandler:
    """Handler that retries on failure with configurable backoff.

    backoff_strategy: 'linear' or 'exponential'
    """

    def __init__(
        self,
        handler: EventHandler,
        *,
        max_retries: int = 3,
        backoff_strategy: str = "linear",
        base_delay: float = 0.01,
    ) -> None:
        self._handler = handler
        self._max_retries = max_retries
        self._backoff_strategy = backoff_strategy
        self._base_delay = base_delay
        self.attempts: list[int] = []  # track attempt counts per handle call

    def handle(self, event: Event) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._handler.handle(event)
                self.attempts.append(attempt)
                return
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._compute_delay(attempt)
                    time.sleep(delay)
        self.attempts.append(self._max_retries)
        raise last_error  # type: ignore[misc]

    def _compute_delay(self, attempt: int) -> float:
        if self._backoff_strategy == "exponential":
            return self._base_delay * (2 ** (attempt - 1))
        return self._base_delay * attempt


class BatchHandler:
    """Accumulates events and processes them in batches."""

    def __init__(
        self,
        handler: Callable[[list[Event]], None],
        *,
        batch_size: int = 10,
        flush_interval: float = 1.0,
    ) -> None:
        self._handler = handler
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[Event] = []
        self._last_flush: float = time.time()

    def handle(self, event: Event) -> None:
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            self.flush()
        elif time.time() - self._last_flush >= self._flush_interval:
            self.flush()

    def flush(self) -> None:
        if self._buffer:
            batch = self._buffer[:]
            self._buffer.clear()
            self._last_flush = time.time()
            self._handler(batch)

    @property
    def pending(self) -> int:
        return len(self._buffer)


class LoggingHandler:
    """Logs all events to the Python logger."""

    def __init__(self, logger_name: str = "pylon.events") -> None:
        self._logger = logging.getLogger(logger_name)

    def handle(self, event: Event) -> None:
        self._logger.info(
            "Event: type=%s source=%s id=%s",
            event.type,
            event.source,
            event.id,
        )
