"""Tests for WebSocket/SSE streaming handler."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pylon.gateway.streaming import StreamConfig, StreamingHandler
from pylon.providers.base import Message, Response, TokenUsage


class TestStreamConfigDefaults:
    def test_stream_config_defaults(self):
        config = StreamConfig()
        assert config.websocket_enabled is True
        assert config.sse_enabled is True
        assert config.websocket_path == "/ws"
        assert config.sse_path == "/sse"


class TestSSEEventFormat:
    def test_sse_event_format(self):
        result = StreamingHandler._format_sse_event("chunk", {})
        assert result.startswith("event: chunk\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_sse_event_with_data(self):
        data = {"content": "Hello, world!"}
        result = StreamingHandler._format_sse_event("chunk", data)
        assert "event: chunk\n" in result
        lines = result.strip().split("\n")
        data_line = [l for l in lines if l.startswith("data: ")][0]
        parsed = json.loads(data_line.removeprefix("data: "))
        assert parsed["content"] == "Hello, world!"


class TestStreamingHandlerInit:
    def test_streaming_handler_init(self):
        handler = StreamingHandler()
        assert handler.config.websocket_enabled is True
        assert handler._chat_handler is None

        custom = StreamConfig(websocket_enabled=False, websocket_path="/custom")
        handler2 = StreamingHandler(config=custom)
        assert handler2.config.websocket_enabled is False
        assert handler2.config.websocket_path == "/custom"


class TestWebSocketMessageParse:
    def test_websocket_message_parse(self):
        valid = json.dumps({
            "jsonrpc": "2.0",
            "method": "chat",
            "params": {
                "messages": [{"role": "user", "content": "hi"}],
                "model": "test-model",
            },
            "id": "1",
        })
        result = StreamingHandler._parse_jsonrpc(valid)
        assert result is not None
        assert result["method"] == "chat"
        assert result["id"] == "1"
        assert result["params"]["model"] == "test-model"

        # Invalid cases
        assert StreamingHandler._parse_jsonrpc("not json") is None
        assert StreamingHandler._parse_jsonrpc(json.dumps({"method": "chat"})) is None
        assert StreamingHandler._parse_jsonrpc(json.dumps("string")) is None


class TestWebSocketResponseFormat:
    @pytest.mark.asyncio
    async def test_websocket_response_format(self):
        """Verify JSON-RPC chunk and done responses from a WebSocket session."""
        response = Response(
            content="Hello!",
            model="test",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

        async def mock_handler(messages, model):
            return response

        handler = StreamingHandler(chat_handler=mock_handler)

        sent: list[str] = []
        recv_calls = 0

        async def mock_recv():
            nonlocal recv_calls
            recv_calls += 1
            if recv_calls == 1:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "method": "chat",
                    "params": {"messages": [{"role": "user", "content": "hi"}]},
                    "id": "42",
                })
            raise ConnectionError("done")

        ws = AsyncMock()
        ws.recv = mock_recv
        ws.send = AsyncMock(side_effect=lambda d: sent.append(d))

        await handler.handle_websocket(ws, "/ws")

        assert len(sent) == 2
        chunk = json.loads(sent[0])
        assert chunk["jsonrpc"] == "2.0"
        assert chunk["result"]["type"] == "chunk"
        assert chunk["result"]["content"] == "Hello!"
        assert chunk["id"] == "42"

        done = json.loads(sent[1])
        assert done["result"]["type"] == "done"
        assert done["result"]["usage"]["input_tokens"] == 10
        assert done["result"]["usage"]["output_tokens"] == 5
        assert done["result"]["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_websocket_unknown_method(self):
        """Unknown method returns -32601 error."""
        handler = StreamingHandler()
        sent: list[str] = []
        recv_calls = 0

        async def mock_recv():
            nonlocal recv_calls
            recv_calls += 1
            if recv_calls == 1:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "method": "unknown",
                    "params": {},
                    "id": "1",
                })
            raise ConnectionError("done")

        ws = AsyncMock()
        ws.recv = mock_recv
        ws.send = AsyncMock(side_effect=lambda d: sent.append(d))
        await handler.handle_websocket(ws, "/ws")
        assert len(sent) == 1
        err = json.loads(sent[0])
        assert err["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_websocket_no_chat_handler(self):
        """No chat handler returns -32000 error."""
        handler = StreamingHandler()
        sent: list[str] = []
        recv_calls = 0

        async def mock_recv():
            nonlocal recv_calls
            recv_calls += 1
            if recv_calls == 1:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "method": "chat",
                    "params": {"messages": [{"role": "user", "content": "hi"}]},
                    "id": "2",
                })
            raise ConnectionError("done")

        ws = AsyncMock()
        ws.recv = mock_recv
        ws.send = AsyncMock(side_effect=lambda d: sent.append(d))
        await handler.handle_websocket(ws, "/ws")
        assert len(sent) == 1
        err = json.loads(sent[0])
        assert err["error"]["code"] == -32000

    @pytest.mark.asyncio
    async def test_websocket_invalid_messages(self):
        """Invalid messages param returns -32602 error."""
        handler = StreamingHandler()
        sent: list[str] = []
        recv_calls = 0

        async def mock_recv():
            nonlocal recv_calls
            recv_calls += 1
            if recv_calls == 1:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "method": "chat",
                    "params": {"messages": "not a list"},
                    "id": "3",
                })
            raise ConnectionError("done")

        ws = AsyncMock()
        ws.recv = mock_recv
        ws.send = AsyncMock(side_effect=lambda d: sent.append(d))
        await handler.handle_websocket(ws, "/ws")
        assert len(sent) == 1
        err = json.loads(sent[0])
        assert err["error"]["code"] == -32602


class TestSSEHandler:
    @pytest.mark.asyncio
    async def test_handle_sse_success(self):
        """SSE handler sends chunk and done events."""
        response = Response(
            content="SSE response",
            model="test",
            usage=TokenUsage(input_tokens=5, output_tokens=3),
        )

        async def mock_handler(messages, model):
            return response

        handler = StreamingHandler(chat_handler=mock_handler)
        request = MagicMock()
        request.body = json.dumps({
            "messages": [{"role": "user", "content": "hello"}],
        }).encode()
        transport = AsyncMock()

        await handler.handle_sse(request, transport)

        assert transport.send_event.call_count == 2
        chunk_call = transport.send_event.call_args_list[0][0][0]
        assert "SSE response" in chunk_call
        transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sse_invalid_json(self):
        """SSE handler returns error for invalid JSON body."""
        handler = StreamingHandler()
        request = MagicMock()
        request.body = b"not json"
        transport = AsyncMock()

        await handler.handle_sse(request, transport)

        transport.send_event.assert_called_once()
        call_arg = transport.send_event.call_args[0][0]
        assert "Invalid JSON" in call_arg
        transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sse_no_handler(self):
        """SSE handler returns error when no chat handler configured."""
        handler = StreamingHandler()
        request = MagicMock()
        request.body = json.dumps({
            "messages": [{"role": "user", "content": "hi"}],
        }).encode()
        transport = AsyncMock()

        await handler.handle_sse(request, transport)

        transport.send_event.assert_called_once()
        call_arg = transport.send_event.call_args[0][0]
        assert "No chat handler" in call_arg
