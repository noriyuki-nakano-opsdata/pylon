"""Fallback chain and cached fallback implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = object()


@dataclass
class FallbackResult:
    value: Any = None
    source_index: int = -1
    errors: list[Exception] = field(default_factory=list)


class AllFallbacksFailedError(RuntimeError):
    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        super().__init__(f"All {len(errors)} fallbacks failed")


class FallbackChain:
    def __init__(self, fns: list[Callable[..., Any]] | None = None) -> None:
        self._fns: list[Callable[..., Any]] = list(fns) if fns else []
        self._default: Any = _SENTINEL

    def add(self, fn: Callable[..., Any]) -> FallbackChain:
        self._fns.append(fn)
        return self

    def with_default(self, value: Any) -> FallbackChain:
        self._default = value
        return self

    def execute(self, *args: Any, **kwargs: Any) -> FallbackResult:
        errors: list[Exception] = []
        for i, fn in enumerate(self._fns):
            try:
                result = fn(*args, **kwargs)
                return FallbackResult(value=result, source_index=i, errors=errors)
            except Exception as exc:
                errors.append(exc)

        if self._default is not _SENTINEL:
            return FallbackResult(value=self._default, source_index=-1, errors=errors)

        raise AllFallbacksFailedError(errors)


class CachedFallback:
    """Caches the last successful result and returns it when the primary fails."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = fn
        self._cached: Any = _SENTINEL
        self._has_cache: bool = False

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            result = self._fn(*args, **kwargs)
            self._cached = result
            self._has_cache = True
            return result
        except Exception:
            if self._has_cache:
                return self._cached
            raise

    @property
    def has_cache(self) -> bool:
        return self._has_cache

    def clear_cache(self) -> None:
        self._cached = _SENTINEL
        self._has_cache = False
