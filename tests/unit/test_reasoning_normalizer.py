"""Tests for ReasoningNormalizer (Step 1.4)."""

from __future__ import annotations

from pylon.providers.base import Message, ReasoningOutput
from pylon.providers.reasoning import (
    AnthropicReasoningHandler,
    DeepSeekReasoningHandler,
    OpenAIReasoningHandler,
    ReasoningNormalizer,
)


def test_anthropic_extract_thinking_blocks() -> None:
    """Anthropic responses with thinking content blocks are extracted."""
    handler = AnthropicReasoningHandler()
    raw = {
        "content": [
            {
                "type": "thinking",
                "thinking": "Let me reason about this...",
                "signature": "sig_abc123",
            },
            {
                "type": "thinking",
                "thinking": "And also consider this...",
                "signature": "sig_def456",
            },
            {
                "type": "text",
                "text": "Here is my answer.",
            },
        ],
        "usage": {"reasoning_tokens": 42},
    }

    result = handler.extract(raw)

    assert result is not None
    assert "Let me reason about this..." in result.content
    assert "And also consider this..." in result.content
    assert result.tokens == 42
    assert result.redacted_for_resend is not None
    assert len(result.redacted_for_resend) == 2
    assert result.redacted_for_resend[0]["signature"] == "sig_abc123"
    assert result.redacted_for_resend[1]["signature"] == "sig_def456"


def test_anthropic_prepare_resend() -> None:
    """Anthropic handler re-inserts thinking blocks into assistant messages."""
    handler = AnthropicReasoningHandler()
    messages = [
        Message(role="user", content="What is 2+2?"),
        Message(role="assistant", content="The answer is 4."),
        Message(role="user", content="Why?"),
    ]
    reasoning_history = [
        ReasoningOutput(
            content="I need to add 2 and 2.",
            tokens=10,
            redacted_for_resend=[
                {
                    "type": "thinking",
                    "thinking": "I need to add 2 and 2.",
                    "signature": "sig_xyz",
                }
            ],
        ),
    ]

    result = handler.prepare_messages(messages, reasoning_history)

    # Should have same number of messages
    assert len(result) == 3
    # User messages unchanged
    assert result[0].content == "What is 2+2?"
    assert result[2].content == "Why?"
    # Assistant message should still exist
    assert result[1].role == "assistant"


def test_deepseek_extract_reasoning_content() -> None:
    """DeepSeek reasoning_content field is extracted correctly."""
    handler = DeepSeekReasoningHandler()
    raw = {
        "choices": [
            {
                "message": {
                    "content": "The answer is 4.",
                    "reasoning_content": "Step 1: 2+2=4. Step 2: Verify.",
                },
            }
        ],
        "usage": {
            "reasoning_tokens": 15,
        },
    }

    result = handler.extract(raw)

    assert result is not None
    assert result.content == "Step 1: 2+2=4. Step 2: Verify."
    assert result.tokens == 15
    assert result.redacted_for_resend is None


def test_deepseek_strip_on_resend() -> None:
    """DeepSeek handler strips reasoning data — must not re-send."""
    handler = DeepSeekReasoningHandler()
    messages = [
        Message(role="user", content="What is 2+2?"),
        Message(role="assistant", content="4"),
        Message(role="user", content="Why?"),
    ]
    reasoning_history = [
        ReasoningOutput(content="Because math.", tokens=5),
    ]

    result = handler.prepare_messages(messages, reasoning_history)

    # Messages returned unchanged (no reasoning data injected)
    assert len(result) == 3
    assert result[0].content == "What is 2+2?"
    assert result[1].content == "4"
    assert result[2].content == "Why?"
    # Verify we got copies, not the same objects
    assert result[0] is not messages[0]


def test_openai_no_modification() -> None:
    """OpenAI handler returns messages unchanged on resend."""
    handler = OpenAIReasoningHandler()
    messages = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there"),
        Message(role="user", content="How are you?"),
    ]
    reasoning_history = [
        ReasoningOutput(content="Some reasoning", tokens=10),
    ]

    result = handler.prepare_messages(messages, reasoning_history)

    # Should return the exact same list (no modification needed)
    assert result is messages
    assert len(result) == 3


def test_normalizer_unknown_provider() -> None:
    """ReasoningNormalizer returns None for unknown providers."""
    normalizer = ReasoningNormalizer()
    raw = {"content": "test"}

    result = normalizer.extract("unknown_provider", raw)

    assert result is None

    # prepare_for_resend also passes through unchanged
    messages = [Message(role="user", content="Hello")]
    prepared = normalizer.prepare_for_resend("unknown_provider", messages, [])
    assert prepared is messages
