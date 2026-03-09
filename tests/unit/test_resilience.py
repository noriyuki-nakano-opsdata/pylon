"""Tests for resilience module."""

from __future__ import annotations

import asyncio
import unittest

import pytest

from pylon.resilience import (
    AllFallbacksFailedError,
    AsyncBulkhead,
    Bulkhead,
    BulkheadFullError,
    CachedFallback,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    ConstantBackoff,
    ExponentialBackoff,
    FallbackChain,
    JitteredBackoff,
    LinearBackoff,
    RetryExhaustedError,
    RetryPolicy,
    retry,
    with_retry,
)

# --- CircuitBreaker ---

class TestCircuitBreaker(unittest.TestCase):
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_successful_call(self):
        cb = CircuitBreaker()
        result = cb.call(lambda: 42)
        self.assertEqual(result, 42)
        self.assertEqual(cb.metrics.successes, 1)

    def test_failed_call_recorded(self):
        cb = CircuitBreaker()
        with self.assertRaises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        self.assertEqual(cb.metrics.failures, 1)

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_open_rejects_calls(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
        with self.assertRaises(CircuitOpenError):
            cb.call(lambda: 1)

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, timeout=0.05))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        self.assertEqual(cb.state, CircuitState.OPEN)
        import time
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=1, success_threshold=1, timeout=0.05
        ))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        import time
        time.sleep(0.06)
        result = cb.call(lambda: "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, timeout=0.05))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        import time
        time.sleep(0.06)
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_reset(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        cb.reset()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.metrics.failures, 0)

    def test_force_open(self):
        cb = CircuitBreaker()
        cb.force_open()
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_force_close(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        cb.force_close()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_on_state_change_callback(self):
        changes = []
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1),
            on_state_change=lambda old, new: changes.append((old, new)),
        )
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0], (CircuitState.CLOSED, CircuitState.OPEN))

    def test_metrics_total_calls(self):
        cb = CircuitBreaker()
        cb.call(lambda: 1)
        cb.call(lambda: 2)
        self.assertEqual(cb.metrics.total_calls, 2)

    def test_config_validates_half_open_max_calls(self):
        """C4: half_open_max_calls must be >= success_threshold."""
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(success_threshold=3, half_open_max_calls=2)
        # Valid: equal
        cfg = CircuitBreakerConfig(success_threshold=2, half_open_max_calls=2)
        self.assertEqual(cfg.half_open_max_calls, 2)

    def test_default_config_allows_recovery(self):
        """C4: Default config must allow HALF_OPEN -> CLOSED recovery."""
        cfg = CircuitBreakerConfig()
        self.assertGreaterEqual(cfg.half_open_max_calls, cfg.success_threshold)

    def test_callback_not_called_under_lock(self):
        """C3: State change callback must not deadlock."""
        cb_ref = [None]

        def callback(old, new):
            # Access the circuit breaker's state property inside the callback.
            # Before the fix, this would deadlock because _transition was
            # called while holding the lock, and state also acquires the lock.
            _ = cb_ref[0].state

        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1),
            on_state_change=callback,
        )
        cb_ref[0] = cb
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
        # If we reach here, no deadlock occurred
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_half_open_single_failure_returns_to_open(self):
        """In HALF_OPEN, one failure transitions back to OPEN."""
        import time
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, timeout=0.05))
        # Trip to OPEN
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        self.assertEqual(cb.state, CircuitState.OPEN)
        # Wait for timeout to transition to HALF_OPEN
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        # Single failure in HALF_OPEN should go back to OPEN
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("half-open fail")))
        except RuntimeError:
            pass
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_state_change_callback_exception_doesnt_break_circuit(self):
        """If on_state_change callback raises, circuit breaker still works."""
        def bad_callback(old, new):
            raise ValueError("callback error")

        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1),
            on_state_change=bad_callback,
        )
        # The callback will raise when transitioning CLOSED -> OPEN,
        # but the exception propagates from the call() that already raised.
        # After that the circuit should still be in OPEN state.
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("trigger")))
        except (RuntimeError, ValueError):
            pass
        # Circuit should still be in OPEN state despite callback error
        # Access internal state directly to avoid triggering another callback
        self.assertEqual(cb._state, CircuitState.OPEN)

    def test_consecutive_success_threshold(self):
        """Verify exact number of successes needed to close from HALF_OPEN."""
        import time
        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=1, success_threshold=2,
            timeout=0.05, half_open_max_calls=3,
        ))
        # Trip to OPEN
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        # First success: still HALF_OPEN (need 2)
        cb.call(lambda: "ok1")
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        # Second success: transitions to CLOSED
        cb.call(lambda: "ok2")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_metrics_track_failures(self):
        """After failures, metrics.failures count is correct."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=10))
        for i in range(5):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        self.assertEqual(cb.metrics.failures, 5)
        self.assertIsNotNone(cb.metrics.last_failure_time)
        self.assertEqual(cb.metrics.total_calls, 5)


# --- Retry ---

class TestRetry(unittest.TestCase):
    def test_succeeds_first_try(self):
        result = retry(lambda: 42, RetryPolicy(max_attempts=3, backoff=ConstantBackoff(0)))
        self.assertEqual(result, 42)

    def test_succeeds_after_retries(self):
        counter = {"n": 0}
        def flaky():
            counter["n"] += 1
            if counter["n"] < 3:
                raise ValueError("not yet")
            return "ok"
        result = retry(flaky, RetryPolicy(max_attempts=3, backoff=ConstantBackoff(0)))
        self.assertEqual(result, "ok")

    def test_exhausted(self):
        with self.assertRaises(RetryExhaustedError) as cm:
            retry(
                lambda: (_ for _ in ()).throw(ValueError("fail")),
                RetryPolicy(max_attempts=3, backoff=ConstantBackoff(0)),
            )
        self.assertEqual(len(cm.exception.attempts), 3)

    def test_non_retryable_exception(self):
        with self.assertRaises(TypeError):
            retry(
                lambda: (_ for _ in ()).throw(TypeError("bad")),
                RetryPolicy(
                    max_attempts=3,
                    backoff=ConstantBackoff(0),
                    retryable_exceptions=(ValueError,),
                ),
            )

    def test_on_retry_callback(self):
        retries = []
        counter = {"n": 0}
        def flaky():
            counter["n"] += 1
            if counter["n"] < 2:
                raise ValueError("retry me")
            return "done"
        retry(
            flaky,
            RetryPolicy(
                max_attempts=3,
                backoff=ConstantBackoff(0),
                on_retry=lambda attempt, exc: retries.append(attempt),
            ),
        )
        self.assertEqual(retries, [1])

    def test_with_retry_decorator(self):
        counter = {"n": 0}

        @with_retry(RetryPolicy(max_attempts=2, backoff=ConstantBackoff(0)))
        def flaky():
            counter["n"] += 1
            if counter["n"] < 2:
                raise ValueError()
            return "ok"

        self.assertEqual(flaky(), "ok")

    def test_constant_backoff(self):
        b = ConstantBackoff(2.0)
        self.assertEqual(b.delay(0), 2.0)
        self.assertEqual(b.delay(5), 2.0)

    def test_linear_backoff(self):
        b = LinearBackoff(initial=1.0, increment=0.5)
        self.assertEqual(b.delay(0), 1.0)
        self.assertEqual(b.delay(2), 2.0)

    def test_exponential_backoff(self):
        b = ExponentialBackoff(base=1.0, multiplier=2.0, max_delay=10.0)
        self.assertEqual(b.delay(0), 1.0)
        self.assertEqual(b.delay(1), 2.0)
        self.assertEqual(b.delay(2), 4.0)
        self.assertEqual(b.delay(10), 10.0)  # capped

    def test_jittered_backoff(self):
        b = JitteredBackoff(ExponentialBackoff(base=1.0), jitter_range=0.5)
        delay = b.delay(0)
        self.assertGreaterEqual(delay, 1.0)
        self.assertLessEqual(delay, 1.5)


# --- Fallback ---

class TestFallbackChain(unittest.TestCase):
    def test_first_succeeds(self):
        chain = FallbackChain([lambda: "primary"])
        result = chain.execute()
        self.assertEqual(result.value, "primary")
        self.assertEqual(result.source_index, 0)
        self.assertEqual(len(result.errors), 0)

    def test_falls_to_second(self):
        chain = FallbackChain([
            lambda: (_ for _ in ()).throw(RuntimeError("fail")),
            lambda: "backup",
        ])
        result = chain.execute()
        self.assertEqual(result.value, "backup")
        self.assertEqual(result.source_index, 1)
        self.assertEqual(len(result.errors), 1)

    def test_with_default(self):
        chain = FallbackChain([
            lambda: (_ for _ in ()).throw(RuntimeError()),
        ]).with_default("default_val")
        result = chain.execute()
        self.assertEqual(result.value, "default_val")
        self.assertEqual(result.source_index, -1)

    def test_all_fail_no_default(self):
        chain = FallbackChain([
            lambda: (_ for _ in ()).throw(RuntimeError("a")),
            lambda: (_ for _ in ()).throw(RuntimeError("b")),
        ])
        with self.assertRaises(AllFallbacksFailedError) as cm:
            chain.execute()
        self.assertEqual(len(cm.exception.errors), 2)

    def test_add_method(self):
        chain = FallbackChain()
        chain.add(lambda: "added")
        result = chain.execute()
        self.assertEqual(result.value, "added")


class TestCachedFallback(unittest.TestCase):
    def test_caches_success(self):
        call_count = {"n": 0}
        def fn():
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise RuntimeError("fail")
            return "cached_value"

        cf = CachedFallback(fn)
        self.assertEqual(cf.execute(), "cached_value")
        self.assertTrue(cf.has_cache)
        # Second call fails but returns cache
        self.assertEqual(cf.execute(), "cached_value")

    def test_no_cache_raises(self):
        cf = CachedFallback(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        with self.assertRaises(RuntimeError):
            cf.execute()
        self.assertFalse(cf.has_cache)

    def test_clear_cache(self):
        cf = CachedFallback(lambda: "val")
        cf.execute()
        cf.clear_cache()
        self.assertFalse(cf.has_cache)


# --- Bulkhead ---

class TestBulkhead(unittest.TestCase):
    def test_execute(self):
        bh = Bulkhead(max_concurrent=2)
        result = bh.execute(lambda: 42)
        self.assertEqual(result, 42)
        self.assertEqual(bh.stats.completed, 1)

    def test_stats_after_completion(self):
        bh = Bulkhead(max_concurrent=5)
        for i in range(3):
            bh.execute(lambda: i)
        stats = bh.stats
        self.assertEqual(stats.completed, 3)
        self.assertEqual(stats.active, 0)


class TestAsyncBulkhead:
    @pytest.mark.asyncio
    async def test_execute(self):
        bh = AsyncBulkhead(max_concurrent=2)
        result = await bh.execute(_async_return, 42)
        assert result == 42
        assert bh.stats.completed == 1

    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        bh = AsyncBulkhead(max_concurrent=3, max_queue=5)
        results = await asyncio.gather(*[
            bh.execute(_async_return, i) for i in range(3)
        ])
        assert sorted(results) == [0, 1, 2]
        assert bh.stats.completed == 3

    @pytest.mark.asyncio
    async def test_bulkhead_full_rejection(self):
        bh = AsyncBulkhead(max_concurrent=1, max_queue=0)
        held = asyncio.Event()
        release = asyncio.Event()

        async def hold():
            held.set()
            await release.wait()
            return "held"

        task = asyncio.create_task(bh.execute(hold))
        await held.wait()
        await asyncio.sleep(0)  # let the task acquire semaphore

        with pytest.raises(BulkheadFullError):
            await bh.execute(_async_return, "rejected")

        release.set()
        await task


async def _async_return(value):
    return value


if __name__ == "__main__":
    unittest.main()
