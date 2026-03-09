"""Unit tests for KimiCodeBridge and KimiCodeProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from pylon.bridges.kimi_code import KimiCodeBridge, KimiCodeProvider
from pylon.providers.base import Message, Response


class TestKimiCodeBridge:
    def test_command_defaults(self) -> None:
        bridge = KimiCodeBridge()
        assert "kimi" in bridge._command
        assert "--print" in bridge._command
        assert bridge._model == "kimi-latest"

    def test_command_stream_json(self) -> None:
        bridge = KimiCodeBridge(output_format="stream-json")
        assert "--output-format" in bridge._command
        assert "stream-json" in bridge._command

    def test_parse_response_text(self) -> None:
        bridge = KimiCodeBridge()
        resp = bridge._parse_response("Hello from Kimi\n")
        assert resp.content == "Hello from Kimi"
        assert resp.model == "kimi-latest"
        assert resp.finish_reason == "stop"

    def test_parse_response_stream_json(self) -> None:
        bridge = KimiCodeBridge(output_format="stream-json")
        raw = (
            '{"content":"Hello "}\n'
            '{"content":"world"}\n'
        )
        resp = bridge._parse_response(raw)
        assert resp.content == "Hello world"

    def test_parse_response_stream_json_fallback(self) -> None:
        bridge = KimiCodeBridge(output_format="stream-json")
        raw = "plain text fallback\n"
        resp = bridge._parse_response(raw)
        assert resp.content == "plain text fallback"


class TestKimiCodeProvider:
    def test_provider_name(self) -> None:
        bridge = KimiCodeBridge()
        provider = KimiCodeProvider(bridge)
        assert provider.provider_name == "kimi-code"
        assert provider.model_id == "kimi-latest"

    @pytest.mark.asyncio
    async def test_chat(self) -> None:
        bridge = KimiCodeBridge()
        bridge.send = AsyncMock(return_value="Kimi response")
        provider = KimiCodeProvider(bridge)
        messages = [Message(role="user", content="Hello")]
        result = await provider.chat(messages)
        assert isinstance(result, Response)
        assert result.content == "Kimi response"

    @pytest.mark.asyncio
    async def test_stream_fallback(self) -> None:
        bridge = KimiCodeBridge()
        bridge.send = AsyncMock(return_value="streamed result")
        provider = KimiCodeProvider(bridge)
        messages = [Message(role="user", content="Hello")]
        chunks = [c async for c in provider.stream(messages)]
        assert len(chunks) == 1
        assert chunks[0].content == "streamed result"
        assert chunks[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_extracts_last_user_message(self) -> None:
        bridge = KimiCodeBridge()
        bridge.send = AsyncMock(return_value="response")
        provider = KimiCodeProvider(bridge)
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="First"),
            Message(role="assistant", content="OK"),
            Message(role="user", content="Second"),
        ]
        await provider.chat(messages)
        # Should send last user message, not role-tagged format
        bridge.send.assert_called_once_with("Second")


class TestKimiCodeBridgeParseFiltering:
    def test_parse_filters_control_blocks(self) -> None:
        bridge = KimiCodeBridge()
        raw = (
            "TurnBegin(type='turn_begin')\n"
            "StepBegin(step=1)\n"
            "StatusUpdate(status='thinking')\n"
            "TextPart(type='text', text='Hello world')\n"
            "TurnEnd()\n"
        )
        resp = bridge._parse_response(raw)
        assert resp.content == "Hello world"

    def test_parse_multiple_text_parts(self) -> None:
        bridge = KimiCodeBridge()
        raw = (
            "TextPart(type='text', text='Line 1')\n"
            "TextPart(type='text', text='Line 2')\n"
        )
        resp = bridge._parse_response(raw)
        assert resp.content == "Line 1\nLine 2"

    def test_parse_plain_text_without_control(self) -> None:
        bridge = KimiCodeBridge()
        raw = "Just plain text\nwith two lines\n"
        resp = bridge._parse_response(raw)
        assert resp.content == "Just plain text\nwith two lines"
