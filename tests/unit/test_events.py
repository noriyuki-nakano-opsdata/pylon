"""Tests for Pylon event bus, handlers, and store."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from pylon.events.bus import EventBus
from pylon.events.handlers import (
    BatchHandler,
    FilteredHandler,
    FunctionHandler,
    LoggingHandler,
    RetryHandler,
)
from pylon.events.store import EventStore
from pylon.events.types import (
    AGENT_CREATED,
    AGENT_FAILED,
    AGENT_STARTED,
    AGENT_STOPPED,
    APPROVAL_GRANTED,
    APPROVAL_REQUESTED,
    KILL_SWITCH_ACTIVATED,
    TASK_ASSIGNED,
    TASK_COMPLETED,
    WORKFLOW_COMPLETED,
    WORKFLOW_FAILED,
    WORKFLOW_STARTED,
    Event,
    EventFilter,
)

# --- Event types ---

class TestEventTypes:
    def test_event_creation(self) -> None:
        event = Event(type=AGENT_CREATED, source="test", data={"name": "agent-1"})
        assert event.type == AGENT_CREATED
        assert event.source == "test"
        assert event.data["name"] == "agent-1"
        assert event.id  # uuid generated
        assert event.timestamp > 0

    def test_event_roundtrip(self) -> None:
        event = Event(
            type=WORKFLOW_STARTED,
            source="orchestrator",
            data={"wf": "main"},
            correlation_id="corr-1",
            metadata={"env": "test"},
        )
        d = event.to_dict()
        restored = Event.from_dict(d)
        assert restored.type == WORKFLOW_STARTED
        assert restored.correlation_id == "corr-1"
        assert restored.metadata["env"] == "test"

    def test_event_constants_exist(self) -> None:
        constants = [
            AGENT_CREATED, AGENT_STARTED, AGENT_STOPPED, AGENT_FAILED,
            WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED,
            TASK_ASSIGNED, TASK_COMPLETED,
            KILL_SWITCH_ACTIVATED, APPROVAL_REQUESTED, APPROVAL_GRANTED,
        ]
        assert len(constants) == 12
        assert all(isinstance(c, str) for c in constants)


class TestEventFilter:
    def test_filter_by_type(self) -> None:
        f = EventFilter(event_types=[AGENT_CREATED])
        assert f.matches(Event(type=AGENT_CREATED))
        assert not f.matches(Event(type=AGENT_FAILED))

    def test_filter_by_source(self) -> None:
        f = EventFilter(sources=["orchestrator"])
        assert f.matches(Event(type=AGENT_CREATED, source="orchestrator"))
        assert not f.matches(Event(type=AGENT_CREATED, source="agent"))

    def test_filter_by_correlation(self) -> None:
        f = EventFilter(correlation_id="corr-x")
        assert f.matches(Event(type=AGENT_CREATED, correlation_id="corr-x"))
        assert not f.matches(Event(type=AGENT_CREATED, correlation_id="corr-y"))

    def test_filter_combined(self) -> None:
        f = EventFilter(event_types=[AGENT_CREATED], sources=["orch"])
        assert f.matches(Event(type=AGENT_CREATED, source="orch"))
        assert not f.matches(Event(type=AGENT_CREATED, source="other"))
        assert not f.matches(Event(type=AGENT_FAILED, source="orch"))

    def test_empty_filter_matches_all(self) -> None:
        f = EventFilter()
        assert f.matches(Event(type=AGENT_CREATED, source="any"))


# --- EventBus ---

class TestEventBus:
    def test_basic_pubsub(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(AGENT_CREATED, lambda e: received.append(e))

        event = Event(type=AGENT_CREATED, source="test")
        count = bus.publish(event)
        assert count == 1
        assert len(received) == 1
        assert received[0].id == event.id

    def test_multiple_subscribers(self) -> None:
        bus = EventBus()
        counts = {"a": 0, "b": 0}
        bus.subscribe(AGENT_CREATED, lambda e: counts.__setitem__("a", counts["a"] + 1))
        bus.subscribe(AGENT_CREATED, lambda e: counts.__setitem__("b", counts["b"] + 1))

        bus.publish(Event(type=AGENT_CREATED))
        assert counts["a"] == 1
        assert counts["b"] == 1

    def test_type_isolation(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(AGENT_CREATED, lambda e: received.append(e))

        bus.publish(Event(type=AGENT_FAILED))
        assert len(received) == 0

    def test_wildcard_subscription(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("*", lambda e: received.append(e))

        bus.publish(Event(type=AGENT_CREATED))
        bus.publish(Event(type=WORKFLOW_STARTED))
        assert len(received) == 2

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        sub_id = bus.subscribe(AGENT_CREATED, lambda e: received.append(e))

        bus.publish(Event(type=AGENT_CREATED))
        assert len(received) == 1

        result = bus.unsubscribe(sub_id)
        assert result is True

        bus.publish(Event(type=AGENT_CREATED))
        assert len(received) == 1  # no new events

    def test_unsubscribe_unknown(self) -> None:
        bus = EventBus()
        assert bus.unsubscribe("nonexistent") is False

    def test_dead_letter_queue(self) -> None:
        bus = EventBus()

        def failing_handler(e: Event) -> None:
            raise RuntimeError("handler crashed")

        bus.subscribe(AGENT_CREATED, failing_handler)

        count = bus.publish(Event(type=AGENT_CREATED))
        assert count == 0
        assert len(bus.dead_letters) == 1
        assert "handler crashed" in bus.dead_letters[0].error

    def test_subscribe_with_filter(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        f = EventFilter(sources=["orch"])
        bus.subscribe(AGENT_CREATED, lambda e: received.append(e), event_filter=f)

        bus.publish(Event(type=AGENT_CREATED, source="orch"))
        bus.publish(Event(type=AGENT_CREATED, source="other"))
        assert len(received) == 1

    def test_subscription_count(self) -> None:
        bus = EventBus()
        bus.subscribe(AGENT_CREATED, lambda e: None)
        bus.subscribe(AGENT_FAILED, lambda e: None)
        assert bus.subscription_count == 2

    def test_dead_letter_queue_bounded(self) -> None:
        """M5: dead letter queue must not grow beyond max_dead_letters."""
        bus = EventBus(max_dead_letters=3)

        def failing_handler(e: Event) -> None:
            raise RuntimeError("boom")

        bus.subscribe(AGENT_CREATED, failing_handler)

        for _ in range(5):
            bus.publish(Event(type=AGENT_CREATED))

        assert len(bus.dead_letters) == 3

    def test_dead_letter_queue_evicts_oldest(self) -> None:
        """M5: oldest entries are evicted when max is exceeded."""
        bus = EventBus(max_dead_letters=2)

        def failing_handler(e: Event) -> None:
            raise RuntimeError(e.data.get("i", ""))

        bus.subscribe(AGENT_CREATED, failing_handler)

        for i in range(4):
            bus.publish(Event(type=AGENT_CREATED, data={"i": str(i)}))

        dl = bus.dead_letters
        assert len(dl) == 2
        assert dl[0].error == "2"
        assert dl[1].error == "3"

    @pytest.mark.asyncio
    async def test_publish_async(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(AGENT_CREATED, lambda e: received.append(e))

        count = await bus.publish_async(Event(type=AGENT_CREATED))
        assert count == 1
        assert len(received) == 1

    def test_unsubscribe_unknown_handler_is_noop(self) -> None:
        """Unsubscribing a handler that was never subscribed doesn't raise."""
        bus = EventBus()
        result = bus.unsubscribe("never-existed-id")
        assert result is False
        # Ensure bus still works normally after
        received: list[Event] = []
        bus.subscribe(AGENT_CREATED, lambda e: received.append(e))
        bus.publish(Event(type=AGENT_CREATED))
        assert len(received) == 1

    def test_publish_no_subscribers_goes_to_dead_letter(self) -> None:
        """Publishing event with no subscribers returns 0 and no dead letters
        (dead letters are for handler failures, not missing subscribers)."""
        bus = EventBus()
        count = bus.publish(Event(type=AGENT_CREATED))
        assert count == 0
        assert len(bus.dead_letters) == 0

    def test_wildcard_subscription_receives_all_events(self) -> None:
        """Wildcard subscriber receives events from multiple topics."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("*", lambda e: received.append(e))

        bus.publish(Event(type=AGENT_CREATED))
        bus.publish(Event(type=WORKFLOW_STARTED))
        bus.publish(Event(type=TASK_COMPLETED))
        assert len(received) == 3
        assert {e.type for e in received} == {AGENT_CREATED, WORKFLOW_STARTED, TASK_COMPLETED}

    def test_handler_exception_doesnt_break_other_handlers(self) -> None:
        """If one handler raises, other handlers for same event still execute."""
        bus = EventBus()
        received: list[str] = []

        bus.subscribe(AGENT_CREATED, lambda e: received.append("first"))

        def failing(e: Event) -> None:
            raise RuntimeError("broken handler")

        bus.subscribe(AGENT_CREATED, failing)
        bus.subscribe(AGENT_CREATED, lambda e: received.append("third"))

        count = bus.publish(Event(type=AGENT_CREATED))
        # Two handlers succeeded, one failed
        assert count == 2
        assert received == ["first", "third"]
        assert len(bus.dead_letters) == 1

    def test_subscribe_and_publish_multiple_handlers(self) -> None:
        """Multiple handlers for same event all fire."""
        bus = EventBus()
        results: list[int] = []
        bus.subscribe(AGENT_CREATED, lambda e: results.append(1))
        bus.subscribe(AGENT_CREATED, lambda e: results.append(2))
        bus.subscribe(AGENT_CREATED, lambda e: results.append(3))

        count = bus.publish(Event(type=AGENT_CREATED))
        assert count == 3
        assert results == [1, 2, 3]


# --- Handlers ---

class TestFunctionHandler:
    def test_wraps_function(self) -> None:
        events: list[Event] = []
        handler = FunctionHandler(lambda e: events.append(e))
        handler.handle(Event(type=AGENT_CREATED))
        assert len(events) == 1


class TestFilteredHandler:
    def test_filters_events(self) -> None:
        events: list[Event] = []
        inner = FunctionHandler(lambda e: events.append(e))
        handler = FilteredHandler(inner, EventFilter(event_types=[AGENT_CREATED]))

        handler.handle(Event(type=AGENT_CREATED))
        handler.handle(Event(type=AGENT_FAILED))
        assert len(events) == 1


class TestRetryHandler:
    def test_succeeds_first_try(self) -> None:
        events: list[Event] = []
        inner = FunctionHandler(lambda e: events.append(e))
        handler = RetryHandler(inner, max_retries=3, base_delay=0.001)

        handler.handle(Event(type=AGENT_CREATED))
        assert len(events) == 1
        assert handler.attempts == [1]

    def test_retries_on_failure(self) -> None:
        call_count = 0

        def flaky(e: Event) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("flaky")

        inner = FunctionHandler(flaky)
        handler = RetryHandler(inner, max_retries=3, base_delay=0.001)
        handler.handle(Event(type=AGENT_CREATED))
        assert call_count == 3
        assert handler.attempts == [3]

    def test_exhausts_retries(self) -> None:
        inner = FunctionHandler(lambda e: (_ for _ in ()).throw(RuntimeError("always fails")))
        handler = RetryHandler(inner, max_retries=2, base_delay=0.001)

        with pytest.raises(RuntimeError, match="always fails"):
            handler.handle(Event(type=AGENT_CREATED))

    def test_exponential_backoff(self) -> None:
        handler = RetryHandler(
            FunctionHandler(lambda e: None),
            backoff_strategy="exponential",
            base_delay=0.1,
        )
        assert handler._compute_delay(1) == pytest.approx(0.1)
        assert handler._compute_delay(2) == pytest.approx(0.2)
        assert handler._compute_delay(3) == pytest.approx(0.4)


class TestBatchHandler:
    def test_flushes_at_batch_size(self) -> None:
        batches: list[list[Event]] = []
        handler = BatchHandler(lambda b: batches.append(b), batch_size=3)

        for i in range(3):
            handler.handle(Event(type=AGENT_CREATED, data={"i": i}))

        assert len(batches) == 1
        assert len(batches[0]) == 3
        assert handler.pending == 0

    def test_partial_batch_not_flushed(self) -> None:
        batches: list[list[Event]] = []
        handler = BatchHandler(lambda b: batches.append(b), batch_size=10, flush_interval=9999)

        handler.handle(Event(type=AGENT_CREATED))
        assert len(batches) == 0
        assert handler.pending == 1

    def test_manual_flush(self) -> None:
        batches: list[list[Event]] = []
        handler = BatchHandler(lambda b: batches.append(b), batch_size=10)

        handler.handle(Event(type=AGENT_CREATED))
        handler.flush()
        assert len(batches) == 1
        assert handler.pending == 0


class TestLoggingHandler:
    def test_logs_event(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging
        with caplog.at_level(logging.INFO, logger="pylon.events"):
            handler = LoggingHandler()
            handler.handle(Event(type=AGENT_CREATED, source="test", id="ev-1"))
        assert "agent.created" in caplog.text
        assert "ev-1" in caplog.text


# --- EventStore ---

class TestEventStore:
    def test_append_and_get(self) -> None:
        store = EventStore()
        event = Event(type=AGENT_CREATED, source="test")
        store.append(event)

        retrieved = store.get(event.id)
        assert retrieved is not None
        assert retrieved.id == event.id

    def test_get_nonexistent(self) -> None:
        store = EventStore()
        assert store.get("nope") is None

    def test_query_by_type(self) -> None:
        store = EventStore()
        store.append(Event(type=AGENT_CREATED))
        store.append(Event(type=AGENT_FAILED))
        store.append(Event(type=AGENT_CREATED))

        results = store.query(EventFilter(event_types=[AGENT_CREATED]))
        assert len(results) == 2

    def test_query_with_limit_offset(self) -> None:
        store = EventStore()
        for i in range(5):
            store.append(Event(type=AGENT_CREATED, data={"i": i}))

        results = store.query(EventFilter(event_types=[AGENT_CREATED]), limit=2, offset=1)
        assert len(results) == 2
        assert results[0].data["i"] == 1
        assert results[1].data["i"] == 2

    def test_get_by_correlation(self) -> None:
        store = EventStore()
        store.append(Event(type=AGENT_CREATED, correlation_id="corr-1"))
        store.append(Event(type=AGENT_STARTED, correlation_id="corr-1"))
        store.append(Event(type=AGENT_CREATED, correlation_id="corr-2"))

        results = store.get_by_correlation("corr-1")
        assert len(results) == 2

    def test_replay(self) -> None:
        store = EventStore()
        t0 = time.time()
        store.append(Event(type=AGENT_CREATED, timestamp=t0 - 10))
        store.append(Event(type=AGENT_STARTED, timestamp=t0 - 5))
        store.append(Event(type=AGENT_STOPPED, timestamp=t0))

        replayed: list[Event] = []
        count = store.replay(lambda e: replayed.append(e), from_timestamp=t0 - 7)
        assert count == 2
        assert replayed[0].type == AGENT_STARTED

    def test_replay_full(self) -> None:
        store = EventStore()
        for _ in range(3):
            store.append(Event(type=AGENT_CREATED))

        replayed: list[Event] = []
        count = store.replay(lambda e: replayed.append(e))
        assert count == 3

    def test_replay_time_range(self) -> None:
        store = EventStore()
        t0 = time.time()
        store.append(Event(type=AGENT_CREATED, timestamp=t0 - 20))
        store.append(Event(type=AGENT_STARTED, timestamp=t0 - 10))
        store.append(Event(type=AGENT_STOPPED, timestamp=t0))

        replayed: list[Event] = []
        count = store.replay(
            lambda e: replayed.append(e),
            from_timestamp=t0 - 15,
            to_timestamp=t0 - 5,
        )
        assert count == 1
        assert replayed[0].type == AGENT_STARTED

    def test_count(self) -> None:
        store = EventStore()
        assert store.count == 0
        store.append(Event(type=AGENT_CREATED))
        store.append(Event(type=AGENT_FAILED))
        assert store.count == 2


# --- Integration ---

class TestBusStoreIntegration:
    def test_bus_stores_events(self) -> None:
        bus = EventBus()
        store = EventStore()

        bus.subscribe("*", lambda e: store.append(e))

        bus.publish(Event(type=AGENT_CREATED, source="orch", correlation_id="wf-1"))
        bus.publish(Event(type=AGENT_STARTED, source="orch", correlation_id="wf-1"))
        bus.publish(Event(type=WORKFLOW_COMPLETED, source="orch", correlation_id="wf-1"))

        assert store.count == 3
        correlated = store.get_by_correlation("wf-1")
        assert len(correlated) == 3


# --- Thread Safety ---

class TestEventBusThreadSafety:
    def test_concurrent_publish_and_subscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []
        lock = threading.Lock()

        def handler(e: Event) -> None:
            with lock:
                received.append(e)

        bus.subscribe(AGENT_CREATED, handler)
        errors: list[Exception] = []

        def publisher() -> None:
            try:
                for _ in range(20):
                    bus.publish(Event(type=AGENT_CREATED, source="thread"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publisher) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(received) == 100  # 5 threads * 20 publishes
