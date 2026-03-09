"""Tests for ContextManager.prepare_for_provider."""

from pylon.providers.base import Message
from pylon.runtime.context import ContextManager, ContextWindowConfig


class TestPrepareForProvider:
    def test_prepare_for_provider_no_compaction(self) -> None:
        manager = ContextManager(config=ContextWindowConfig(max_input_tokens=50000))
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = manager.prepare_for_provider(
            messages,
            context_window=200000,
            max_output_tokens=8192,
        )
        assert not result.was_compacted
        assert len(result.messages) == 2

    def test_prepare_for_provider_triggers_compaction(self) -> None:
        manager = ContextManager(
            config=ContextWindowConfig(
                max_input_tokens=50000,
                keep_last_messages=2,
            ),
        )
        # Create messages that exceed a tiny context window
        messages = [
            Message(role="user", content="A" * 5000),
            Message(role="assistant", content="B" * 5000),
            Message(role="user", content="C" * 5000),
            Message(role="assistant", content="D" * 5000),
            Message(role="user", content="E" * 5000),
        ]
        result = manager.prepare_for_provider(
            messages,
            context_window=2000,  # very small window
            max_output_tokens=500,
        )
        assert result.was_compacted
        assert result.prepared_input_tokens < result.original_input_tokens

    def test_prepare_for_provider_preserves_original_config(self) -> None:
        original_max = 50000
        manager = ContextManager(config=ContextWindowConfig(max_input_tokens=original_max))
        messages = [Message(role="user", content="test")]

        manager.prepare_for_provider(
            messages,
            context_window=200000,
            max_output_tokens=8192,
        )
        assert manager.config.max_input_tokens == original_max
