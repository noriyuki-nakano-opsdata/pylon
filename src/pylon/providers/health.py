"""Provider health tracking at (provider, model) pair granularity.

Wraps RateLimitManager to track health per model endpoint, not just per provider.
A provider's haiku endpoint may be healthy while opus is rate-limited.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from pylon.cost.rate_limiter import RateLimitManager


@dataclass
class EndpointHealth:
    """Health state for a single (provider, model) endpoint."""

    provider: str
    model_id: str
    is_healthy: bool = True
    consecutive_failures: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_error_code: int | None = None
    total_requests: int = 0
    total_failures: int = 0


class ProviderHealthTracker:
    """Tracks health at (provider, model) pair granularity.

    Delegates to RateLimitManager for provider-level rate limiting
    and circuit breaking, while maintaining per-model health state.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
    ) -> None:
        self._rate_limiter = rate_limiter or RateLimitManager()
        self._lock = threading.Lock()
        self._endpoints: dict[tuple[str, str], EndpointHealth] = {}

    def _key(self, provider: str, model: str) -> tuple[str, str]:
        return (provider, model)

    def _get_endpoint(self, provider: str, model: str) -> EndpointHealth:
        key = self._key(provider, model)
        if key not in self._endpoints:
            self._endpoints[key] = EndpointHealth(
                provider=provider, model_id=model,
            )
        return self._endpoints[key]

    def record_success(
        self, provider: str, model: str, latency_ms: float = 0.0,
    ) -> None:
        """Record successful request.

        The _rate_limiter call is intentionally outside self._lock.
        Endpoint health (per model) and provider-level rate limiting are
        independent concerns with separate locks; nesting them would risk
        deadlocks under high concurrency.  The _rate_limiter manages its
        own internal lock for thread safety.
        """
        with self._lock:
            ep = self._get_endpoint(provider, model)
            ep.is_healthy = True
            ep.consecutive_failures = 0
            ep.last_success_time = time.monotonic()
            ep.total_requests += 1
        self._rate_limiter.record_success(provider, latency_ms=latency_ms)

    def record_failure(
        self, provider: str, model: str, error: Exception,
    ) -> None:
        """Record failed request.

        The _rate_limiter call is intentionally outside self._lock.
        See record_success() docstring for rationale on lock ordering.
        """
        status_code = _extract_status(error)
        with self._lock:
            ep = self._get_endpoint(provider, model)
            ep.consecutive_failures += 1
            ep.last_failure_time = time.monotonic()
            ep.last_error_code = status_code
            ep.total_requests += 1
            ep.total_failures += 1
            if ep.consecutive_failures >= 3:
                ep.is_healthy = False
        self._rate_limiter.record_failure(provider, status_code=status_code)

    def is_available(self, provider: str, model: str = "") -> bool:
        """Check if an endpoint is available."""
        # Check provider-level rate limiting first
        if not self._rate_limiter.can_send(provider):
            return False
        if not model:
            return True
        with self._lock:
            key = self._key(provider, model)
            ep = self._endpoints.get(key)
            if ep is None:
                return True  # Unknown endpoint: allow
            return ep.is_healthy

    def available_providers(self) -> set[str]:
        """Return set of provider names that are currently available."""
        with self._lock:
            all_providers = {ep.provider for ep in self._endpoints.values()}
        return {p for p in all_providers if self._rate_limiter.can_send(p)}

    def get_endpoint_health(
        self, provider: str, model: str,
    ) -> EndpointHealth:
        """Get health state for an endpoint."""
        with self._lock:
            return self._get_endpoint(provider, model)

    def reset(self, provider: str, model: str = "") -> None:
        """Reset health state for an endpoint or entire provider."""
        with self._lock:
            if model:
                key = self._key(provider, model)
                self._endpoints.pop(key, None)
            else:
                keys = [k for k in self._endpoints if k[0] == provider]
                for k in keys:
                    del self._endpoints[k]
        self._rate_limiter.reset_provider(provider)


def _extract_status(exc: Exception) -> int:
    """Extract HTTP status code from an exception."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    details = getattr(exc, "details", {})
    if isinstance(details, dict):
        code = details.get("status_code")
        if isinstance(code, int):
            return code
    return 500
