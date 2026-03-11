"""Self-critique and reflection engine for iterative improvement.

Implements the Reflexion pattern: after each execution attempt, the agent
generates a "semantic gradient" — a natural language critique of what went
wrong and how to improve.  This text is injected into the next attempt's
context, enabling learning without weight updates.

Integrates with Pylon's existing Critic → Verifier pipeline:
- Critic.evaluate() produces EvaluationResult
- ReflectionEngine.reflect() converts failed evaluations into actionable text
- The reflection text is prepended to the next iteration's messages
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReflectionEntry:
    """A single reflection produced after an evaluation."""

    iteration: int
    critique: str  # What went wrong
    suggestion: str  # How to improve
    score: float  # Evaluation score (0.0 - 1.0)
    evaluation_kind: str  # e.g. "response_quality", "tool_trajectory"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReflectionMemory:
    """Stores reflections across iterations for context injection."""

    entries: list[ReflectionEntry] = field(default_factory=list)
    max_entries: int = 10

    def add(self, entry: ReflectionEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]

    def to_prompt_text(self) -> str:
        """Format reflections for injection into LLM context."""
        if not self.entries:
            return ""

        lines = ["<reflections>", "Previous attempts and lessons learned:"]
        for entry in self.entries:
            lines.append(
                f"- Attempt {entry.iteration} (score: {entry.score:.2f}): "
                f"{entry.critique} → {entry.suggestion}"
            )
        lines.append("</reflections>")
        return "\n".join(lines)

    @property
    def latest(self) -> ReflectionEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def average_score(self) -> float:
        if not self.entries:
            return 0.0
        return sum(e.score for e in self.entries) / len(self.entries)

    @property
    def is_improving(self) -> bool:
        """Check if scores are trending upward."""
        if len(self.entries) < 2:
            return False
        recent = self.entries[-3:]
        return recent[-1].score > recent[0].score


class ReflectionEngine:
    """Generates structured reflections from evaluation results.

    Usage:
        engine = ReflectionEngine()
        entry = engine.reflect(
            iteration=1,
            evaluation_results=critic_results,
            execution_context={"code": "...", "test_results": [...]},
        )
        memory.add(entry)
        # Inject memory.to_prompt_text() into next LLM call
    """

    def __init__(
        self,
        *,
        critique_template: str | None = None,
        max_reflection_tokens: int = 500,
    ) -> None:
        self._critique_template = critique_template or self._default_template()
        self._max_tokens = max_reflection_tokens

    def reflect(
        self,
        *,
        iteration: int,
        evaluation_results: list[dict[str, Any]],
        execution_context: dict[str, Any] | None = None,
    ) -> ReflectionEntry:
        """Generate a reflection from evaluation results.

        This is a synchronous, deterministic analysis of evaluation data
        (no LLM call required). For LLM-powered deeper reflection, use
        reflect_with_llm().

        Args:
            iteration: Current iteration number.
            evaluation_results: List of evaluation result dicts with
                'kind', 'score', 'passed', 'details' fields.
            execution_context: Additional context (code changes, etc.).

        Returns:
            ReflectionEntry with critique and improvement suggestion.
        """
        failed = [r for r in evaluation_results if not r.get("passed", True)]
        if not failed:
            return ReflectionEntry(
                iteration=iteration,
                critique="All criteria passed.",
                suggestion="Continue with current approach.",
                score=1.0,
                evaluation_kind="aggregate",
            )

        avg_score = sum(r.get("score", 0.0) for r in evaluation_results) / max(
            len(evaluation_results), 1
        )

        critiques: list[str] = []
        suggestions: list[str] = []
        primary_kind = "aggregate"

        for result in failed:
            kind = result.get("kind", "unknown")
            score = result.get("score", 0.0)
            details = result.get("details", "")

            critique, suggestion = self._analyze_failure(kind, score, details)
            critiques.append(critique)
            suggestions.append(suggestion)
            if primary_kind == "aggregate":
                primary_kind = kind

        return ReflectionEntry(
            iteration=iteration,
            critique="; ".join(critiques),
            suggestion="; ".join(suggestions),
            score=avg_score,
            evaluation_kind=primary_kind,
            metadata={
                "failed_count": len(failed),
                "total_count": len(evaluation_results),
                "context": execution_context or {},
            },
        )

    def _analyze_failure(
        self, kind: str, score: float, details: str
    ) -> tuple[str, str]:
        """Analyze a specific failure and produce critique + suggestion."""
        analysis = {
            "response_quality": (
                f"Response quality score {score:.2f} below threshold",
                "Provide more detailed and specific responses",
            ),
            "tool_trajectory": (
                f"Tool usage pattern incorrect: {details}",
                "Review the expected tool call sequence and adjust approach",
            ),
            "hallucination": (
                f"Hallucination detected (score: {score:.2f}): {details}",
                "Ground responses in available data; avoid speculation",
            ),
            "safety": (
                f"Safety check failed: {details}",
                "Review safety constraints and ensure compliance",
            ),
            "state_value": (
                f"Expected state value not achieved: {details}",
                "Verify state mutations match the expected outcomes",
            ),
        }
        return analysis.get(
            kind,
            (
                f"Evaluation '{kind}' failed with score {score:.2f}",
                "Review the failure details and adjust approach",
            ),
        )

    @staticmethod
    def _default_template() -> str:
        return (
            "You are a reflection agent. Analyze the following execution "
            "result and provide a concise critique of what went wrong "
            "and how to improve."
        )
