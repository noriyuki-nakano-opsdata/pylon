"""Retry strategies with configurable backoff."""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class RetryExhaustedError(RuntimeError):
    def __init__(self, attempts: list[Exception]) -> None:
        self.attempts = attempts
        super().__init__(
            f"All {len(attempts)} retry attempts exhausted. "
            f"Last error: {attempts[-1] if attempts else 'unknown'}"
        )


class BackoffStrategy:
    def delay(self, attempt: int) -> float:
        raise NotImplementedError


class ConstantBackoff(BackoffStrategy):
    def __init__(self, delay_seconds: float = 1.0) -> None:
        self._delay = delay_seconds

    def delay(self, attempt: int) -> float:
        return self._delay


class LinearBackoff(BackoffStrategy):
    def __init__(self, initial: float = 1.0, increment: float = 1.0) -> None:
        self._initial = initial
        self._increment = increment

    def delay(self, attempt: int) -> float:
        return self._initial + self._increment * attempt


class ExponentialBackoff(BackoffStrategy):
    def __init__(self, base: float = 1.0, multiplier: float = 2.0, max_delay: float = 60.0) -> None:
        self._base = base
        self._multiplier = multiplier
        self._max_delay = max_delay

    def delay(self, attempt: int) -> float:
        return min(self._base * (self._multiplier ** attempt), self._max_delay)


class JitteredBackoff(BackoffStrategy):
    def __init__(self, base_strategy: BackoffStrategy | None = None, jitter_range: float = 0.5) -> None:
        self._base = base_strategy or ExponentialBackoff()
        self._jitter_range = jitter_range

    def delay(self, attempt: int) -> float:
        base_delay = self._base.delay(attempt)
        jitter = base_delay * self._jitter_range * random.random()
        return base_delay + jitter


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff: BackoffStrategy = field(default_factory=ConstantBackoff)
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    on_retry: Callable[[int, Exception], None] | None = None


def retry(fn: Callable[..., Any], policy: RetryPolicy | None = None, *args: Any, **kwargs: Any) -> Any:
    p = policy or RetryPolicy()
    errors: list[Exception] = []

    for attempt in range(p.max_attempts):
        try:
            return fn(*args, **kwargs)
        except p.retryable_exceptions as exc:
            errors.append(exc)
            if attempt < p.max_attempts - 1:
                if p.on_retry:
                    p.on_retry(attempt + 1, exc)
                delay = p.backoff.delay(attempt)
                time.sleep(delay)
        except Exception as exc:
            # Non-retryable exception
            raise

    raise RetryExhaustedError(errors)


def with_retry(policy: RetryPolicy | None = None) -> Callable:
    """Decorator for retry."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return retry(fn, policy, *args, **kwargs)
        return wrapper
    return decorator
