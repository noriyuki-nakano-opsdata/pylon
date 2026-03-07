"""Memory Repository — 4-layer memory CRUD (FR-07).

Layers: Working (in-process), Episodic (30d TTL), Semantic (permanent), Procedural (permanent).
Per-tenant schema isolation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class EpisodicEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    content: str = ""
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30)
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SemanticEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    key: str = ""
    content: str = ""
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProceduralEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pattern: str = ""
    action: str = ""
    success_rate: float = 0.0
    execution_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryRepository:
    """In-memory implementation of the 4-layer memory repository.

    Production uses PostgreSQL + pgvector with per-tenant schemas.
    """

    def __init__(self) -> None:
        self._episodic: dict[str, EpisodicEntry] = {}
        self._semantic: dict[str, SemanticEntry] = {}
        self._procedural: dict[str, ProceduralEntry] = {}

    # -- Episodic --

    async def store_episodic(self, entry: EpisodicEntry) -> EpisodicEntry:
        self._episodic[entry.id] = entry
        return entry

    async def get_episodic(self, id: str) -> EpisodicEntry | None:
        entry = self._episodic.get(id)
        if entry and entry.expires_at < datetime.now(timezone.utc):
            del self._episodic[id]
            return None
        return entry

    async def list_episodic(self, agent_id: str, *, limit: int = 50) -> list[EpisodicEntry]:
        now = datetime.now(timezone.utc)
        results = [
            e for e in self._episodic.values()
            if e.agent_id == agent_id and e.expires_at >= now
        ]
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    async def cleanup_expired(self) -> int:
        """Remove expired episodic entries. Returns count removed."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._episodic.items() if v.expires_at < now]
        for k in expired:
            del self._episodic[k]
        return len(expired)

    # -- Semantic --

    async def store_semantic(self, entry: SemanticEntry) -> SemanticEntry:
        self._semantic[entry.id] = entry
        return entry

    async def get_semantic(self, id: str) -> SemanticEntry | None:
        return self._semantic.get(id)

    async def get_semantic_by_key(self, key: str) -> SemanticEntry | None:
        for entry in self._semantic.values():
            if entry.key == key:
                return entry
        return None

    async def list_semantic(self, *, limit: int = 50) -> list[SemanticEntry]:
        results = sorted(self._semantic.values(), key=lambda e: e.updated_at, reverse=True)
        return results[:limit]

    # -- Procedural --

    async def store_procedural(self, entry: ProceduralEntry) -> ProceduralEntry:
        self._procedural[entry.id] = entry
        return entry

    async def get_procedural(self, id: str) -> ProceduralEntry | None:
        return self._procedural.get(id)

    async def update_procedural_stats(
        self, id: str, *, success: bool
    ) -> ProceduralEntry | None:
        entry = self._procedural.get(id)
        if not entry:
            return None
        entry.execution_count += 1
        total = entry.execution_count
        if success:
            entry.success_rate = (entry.success_rate * (total - 1) + 1.0) / total
        else:
            entry.success_rate = (entry.success_rate * (total - 1)) / total
        entry.updated_at = datetime.now(timezone.utc)
        return entry

    async def list_procedural(self, *, limit: int = 50) -> list[ProceduralEntry]:
        results = sorted(
            self._procedural.values(), key=lambda e: e.success_rate, reverse=True
        )
        return results[:limit]
