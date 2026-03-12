"""Semantic tool selection for large tool registries.

When an agent has access to 100+ tools, including all of them in the
LLM prompt is impractical (context window waste and selection confusion).
This module provides intelligent tool pre-filtering based on the current
task context.

Strategy:
1. If sentence-transformers is available → semantic embedding search
2. Fallback → TF-IDF keyword matching (no external dependencies)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDescriptor:
    """Lightweight tool description for selection purposes."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def searchable_text(self) -> str:
        """Combined text for search indexing."""
        parts = [self.name, self.description, self.category]
        parts.extend(self.tags)
        for param_name, param_info in self.parameters.items():
            parts.append(param_name)
            if isinstance(param_info, dict):
                parts.append(param_info.get("description", ""))
        return " ".join(parts)


class SemanticToolSelector:
    """Select the most relevant tools for a given query.

    Automatically chooses between embedding-based and TF-IDF-based
    search depending on available dependencies.

    Usage:
        selector = SemanticToolSelector(tools)
        relevant = selector.select("read the contents of a file", top_k=5)
    """

    def __init__(
        self,
        tools: list[ToolDescriptor],
        *,
        encoder: Any | None = None,
    ) -> None:
        self._tools = tools
        self._encoder = encoder
        self._embeddings: list[Any] | None = None
        self._tfidf_index: _TFIDFIndex | None = None

        if self._encoder is not None:
            try:
                texts = [t.searchable_text for t in tools]
                self._embeddings = self._encoder.encode(texts) if self._encoder else None
            except Exception:
                self._encoder = None
                self._embeddings = None

        # Always build TF-IDF as fallback
        self._tfidf_index = _TFIDFIndex(
            [t.searchable_text for t in tools]
        )

    def select(self, query: str, top_k: int = 10) -> list[ToolDescriptor]:
        """Select the top-k most relevant tools for the query."""
        if not self._tools:
            return []

        if self._encoder is not None and self._embeddings is not None:
            return self._select_by_embedding(query, top_k)
        return self._select_by_tfidf(query, top_k)

    def select_with_scores(
        self, query: str, top_k: int = 10
    ) -> list[tuple[ToolDescriptor, float]]:
        """Select tools with relevance scores."""
        if not self._tools:
            return []

        if self._encoder is not None and self._embeddings is not None:
            return self._select_by_embedding_scored(query, top_k)
        return self._select_by_tfidf_scored(query, top_k)

    def _select_by_embedding(
        self, query: str, top_k: int
    ) -> list[ToolDescriptor]:
        return [t for t, _ in self._select_by_embedding_scored(query, top_k)]

    def _select_by_embedding_scored(
        self, query: str, top_k: int
    ) -> list[tuple[ToolDescriptor, float]]:
        try:
            import numpy as np

            if not self._encoder or self._embeddings is None:
                return self._select_by_tfidf_scored(query, top_k)
            query_emb = self._encoder.encode(query)
            similarities = np.dot(self._embeddings, query_emb) / (
                np.linalg.norm(self._embeddings, axis=1)
                * np.linalg.norm(query_emb)
                + 1e-8
            )
            top_indices = np.argsort(similarities)[-top_k:][::-1]
            return [
                (self._tools[i], float(similarities[i]))
                for i in top_indices
                if similarities[i] > 0
            ]
        except Exception:
            return self._select_by_tfidf_scored(query, top_k)

    def _select_by_tfidf(self, query: str, top_k: int) -> list[ToolDescriptor]:
        return [t for t, _ in self._select_by_tfidf_scored(query, top_k)]

    def _select_by_tfidf_scored(
        self, query: str, top_k: int
    ) -> list[tuple[ToolDescriptor, float]]:
        assert self._tfidf_index is not None
        scores = self._tfidf_index.search(query)
        scored = [
            (self._tools[i], score)
            for i, score in enumerate(scores)
            if score > 0
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ---- TF-IDF Index (zero-dependency fallback) --------------------------------


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return [t for t in re.split(r"[^a-z0-9_]+", text.lower()) if len(t) > 1]


class _TFIDFIndex:
    """Minimal TF-IDF implementation for tool search fallback.

    No external dependencies. Suitable for registries up to ~1000 tools.
    """

    def __init__(self, documents: list[str]) -> None:
        self._n_docs = len(documents)
        self._doc_tokens: list[list[str]] = []
        self._doc_tf: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}

        # Build index
        df: Counter[str] = Counter()
        for doc in documents:
            tokens = _tokenize(doc)
            self._doc_tokens.append(tokens)
            tf = Counter(tokens)
            total = max(len(tokens), 1)
            self._doc_tf.append({t: c / total for t, c in tf.items()})
            for t in set(tokens):
                df[t] += 1

        # IDF
        for term, doc_freq in df.items():
            self._idf[term] = math.log((self._n_docs + 1) / (doc_freq + 1)) + 1

    def search(self, query: str) -> list[float]:
        """Return TF-IDF similarity scores for all documents."""
        query_tokens = _tokenize(query)
        query_tf = Counter(query_tokens)
        total = max(len(query_tokens), 1)
        query_tfidf = {
            t: (c / total) * self._idf.get(t, 0.0) for t, c in query_tf.items()
        }

        scores: list[float] = []
        for doc_tf in self._doc_tf:
            doc_tfidf = {
                t: tf * self._idf.get(t, 0.0) for t, tf in doc_tf.items()
            }
            score = _cos_sim_sparse(query_tfidf, doc_tfidf)
            scores.append(score)
        return scores


def _cos_sim_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    return dot / (norm_a * norm_b) if norm_a * norm_b > 0 else 0.0
