"""Repository Protocol — L4 abstraction layer (SPECIFICATION v1.1 §2.1).

L3 modules access L4 only through Repository interfaces.
No direct SQL/NATS from L3.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class ReadRepository(Protocol[T]):
    """Read-side repository contract."""

    async def get(self, id: str) -> T | None:
        """Get entity by ID."""
        ...

    async def list(self, *, limit: int = 100, offset: int = 0, **filters: Any) -> list[T]:
        """List entities with optional filters."""
        ...


@runtime_checkable
class WriteRepository(Protocol[T]):
    """Write-side repository contract."""

    async def create(self, entity: T) -> T:
        """Create a new entity."""
        ...

    async def update(self, id: str, **updates: Any) -> T | None:
        """Update entity fields."""
        ...

    async def delete(self, id: str) -> bool:
        """Delete entity by ID. Returns True if deleted."""
        ...


@runtime_checkable
class Repository(ReadRepository[T], WriteRepository[T], Protocol[T]):
    """Backward-compatible full repository contract."""


@runtime_checkable
class SearchableRepository(ReadRepository[T], Protocol[T]):
    """Repository with vector search capability."""

    async def search(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
        threshold: float = 0.7,
        **filters: Any,
    ) -> list[tuple[T, float]]:
        """Search by vector similarity. Returns (entity, score) pairs."""
        ...
