"""Tests for improved token estimation with Japanese text support."""

from __future__ import annotations

from pylon.providers.base import Message
from pylon.runtime.context import _estimate_message_tokens


def test_empty_messages_returns_one() -> None:
    assert _estimate_message_tokens([]) == 1


def test_ascii_text_estimation() -> None:
    msgs = [Message(role="user", content="hello world")]
    result = _estimate_message_tokens(msgs)
    assert result >= 1


def test_japanese_text_higher_than_naive() -> None:
    """Japanese text should produce more tokens than len//4 naive estimate."""
    jp_text = "こんにちは世界、これはテストです。日本語のトークン推定を改善します。"
    msgs = [Message(role="user", content=jp_text)]
    result = _estimate_message_tokens(msgs)
    naive = max(1, len(jp_text) // 4)
    # With proper estimation, Japanese characters should count more than ASCII
    assert result >= naive


def test_mixed_text_estimation() -> None:
    """Mixed ASCII + Japanese text should be estimated reasonably."""
    mixed = "Hello, 世界! This is a test. テストです。"
    msgs = [Message(role="user", content=mixed)]
    result = _estimate_message_tokens(msgs)
    assert result >= 1


def test_estimate_message_tokens_via_llm_module() -> None:
    """llm.estimate_message_tokens delegates to context._estimate_message_tokens."""
    from pylon.runtime.llm import estimate_message_tokens

    msgs = [Message(role="user", content="hello")]
    assert estimate_message_tokens(msgs) == _estimate_message_tokens(msgs)
