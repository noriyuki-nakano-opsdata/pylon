"""Tests for rate limiter and circuit breaker integration."""

from __future__ import annotations

import pytest

from pylon.cost.rate_limiter import (
    ProviderHealth,
    ProviderQuota,
    QuotaWindow,
    RateLimitManager,
    _duration_header,
)
from pylon.resilience.circuit_breaker import CircuitBreakerConfig, CircuitState


@pytest.fixture
def rlm() -> RateLimitManager:
    mgr = RateLimitManager()
    mgr.register_provider(ProviderQuota(
        provider="anthropic", rpm=60, tpm=100_000, concurrent=5,
    ))
    mgr.register_provider(ProviderQuota(
        provider="openai", rpm=500, tpm=200_000, concurrent=20,
    ))
    return mgr


class TestRateLimitManager:
    def test_can_send_initially(self, rlm: RateLimitManager) -> None:
        assert rlm.can_send("anthropic", estimated_tokens=1000) is True

    def test_can_send_unknown_provider(self, rlm: RateLimitManager) -> None:
        assert rlm.can_send("unknown") is True

    def test_record_success(self, rlm: RateLimitManager) -> None:
        rlm.acquire("anthropic")
        rlm.record_success("anthropic", latency_ms=150.0)
        rlm.release("anthropic")
        health = rlm.get_health("anthropic")
        assert health.total_requests == 1
        assert health.failure_rate == 0.0

    def test_record_failure_trips_breaker(self, rlm: RateLimitManager) -> None:
        # Register with low threshold for testing.
        mgr = RateLimitManager()
        mgr.register_provider(
            ProviderQuota(provider="test", rpm=100, tpm=100_000),
            circuit_config=CircuitBreakerConfig(
                failure_threshold=2, success_threshold=1, timeout=1.0,
            ),
        )
        mgr.record_failure("test", status_code=500)
        mgr.record_failure("test", status_code=500)
        assert mgr.get_circuit_state("test") == CircuitState.OPEN
        assert mgr.can_send("test") is False

    def test_client_error_does_not_trip_breaker(
        self, rlm: RateLimitManager,
    ) -> None:
        for _ in range(10):
            rlm.record_failure("anthropic", status_code=400)
        # 400 is a client error; circuit should stay CLOSED.
        assert rlm.get_circuit_state("anthropic") == CircuitState.CLOSED

    def test_should_retry(self, rlm: RateLimitManager) -> None:
        assert rlm.should_retry("anthropic", 429) is True
        assert rlm.should_retry("anthropic", 500) is True
        assert rlm.should_retry("anthropic", 400) is False
        assert rlm.should_retry("anthropic", 401) is False

    def test_next_retry_delay_exponential(self, rlm: RateLimitManager) -> None:
        rlm.record_failure("anthropic", status_code=500)
        d1 = rlm.next_retry_delay("anthropic", base_seconds=1.0)
        rlm.record_failure("anthropic", status_code=500)
        d2 = rlm.next_retry_delay("anthropic", base_seconds=1.0)
        # Second delay should be larger due to exponential backoff.
        assert d2 > d1

    def test_update_quota_from_headers(self, rlm: RateLimitManager) -> None:
        headers = {
            "x-ratelimit-limit-requests": "60",
            "x-ratelimit-remaining-requests": "10",
            "x-ratelimit-reset-requests": "30s",
            "x-ratelimit-limit-tokens": "100000",
            "x-ratelimit-remaining-tokens": "50000",
        }
        rlm.update_quota_from_headers("anthropic", headers)
        # After update, should still be sendable if remaining > 0.
        assert rlm.can_send("anthropic", estimated_tokens=1000) is True

    def test_reset_provider(self, rlm: RateLimitManager) -> None:
        rlm.record_failure("anthropic", status_code=500)
        rlm.reset_provider("anthropic")
        health = rlm.get_health("anthropic")
        assert health.total_requests == 0

    def test_health_metrics(self, rlm: RateLimitManager) -> None:
        for i in range(10):
            rlm.record_success("anthropic", latency_ms=float(i * 10))
        health = rlm.get_health("anthropic")
        assert health.total_requests == 10
        assert health.percentile(50) > 0
        assert health.percentile(99) >= health.percentile(50)


class TestQuotaWindow:
    def test_can_fit(self) -> None:
        window = QuotaWindow(
            requests_limit=60,
            requests_remaining=10,
            tokens_limit=100_000,
            tokens_remaining=50_000,
        )
        assert window.can_fit(1000) is True
        assert window.can_fit(60_000) is False

    def test_exhausted_requests(self) -> None:
        window = QuotaWindow(
            requests_limit=60,
            requests_remaining=0,
            tokens_limit=100_000,
            tokens_remaining=50_000,
        )
        assert window.can_fit(100) is False


class TestProviderHealth:
    def test_availability(self) -> None:
        health = ProviderHealth(total_requests=100, total_failures=5)
        assert health.availability == pytest.approx(0.95)

    def test_empty_percentile(self) -> None:
        health = ProviderHealth()
        assert health.percentile(99) == 0.0


class TestDurationHeader:
    def test_seconds(self) -> None:
        assert _duration_header({"k": "30s"}, "k") == 30.0

    def test_minutes_and_seconds(self) -> None:
        assert _duration_header({"k": "1m30s"}, "k") == 90.0

    def test_missing(self) -> None:
        assert _duration_header({}, "k") == 0.0
