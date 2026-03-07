"""API middleware: authentication, tenant isolation, rate limiting."""

from __future__ import annotations

import hashlib
import secrets as _secrets
import time
from dataclasses import dataclass, field
from typing import Any

from pylon.api.server import HandlerFunc, Request, Response


class AuthMiddleware:
    """Bearer token authentication middleware."""

    def __init__(self, valid_tokens: set[str] | None = None) -> None:
        self._valid_tokens = valid_tokens or set()

    def add_token(self, token: str) -> None:
        self._valid_tokens.add(token)

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        # Skip auth for health endpoint
        if request.path == "/health":
            return next_handler(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return Response(status_code=401, body={"error": "Missing or invalid Authorization header"})

        token = auth[7:]
        if not any(_secrets.compare_digest(token, t) for t in self._valid_tokens):
            return Response(status_code=401, body={"error": "Invalid token"})

        request.context["authenticated"] = True
        request.context["token_hash"] = hashlib.sha256(token.encode()).hexdigest()[:16]
        return next_handler(request)


class TenantMiddleware:
    """Extracts X-Tenant-ID header and injects into request context."""

    def __init__(self, *, require_tenant: bool = True) -> None:
        self._require = require_tenant

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        # Skip for health endpoint
        if request.path == "/health":
            return next_handler(request)

        tenant_id = request.headers.get("x-tenant-id", "")
        if not tenant_id and self._require:
            return Response(status_code=400, body={"error": "X-Tenant-ID header is required"})

        request.context["tenant_id"] = tenant_id or "default"
        return next_handler(request)


@dataclass
class _TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float
    refill_rate: float  # tokens per second
    last_refill: float = 0.0

    def consume(self, now: float) -> bool:
        """Try to consume one token. Returns True if allowed."""
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware:
    """Per-tenant token bucket rate limiter."""

    def __init__(
        self,
        *,
        requests_per_second: float = 10.0,
        burst: int = 20,
    ) -> None:
        self._rps = requests_per_second
        self._burst = burst
        self._buckets: dict[str, _TokenBucket] = {}

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        tenant_id = request.context.get("tenant_id", "default")
        bucket = self._buckets.get(tenant_id)
        if bucket is None:
            bucket = _TokenBucket(
                capacity=self._burst,
                tokens=float(self._burst),
                refill_rate=self._rps,
                last_refill=time.monotonic(),
            )
            self._buckets[tenant_id] = bucket

        if not bucket.consume(time.monotonic()):
            return Response(
                status_code=429,
                body={"error": "Rate limit exceeded"},
                headers={
                    "content-type": "application/json",
                    "retry-after": str(max(1, int(1.0 / self._rps))),
                },
            )

        return next_handler(request)


class MiddlewareChain:
    """Convenience builder for chaining multiple middlewares."""

    def __init__(self) -> None:
        self._middlewares: list[Any] = []

    def add(self, middleware: Any) -> MiddlewareChain:
        self._middlewares.append(middleware)
        return self

    @property
    def middlewares(self) -> list[Any]:
        return list(self._middlewares)
