"""Immutable event store for audit trail and state replay."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """An immutable domain event representing a state change."""

    event_id: str
    event_type: str
    stream_id: str
    payload: dict[str, Any]
    occurred_at: float
    sequence: int = 0
    correlation_id: str = ""


class EventStore:
    """Append-only event store with stream-based retrieval.

    Events are globally ordered by sequence number and can be read
    by stream or globally. Thread-safe via internal lock.
    """

    def __init__(self, max_events: int = 100000) -> None:
        self._max_events = max_events
        self._events: list[DomainEvent] = []
        self._streams: dict[str, list[int]] = {}
        self._sequence: int = 0
        self._event_index: dict[str, int] = {}
        self._lock = threading.Lock()

    def append(
        self,
        event_type: str,
        stream_id: str,
        payload: dict[str, Any],
        *,
        correlation_id: str = "",
    ) -> DomainEvent:
        """Append a new event and return it."""
        with self._lock:
            self._sequence += 1
            event = DomainEvent(
                event_id=uuid.uuid4().hex,
                event_type=event_type,
                stream_id=stream_id,
                payload=dict(payload),  # Shallow copy to prevent external mutation
                occurred_at=time.time(),
                sequence=self._sequence,
                correlation_id=correlation_id,
            )
            idx = len(self._events)
            self._events.append(event)
            self._streams.setdefault(stream_id, []).append(idx)
            self._event_index[event.event_id] = idx

            if len(self._events) > self._max_events:
                self._compact()

            return event

    def read_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[DomainEvent]:
        """Read events for a specific stream, optionally after a sequence number."""
        with self._lock:
            indices = self._streams.get(stream_id, [])
            return [
                self._events[i]
                for i in indices
                if self._events[i].sequence > after_sequence
            ]

    def read_all(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        """Read all events after a sequence number, up to limit."""
        with self._lock:
            result: list[DomainEvent] = []
            for event in self._events:
                if event.sequence > after_sequence:
                    result.append(event)
                    if len(result) >= limit:
                        break
            return result

    def get_event(self, event_id: str) -> DomainEvent | None:
        """Retrieve a single event by its ID."""
        with self._lock:
            idx = self._event_index.get(event_id)
            if idx is None:
                return None
            return self._events[idx]

    def stream_ids(self) -> list[str]:
        """Return all known stream IDs."""
        with self._lock:
            return list(self._streams.keys())

    def count(self) -> int:
        """Return the total number of stored events."""
        with self._lock:
            return len(self._events)

    def _compact(self) -> None:
        """Remove oldest half of events to amortize rebuild cost."""
        if len(self._events) <= self._max_events:
            return
        keep = self._max_events // 2
        self._events = self._events[-keep:]
        # Rebuild indices
        self._streams.clear()
        self._event_index.clear()
        for i, event in enumerate(self._events):
            self._streams.setdefault(event.stream_id, []).append(i)
            self._event_index[event.event_id] = i
