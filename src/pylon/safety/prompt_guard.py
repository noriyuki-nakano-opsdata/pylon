"""Prompt Guard pipeline (SPECIFICATION Section 2.4).

External Input -> Pattern Matcher (regex) -> Classifier LLM (secondary)
              -> Sanitized Input -> Primary LLM
              -> Output Validator -> Response

Trust-level-based guard application:
- trusted: no guard
- internal: pattern match only
- untrusted: full pipeline (pattern + classifier)
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Callable

from pylon.errors import PromptInjectionError
from pylon.types import TrustLevel


_DEFAULT_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?previous\s+instructions", "ignore_previous"),
    (r"ignore\s+(all\s+)?above\s+instructions", "ignore_above"),
    (r"disregard\s+(all\s+)?previous", "disregard_previous"),
    (r"system\s+prompt\s*:", "system_prompt_leak"),
    (r"you\s+are\s+now\b", "role_override"),
    (r"act\s+as\s+(if\s+you\s+are\s+)?a\s+different", "role_override"),
    (r"pretend\s+you\s+are", "role_override"),
    (r"reveal\s+(your\s+)?(system|initial)\s+(prompt|instructions)", "system_prompt_leak"),
    (r"output\s+your\s+(system\s+)?prompt", "system_prompt_leak"),
    (r"print\s+your\s+(system\s+)?instructions", "system_prompt_leak"),
    (r"<\s*/?\s*system\s*>", "xml_injection"),
    (r"\[\s*INST\s*\]", "format_injection"),
    (r"```\s*system", "code_block_injection"),
    (r"do\s+not\s+follow\s+(any\s+)?previous", "ignore_previous"),
    (r"override\s+(all\s+)?safety", "safety_override"),
    (r"bypass\s+(all\s+)?restrictions", "safety_override"),
    (r"jailbreak", "jailbreak"),
    (r"DAN\s+mode", "jailbreak"),
]


@dataclass
class PatternMatch:
    """Result of a pattern match detection."""

    pattern_name: str
    matched_text: str
    position: int


class PatternMatcher:
    """Detects known prompt injection patterns via regex."""

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        patterns = _DEFAULT_PATTERNS + (extra_patterns or [])
        self._compiled: list[tuple[re.Pattern[str], str]] = [
            (re.compile(p, re.IGNORECASE), name) for p, name in patterns
        ]

    def scan(self, text: str) -> list[PatternMatch]:
        """Scan text for injection patterns. Returns all matches."""
        matches: list[PatternMatch] = []
        for regex, name in self._compiled:
            for m in regex.finditer(text):
                matches.append(
                    PatternMatch(
                        pattern_name=name,
                        matched_text=m.group(),
                        position=m.start(),
                    )
                )
        return matches


# Type alias for classifier callback (returns True if injection detected)
ClassifierFunc = Callable[[str], bool]


def _default_classifier(text: str) -> bool:
    """Stub classifier. In production, this calls a secondary LLM."""
    return False


class PromptGuard:
    """Full prompt guard pipeline integrating pattern matching and classification.

    Trust levels determine which stages run:
    - TRUSTED: bypass all guards
    - INTERNAL: pattern matching only
    - UNTRUSTED: pattern matching + classifier LLM
    """

    def __init__(
        self,
        *,
        pattern_matcher: PatternMatcher | None = None,
        classifier: ClassifierFunc | None = None,
    ) -> None:
        self._matcher = pattern_matcher or PatternMatcher()
        self._classifier = classifier or _default_classifier
        self._using_default_classifier = classifier is None

    def check(self, text: str, trust_level: TrustLevel) -> str:
        """Run the prompt guard pipeline.

        Returns the original text if safe.
        Raises PromptInjectionError if injection detected.
        """
        if trust_level == TrustLevel.TRUSTED:
            return text

        # Stage 1: Pattern matching (internal + untrusted)
        matches = self._matcher.scan(text)
        if matches:
            first = matches[0]
            raise PromptInjectionError(
                f"Prompt injection detected: pattern '{first.pattern_name}' "
                f"at position {first.position}",
                details={
                    "pattern": first.pattern_name,
                    "matched_text": first.matched_text,
                    "total_matches": len(matches),
                },
            )

        # Stage 2: Classifier LLM (untrusted only)
        if trust_level == TrustLevel.UNTRUSTED:
            if self._using_default_classifier:
                warnings.warn(
                    "PromptGuard is using the default stub classifier which always "
                    "returns False. Configure a real classifier for production use.",
                    UserWarning,
                    stacklevel=2,
                )
            if self._classifier(text):
                raise PromptInjectionError(
                    "Prompt injection detected by classifier",
                    details={"detection_method": "classifier"},
                )

        return text
