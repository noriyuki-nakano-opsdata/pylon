"""Unit tests for ClaudeCodeBridge and ClaudeCodeProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylon.bridges.claude_code import ClaudeCodeBridge, ClaudeCodeProvider
from pylon.providers.base import Message, Response


class TestClaudeCodeBridge:
    def test_claude_code_bridge_command(self) -> None:
        bridge = ClaudeCodeBridge(model="opus", allowed_tools=["bash", "read"])
        assert "claude" in bridge._command
        assert "--print" in bridge._command
        assert "--output-format" in bridge._command
        assert "json" in bridge._command
        assert "--model" in bridge._command
        assert "opus" in bridge._command
        assert "--allowedTools" in bridge._command

    def test_claude_code_bridge_default_model(self) -> None:
        bridge = ClaudeCodeBridge()
        assert bridge._model == "claude-sonnet-4-6"
        assert "--model" in bridge._command
        assert "claude-sonnet-4-6" in bridge._command

    def test_claude_code_bridge_parse_response(self) -> None:
        bridge = ClaudeCodeBridge()

        # Valid JSON with result field
        data = json.dumps({
            "result": "Hello world",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "stop_reason": "end_turn",
        })
        resp = bridge._parse_response(data)
        assert resp.content == "Hello world"
        assert resp.model == "claude-sonnet-4-6"
        assert resp.usage is not None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 20
        assert resp.finish_reason == "end_turn"

        # Invalid JSON falls back to raw text
        resp2 = bridge._parse_response("plain text response")
        assert resp2.content == "plain text response"


class TestClaudeCodeProvider:
    def test_claude_code_provider_name(self) -> None:
        bridge = ClaudeCodeBridge()
        provider = ClaudeCodeProvider(bridge)
        assert provider.provider_name == "claude-code"
        assert provider.model_id == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_claude_code_provider_chat(self) -> None:
        bridge = ClaudeCodeBridge()
        response_data = json.dumps({
            "result": "Generated code",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 5, "output_tokens": 15},
        })
        bridge.send = AsyncMock(return_value=response_data)

        provider = ClaudeCodeProvider(bridge)
        messages = [Message(role="user", content="Write a function")]

        result = await provider.chat(messages)
        assert isinstance(result, Response)
        assert result.content == "Generated code"
        assert result.model == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_claude_code_provider_stream(self) -> None:
        bridge = ClaudeCodeBridge()
        response_data = json.dumps({
            "result": "Streamed code",
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        })
        bridge.send = AsyncMock(return_value=response_data)
        provider = ClaudeCodeProvider(bridge)
        messages = [Message(role="user", content="Stream test")]
        chunks = [c async for c in provider.stream(messages)]
        assert len(chunks) == 1
        assert chunks[0].content == "Streamed code"
        assert chunks[0].finish_reason == "stop"


class TestClaudeCodeBridgeEdgeCases:
    def test_parse_response_non_dict_json(self) -> None:
        bridge = ClaudeCodeBridge()
        resp = bridge._parse_response("[1, 2, 3]")
        assert resp.content == "[1, 2, 3]"

    def test_max_turns_in_command(self) -> None:
        bridge = ClaudeCodeBridge(max_turns=5)
        assert "--max-turns" in bridge._command
        assert "5" in bridge._command

    def test_max_turns_default_omitted(self) -> None:
        bridge = ClaudeCodeBridge()
        assert "--max-turns" not in bridge._command
