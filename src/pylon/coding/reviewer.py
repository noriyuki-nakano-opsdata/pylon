from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Awaitable


class Severity(enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ReviewComment:
    file_path: str
    line: int
    message: str
    severity: Severity


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    comments: list[ReviewComment]
    severity: Severity


@dataclass
class QualityGateConfig:
    max_file_size: int = 500
    required_tests: bool = True
    max_complexity: int = 10


@dataclass(frozen=True)
class CodeChange:
    """Represents a single file change submitted for review."""

    file_path: str
    content: str
    line_count: int = 0
    has_tests: bool = False


class CodeReviewer:
    """Reviews code changes against quality gates."""

    def __init__(
        self,
        *,
        quality_gates: QualityGateConfig | None = None,
        review_fn: Callable[[list[CodeChange]], Awaitable[ReviewResult]] | None = None,
    ) -> None:
        self.quality_gates = quality_gates or QualityGateConfig()
        self._review_fn = review_fn

    async def review(self, changes: list[CodeChange]) -> ReviewResult:
        if self._review_fn is not None:
            return await self._review_fn(changes)

        return self._gate_review(changes)

    # ------------------------------------------------------------------

    def _gate_review(self, changes: list[CodeChange]) -> ReviewResult:
        comments: list[ReviewComment] = []
        worst_severity = Severity.INFO

        for change in changes:
            line_count = change.line_count or change.content.count("\n") + 1

            if line_count > self.quality_gates.max_file_size:
                comment = ReviewComment(
                    file_path=change.file_path,
                    line=0,
                    message=(
                        f"File exceeds max size: {line_count} lines "
                        f"(limit {self.quality_gates.max_file_size})"
                    ),
                    severity=Severity.WARNING,
                )
                comments.append(comment)
                worst_severity = _max_severity(worst_severity, Severity.WARNING)

            if self.quality_gates.required_tests and not change.has_tests:
                comment = ReviewComment(
                    file_path=change.file_path,
                    line=0,
                    message="No tests found for this change",
                    severity=Severity.ERROR,
                )
                comments.append(comment)
                worst_severity = _max_severity(worst_severity, Severity.ERROR)

        approved = worst_severity != Severity.ERROR
        return ReviewResult(
            approved=approved,
            comments=comments,
            severity=worst_severity,
        )


_SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


def _max_severity(a: Severity, b: Severity) -> Severity:
    return a if _SEVERITY_ORDER[a] >= _SEVERITY_ORDER[b] else b
