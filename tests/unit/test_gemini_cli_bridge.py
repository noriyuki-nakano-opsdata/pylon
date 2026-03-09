"""Unit tests for GeminiCLIBridge and GeminiCLIProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pylon.bridges.gemini_cli import GeminiCLIBridge, GeminiCLIProvider
from pylon.providers.base import Message, Response


class TestGeminiCLIBridge:
    def test_command_defaults(self) -> None:
        bridge = GeminiCLIBridge()
        assert "gemini" in bridge._command
        assert "-m" in bridge._command
        assert "gemini-2.5-pro" in bridge._command
        assert "-y" in bridge._command
        assert bridge._model == "gemini-2.5-pro"

    def test_command_no_yolo(self) -> None:
        bridge = GeminiCLIBridge(yolo=False)
        assert "-y" not in bridge._command

    def test_command_sandbox(self) -> None:
        bridge = GeminiCLIBridge(sandbox=True)
        assert "-s" in bridge._command

    def test_command_custom_model(self) -> None:
        bridge = GeminiCLIBridge(model="gemini-2.5-flash")
        assert "gemini-2.5-flash" in bridge._command
        assert bridge._model == "gemini-2.5-flash"

    def test_parse_response(self) -> None:
        bridge = GeminiCLIBridge()
        resp = bridge._parse_response("Hello from Gemini\n")
        assert resp.content == "Hello from Gemini"
        assert resp.model == "gemini-2.5-pro"
        assert resp.finish_reason == "stop"


class TestGeminiCLIProvider:
    def test_provider_name(self) -> None:
        bridge = GeminiCLIBridge()
        provider = GeminiCLIProvider(bridge)
        assert provider.provider_name == "gemini-cli"
        assert provider.model_id == "gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_chat(self) -> None:
        bridge = GeminiCLIBridge()
        bridge.send = AsyncMock(return_value="Gemini response")
        provider = GeminiCLIProvider(bridge)
        messages = [Message(role="user", content="Hello")]
        result = await provider.chat(messages)
        assert isinstance(result, Response)
        assert result.content == "Gemini response"

    @pytest.mark.asyncio
    async def test_stream_fallback(self) -> None:
        bridge = GeminiCLIBridge()
        bridge.send = AsyncMock(return_value="streamed result")
        provider = GeminiCLIProvider(bridge)
        messages = [Message(role="user", content="Hello")]
        chunks = [c async for c in provider.stream(messages)]
        assert len(chunks) == 1
        assert chunks[0].content == "streamed result"
        assert chunks[0].finish_reason == "stop"
