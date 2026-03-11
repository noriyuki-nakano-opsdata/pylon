"""EventBus - In-memory pub/sub event bus."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pylon.events.types import Event, EventFilter


@dataclass
class _Subscription:
    id: str
    event_type: str  # "*" for wildcard
    handler: Callable[[Event], None]
    event_filter: EventFilter | None = None


@dataclass
class DeadLetterEntry:
    """Record of a failed handler invocation."""

    event: Event
    subscription_id: str
    error: str


class EventBus:
    """In-memory pub/sub event bus.

    Designed for replacement with NATS or similar broker.
    """

    def __init__(self, max_dead_letters: int = 10000) -> None:
        self._subscriptions: dict[str, _Subscription] = {}
        self._dead_letters: deque[DeadLetterEntry] = deque(maxlen=max_dead_letters)
        self._lock = threading.Lock()

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], None],
        event_filter: EventFilter | None = None,
    ) -> str:
        """Subscribe to an event type. Use '*' for all events."""
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._subscriptions[sub_id] = _Subscription(
                id=sub_id,
                event_type=event_type,
                handler=handler,
                event_filter=event_filter,
            )
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription. Returns True if it existed."""
        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def publish(self, event: Event) -> int:
        """Publish an event synchronously. Returns count of notified handlers."""
        with self._lock:
            subs = list(self._subscriptions.values())
        count = 0
        for sub in subs:
            if not self._matches(sub, event):
                continue
            try:
                result = sub.handler(event)
                if asyncio.iscoroutine(result):
                    result.close()  # Cannot await in sync publish; prevent leak
                    raise TypeError(
                        "Async handler registered for sync publish(). "
                        "Use publish_async() instead."
                    )
                count += 1
            except Exception as e:
                with self._lock:
                    self._dead_letters.append(
                        DeadLetterEntry(
                            event=event,
                            subscription_id=sub.id,
                            error=str(e),
                        )
                    )
        return count

    async def publish_async(self, event: Event) -> int:
        """Publish an event, running handlers in the event loop."""
        with self._lock:
            subs = list(self._subscriptions.values())
        count = 0
        for sub in subs:
            if not self._matches(sub, event):
                continue
            try:
                result = sub.handler(event)
                if asyncio.iscoroutine(result):
                    await result
                count += 1
            except Exception as e:
                with self._lock:
                    self._dead_letters.append(
                        DeadLetterEntry(
                            event=event,
                            subscription_id=sub.id,
                            error=str(e),
                        )
                    )
        return count

    @property
    def dead_letters(self) -> list[DeadLetterEntry]:
        with self._lock:
            return list(self._dead_letters)

    @property
    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def _matches(self, sub: _Subscription, event: Event) -> bool:
        if sub.event_type != "*" and sub.event_type != event.type:
            return False
        if sub.event_filter and not sub.event_filter.matches(event):
            return False
        return True
