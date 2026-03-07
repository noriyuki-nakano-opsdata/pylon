"""Rate limiting with token bucket and sliding window algorithms."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Token bucket rate limiter.

    Tokens refill at a constant rate up to capacity.
    """

    capacity: float
    refill_rate: float  # tokens per second
    _tokens: float = field(init=False, default=0.0)
    _last_refill: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = 0.0  # sentinel; set on first operation

    def can_consume(self, tokens: float = 1.0, now: float | None = None) -> bool:
        """Check if tokens are available without consuming them."""
        self._refill(now)
        return self._tokens >= tokens

    def consume(self, tokens: float = 1.0, now: float | None = None) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        self._refill(now)
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def available(self, now: float | None = None) -> float:
        self._refill(now)
        return self._tokens

    def _refill(self, now: float | None = None) -> None:
        now = now or time.monotonic()
        if self._last_refill == 0.0:
            self._last_refill = now
            return
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now


@dataclass
class SlidingWindow:
    """Sliding window rate limiter."""

    window_seconds: float
    max_requests: int
    _timestamps: list[float] = field(init=False, default_factory=list)

    def allow(self, now: float | None = None) -> bool:
        """Check if a request is allowed within the window."""
        now = now or time.monotonic()
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) < self.max_requests:
            self._timestamps.append(now)
            return True
        return False

    def can_allow(self, now: float | None = None) -> bool:
        """Check if a request would be allowed without recording it."""
        now = now or time.monotonic()
        cutoff = now - self.window_seconds
        active = sum(1 for t in self._timestamps if t > cutoff)
        return active < self.max_requests

    def count(self, now: float | None = None) -> int:
        now = now or time.monotonic()
        cutoff = now - self.window_seconds
        return sum(1 for t in self._timestamps if t > cutoff)


class CompositeLimit:
    """Combines multiple rate limiters with AND logic."""

    def __init__(self, *limiters: TokenBucket | SlidingWindow) -> None:
        self._limiters = list(limiters)

    def allow(self, now: float | None = None) -> bool:
        """Returns True only if ALL limiters allow.

        Uses a two-phase approach: first check all limiters without
        consuming, then consume only if all would allow. This prevents
        token consumption when a later limiter denies the request.
        """
        # Phase 1: dry-run check
        for limiter in self._limiters:
            if isinstance(limiter, TokenBucket):
                if not limiter.can_consume(1.0, now):
                    return False
            elif isinstance(limiter, SlidingWindow):
                if not limiter.can_allow(now):
                    return False

        # Phase 2: all passed, actually consume
        for limiter in self._limiters:
            if isinstance(limiter, TokenBucket):
                limiter.consume(1.0, now)
            elif isinstance(limiter, SlidingWindow):
                limiter.allow(now)
        return True


class KeyedRateLimiter:
    """Per-key rate limiting (e.g., per tenant, user, or API key)."""

    def __init__(self, factory: callable) -> None:
        self._factory = factory
        self._limiters: dict[str, TokenBucket | SlidingWindow] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        if key not in self._limiters:
            self._limiters[key] = self._factory()
        limiter = self._limiters[key]
        if isinstance(limiter, TokenBucket):
            return limiter.consume(1.0, now)
        return limiter.allow(now)

    def get_limiter(self, key: str) -> TokenBucket | SlidingWindow | None:
        return self._limiters.get(key)

    def reset(self, key: str) -> None:
        self._limiters.pop(key, None)
