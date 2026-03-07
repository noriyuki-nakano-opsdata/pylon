"""Memory Distillation — episodic-to-semantic pattern extraction with quality gate.

Collects episodic memories, extracts recurring patterns via pluggable strategies,
applies a quality gate, and stores accepted patterns as semantic entries.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from pylon.repository.memory import EpisodicEntry, MemoryRepository, SemanticEntry


@dataclass
class DistillationConfig:
    batch_size: int = 100
    min_episodes: int = 3
    confidence_threshold: float = 0.5
    max_pattern_age_days: int = 30


@dataclass
class DistillationReport:
    agent_id: str
    episodes_scanned: int
    patterns_extracted: int
    patterns_accepted: int
    patterns_rejected: int
    quality_score: float


class QualityGate:
    """Validates candidate semantic entries before storage."""

    def __init__(self, config: DistillationConfig) -> None:
        self._config = config

    def check_confidence(self, score: float) -> bool:
        return score >= self._config.confidence_threshold

    def check_duplicate(self, content: str, existing: list[SemanticEntry]) -> bool:
        """Returns True if content is a duplicate of an existing entry."""
        normalized = content.strip().lower()
        for entry in existing:
            if entry.content.strip().lower() == normalized:
                return True
        return False

    def check_relevance(self, content: str, agent_id: str) -> float:
        """Score relevance of content to the agent (0.0-1.0).

        Heuristic: longer, more specific content scores higher.
        Content mentioning the agent scores a bonus.
        """
        if not content.strip():
            return 0.0
        words = content.split()
        length_score = min(len(words) / 20.0, 1.0)
        agent_bonus = 0.2 if agent_id.lower() in content.lower() else 0.0
        return min(length_score + agent_bonus, 1.0)

    def validate(
        self, candidate: SemanticEntry, existing: list[SemanticEntry]
    ) -> tuple[bool, str]:
        """Validate a candidate semantic entry. Returns (accepted, reason)."""
        if not candidate.content.strip():
            return False, "Empty content"

        if self.check_duplicate(candidate.content, existing):
            return False, "Duplicate of existing entry"

        relevance = self.check_relevance(
            candidate.content, candidate.metadata.get("agent_id", "")
        )
        if not self.check_confidence(relevance):
            return False, f"Low relevance score: {relevance:.2f}"

        return True, "Accepted"


class DistillationStrategy(ABC):
    """Base class for pattern extraction strategies."""

    @abstractmethod
    def extract(self, episodes: list[EpisodicEntry]) -> list[dict[str, Any]]:
        """Extract patterns from episodes.

        Returns list of dicts with 'content', 'confidence', and 'metadata' keys.
        """


class FrequencyStrategy(DistillationStrategy):
    """Extract recurring patterns based on word/phrase overlap."""

    def __init__(self, overlap_threshold: float = 0.3) -> None:
        self._threshold = overlap_threshold

    def extract(self, episodes: list[EpisodicEntry]) -> list[dict[str, Any]]:
        if len(episodes) < 2:
            return []

        word_counter: Counter[str] = Counter()
        for ep in episodes:
            words = set(re.findall(r"\w+", ep.content.lower()))
            for w in words:
                word_counter[w] += 1

        total = len(episodes)
        frequent_words = {
            w for w, count in word_counter.items()
            if count / total >= self._threshold and len(w) > 2
        }

        if not frequent_words:
            return []

        # Group episodes by shared frequent words
        clusters: list[list[EpisodicEntry]] = []
        used: set[str] = set()

        for ep in episodes:
            if ep.id in used:
                continue
            ep_words = set(re.findall(r"\w+", ep.content.lower()))
            shared = ep_words & frequent_words
            if not shared:
                continue

            cluster = [ep]
            used.add(ep.id)
            for other in episodes:
                if other.id in used:
                    continue
                other_words = set(re.findall(r"\w+", other.content.lower()))
                overlap = len(shared & other_words) / max(len(shared), 1)
                if overlap >= self._threshold:
                    cluster.append(other)
                    used.add(other.id)

            if len(cluster) >= 2:
                clusters.append(cluster)

        patterns: list[dict[str, Any]] = []
        for cluster in clusters:
            all_words_sets = [
                set(re.findall(r"\w+", ep.content.lower())) for ep in cluster
            ]
            common = set.intersection(*all_words_sets) if all_words_sets else set()
            common = {w for w in common if len(w) > 2}
            if common:
                confidence = len(cluster) / total
                patterns.append({
                    "content": f"Recurring pattern ({len(cluster)} episodes): {' '.join(sorted(common))}",
                    "confidence": min(confidence, 1.0),
                    "metadata": {
                        "strategy": "frequency",
                        "episode_count": len(cluster),
                        "common_words": sorted(common),
                    },
                })

        return patterns


class RecencyStrategy(DistillationStrategy):
    """Weight recent episodes higher for pattern extraction."""

    def __init__(self, decay_days: int = 7) -> None:
        self._decay_days = decay_days

    def extract(self, episodes: list[EpisodicEntry]) -> list[dict[str, Any]]:
        if not episodes:
            return []

        now = datetime.now(timezone.utc)
        weighted: list[tuple[EpisodicEntry, float]] = []
        for ep in episodes:
            age_days = (now - ep.created_at).total_seconds() / 86400
            weight = max(1.0 - (age_days / self._decay_days), 0.1)
            weighted.append((ep, weight))

        weighted.sort(key=lambda x: x[1], reverse=True)

        patterns: list[dict[str, Any]] = []
        if weighted:
            top = weighted[: max(len(weighted) // 2, 1)]
            avg_weight = sum(w for _, w in top) / len(top)
            combined = " | ".join(ep.content[:100] for ep, _ in top[:3])
            patterns.append({
                "content": f"Recent pattern: {combined}",
                "confidence": avg_weight,
                "metadata": {
                    "strategy": "recency",
                    "episode_count": len(top),
                },
            })

        return patterns


class AgentSpecificStrategy(DistillationStrategy):
    """Per-agent pattern extraction based on content similarity."""

    def extract(self, episodes: list[EpisodicEntry]) -> list[dict[str, Any]]:
        if not episodes:
            return []

        by_agent: dict[str, list[EpisodicEntry]] = {}
        for ep in episodes:
            by_agent.setdefault(ep.agent_id, []).append(ep)

        patterns: list[dict[str, Any]] = []
        for agent_id, agent_eps in by_agent.items():
            if len(agent_eps) < 2:
                continue

            word_sets = [
                set(re.findall(r"\w+", ep.content.lower())) for ep in agent_eps
            ]
            common = set.intersection(*word_sets) if word_sets else set()
            common = {w for w in common if len(w) > 2}

            if common:
                confidence = len(agent_eps) / len(episodes)
                patterns.append({
                    "content": f"Agent '{agent_id}' pattern: {' '.join(sorted(common))}",
                    "confidence": min(confidence, 1.0),
                    "metadata": {
                        "strategy": "agent_specific",
                        "agent_id": agent_id,
                        "episode_count": len(agent_eps),
                        "common_words": sorted(common),
                    },
                })

        return patterns


class MemoryDistiller:
    """Orchestrates the distillation pipeline: collect -> extract -> gate -> store."""

    def __init__(
        self,
        repo: MemoryRepository,
        config: DistillationConfig | None = None,
        strategies: list[DistillationStrategy] | None = None,
    ) -> None:
        self._repo = repo
        self._config = config or DistillationConfig()
        self._strategies = strategies or [FrequencyStrategy()]
        self._quality_gate = QualityGate(self._config)

    async def distill(self, agent_id: str) -> DistillationReport:
        """Run distillation pipeline for a single agent."""
        episodes = await self._repo.list_episodic(
            agent_id, limit=self._config.batch_size
        )

        if len(episodes) < self._config.min_episodes:
            return DistillationReport(
                agent_id=agent_id,
                episodes_scanned=len(episodes),
                patterns_extracted=0,
                patterns_accepted=0,
                patterns_rejected=0,
                quality_score=0.0,
            )

        # Extract patterns using all strategies
        all_patterns: list[dict[str, Any]] = []
        for strategy in self._strategies:
            all_patterns.extend(strategy.extract(episodes))

        existing = await self._repo.list_semantic()
        accepted = 0
        rejected = 0

        for pattern in all_patterns:
            candidate = SemanticEntry(
                key=f"distilled-{uuid.uuid4().hex[:8]}",
                content=pattern["content"],
                metadata={
                    **pattern.get("metadata", {}),
                    "agent_id": agent_id,
                    "distilled_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            ok, reason = self._quality_gate.validate(candidate, existing)
            if ok:
                await self._repo.store_semantic(candidate)
                existing.append(candidate)
                accepted += 1
            else:
                rejected += 1

        total = accepted + rejected
        quality_score = accepted / total if total > 0 else 0.0

        return DistillationReport(
            agent_id=agent_id,
            episodes_scanned=len(episodes),
            patterns_extracted=len(all_patterns),
            patterns_accepted=accepted,
            patterns_rejected=rejected,
            quality_score=quality_score,
        )

    async def distill_all(self) -> list[DistillationReport]:
        """Run distillation for all agents with episodic entries."""
        episodes = await self._repo.list_episodic("", limit=0)

        # Collect all unique agent IDs from the repo
        agent_ids: set[str] = set()
        for entry in self._repo._episodic.values():
            agent_ids.add(entry.agent_id)

        reports: list[DistillationReport] = []
        for agent_id in sorted(agent_ids):
            report = await self.distill(agent_id)
            reports.append(report)

        return reports
