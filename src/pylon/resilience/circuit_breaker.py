"""CircuitBreaker pattern implementation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    def __init__(self, remaining: float = 0.0) -> None:
        self.remaining = remaining
        super().__init__(f"Circuit is OPEN (retry in {remaining:.1f}s)")


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0
    half_open_max_calls: int = 1


@dataclass
class CircuitMetrics:
    total_calls: int = 0
    failures: int = 0
    successes: int = 0
    last_failure_time: float | None = None


class CircuitBreaker:
    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        on_state_change: Callable[[CircuitState, CircuitState], None] | None = None,
    ) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._on_state_change = on_state_change
        self._metrics = CircuitMetrics()
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._opened_at: float = 0.0
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self._config.timeout:
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    @property
    def metrics(self) -> CircuitMetrics:
        return self._metrics

    def _transition(self, new_state: CircuitState) -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._consecutive_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
        elif new_state == CircuitState.OPEN:
            self._opened_at = time.monotonic()
        if self._on_state_change:
            self._on_state_change(old, new_state)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        current = self.state  # triggers timeout check
        self._metrics.total_calls += 1

        if current == CircuitState.OPEN:
            remaining = max(0.0, self._config.timeout - (time.monotonic() - self._opened_at))
            raise CircuitOpenError(remaining)

        if current == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._config.half_open_max_calls:
                raise CircuitOpenError(0.0)
            self._half_open_calls += 1

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        self._metrics.successes += 1
        self._consecutive_failures = 0
        self._consecutive_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            if self._consecutive_successes >= self._config.success_threshold:
                self._transition(CircuitState.CLOSED)

    def _on_failure(self) -> None:
        self._metrics.failures += 1
        self._metrics.last_failure_time = time.monotonic()
        self._consecutive_failures += 1
        self._consecutive_successes = 0

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self._config.failure_threshold:
                self._transition(CircuitState.OPEN)

    def reset(self) -> None:
        self._transition(CircuitState.CLOSED)
        self._metrics = CircuitMetrics()
        self._consecutive_failures = 0
        self._consecutive_successes = 0

    def force_open(self) -> None:
        self._transition(CircuitState.OPEN)

    def force_close(self) -> None:
        self._transition(CircuitState.CLOSED)
