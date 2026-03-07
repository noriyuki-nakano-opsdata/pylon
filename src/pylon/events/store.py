"""EventStore - In-memory event persistence and replay."""

from __future__ import annotations

from collections.abc import Callable

from pylon.events.types import Event, EventFilter


class EventStore:
    """In-memory append-only event store with query and replay."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._index: dict[str, Event] = {}

    def append(self, event: Event) -> Event:
        """Append an event to the store."""
        self._events.append(event)
        self._index[event.id] = event
        return event

    def get(self, event_id: str) -> Event | None:
        """Retrieve an event by ID."""
        return self._index.get(event_id)

    def query(
        self,
        event_filter: EventFilter,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Event]:
        """Query events matching a filter."""
        matched = [e for e in self._events if event_filter.matches(e)]
        return matched[offset : offset + limit]

    def get_by_correlation(self, correlation_id: str) -> list[Event]:
        """Get all events with a given correlation ID."""
        return [e for e in self._events if e.correlation_id == correlation_id]

    def replay(
        self,
        handler: Callable[[Event], None],
        *,
        from_timestamp: float | None = None,
        to_timestamp: float | None = None,
    ) -> int:
        """Replay events within a time range to a handler.

        Returns the number of events replayed.
        """
        count = 0
        for event in self._events:
            if from_timestamp is not None and event.timestamp < from_timestamp:
                continue
            if to_timestamp is not None and event.timestamp > to_timestamp:
                continue
            handler(event)
            count += 1
        return count

    @property
    def count(self) -> int:
        return len(self._events)
