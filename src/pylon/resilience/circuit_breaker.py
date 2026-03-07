"""CircuitBreaker pattern implementation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
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
    half_open_max_calls: int = 2

    def __post_init__(self) -> None:
        if self.half_open_max_calls < self.success_threshold:
            raise ValueError(
                f"half_open_max_calls ({self.half_open_max_calls}) must be "
                f">= success_threshold ({self.success_threshold})"
            )


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
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        transition = None
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._config.timeout:
                    transition = self._transition(CircuitState.HALF_OPEN)
            current = self._state
        self._fire_state_change(transition)
        return current

    @property
    def metrics(self) -> CircuitMetrics:
        return self._metrics

    def _transition(self, new_state: CircuitState) -> tuple[CircuitState, CircuitState] | None:
        """Transition to a new state. Returns (old, new) if changed, None otherwise.

        Must be called with self._lock held. The caller is responsible for
        invoking _fire_state_change() outside the lock with the returned tuple.
        """
        if new_state == self._state:
            return None
        old = self._state
        self._state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._consecutive_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
        elif new_state == CircuitState.OPEN:
            self._opened_at = time.monotonic()
        return (old, new_state)

    def _fire_state_change(self, transition: tuple[CircuitState, CircuitState] | None) -> None:
        """Invoke state change callback outside the lock."""
        if transition is not None and self._on_state_change:
            self._on_state_change(transition[0], transition[1])

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        transition = None
        with self._lock:
            current = self._state
            if current == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._config.timeout:
                    transition = self._transition(CircuitState.HALF_OPEN)
                    current = self._state
                else:
                    remaining = max(
                        0.0,
                        self._config.timeout - (time.monotonic() - self._opened_at),
                    )
                    raise CircuitOpenError(remaining)

            self._metrics.total_calls += 1

            if current == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitOpenError(0.0)
                self._half_open_calls += 1

        self._fire_state_change(transition)

        try:
            result = fn(*args, **kwargs)
            with self._lock:
                t = self._on_success()
            self._fire_state_change(t)
            return result
        except Exception:
            with self._lock:
                t = self._on_failure()
            self._fire_state_change(t)
            raise

    def _on_success(self) -> tuple[CircuitState, CircuitState] | None:
        self._metrics.successes += 1
        self._consecutive_failures = 0
        self._consecutive_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            if self._consecutive_successes >= self._config.success_threshold:
                return self._transition(CircuitState.CLOSED)
        return None

    def _on_failure(self) -> tuple[CircuitState, CircuitState] | None:
        self._metrics.failures += 1
        self._metrics.last_failure_time = time.monotonic()
        self._consecutive_failures += 1
        self._consecutive_successes = 0

        if self._state == CircuitState.HALF_OPEN:
            return self._transition(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self._config.failure_threshold:
                return self._transition(CircuitState.OPEN)
        return None

    def reset(self) -> None:
        with self._lock:
            transition = self._transition(CircuitState.CLOSED)
            self._metrics = CircuitMetrics()
            self._consecutive_failures = 0
            self._consecutive_successes = 0
        self._fire_state_change(transition)

    def force_open(self) -> None:
        with self._lock:
            transition = self._transition(CircuitState.OPEN)
        self._fire_state_change(transition)

    def force_close(self) -> None:
        with self._lock:
            transition = self._transition(CircuitState.CLOSED)
        self._fire_state_change(transition)
