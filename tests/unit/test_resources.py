"""Tests for rate limiter, quota manager, resource pool, and monitor."""

from __future__ import annotations

import pytest

from pylon.resources.limiter import (
    CompositeLimit,
    KeyedRateLimiter,
    SlidingWindow,
    TokenBucket,
)
from pylon.resources.monitor import (
    Alert,
    Comparator,
    ResourceMonitor,
)
from pylon.resources.pool import (
    PoolConfig,
    PoolContextManager,
    PoolExhaustedError,
    ResourcePool,
)
from pylon.resources.quota import (
    QuotaDefinition,
    QuotaManager,
    ResourceType,
)

# === TokenBucket Tests ===


class TestTokenBucket:
    def test_consume_within_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.consume(5.0) is True
        assert bucket.available() == pytest.approx(5.0, abs=0.1)

    def test_consume_exceeds_capacity(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(6.0) is False

    def test_refill(self):
        bucket = TokenBucket(capacity=10, refill_rate=10.0)
        now = 1000.0
        bucket.consume(10.0, now=now)
        assert bucket.available(now=now) == pytest.approx(0.0, abs=0.01)
        # After 0.5s at 10/s = 5 tokens refilled
        assert bucket.available(now=now + 0.5) == pytest.approx(5.0, abs=0.1)

    def test_refill_capped_at_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=100.0)
        now = 1000.0
        bucket.consume(5.0, now=now)
        # After 1s at 100/s, should cap at 10
        assert bucket.available(now=now + 1.0) == pytest.approx(10.0, abs=0.1)

    def test_consume_exact_capacity(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(5.0) is True
        assert bucket.consume(1.0) is False


# === SlidingWindow Tests ===


class TestSlidingWindow:
    def test_allow_within_limit(self):
        sw = SlidingWindow(window_seconds=10.0, max_requests=3)
        now = 1000.0
        assert sw.allow(now) is True
        assert sw.allow(now + 1) is True
        assert sw.allow(now + 2) is True
        assert sw.allow(now + 3) is False

    def test_window_expiry(self):
        sw = SlidingWindow(window_seconds=5.0, max_requests=2)
        now = 1000.0
        sw.allow(now)
        sw.allow(now + 1)
        assert sw.allow(now + 2) is False
        # After window expires
        assert sw.allow(now + 6) is True

    def test_count(self):
        sw = SlidingWindow(window_seconds=10.0, max_requests=5)
        now = 1000.0
        sw.allow(now)
        sw.allow(now + 1)
        assert sw.count(now + 2) == 2


# === CompositeLimit Tests ===


class TestCompositeLimit:
    def test_all_allow(self):
        tb = TokenBucket(capacity=10, refill_rate=0)
        sw = SlidingWindow(window_seconds=60, max_requests=10)
        comp = CompositeLimit(tb, sw)
        assert comp.allow() is True

    def test_one_blocks(self):
        tb = TokenBucket(capacity=1, refill_rate=0)
        sw = SlidingWindow(window_seconds=60, max_requests=10)
        comp = CompositeLimit(tb, sw)
        comp.allow()  # consume the 1 token
        assert comp.allow() is False


# === KeyedRateLimiter Tests ===


class TestKeyedRateLimiter:
    def test_per_key_isolation(self):
        limiter = KeyedRateLimiter(lambda: SlidingWindow(window_seconds=60, max_requests=2))
        now = 1000.0
        assert limiter.allow("user-a", now) is True
        assert limiter.allow("user-a", now + 1) is True
        assert limiter.allow("user-a", now + 2) is False
        # user-b is independent
        assert limiter.allow("user-b", now) is True

    def test_reset_key(self):
        limiter = KeyedRateLimiter(lambda: SlidingWindow(window_seconds=60, max_requests=1))
        limiter.allow("k1")
        limiter.reset("k1")
        assert limiter.get_limiter("k1") is None


# === QuotaManager Tests ===


class TestQuotaManager:
    def test_allocate_within_quota(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.API_CALLS, limit=100))
        assert mgr.allocate("t1", ResourceType.API_CALLS, 50) is True

    def test_allocate_exceeds_quota(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.API_CALLS, limit=100))
        mgr.allocate("t1", ResourceType.API_CALLS, 80)
        assert mgr.allocate("t1", ResourceType.API_CALLS, 30) is False

    def test_allocate_unknown_tenant(self):
        mgr = QuotaManager()
        assert mgr.allocate("unknown", ResourceType.API_CALLS, 1) is False

    def test_release(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.AGENTS, limit=5))
        mgr.allocate("t1", ResourceType.AGENTS, 3)
        mgr.release("t1", ResourceType.AGENTS, 2)
        usage = mgr.get_usage("t1")
        assert usage[ResourceType.AGENTS].used == pytest.approx(1.0)

    def test_release_below_zero_clamps(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.AGENTS, limit=5))
        mgr.allocate("t1", ResourceType.AGENTS, 2)
        mgr.release("t1", ResourceType.AGENTS, 10)
        usage = mgr.get_usage("t1")
        assert usage[ResourceType.AGENTS].used == 0.0

    def test_get_usage(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.TOKENS, limit=1000))
        mgr.allocate("t1", ResourceType.TOKENS, 300)
        usage = mgr.get_usage("t1")
        info = usage[ResourceType.TOKENS]
        assert info.used == 300
        assert info.limit == 1000
        assert info.remaining == 700
        assert not info.exhausted

    def test_usage_exhausted(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.TOKENS, limit=10))
        mgr.allocate("t1", ResourceType.TOKENS, 10)
        info = mgr.get_usage("t1")[ResourceType.TOKENS]
        assert info.exhausted

    def test_reset_specific_resource(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.API_CALLS, limit=100))
        mgr.set_quota("t1", QuotaDefinition(ResourceType.TOKENS, limit=500))
        mgr.allocate("t1", ResourceType.API_CALLS, 50)
        mgr.allocate("t1", ResourceType.TOKENS, 200)
        mgr.reset("t1", ResourceType.API_CALLS)
        usage = mgr.get_usage("t1")
        assert usage[ResourceType.API_CALLS].used == 0
        assert usage[ResourceType.TOKENS].used == 200

    def test_reset_all(self):
        mgr = QuotaManager()
        mgr.set_quota("t1", QuotaDefinition(ResourceType.API_CALLS, limit=100))
        mgr.allocate("t1", ResourceType.API_CALLS, 50)
        mgr.reset("t1")
        usage = mgr.get_usage("t1")
        assert usage[ResourceType.API_CALLS].used == 0


# === ResourcePool Tests ===


_counter = 0


def _int_factory() -> int:
    global _counter
    _counter += 1
    return _counter


class TestResourcePool:
    def setup_method(self):
        global _counter
        _counter = 0

    def test_acquire_creates(self):
        pool = ResourcePool(_int_factory)
        item = pool.acquire()
        assert item == 1
        assert pool.stats.active == 1

    def test_release_returns_to_idle(self):
        pool = ResourcePool(_int_factory)
        item = pool.acquire()
        pool.release(item)
        assert pool.stats.idle == 1
        assert pool.stats.active == 0

    def test_acquire_reuses_idle(self):
        pool = ResourcePool(_int_factory)
        item = pool.acquire()
        pool.release(item)
        reused = pool.acquire()
        assert reused == item
        assert pool.stats.total_created == 1

    def test_max_size_enforced(self):
        pool = ResourcePool(_int_factory, PoolConfig(max_size=2))
        pool.acquire()
        pool.acquire()
        with pytest.raises(PoolExhaustedError):
            pool.acquire()

    def test_fill(self):
        pool = ResourcePool(_int_factory, PoolConfig(min_size=3, max_size=5))
        created = pool.fill()
        assert created == 3
        assert pool.stats.idle == 3

    def test_fill_respects_max(self):
        pool = ResourcePool(_int_factory, PoolConfig(min_size=10, max_size=2))
        created = pool.fill()
        assert created == 2

    def test_validation_fn(self):
        valid_items = {1, 3}
        config = PoolConfig(validation_fn=lambda x: x in valid_items)
        pool = ResourcePool(_int_factory, config)
        item1 = pool.acquire()  # creates 1, valid
        assert item1 == 1
        pool.release(item1)
        # item1 is valid, should be reused
        assert pool.acquire() == 1

    def test_validation_discards_invalid(self):
        call_count = 0
        def factory():
            nonlocal call_count
            call_count += 1
            return call_count

        # Only even numbers are valid
        config = PoolConfig(validation_fn=lambda x: x % 2 == 0)
        pool = ResourcePool(factory, config)
        item = pool.acquire()  # creates 1, invalid on release
        pool.release(item)
        # On next acquire, item 1 is invalid, discarded, creates 2
        item2 = pool.acquire()
        assert item2 == 2

    def test_context_manager(self):
        pool = ResourcePool(_int_factory)
        ctx = PoolContextManager(pool)
        with ctx as item:
            assert item == 1
            assert pool.stats.active == 1
        assert pool.stats.active == 0
        assert pool.stats.idle == 1

    def test_destroy(self):
        pool = ResourcePool(_int_factory)
        item = pool.acquire()
        pool.destroy(item)
        assert pool.stats.active == 0

    def test_wait_count_tracked(self):
        pool = ResourcePool(_int_factory, PoolConfig(max_size=1))
        pool.acquire()
        with pytest.raises(PoolExhaustedError):
            pool.acquire()
        assert pool.stats.wait_count == 1


# === ResourceMonitor Tests ===


class TestResourceMonitor:
    def test_track_and_get_current(self):
        mon = ResourceMonitor()
        mon.track("cpu", 75.0)
        assert mon.get_current("cpu") == 75.0

    def test_get_current_missing(self):
        mon = ResourceMonitor()
        assert mon.get_current("missing") is None

    def test_get_history(self):
        mon = ResourceMonitor()
        mon.track("cpu", 50.0, now=100.0)
        mon.track("cpu", 60.0, now=101.0)
        mon.track("cpu", 70.0, now=102.0)
        history = mon.get_history("cpu")
        assert len(history) == 3

    def test_get_history_with_window(self):
        mon = ResourceMonitor()
        mon.track("cpu", 50.0, now=100.0)
        mon.track("cpu", 60.0, now=105.0)
        mon.track("cpu", 70.0, now=110.0)
        history = mon.get_history("cpu", window_seconds=6.0, now=110.0)
        assert len(history) == 2  # 105 and 110

    def test_track_with_labels(self):
        mon = ResourceMonitor()
        mon.track("requests", 10, labels={"method": "GET"})
        history = mon.get_history("requests")
        assert history[0].labels == {"method": "GET"}

    def test_alert_triggered(self):
        triggered: list[tuple[str, float]] = []
        mon = ResourceMonitor()
        mon.add_alert("cpu", Alert(
            threshold=80.0,
            comparator=Comparator.GT,
            callback=lambda r, v, t: triggered.append((r, v)),
            name="cpu-high",
        ))
        mon.track("cpu", 90.0)
        result = mon.check_alerts()
        assert len(result) == 1
        assert triggered[0] == ("cpu", 90.0)

    def test_alert_not_triggered_below_threshold(self):
        triggered: list = []
        mon = ResourceMonitor()
        mon.add_alert("cpu", Alert(
            threshold=80.0,
            comparator=Comparator.GT,
            callback=lambda r, v, t: triggered.append(1),
        ))
        mon.track("cpu", 50.0)
        mon.check_alerts()
        assert len(triggered) == 0

    def test_alert_lt_comparator(self):
        triggered: list = []
        mon = ResourceMonitor()
        mon.add_alert("memory_free", Alert(
            threshold=100.0,
            comparator=Comparator.LT,
            callback=lambda r, v, t: triggered.append(v),
        ))
        mon.track("memory_free", 50.0)
        mon.check_alerts()
        assert len(triggered) == 1

    def test_alert_not_re_triggered(self):
        count = [0]
        mon = ResourceMonitor()
        mon.add_alert("cpu", Alert(
            threshold=80.0,
            comparator=Comparator.GT,
            callback=lambda r, v, t: count.__setitem__(0, count[0] + 1),
        ))
        mon.track("cpu", 90.0)
        mon.check_alerts()
        mon.track("cpu", 95.0)
        mon.check_alerts()
        assert count[0] == 1  # only triggered once

    def test_alert_re_arms_after_clear(self):
        count = [0]
        mon = ResourceMonitor()
        mon.add_alert("cpu", Alert(
            threshold=80.0,
            comparator=Comparator.GT,
            callback=lambda r, v, t: count.__setitem__(0, count[0] + 1),
        ))
        mon.track("cpu", 90.0)
        mon.check_alerts()
        mon.track("cpu", 50.0)  # drops below
        mon.check_alerts()
        mon.track("cpu", 90.0)  # rises again
        mon.check_alerts()
        assert count[0] == 2

    def test_resources_list(self):
        mon = ResourceMonitor()
        mon.track("cpu", 50)
        mon.track("memory", 4096)
        assert sorted(mon.resources()) == ["cpu", "memory"]

    def test_max_history_limit(self):
        mon = ResourceMonitor(max_history=5)
        for i in range(10):
            mon.track("cpu", float(i), now=float(i))
        assert len(mon.get_history("cpu")) == 5
