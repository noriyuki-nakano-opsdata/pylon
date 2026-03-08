"""Health check system for Pylon API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union


@dataclass(frozen=True)
class HealthCheckResult:
    """Result of a single health check."""

    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# A check callable may return a result synchronously or as a coroutine.
CheckCallable = Callable[[], Union[HealthCheckResult, Awaitable[HealthCheckResult]]]


class HealthChecker:
    """Runs registered health checks and aggregates results."""

    def __init__(self) -> None:
        self._checks: list[tuple[str, CheckCallable]] = []

    def register(self, name: str, check: CheckCallable) -> None:
        """Register a named health check."""
        self._checks.append((name, check))

    async def run_all(self) -> dict[str, Any]:
        """Execute every registered check and return an aggregate report."""
        results: list[HealthCheckResult] = []
        for name, check_fn in self._checks:
            try:
                result = check_fn()
                if hasattr(result, "__await__"):
                    result = await result
                results.append(result)  # type: ignore[arg-type]
            except Exception as exc:
                results.append(
                    HealthCheckResult(
                        name=name,
                        status="unhealthy",
                        message=str(exc),
                    )
                )

        overall = "healthy"
        for r in results:
            if r.status == "unhealthy":
                overall = "unhealthy"
                break
            if r.status == "degraded" and overall == "healthy":
                overall = "degraded"

        return {
            "status": overall,
            "checks": [
                {"name": r.name, "status": r.status, "message": r.message, **r.details}
                for r in results
            ],
        }

    def run_all_sync(self) -> dict[str, Any]:
        """Synchronous wrapper around :meth:`run_all`."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.run_all())
        finally:
            loop.close()


def _system_check() -> HealthCheckResult:
    """Basic system liveness check."""
    return HealthCheckResult(name="system", status="healthy", message="operational")


def build_default_checker() -> HealthChecker:
    """Create a :class:`HealthChecker` with default checks registered."""
    checker = HealthChecker()
    checker.register("system", _system_check)
    return checker
