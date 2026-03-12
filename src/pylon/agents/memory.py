"""Two-tier agent memory: core (in-context) + archival (searchable).

Inspired by MemGPT/Letta's virtual memory architecture:
- Core Memory: always visible in the LLM prompt (persona, task context)
- Archival Memory: searchable via embedding similarity
- Recall Memory: conversation history with sliding window

Agents can self-edit memory through tool calls:
- core_memory_append / core_memory_replace
- archival_memory_insert / archival_memory_search
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    """A single entry in archival memory."""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    embedding: list[float] | None = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


@dataclass
class CoreMemoryBlock:
    """A named block of core memory, always visible in context."""

    label: str  # e.g., "persona", "task", "user"
    content: str
    max_chars: int = 2000

    def append(self, text: str) -> bool:
        """Append text to this block. Returns False if would exceed limit."""
        new_content = self.content + "\n" + text if self.content else text
        if len(new_content) > self.max_chars:
            return False
        self.content = new_content
        return True

    def replace(self, old: str, new: str) -> bool:
        """Replace text in this block. Returns False if old not found."""
        if old not in self.content:
            return False
        self.content = self.content.replace(old, new, 1)
        return True

    @property
    def usage_ratio(self) -> float:
        return len(self.content) / self.max_chars if self.max_chars else 0.0


class CoreMemory:
    """In-context memory blocks, always included in the LLM prompt."""

    def __init__(self, blocks: dict[str, CoreMemoryBlock] | None = None) -> None:
        self._blocks = blocks or {}

    def add_block(self, label: str, content: str = "", max_chars: int = 2000) -> None:
        self._blocks[label] = CoreMemoryBlock(
            label=label, content=content, max_chars=max_chars
        )

    def get_block(self, label: str) -> CoreMemoryBlock | None:
        return self._blocks.get(label)

    def append(self, label: str, text: str) -> bool:
        block = self._blocks.get(label)
        if block is None:
            return False
        return block.append(text)

    def replace(self, label: str, old: str, new: str) -> bool:
        block = self._blocks.get(label)
        if block is None:
            return False
        return block.replace(old, new)

    def to_prompt_text(self) -> str:
        """Format all core memory blocks for LLM context injection."""
        if not self._blocks:
            return ""
        lines = ["<core_memory>"]
        for label, block in self._blocks.items():
            if block.content:
                lines.append(f"[{label}]")
                lines.append(block.content)
        lines.append("</core_memory>")
        return "\n".join(lines)

    @property
    def total_chars(self) -> int:
        return sum(len(b.content) for b in self._blocks.values())

    @property
    def block_labels(self) -> list[str]:
        return list(self._blocks.keys())


class ArchivalMemory:
    """Searchable long-term memory using embedding similarity.

    Uses an in-memory vector store by default. For production, connect
    to an external vector database.

    When ``sentence-transformers`` is not available, falls back to
    TF-IDF based similarity search.
    """

    def __init__(
        self,
        *,
        encoder: Any | None = None,
        max_entries: int = 10000,
    ) -> None:
        self._entries: list[MemoryEntry] = []
        self._max_entries = max_entries
        self._encoder = encoder
        self._use_embeddings = encoder is not None

    def add(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Add content to archival memory. Returns entry ID."""
        entry_id = hashlib.md5(
            f"{content}{time.time()}".encode()
        ).hexdigest()[:12]

        embedding = None
        if self._use_embeddings and self._encoder is not None:
            try:
                embedding = self._encoder.encode(content).tolist() if self._encoder else None
            except Exception:
                pass

        entry = MemoryEntry(
            id=entry_id,
            content=content,
            metadata=metadata or {},
            embedding=embedding,
        )
        self._entries.append(entry)

        # Evict oldest if over limit
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

        return entry_id

    def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Search archival memory by similarity."""
        if not self._entries:
            return []

        if self._use_embeddings and self._encoder is not None:
            return self._search_by_embedding(query, top_k)
        return self._search_by_keyword(query, top_k)

    def _search_by_embedding(self, query: str, top_k: int) -> list[MemoryEntry]:
        """Search using cosine similarity on embeddings."""
        try:
            if not self._encoder:
                return self._search_by_keyword(query, top_k)
            query_emb = self._encoder.encode(query)
        except Exception:
            return self._search_by_keyword(query, top_k)

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._entries:
            if entry.embedding is None:
                continue
            score = _cosine_similarity(query_emb, entry.embedding)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def _search_by_keyword(self, query: str, top_k: int) -> list[MemoryEntry]:
        """Fallback search using simple keyword matching."""
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._entries:
            content_lower = entry.content.lower()
            content_terms = set(content_lower.split())
            overlap = query_terms & content_terms
            if overlap:
                score = len(overlap) / max(len(query_terms), 1)
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def get(self, entry_id: str) -> MemoryEntry | None:
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def delete(self, entry_id: str) -> bool:
        for i, entry in enumerate(self._entries):
            if entry.id == entry_id:
                self._entries.pop(i)
                return True
        return False

    @property
    def size(self) -> int:
        return len(self._entries)


class WorkingMemory:
    """Combined core + archival memory for an agent.

    Provides the full memory interface that agents interact with,
    including MemGPT-style tool definitions for self-editing.
    """

    def __init__(
        self,
        *,
        core: CoreMemory | None = None,
        archival: ArchivalMemory | None = None,
        recall_window: int = 20,
    ) -> None:
        self.core = core or CoreMemory()
        self.archival = archival or ArchivalMemory()
        self._recall_buffer: list[dict[str, Any]] = []
        self._recall_window = recall_window

    def record_message(self, role: str, content: str) -> None:
        """Record a message in recall memory (sliding window)."""
        self._recall_buffer.append(
            {"role": role, "content": content, "timestamp": time.time()}
        )
        if len(self._recall_buffer) > self._recall_window:
            # Move oldest messages to archival
            evicted = self._recall_buffer[: -self._recall_window]
            self._recall_buffer = self._recall_buffer[-self._recall_window :]
            for msg in evicted:
                self.archival.add(
                    f"[{msg['role']}] {msg['content']}",
                    metadata={"source": "recall_eviction"},
                )

    def to_context(self) -> str:
        """Generate the full memory context for prompt injection."""
        parts: list[str] = []

        core_text = self.core.to_prompt_text()
        if core_text:
            parts.append(core_text)

        return "\n\n".join(parts)

    @staticmethod
    def memory_tool_definitions() -> list[dict[str, Any]]:
        """Return tool definitions for MemGPT-style memory self-editing."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "core_memory_append",
                    "description": "Append text to a core memory block.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["label", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "core_memory_replace",
                    "description": "Replace text in a core memory block.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "old_content": {"type": "string"},
                            "new_content": {"type": "string"},
                        },
                        "required": ["label", "old_content", "new_content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "archival_memory_insert",
                    "description": "Save information to archival memory for later retrieval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "archival_memory_search",
                    "description": "Search archival memory for relevant information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "default": 5},
                        },
                        "required": ["query"],
                    },
                },
            },
        ]


def _cosine_similarity(a: Any, b: Any) -> float:
    """Compute cosine similarity between two vectors.

    Uses numpy if available, otherwise falls back to pure Python.
    """
    try:
        import numpy as np

        a_arr = np.asarray(a, dtype=float)
        b_arr = np.asarray(b, dtype=float)
        dot = np.dot(a_arr, b_arr)
        norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        return float(dot / norm) if norm > 0 else 0.0
    except ImportError:
        # Pure Python fallback
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0.0
