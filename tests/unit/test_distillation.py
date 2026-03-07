"""Tests for memory distillation with quality gate."""

from __future__ import annotations

import pytest

from pylon.repository.distillation import (
    AgentSpecificStrategy,
    DistillationConfig,
    DistillationReport,
    FrequencyStrategy,
    MemoryDistiller,
    QualityGate,
    RecencyStrategy,
)
from pylon.repository.memory import EpisodicEntry, MemoryRepository, SemanticEntry


# -- FrequencyStrategy --


class TestFrequencyStrategy:
    def test_extracts_recurring_patterns(self) -> None:
        episodes = [
            EpisodicEntry(agent_id="a1", content="The user requested authentication fix"),
            EpisodicEntry(agent_id="a1", content="Authentication fix was applied successfully"),
            EpisodicEntry(agent_id="a1", content="Another authentication fix needed for login"),
        ]
        strategy = FrequencyStrategy(overlap_threshold=0.3)
        patterns = strategy.extract(episodes)
        assert len(patterns) >= 1
        assert patterns[0]["confidence"] > 0
        assert "frequency" in patterns[0]["metadata"]["strategy"]

    def test_no_patterns_from_single_episode(self) -> None:
        episodes = [EpisodicEntry(agent_id="a1", content="Single episode here")]
        strategy = FrequencyStrategy()
        patterns = strategy.extract(episodes)
        assert patterns == []

    def test_no_patterns_from_unrelated_content(self) -> None:
        episodes = [
            EpisodicEntry(agent_id="a1", content="alpha bravo charlie"),
            EpisodicEntry(agent_id="a1", content="xray yankee zulu"),
        ]
        strategy = FrequencyStrategy(overlap_threshold=0.8)
        patterns = strategy.extract(episodes)
        assert patterns == []


# -- RecencyStrategy --


class TestRecencyStrategy:
    def test_extracts_recent_patterns(self) -> None:
        episodes = [
            EpisodicEntry(agent_id="a1", content="Recent task completed"),
            EpisodicEntry(agent_id="a1", content="Another recent activity"),
        ]
        strategy = RecencyStrategy(decay_days=7)
        patterns = strategy.extract(episodes)
        assert len(patterns) == 1
        assert patterns[0]["metadata"]["strategy"] == "recency"

    def test_empty_episodes(self) -> None:
        strategy = RecencyStrategy()
        patterns = strategy.extract([])
        assert patterns == []


# -- AgentSpecificStrategy --


class TestAgentSpecificStrategy:
    def test_per_agent_patterns(self) -> None:
        episodes = [
            EpisodicEntry(agent_id="coder", content="Fixed authentication bug in module"),
            EpisodicEntry(agent_id="coder", content="Fixed validation bug in module"),
            EpisodicEntry(agent_id="tester", content="Ran integration tests suite"),
            EpisodicEntry(agent_id="tester", content="Ran unit tests suite"),
        ]
        strategy = AgentSpecificStrategy()
        patterns = strategy.extract(episodes)
        assert len(patterns) >= 1
        agent_ids = [p["metadata"]["agent_id"] for p in patterns]
        assert any(a in agent_ids for a in ("coder", "tester"))

    def test_empty_episodes(self) -> None:
        strategy = AgentSpecificStrategy()
        assert strategy.extract([]) == []


# -- QualityGate --


class TestQualityGate:
    def setup_method(self) -> None:
        self.config = DistillationConfig(confidence_threshold=0.3)
        self.gate = QualityGate(self.config)

    def test_check_confidence_pass(self) -> None:
        assert self.gate.check_confidence(0.5) is True

    def test_check_confidence_fail(self) -> None:
        assert self.gate.check_confidence(0.1) is False

    def test_check_duplicate_detected(self) -> None:
        existing = [SemanticEntry(content="existing pattern")]
        assert self.gate.check_duplicate("Existing Pattern", existing) is True

    def test_check_duplicate_not_found(self) -> None:
        existing = [SemanticEntry(content="existing pattern")]
        assert self.gate.check_duplicate("new pattern", existing) is False

    def test_check_relevance_empty(self) -> None:
        assert self.gate.check_relevance("", "agent-1") == 0.0

    def test_check_relevance_with_agent_bonus(self) -> None:
        score = self.gate.check_relevance(
            "The agent-1 completed a complex multi-step task involving deployment",
            "agent-1",
        )
        assert score > 0.3

    def test_validate_accepts_good_candidate(self) -> None:
        candidate = SemanticEntry(
            content="A sufficiently detailed pattern about recurring deployment issues across services",
            metadata={"agent_id": "coder"},
        )
        ok, reason = self.gate.validate(candidate, [])
        assert ok is True
        assert reason == "Accepted"

    def test_validate_rejects_empty(self) -> None:
        candidate = SemanticEntry(content="", metadata={"agent_id": "coder"})
        ok, reason = self.gate.validate(candidate, [])
        assert ok is False
        assert "Empty" in reason

    def test_validate_rejects_duplicate(self) -> None:
        existing = [SemanticEntry(content="known pattern")]
        candidate = SemanticEntry(
            content="Known Pattern", metadata={"agent_id": "coder"}
        )
        ok, reason = self.gate.validate(candidate, existing)
        assert ok is False
        assert "Duplicate" in reason

    def test_validate_rejects_low_relevance(self) -> None:
        gate = QualityGate(DistillationConfig(confidence_threshold=0.9))
        candidate = SemanticEntry(content="hi", metadata={"agent_id": "x"})
        ok, reason = gate.validate(candidate, [])
        assert ok is False
        assert "relevance" in reason.lower()


# -- MemoryDistiller --


class TestMemoryDistiller:
    @pytest.fixture
    def repo(self) -> MemoryRepository:
        return MemoryRepository()

    @pytest.mark.asyncio
    async def test_distill_below_min_episodes(self, repo: MemoryRepository) -> None:
        config = DistillationConfig(min_episodes=5)
        await repo.store_episodic(EpisodicEntry(agent_id="a1", content="only one"))
        distiller = MemoryDistiller(repo, config)
        report = await distiller.distill("a1")
        assert report.episodes_scanned == 1
        assert report.patterns_extracted == 0
        assert report.patterns_accepted == 0

    @pytest.mark.asyncio
    async def test_distill_extracts_and_stores(self, repo: MemoryRepository) -> None:
        for i in range(5):
            await repo.store_episodic(
                EpisodicEntry(
                    agent_id="coder",
                    content=f"Fixed authentication bug in login module iteration {i}",
                )
            )

        config = DistillationConfig(min_episodes=3, confidence_threshold=0.1)
        distiller = MemoryDistiller(repo, config, strategies=[FrequencyStrategy(0.3)])
        report = await distiller.distill("coder")

        assert isinstance(report, DistillationReport)
        assert report.agent_id == "coder"
        assert report.episodes_scanned == 5
        assert report.patterns_extracted >= 1
        assert report.patterns_accepted + report.patterns_rejected == report.patterns_extracted

        semantic = await repo.list_semantic()
        assert len(semantic) == report.patterns_accepted

    @pytest.mark.asyncio
    async def test_distill_report_fields(self, repo: MemoryRepository) -> None:
        config = DistillationConfig(min_episodes=2, confidence_threshold=0.1)
        for i in range(3):
            await repo.store_episodic(
                EpisodicEntry(
                    agent_id="agent-x",
                    content=f"Repeated deployment workflow step {i} with monitoring",
                )
            )
        distiller = MemoryDistiller(repo, config, strategies=[FrequencyStrategy(0.3)])
        report = await distiller.distill("agent-x")
        assert report.quality_score >= 0.0
        assert report.quality_score <= 1.0

    @pytest.mark.asyncio
    async def test_distill_empty_episodes(self, repo: MemoryRepository) -> None:
        config = DistillationConfig(min_episodes=1)
        distiller = MemoryDistiller(repo, config)
        report = await distiller.distill("nonexistent")
        assert report.episodes_scanned == 0
        assert report.patterns_extracted == 0

    @pytest.mark.asyncio
    async def test_distill_single_episode(self, repo: MemoryRepository) -> None:
        await repo.store_episodic(
            EpisodicEntry(agent_id="solo", content="one and only")
        )
        config = DistillationConfig(min_episodes=2)
        distiller = MemoryDistiller(repo, config)
        report = await distiller.distill("solo")
        assert report.episodes_scanned == 1
        assert report.patterns_extracted == 0

    @pytest.mark.asyncio
    async def test_distill_all(self, repo: MemoryRepository) -> None:
        for i in range(3):
            await repo.store_episodic(
                EpisodicEntry(agent_id="alpha", content=f"Alpha task processing step {i}")
            )
            await repo.store_episodic(
                EpisodicEntry(agent_id="beta", content=f"Beta task processing step {i}")
            )

        config = DistillationConfig(min_episodes=2, confidence_threshold=0.1)
        distiller = MemoryDistiller(repo, config, strategies=[FrequencyStrategy(0.3)])
        reports = await distiller.distill_all()
        assert len(reports) == 2
        agent_ids = {r.agent_id for r in reports}
        assert agent_ids == {"alpha", "beta"}
