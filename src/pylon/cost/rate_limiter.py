"""Per-provider rate limiting with circuit breaker integration.

Tracks RPM/TPM quotas from response headers, provides pre-flight checks
before sending requests, and implements exponential backoff with jitter
for automatic retry. Integrates with the existing CircuitBreaker from
pylon.resilience.circuit_breaker.

Latency percentiles (P50/P95/P99) are tracked per provider for
observability and routing decisions.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pylon.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
)


@dataclass(frozen=True)
class QuotaWindow:
    """Rate limit window parsed from provider response headers.

    Providers report limits via headers like:
        x-ratelimit-limit-requests: 60
        x-ratelimit-remaining-requests: 45
        x-ratelimit-reset-requests: 30s
        x-ratelimit-limit-tokens: 100000
        x-ratelimit-remaining-tokens: 80000
    """

    requests_limit: int = 0
    requests_remaining: int = 0
    requests_reset_seconds: float = 0.0
    tokens_limit: int = 0
    tokens_remaining: int = 0
    tokens_reset_seconds: float = 0.0
    recorded_at: float = 0.0

    def can_fit(self, estimated_tokens: int) -> bool:
        """Pre-flight check: can this request fit within remaining quota?"""
        if self.requests_remaining <= 0 and self.requests_limit > 0:
            return False
        if (
            self.tokens_remaining < estimated_tokens
            and self.tokens_limit > 0
        ):
            return False
        return True

    @property
    def seconds_until_reset(self) -> float:
        """Seconds until the rate limit window resets."""
        if self.recorded_at == 0:
            return 0.0
        elapsed = time.monotonic() - self.recorded_at
        remaining = max(
            self.requests_reset_seconds,
            self.tokens_reset_seconds,
        ) - elapsed
        return max(0.0, remaining)


@dataclass(frozen=True)
class ProviderQuota:
    """Static per-provider quota configuration.

    Used as defaults when response headers are not available.
    """

    provider: str
    rpm: int = 60          # Requests per minute
    tpm: int = 100_000     # Tokens per minute
    concurrent: int = 10   # Max concurrent requests


@dataclass
class ProviderHealth:
    """Live health metrics for a provider.

    Tracks failure rate, latency distribution, and availability for
    observability and routing decisions.
    """

    total_requests: int = 0
    total_failures: int = 0
    latencies_ms: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000),
    )
    last_failure_at: float = 0.0
    last_success_at: float = 0.0

    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_failures / self.total_requests

    @property
    def availability(self) -> float:
        """Availability as fraction [0.0, 1.0]."""
        return 1.0 - self.failure_rate

    def percentile(self, p: float) -> float:
        """Calculate latency percentile (e.g., p=50, p=95, p=99).

        Returns 0.0 if no data.
        """
        if not self.latencies_ms:
            return 0.0
        sorted_vals = sorted(self.latencies_ms)
        idx = int(math.ceil(p / 100.0 * len(sorted_vals))) - 1
        return sorted_vals[max(0, idx)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "failure_rate": round(self.failure_rate, 4),
            "availability": round(self.availability, 4),
            "latency_p50_ms": round(self.percentile(50), 1),
            "latency_p95_ms": round(self.percentile(95), 1),
            "latency_p99_ms": round(self.percentile(99), 1),
        }


# HTTP status codes that indicate rate limiting (429) or server error (5xx).
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# HTTP status codes that indicate client error (do NOT retry).
_CLIENT_ERROR_CODES = frozenset(range(400, 429))


class RateLimitManager:
    """Per-provider rate limiting with circuit breaker and health tracking.

    Usage:
        rlm = RateLimitManager()
        rlm.register_provider(ProviderQuota(provider="anthropic", rpm=60, tpm=100000))

        # Pre-flight check before sending request:
        if rlm.can_send("anthropic", estimated_tokens=2000):
            try:
                response = await provider.chat(messages)
                rlm.record_success("anthropic", latency_ms=150.0)
                rlm.update_quota_from_headers("anthropic", response.headers)
            except ProviderError as e:
                rlm.record_failure("anthropic", status_code=e.status_code)
                if rlm.should_retry("anthropic", e.status_code):
                    delay = rlm.next_retry_delay("anthropic")
                    await asyncio.sleep(delay)
        else:
            wait = rlm.wait_time("anthropic")
            await asyncio.sleep(wait)

    Integration with LLMRuntime:
        Wrap provider.chat() calls with can_send() pre-flight check and
        record_success()/record_failure() post-call tracking. The existing
        CircuitBreaker handles state transitions; this class adds quota
        awareness and latency tracking on top.
    """

    def __init__(
        self,
        default_circuit_config: CircuitBreakerConfig | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._default_circuit_config = default_circuit_config or CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout=30.0,
            half_open_max_calls=2,
        )
        # provider -> static quota config
        self._quotas: dict[str, ProviderQuota] = {}
        # provider -> live window from response headers
        self._windows: dict[str, QuotaWindow] = {}
        # provider -> circuit breaker
        self._breakers: dict[str, CircuitBreaker] = {}
        # provider -> health metrics
        self._health: dict[str, ProviderHealth] = {}
        # provider -> retry attempt counter (reset on success)
        self._retry_counts: dict[str, int] = {}
        # provider -> in-flight request count
        self._in_flight: dict[str, int] = {}
        # provider -> last request time (for RPM tracking)
        self._request_times: dict[str, deque[float]] = {}

    def register_provider(
        self,
        quota: ProviderQuota,
        circuit_config: CircuitBreakerConfig | None = None,
    ) -> None:
        """Register a provider with its quota and circuit breaker config."""
        config = circuit_config or self._default_circuit_config
        with self._lock:
            self._quotas[quota.provider] = quota
            self._breakers[quota.provider] = CircuitBreaker(config=config)
            self._health[quota.provider] = ProviderHealth()
            self._retry_counts[quota.provider] = 0
            self._in_flight[quota.provider] = 0
            self._request_times[quota.provider] = deque(maxlen=quota.rpm * 2)

    def can_send(self, provider: str, estimated_tokens: int = 0) -> bool:
        """Pre-flight check: can this request be sent now?

        Checks:
        1. Circuit breaker is not OPEN
        2. Live quota window has capacity (if available)
        3. RPM limit not exceeded (sliding window)
        4. Concurrent request limit not exceeded

        Args:
            provider: Provider name.
            estimated_tokens: Expected token consumption for TPM check.

        Returns:
            True if the request can proceed.
        """
        with self._lock:
            breaker = self._breakers.get(provider)
            if breaker is None:
                return True  # Unknown provider: allow by default

            # Check circuit breaker state.
            try:
                state = breaker.state
            except Exception:
                return False
            if state == CircuitState.OPEN:
                return False

            # Check live quota window.
            window = self._windows.get(provider)
            if window and not window.can_fit(estimated_tokens):
                if window.seconds_until_reset > 0:
                    return False

            # Check RPM (sliding window).
            quota = self._quotas.get(provider)
            if quota:
                times = self._request_times.get(provider, deque())
                now = time.monotonic()
                # Count requests in last 60 seconds.
                while times and now - times[0] > 60.0:
                    times.popleft()
                if len(times) >= quota.rpm:
                    return False

                # Check concurrent limit.
                in_flight = self._in_flight.get(provider, 0)
                if in_flight >= quota.concurrent:
                    return False

        return True

    def acquire(self, provider: str) -> None:
        """Mark a request as in-flight. Call before sending."""
        with self._lock:
            self._in_flight[provider] = self._in_flight.get(provider, 0) + 1
            times = self._request_times.get(provider)
            if times is not None:
                times.append(time.monotonic())

    def release(self, provider: str) -> None:
        """Mark a request as completed. Call in finally block."""
        with self._lock:
            current = self._in_flight.get(provider, 0)
            self._in_flight[provider] = max(0, current - 1)

    def record_success(
        self,
        provider: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a successful request for health tracking.

        Also probes the circuit breaker if in HALF_OPEN state.
        """
        with self._lock:
            health = self._health.get(provider)
            if health:
                health.total_requests += 1
                health.last_success_at = time.monotonic()
                if latency_ms > 0:
                    health.latencies_ms.append(latency_ms)
            self._retry_counts[provider] = 0

            breaker = self._breakers.get(provider)

        # Probe circuit breaker with a no-op success.
        if breaker:
            try:
                breaker.call(lambda: None)
            except CircuitOpenError:
                pass

    def record_failure(
        self,
        provider: str,
        status_code: int = 500,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a failed request.

        Only counts as a circuit breaker failure for retryable status codes
        (429, 5xx). Client errors (4xx except 429) are NOT counted.
        """
        with self._lock:
            health = self._health.get(provider)
            if health:
                health.total_requests += 1
                health.total_failures += 1
                health.last_failure_at = time.monotonic()
                if latency_ms > 0:
                    health.latencies_ms.append(latency_ms)

            self._retry_counts[provider] = (
                self._retry_counts.get(provider, 0) + 1
            )
            breaker = self._breakers.get(provider)

        # Only trip circuit breaker for retryable errors.
        if breaker and status_code in _RETRYABLE_STATUS_CODES:
            try:
                breaker.call(_raise_failure)
            except (CircuitOpenError, _SyntheticError):
                pass

    def update_quota_from_headers(
        self,
        provider: str,
        headers: dict[str, str],
    ) -> None:
        """Parse rate limit headers from a provider response.

        Supports the common x-ratelimit-* header format used by
        OpenAI, Anthropic, and others.
        """
        window = QuotaWindow(
            requests_limit=_int_header(headers, "x-ratelimit-limit-requests"),
            requests_remaining=_int_header(
                headers, "x-ratelimit-remaining-requests",
            ),
            requests_reset_seconds=_duration_header(
                headers, "x-ratelimit-reset-requests",
            ),
            tokens_limit=_int_header(headers, "x-ratelimit-limit-tokens"),
            tokens_remaining=_int_header(
                headers, "x-ratelimit-remaining-tokens",
            ),
            tokens_reset_seconds=_duration_header(
                headers, "x-ratelimit-reset-tokens",
            ),
            recorded_at=time.monotonic(),
        )
        with self._lock:
            self._windows[provider] = window

    def should_retry(self, provider: str, status_code: int) -> bool:
        """Whether a failed request should be retried.

        Returns True for 429 and 5xx. Returns False for client errors.
        """
        if status_code in _CLIENT_ERROR_CODES:
            return False
        return status_code in _RETRYABLE_STATUS_CODES

    def next_retry_delay(
        self,
        provider: str,
        *,
        base_seconds: float = 1.0,
        max_seconds: float = 60.0,
    ) -> float:
        """Calculate exponential backoff with jitter for next retry.

        Args:
            provider: Provider name.
            base_seconds: Base delay for first retry.
            max_seconds: Maximum delay cap.

        Returns:
            Delay in seconds before next retry attempt.
        """
        with self._lock:
            attempt = min(self._retry_counts.get(provider, 0), 20)
        delay = min(base_seconds * (2 ** attempt), max_seconds)
        jitter = delay * 0.5 * random.random()
        return delay + jitter

    def wait_time(self, provider: str) -> float:
        """How long to wait before this provider accepts requests again.

        Checks both the rate limit window reset and circuit breaker timeout.
        """
        with self._lock:
            window = self._windows.get(provider)
            breaker = self._breakers.get(provider)

        wait = 0.0
        if window:
            wait = max(wait, window.seconds_until_reset)
        if breaker and breaker.state == CircuitState.OPEN:
            # Use the circuit breaker's configured timeout.
            wait = max(wait, self._default_circuit_config.timeout)
        return wait

    def get_health(self, provider: str) -> ProviderHealth:
        """Retrieve health metrics for a provider."""
        with self._lock:
            return self._health.get(provider, ProviderHealth())

    def get_all_health(self) -> dict[str, dict[str, Any]]:
        """Retrieve health metrics for all registered providers."""
        with self._lock:
            providers = list(self._health.keys())
        return {
            p: self.get_health(p).to_dict()
            for p in providers
        }

    def get_circuit_state(self, provider: str) -> CircuitState | None:
        """Get the current circuit breaker state for a provider."""
        with self._lock:
            breaker = self._breakers.get(provider)
        if breaker is None:
            return None
        return breaker.state

    def reset_provider(self, provider: str) -> None:
        """Reset circuit breaker and health for a provider."""
        with self._lock:
            breaker = self._breakers.get(provider)
            if breaker:
                breaker.reset()
            health = self._health.get(provider)
            if health:
                self._health[provider] = ProviderHealth()
            self._retry_counts[provider] = 0
            self._windows.pop(provider, None)


class _SyntheticError(Exception):
    """Raised internally to trip the circuit breaker on recorded failures."""


def _raise_failure() -> None:
    raise _SyntheticError()


def _int_header(headers: dict[str, str], key: str) -> int:
    """Parse an integer header value, returning 0 if missing."""
    val = headers.get(key, "")
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _duration_header(headers: dict[str, str], key: str) -> float:
    """Parse a duration header value (e.g., '30s', '1m30s'), returning seconds."""
    val = headers.get(key, "").strip()
    if not val:
        return 0.0
    total = 0.0
    current_num = ""
    for ch in val:
        if ch.isdigit() or ch == ".":
            current_num += ch
        elif ch == "s":
            total += float(current_num) if current_num else 0.0
            current_num = ""
        elif ch == "m":
            total += (float(current_num) * 60) if current_num else 0.0
            current_num = ""
        elif ch == "h":
            total += (float(current_num) * 3600) if current_num else 0.0
            current_num = ""
    if current_num:
        total += float(current_num)
    return total
