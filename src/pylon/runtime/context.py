"""Context preparation utilities for provider-backed runtime calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.providers.base import Message
from pylon.types import AutonomyLevel

try:
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False


_A0_A1_KEYS = frozenset({"input", "task", "node_id"})
_A2_KEYS = _A0_A1_KEYS | frozenset({"memory", "history"})
_HISTORY_LIMIT = 5


def project_context(
    full_context: dict[str, Any],
    autonomy_level: AutonomyLevel,
) -> dict[str, Any]:
    """Project workflow context based on agent autonomy level.

    A0/A1: Only immediate task input and basic state
    A2: Task + relevant memory entries + trimmed history
    A3/A4: Full context including sibling results and goal state
    """
    if autonomy_level >= AutonomyLevel.A3:
        return full_context

    if autonomy_level <= AutonomyLevel.A1:
        return {k: v for k, v in full_context.items() if k in _A0_A1_KEYS}

    # A2: include memory and trimmed history
    projected = {k: v for k, v in full_context.items() if k in _A2_KEYS}
    if "history" in projected and isinstance(projected["history"], list):
        projected["history"] = projected["history"][-_HISTORY_LIMIT:]
    return projected


def _estimate_message_tokens(messages: list[Message]) -> int:
    text = "\n".join(message.content for message in messages)
    if not text:
        return 1
    if _HAS_TIKTOKEN:
        return max(1, len(_ENCODER.encode(text)))
    # Fallback: 日本語対応の簡易推定
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + int(non_ascii_chars / 1.5))


@dataclass(frozen=True)
class ContextWindowConfig:
    """Deterministic context window shaping configuration."""

    max_input_tokens: int = 8000
    keep_last_messages: int = 4
    summary_char_limit: int = 1200

    def __post_init__(self) -> None:
        if self.max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be greater than 0")
        if self.keep_last_messages <= 0:
            raise ValueError("keep_last_messages must be greater than 0")
        if self.summary_char_limit <= 0:
            raise ValueError("summary_char_limit must be greater than 0")


@dataclass(frozen=True)
class PreparedContext:
    """Prepared messages and compaction metadata."""

    messages: list[Message]
    original_input_tokens: int
    prepared_input_tokens: int
    was_compacted: bool = False
    cacheable_prefix: bool = False
    summary: str = ""


@dataclass
class ContextManager:
    """Applies deterministic static-prefix injection and context compaction."""

    config: ContextWindowConfig = field(default_factory=ContextWindowConfig)

    def prepare(
        self,
        messages: list[Message],
        *,
        static_instruction: str = "",
    ) -> PreparedContext:
        working = list(messages)
        if static_instruction and not any(message.role == "system" for message in working):
            working = [Message(role="system", content=static_instruction), *working]

        original_tokens = _estimate_message_tokens(working)
        if original_tokens <= self.config.max_input_tokens:
            return PreparedContext(
                messages=working,
                original_input_tokens=original_tokens,
                prepared_input_tokens=original_tokens,
                was_compacted=False,
                cacheable_prefix=bool(static_instruction or self._has_system_prefix(working)),
            )

        prepared, summary = self._compact_messages(working)
        prepared_tokens = _estimate_message_tokens(prepared)
        return PreparedContext(
            messages=prepared,
            original_input_tokens=original_tokens,
            prepared_input_tokens=prepared_tokens,
            was_compacted=True,
            cacheable_prefix=bool(static_instruction or self._has_system_prefix(prepared)),
            summary=summary,
        )

    def _compact_messages(self, messages: list[Message]) -> tuple[list[Message], str]:
        system_prefix = [message for message in messages if message.role == "system"]
        conversational = [message for message in messages if message.role != "system"]
        keep_count = min(len(conversational), self.config.keep_last_messages)
        omitted = conversational[:-keep_count] if keep_count else conversational
        tail = conversational[-keep_count:] if keep_count else []
        summary = self._summarize(omitted)

        prepared = list(system_prefix)
        if summary:
            prepared.append(Message(role="system", content=summary))
        prepared.extend(tail)
        return prepared, summary

    def _summarize(self, messages: list[Message]) -> str:
        if not messages:
            return ""
        role_counts: dict[str, int] = {}
        total_chars = 0
        for message in messages:
            role_counts[message.role] = role_counts.get(message.role, 0) + 1
            total_chars += len(message.content)
        counts = ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items()))
        summary = (
            f"Compacted prior context: {len(messages)} messages omitted "
            f"({counts}; {total_chars} chars)."
        )
        return summary[: self.config.summary_char_limit]

    def _has_system_prefix(self, messages: list[Message]) -> bool:
        return bool(messages) and messages[0].role == "system"
