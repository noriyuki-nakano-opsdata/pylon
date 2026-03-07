"""Generic resource pool with bounded capacity."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pylon.errors import PylonError


class PoolExhaustedError(PylonError):
    """Raised when the resource pool has no available items."""

    code = "POOL_EXHAUSTED"
    status_code = 429


@dataclass
class PoolStats:
    """Pool usage statistics."""

    active: int = 0
    idle: int = 0
    total_created: int = 0
    wait_count: int = 0


@dataclass
class PoolConfig:
    """Resource pool configuration."""

    min_size: int = 0
    max_size: int = 10
    idle_timeout_seconds: float = 300.0
    validation_fn: Callable[[object], bool] | None = None


class ResourcePool[T]:
    """Bounded resource pool with acquire/release and context manager support."""

    def __init__(
        self,
        factory: Callable[[], T],
        config: PoolConfig | None = None,
    ) -> None:
        self._factory = factory
        self._config = config or PoolConfig()
        self._idle: deque[T] = deque()
        self._active: set[int] = set()  # id(item) tracking
        self._all: dict[int, T] = {}
        self._stats = PoolStats()

    @property
    def stats(self) -> PoolStats:
        self._stats.active = len(self._active)
        self._stats.idle = len(self._idle)
        return self._stats

    def acquire(self) -> T:
        """Acquire a resource from the pool."""
        # Try idle items first
        while self._idle:
            item = self._idle.popleft()
            if self._is_valid(item):
                self._active.add(id(item))
                return item
            # Invalid item - discard
            self._all.pop(id(item), None)

        # Create new if within bounds
        total = len(self._active) + len(self._idle)
        if total >= self._config.max_size:
            self._stats.wait_count += 1
            raise PoolExhaustedError(
                f"Pool exhausted: {total}/{self._config.max_size}",
                details={"active": len(self._active), "idle": len(self._idle)},
            )

        item = self._factory()
        self._all[id(item)] = item
        self._active.add(id(item))
        self._stats.total_created += 1
        return item

    def release(self, item: T) -> None:
        """Return a resource to the pool."""
        item_id = id(item)
        if item_id not in self._active:
            return
        self._active.discard(item_id)
        if self._is_valid(item):
            self._idle.append(item)
        else:
            self._all.pop(item_id, None)

    def destroy(self, item: T) -> None:
        """Permanently remove a resource from the pool."""
        item_id = id(item)
        self._active.discard(item_id)
        # Remove from idle if present
        self._idle = deque(i for i in self._idle if id(i) != item_id)
        self._all.pop(item_id, None)

    def fill(self) -> int:
        """Pre-fill pool to min_size. Returns number created."""
        created = 0
        while len(self._idle) < self._config.min_size:
            total = len(self._active) + len(self._idle)
            if total >= self._config.max_size:
                break
            item = self._factory()
            self._all[id(item)] = item
            self._idle.append(item)
            self._stats.total_created += 1
            created += 1
        return created

    def _is_valid(self, item: T) -> bool:
        if self._config.validation_fn is None:
            return True
        return self._config.validation_fn(item)

    def __enter__(self) -> _PoolContext[T]:
        return _PoolContext(self)

    def __exit__(self, *args: object) -> None:
        pass


class _PoolContext[T]:
    """Context manager for pool acquire/release."""

    def __init__(self, pool: ResourcePool[T]) -> None:
        self._pool = pool
        self._item: T | None = None

    def acquire(self) -> T:
        self._item = self._pool.acquire()
        return self._item

    def release(self) -> None:
        if self._item is not None:
            self._pool.release(self._item)
            self._item = None


class PoolContextManager[T]:
    """Context manager that auto-acquires on enter and releases on exit."""

    def __init__(self, pool: ResourcePool[T]) -> None:
        self._pool = pool
        self._item: T | None = None

    def __enter__(self) -> T:
        self._item = self._pool.acquire()
        return self._item

    def __exit__(self, *args: object) -> None:
        if self._item is not None:
            self._pool.release(self._item)
            self._item = None
