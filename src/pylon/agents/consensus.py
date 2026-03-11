"""Consensus and voting protocols for multi-agent decision making.

Implements ReConcile-style confidence-weighted voting where multiple
agents independently evaluate a question, then reach consensus through
multi-round discussion.

Supports:
- Simple majority voting
- Confidence-weighted (ReConcile) voting
- Multi-round deliberation with re-calibration
"""

from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


class VotingStrategy(enum.Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"  # Confidence-weighted (ReConcile)
    UNANIMOUS = "unanimous"


@dataclass
class AgentVote:
    """A single agent's vote with confidence and explanation."""

    agent_id: str
    answer: str
    confidence: float  # 0.0 - 1.0
    explanation: str = ""
    round_number: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsensusResult:
    """Result of a consensus deliberation."""

    final_answer: str
    confidence: float
    votes: list[AgentVote]
    agreement_ratio: float
    rounds: int
    strategy: VotingStrategy
    dissenting_agents: list[str] = field(default_factory=list)
    discussion_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_unanimous(self) -> bool:
        return self.agreement_ratio == 1.0

    @property
    def is_contested(self) -> bool:
        return self.agreement_ratio < 0.7


class ConsensusProtocol:
    """Multi-agent consensus protocol.

    Usage:
        protocol = ConsensusProtocol(strategy=VotingStrategy.WEIGHTED)
        result = protocol.resolve(votes=[
            AgentVote(agent_id="gpt4", answer="A", confidence=0.9),
            AgentVote(agent_id="claude", answer="A", confidence=0.85),
            AgentVote(agent_id="gemini", answer="B", confidence=0.6),
        ])
    """

    def __init__(
        self,
        *,
        strategy: VotingStrategy = VotingStrategy.WEIGHTED,
        min_confidence: float = 0.5,
        required_agreement: float = 0.5,
    ) -> None:
        self._strategy = strategy
        self._min_confidence = min_confidence
        self._required_agreement = required_agreement

    def resolve(self, votes: list[AgentVote]) -> ConsensusResult:
        """Resolve votes into a consensus result."""
        if not votes:
            return ConsensusResult(
                final_answer="",
                confidence=0.0,
                votes=[],
                agreement_ratio=0.0,
                rounds=0,
                strategy=self._strategy,
            )

        # Filter by minimum confidence
        qualified = [v for v in votes if v.confidence >= self._min_confidence]
        if not qualified:
            qualified = votes  # Fall back to all votes

        if self._strategy == VotingStrategy.MAJORITY:
            return self._majority_vote(qualified, votes)
        elif self._strategy == VotingStrategy.WEIGHTED:
            return self._weighted_vote(qualified, votes)
        elif self._strategy == VotingStrategy.UNANIMOUS:
            return self._unanimous_vote(qualified, votes)
        else:
            return self._majority_vote(qualified, votes)

    def _majority_vote(
        self, qualified: list[AgentVote], all_votes: list[AgentVote]
    ) -> ConsensusResult:
        """Simple majority voting."""
        counts = Counter(v.answer for v in qualified)
        winner, winner_count = counts.most_common(1)[0]
        agreement = winner_count / len(qualified)
        avg_confidence = sum(
            v.confidence for v in qualified if v.answer == winner
        ) / max(winner_count, 1)
        dissenters = [v.agent_id for v in qualified if v.answer != winner]

        return ConsensusResult(
            final_answer=winner,
            confidence=avg_confidence,
            votes=all_votes,
            agreement_ratio=agreement,
            rounds=max(v.round_number for v in all_votes),
            strategy=self._strategy,
            dissenting_agents=dissenters,
        )

    def _weighted_vote(
        self, qualified: list[AgentVote], all_votes: list[AgentVote]
    ) -> ConsensusResult:
        """Confidence-weighted voting (ReConcile pattern)."""
        answer_weights: dict[str, float] = {}
        total_weight = 0.0

        for vote in qualified:
            weight = vote.confidence
            answer_weights[vote.answer] = (
                answer_weights.get(vote.answer, 0.0) + weight
            )
            total_weight += weight

        if not answer_weights or total_weight == 0:
            return self._majority_vote(qualified, all_votes)

        winner = max(answer_weights, key=answer_weights.get)  # type: ignore[arg-type]
        winner_weight = answer_weights[winner]
        agreement = winner_weight / total_weight
        weighted_confidence = winner_weight / max(
            sum(1 for v in qualified if v.answer == winner), 1
        )
        dissenters = [v.agent_id for v in qualified if v.answer != winner]

        return ConsensusResult(
            final_answer=winner,
            confidence=min(weighted_confidence, 1.0),
            votes=all_votes,
            agreement_ratio=agreement,
            rounds=max(v.round_number for v in all_votes),
            strategy=self._strategy,
            dissenting_agents=dissenters,
        )

    def _unanimous_vote(
        self, qualified: list[AgentVote], all_votes: list[AgentVote]
    ) -> ConsensusResult:
        """Unanimous voting — all agents must agree."""
        answers = set(v.answer for v in qualified)
        if len(answers) == 1:
            answer = answers.pop()
            avg_conf = sum(v.confidence for v in qualified) / len(qualified)
            return ConsensusResult(
                final_answer=answer,
                confidence=avg_conf,
                votes=all_votes,
                agreement_ratio=1.0,
                rounds=max(v.round_number for v in all_votes),
                strategy=self._strategy,
            )

        # No unanimous — fall back to weighted
        result = self._weighted_vote(qualified, all_votes)
        return ConsensusResult(
            final_answer=result.final_answer,
            confidence=result.confidence * 0.8,  # Penalize non-unanimous
            votes=all_votes,
            agreement_ratio=result.agreement_ratio,
            rounds=result.rounds,
            strategy=self._strategy,
            dissenting_agents=result.dissenting_agents,
        )


class DebateProtocol:
    """Two-agent debate with judge (structured argumentation).

    Two agents argue for/against a position, then a third agent judges.
    Useful for code review, security analysis, design decisions.
    """

    def __init__(self, *, max_rounds: int = 3) -> None:
        self._max_rounds = max_rounds

    def format_debate_prompt(
        self,
        *,
        question: str,
        position: str,
        opponent_arguments: list[str] | None = None,
        round_number: int = 1,
    ) -> str:
        """Format a debate prompt for one side."""
        prompt = f"Question: {question}\n"
        prompt += f"Your position: {position}\n"
        prompt += f"Round: {round_number}/{self._max_rounds}\n\n"

        if opponent_arguments:
            prompt += "Opponent's previous arguments:\n"
            for i, arg in enumerate(opponent_arguments, 1):
                prompt += f"{i}. {arg}\n"
            prompt += "\nProvide a counter-argument:\n"
        else:
            prompt += "Present your opening argument:\n"

        return prompt

    def format_judge_prompt(
        self,
        *,
        question: str,
        pro_arguments: list[str],
        con_arguments: list[str],
    ) -> str:
        """Format the judge's evaluation prompt."""
        prompt = f"Question: {question}\n\n"
        prompt += "=== Arguments FOR ===\n"
        for i, arg in enumerate(pro_arguments, 1):
            prompt += f"{i}. {arg}\n"
        prompt += "\n=== Arguments AGAINST ===\n"
        for i, arg in enumerate(con_arguments, 1):
            prompt += f"{i}. {arg}\n"
        prompt += (
            "\nEvaluate both sides and provide your verdict. "
            "Include a confidence score (0.0-1.0)."
        )
        return prompt
