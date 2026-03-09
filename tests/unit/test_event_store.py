"""Tests for pylon.intelligence.event_store."""

from pylon.intelligence.event_store import EventStore


class TestEventStore:
    def test_append_event(self) -> None:
        store = EventStore()
        event = store.append("workflow.started", "wf-1", {"name": "test"})
        assert event.event_type == "workflow.started"
        assert event.stream_id == "wf-1"
        assert event.payload == {"name": "test"}
        assert event.sequence == 1
        assert store.count() == 1

    def test_read_stream(self) -> None:
        store = EventStore()
        store.append("workflow.started", "wf-1", {"step": 1})
        store.append("model.routed", "wf-2", {"step": 2})
        store.append("workflow.completed", "wf-1", {"step": 3})

        events = store.read_stream("wf-1")
        assert len(events) == 2
        assert events[0].event_type == "workflow.started"
        assert events[1].event_type == "workflow.completed"

    def test_read_stream_after_sequence(self) -> None:
        store = EventStore()
        e1 = store.append("a", "s1", {})
        store.append("b", "s1", {})
        store.append("c", "s1", {})

        events = store.read_stream("s1", after_sequence=e1.sequence)
        assert len(events) == 2
        assert events[0].event_type == "b"
        assert events[1].event_type == "c"

    def test_read_all(self) -> None:
        store = EventStore()
        for i in range(10):
            store.append(f"event-{i}", f"stream-{i % 3}", {"i": i})

        events = store.read_all(limit=5)
        assert len(events) == 5
        assert events[0].sequence == 1
        assert events[4].sequence == 5

        events_after = store.read_all(after_sequence=8)
        assert len(events_after) == 2
        assert events_after[0].sequence == 9

    def test_stream_ids(self) -> None:
        store = EventStore()
        store.append("a", "stream-a", {})
        store.append("b", "stream-b", {})
        store.append("c", "stream-a", {})

        ids = store.stream_ids()
        assert set(ids) == {"stream-a", "stream-b"}
