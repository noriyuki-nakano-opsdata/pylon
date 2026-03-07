"""Tests for state management module."""

from __future__ import annotations

import time
import unittest

from pylon.state import (
    DiffEntry,
    DiffOp,
    InvalidTransitionError,
    SnapshotManager,
    StateMachine,
    StateMachineConfig,
    StateOp,
    StateOpType,
    StateStore,
    apply_diff,
    compute_diff,
)

# --- StateStore ---

class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.store = StateStore()

    def test_set_and_get(self):
        self.store.set("key1", "value1")
        self.assertEqual(self.store.get("key1"), "value1")

    def test_get_default(self):
        self.assertIsNone(self.store.get("missing"))
        self.assertEqual(self.store.get("missing", 42), 42)

    def test_delete(self):
        self.store.set("key1", "value1")
        self.assertTrue(self.store.delete("key1"))
        self.assertIsNone(self.store.get("key1"))

    def test_delete_missing(self):
        self.assertFalse(self.store.delete("missing"))

    def test_has(self):
        self.store.set("key1", "value1")
        self.assertTrue(self.store.has("key1"))
        self.assertFalse(self.store.has("missing"))

    def test_keys(self):
        self.store.set("a", 1)
        self.store.set("b", 2)
        self.assertEqual(sorted(self.store.keys()), ["a", "b"])

    def test_get_namespace(self):
        self.store.set("ns1.key1", "v1")
        self.store.set("ns1.key2", "v2")
        self.store.set("ns2.key1", "v3")
        ns = self.store.get_namespace("ns1")
        self.assertEqual(ns, {"ns1.key1": "v1", "ns1.key2": "v2"})

    def test_ttl_expiry(self):
        self.store.set("temp", "data", ttl=0.05)
        self.assertEqual(self.store.get("temp"), "data")
        time.sleep(0.06)
        self.assertIsNone(self.store.get("temp"))

    def test_ttl_not_expired(self):
        self.store.set("temp", "data", ttl=10)
        self.assertEqual(self.store.get("temp"), "data")

    def test_transaction_set(self):
        ops = [
            StateOp(op=StateOpType.SET, key="a", value=1),
            StateOp(op=StateOpType.SET, key="b", value=2),
        ]
        self.assertTrue(self.store.transaction(ops))
        self.assertEqual(self.store.get("a"), 1)
        self.assertEqual(self.store.get("b"), 2)

    def test_transaction_delete(self):
        self.store.set("x", 10)
        ops = [StateOp(op=StateOpType.DELETE, key="x")]
        self.assertTrue(self.store.transaction(ops))
        self.assertIsNone(self.store.get("x"))

    def test_transaction_increment(self):
        self.store.set("counter", 5)
        ops = [StateOp(op=StateOpType.INCREMENT, key="counter", value=3)]
        self.assertTrue(self.store.transaction(ops))
        self.assertEqual(self.store.get("counter"), 8)

    def test_transaction_increment_new_key(self):
        ops = [StateOp(op=StateOpType.INCREMENT, key="new_counter", value=1)]
        self.assertTrue(self.store.transaction(ops))
        self.assertEqual(self.store.get("new_counter"), 1)

    def test_transaction_rollback(self):
        self.store.set("keep", "original")
        ops = [
            StateOp(op=StateOpType.SET, key="keep", value="changed"),
            StateOp(op=StateOpType.INCREMENT, key="keep", value=1),  # will fail: string
        ]
        self.assertFalse(self.store.transaction(ops))
        self.assertEqual(self.store.get("keep"), "original")

    def test_on_change_notification(self):
        changes = []
        self.store.on_change("test.*", lambda k, old, new: changes.append((k, old, new)))
        self.store.set("test.key", "val")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], ("test.key", None, "val"))

    def test_on_change_unsubscribe(self):
        changes = []
        unsub = self.store.on_change("*", lambda k, old, new: changes.append(k))
        self.store.set("a", 1)
        unsub()
        self.store.set("b", 2)
        self.assertEqual(len(changes), 1)

    def test_to_dict_and_load(self):
        self.store.set("x", 1)
        self.store.set("y", 2)
        data = self.store.to_dict()
        new_store = StateStore()
        new_store.load(data)
        self.assertEqual(new_store.get("x"), 1)
        self.assertEqual(new_store.get("y"), 2)


# --- StateDiff ---

class TestStateDiff(unittest.TestCase):
    def test_no_changes(self):
        diff = compute_diff({"a": 1}, {"a": 1})
        self.assertEqual(len(diff), 0)

    def test_add(self):
        diff = compute_diff({}, {"a": 1})
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0].op, DiffOp.ADD)
        self.assertEqual(diff[0].new_value, 1)

    def test_delete(self):
        diff = compute_diff({"a": 1}, {})
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0].op, DiffOp.DELETE)
        self.assertEqual(diff[0].old_value, 1)

    def test_modify(self):
        diff = compute_diff({"a": 1}, {"a": 2})
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0].op, DiffOp.MODIFY)

    def test_nested_diff(self):
        old = {"config": {"debug": True, "port": 8080}}
        new = {"config": {"debug": False, "port": 8080, "host": "0.0.0.0"}}
        diff = compute_diff(old, new)
        keys = {e.key for e in diff}
        self.assertIn("config.debug", keys)
        self.assertIn("config.host", keys)
        self.assertNotIn("config.port", keys)

    def test_apply_diff(self):
        old = {"a": 1, "b": 2}
        diff = [
            DiffEntry(key="a", op=DiffOp.MODIFY, old_value=1, new_value=10),
            DiffEntry(key="b", op=DiffOp.DELETE, old_value=2),
            DiffEntry(key="c", op=DiffOp.ADD, new_value=3),
        ]
        result = apply_diff(old, diff)
        self.assertEqual(result, {"a": 10, "c": 3})

    def test_apply_nested_diff(self):
        old = {"x": {"y": 1}}
        diff = [DiffEntry(key="x.y", op=DiffOp.MODIFY, old_value=1, new_value=99)]
        result = apply_diff(old, diff)
        self.assertEqual(result["x"]["y"], 99)

    def test_roundtrip(self):
        old = {"a": 1, "b": {"c": 2, "d": 3}}
        new = {"a": 1, "b": {"c": 5}, "e": 10}
        diff = compute_diff(old, new)
        result = apply_diff(old, diff)
        self.assertEqual(result, new)


# --- SnapshotManager ---

class TestSnapshotManager(unittest.TestCase):
    def setUp(self):
        self.mgr = SnapshotManager()
        self.store = StateStore()

    def test_create_snapshot(self):
        self.store.set("key", "val")
        snap = self.mgr.create_snapshot(self.store, label="v1")
        self.assertEqual(snap.label, "v1")
        self.assertTrue(snap.size_bytes > 0)

    def test_restore_snapshot(self):
        self.store.set("a", 1)
        snap = self.mgr.create_snapshot(self.store, "snap1")
        self.store.set("a", 999)
        restored = self.mgr.restore_snapshot(snap.id)
        self.assertEqual(restored.get("a"), 1)

    def test_list_snapshots(self):
        self.store.set("x", 1)
        self.mgr.create_snapshot(self.store, "s1")
        self.store.set("x", 2)
        self.mgr.create_snapshot(self.store, "s2")
        metas = self.mgr.list_snapshots()
        self.assertEqual(len(metas), 2)
        self.assertEqual(metas[0].label, "s1")
        self.assertEqual(metas[1].label, "s2")

    def test_diff_based_snapshot(self):
        self.store.set("a", 1)
        self.mgr.create_snapshot(self.store, "base")
        self.store.set("b", 2)
        snap2 = self.mgr.create_snapshot(self.store, "diff")
        self.assertTrue(snap2.meta().is_diff)
        restored = self.mgr.restore_snapshot(snap2.id)
        self.assertEqual(restored.get("a"), 1)
        self.assertEqual(restored.get("b"), 2)

    def test_restore_nonexistent(self):
        with self.assertRaises(KeyError):
            self.mgr.restore_snapshot("bad-id")

    def test_delete_snapshot(self):
        self.store.set("x", 1)
        snap = self.mgr.create_snapshot(self.store, "del")
        self.assertTrue(self.mgr.delete_snapshot(snap.id))
        self.assertEqual(len(self.mgr.list_snapshots()), 0)

    def test_delete_parent_materializes_children(self):
        self.store.set("a", 1)
        base = self.mgr.create_snapshot(self.store, "base")
        self.store.set("b", 2)
        child = self.mgr.create_snapshot(self.store, "child")
        self.mgr.delete_snapshot(base.id)
        # Child should still be restorable
        restored = self.mgr.restore_snapshot(child.id)
        self.assertEqual(restored.get("a"), 1)
        self.assertEqual(restored.get("b"), 2)


# --- StateMachine ---

class TestStateMachine(unittest.TestCase):
    def _make_traffic_light(self, allow_self: bool = False) -> StateMachine:
        sm = StateMachine(StateMachineConfig(
            initial_state="red", allow_self_transitions=allow_self
        ))
        sm.add_state("red")
        sm.add_state("yellow")
        sm.add_state("green")
        sm.add_transition("red", "green", "go")
        sm.add_transition("green", "yellow", "slow")
        sm.add_transition("yellow", "red", "stop")
        sm.start()
        return sm

    def test_initial_state(self):
        sm = self._make_traffic_light()
        self.assertEqual(sm.current_state, "red")

    def test_trigger_transition(self):
        sm = self._make_traffic_light()
        result = sm.trigger("go")
        self.assertEqual(result, "green")
        self.assertEqual(sm.current_state, "green")

    def test_invalid_transition(self):
        sm = self._make_traffic_light()
        with self.assertRaises(InvalidTransitionError):
            sm.trigger("slow")  # can't slow from red

    def test_full_cycle(self):
        sm = self._make_traffic_light()
        sm.trigger("go")
        sm.trigger("slow")
        sm.trigger("stop")
        self.assertEqual(sm.current_state, "red")

    def test_history(self):
        sm = self._make_traffic_light()
        sm.trigger("go")
        sm.trigger("slow")
        hist = sm.history
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0].from_state, "red")
        self.assertEqual(hist[0].to_state, "green")
        self.assertEqual(hist[1].event, "slow")

    def test_guard_blocks(self):
        sm = StateMachine(StateMachineConfig(initial_state="locked"))
        sm.add_state("locked")
        sm.add_state("unlocked")
        sm.add_transition("locked", "unlocked", "unlock", guard=lambda: False)
        sm.start()
        with self.assertRaises(InvalidTransitionError):
            sm.trigger("unlock")

    def test_guard_allows(self):
        sm = StateMachine(StateMachineConfig(initial_state="locked"))
        sm.add_state("locked")
        sm.add_state("unlocked")
        sm.add_transition("locked", "unlocked", "unlock", guard=lambda: True)
        sm.start()
        self.assertEqual(sm.trigger("unlock"), "unlocked")

    def test_on_enter_on_exit(self):
        log = []
        sm = StateMachine(StateMachineConfig(initial_state="a"))
        sm.add_state("a", on_exit=lambda s: log.append(f"exit:{s}"))
        sm.add_state("b", on_enter=lambda s: log.append(f"enter:{s}"))
        sm.add_transition("a", "b", "go")
        sm.start()
        sm.trigger("go")
        self.assertEqual(log, ["exit:a", "enter:b"])

    def test_on_enter_called_at_start(self):
        log = []
        sm = StateMachine(StateMachineConfig(initial_state="init"))
        sm.add_state("init", on_enter=lambda s: log.append(f"enter:{s}"))
        sm.start()
        self.assertEqual(log, ["enter:init"])

    def test_self_transition_blocked_by_default(self):
        sm = StateMachine(StateMachineConfig(initial_state="idle"))
        sm.add_state("idle")
        sm.add_transition("idle", "idle", "noop")
        sm.start()
        with self.assertRaises(InvalidTransitionError):
            sm.trigger("noop")

    def test_self_transition_allowed(self):
        sm = StateMachine(StateMachineConfig(initial_state="idle", allow_self_transitions=True))
        sm.add_state("idle")
        sm.add_transition("idle", "idle", "tick")
        sm.start()
        self.assertEqual(sm.trigger("tick"), "idle")

    def test_not_started(self):
        sm = StateMachine(StateMachineConfig(initial_state="a"))
        sm.add_state("a")
        with self.assertRaises(RuntimeError):
            sm.trigger("go")

    def test_available_events(self):
        sm = self._make_traffic_light()
        events = sm.get_available_events()
        self.assertEqual(events, ["go"])


if __name__ == "__main__":
    unittest.main()
