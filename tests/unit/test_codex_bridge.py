"""Unit tests for CodexBridge and CodexProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from pylon.bridges.codex import CodexBridge, CodexProvider
from pylon.providers.base import Message, Response


class TestCodexBridge:
    def test_codex_bridge_command(self) -> None:
        bridge = CodexBridge()
        assert bridge._command == ["codex", "app-server"]

    def test_codex_bridge_default_config(self) -> None:
        bridge = CodexBridge()
        assert bridge._model == "codex-mini"
        assert bridge._approval_policy == "on-failure"
        assert bridge._sandbox_mode == "workspace-write"

    @pytest.mark.asyncio
    async def test_codex_start_session(self) -> None:
        bridge = CodexBridge()
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"session_id": "sess-123"},
        })
        bridge.send = AsyncMock(return_value=response)

        session_id = await bridge.start_session("/workspace")
        assert session_id == "sess-123"
        bridge.send.assert_called_once()

        # Verify the JSON-RPC request
        call_arg = bridge.send.call_args[0][0]
        request = json.loads(call_arg)
        assert request["method"] == "session.start"
        assert request["params"]["workspace"] == "/workspace"
        assert request["params"]["model"] == "codex-mini"

    @pytest.mark.asyncio
    async def test_codex_send_turn(self) -> None:
        bridge = CodexBridge()
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"response": "I fixed the bug."},
        })
        bridge.send = AsyncMock(return_value=response)

        result = await bridge.send_turn("Fix the bug in main.py")
        assert result == "I fixed the bug."

    def test_codex_provider_name(self) -> None:
        bridge = CodexBridge()
        provider = CodexProvider(bridge)
        assert provider.provider_name == "codex"
        assert provider.model_id == "codex-mini"

    @pytest.mark.asyncio
    async def test_codex_provider_chat(self) -> None:
        bridge = CodexBridge()
        bridge.send = AsyncMock(return_value=json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"response": "Fixed the bug."},
        }))
        provider = CodexProvider(bridge)
        messages = [Message(role="user", content="Fix the bug")]
        result = await provider.chat(messages)
        assert result.content == "Fixed the bug."
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_codex_provider_stream(self) -> None:
        bridge = CodexBridge()
        bridge.send = AsyncMock(return_value=json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"response": "Streamed output."},
        }))
        provider = CodexProvider(bridge)
        messages = [Message(role="user", content="Stream test")]
        chunks = [c async for c in provider.stream(messages)]
        assert len(chunks) == 1
        assert chunks[0].content == "Streamed output."
        assert chunks[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_codex_jsonrpc_error(self) -> None:
        bridge = CodexBridge()
        bridge.send = AsyncMock(return_value=json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        }))
        with pytest.raises(RuntimeError, match="JSON-RPC error -32600"):
            await bridge.start_session("/workspace")
