"""WebSocket/SSE streaming handler for LLM response delivery."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from pylon.providers.base import Message, Response, TokenUsage


@dataclass
class StreamConfig:
    """Configuration for streaming endpoints."""

    websocket_enabled: bool = True
    sse_enabled: bool = True
    websocket_path: str = "/ws"
    sse_path: str = "/sse"


@runtime_checkable
class WebSocketConnection(Protocol):
    """Abstract WebSocket connection interface."""

    async def recv(self) -> str: ...
    async def send(self, data: str) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class SSERequest(Protocol):
    """Abstract SSE request interface."""

    @property
    def body(self) -> bytes: ...

    @property
    def headers(self) -> dict[str, str]: ...


@runtime_checkable
class SSETransport(Protocol):
    """Abstract SSE response transport."""

    async def send_event(self, data: str) -> None: ...
    async def close(self) -> None: ...


class StreamingHandler:
    """Handles WebSocket and SSE streaming for LLM responses.

    Uses Protocol abstractions for WebSocket/SSE so concrete implementations
    (e.g. websockets, aiohttp) can be plugged in externally.
    """

    def __init__(
        self,
        chat_handler: Callable[[list[Message], str], Any] | None = None,
        config: StreamConfig | None = None,
    ) -> None:
        self._chat_handler = chat_handler
        self.config = config or StreamConfig()

    async def handle_websocket(self, ws: WebSocketConnection, path: str) -> None:
        """Handle a WebSocket connection using JSON-RPC protocol.

        Receives JSON-RPC requests, delegates to the chat handler,
        and streams chunked responses back over the connection.
        """
        try:
            while True:
                raw = await ws.recv()
                request = self._parse_jsonrpc(raw)
                if request is None:
                    await ws.send(json.dumps(self._jsonrpc_error(
                        None, -32600, "Invalid JSON-RPC request",
                    )))
                    continue

                req_id = request.get("id")
                method = request.get("method")

                if method != "chat":
                    await ws.send(json.dumps(self._jsonrpc_error(
                        req_id, -32601, f"Method not found: {method}",
                    )))
                    continue

                params = request.get("params", {})
                raw_messages = params.get("messages", [])
                if not isinstance(raw_messages, list):
                    await ws.send(json.dumps(self._jsonrpc_error(
                        req_id, -32602, "Invalid params: 'messages' must be a list",
                    )))
                    continue

                invalid_msg = False
                for m in raw_messages:
                    if not isinstance(m, dict) or "role" not in m or "content" not in m:
                        await ws.send(json.dumps(self._jsonrpc_error(
                            req_id, -32602,
                            "Invalid params: each message must be an object with 'role' and 'content'",
                        )))
                        invalid_msg = True
                        break
                if invalid_msg:
                    continue

                messages = [
                    Message(role=m["role"], content=m["content"])
                    for m in raw_messages
                ]
                model = params.get("model", "default")

                if self._chat_handler:
                    response: Response = await self._chat_handler(messages, model)
                    # Send content as a single chunk
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "result": {"type": "chunk", "content": response.content},
                        "id": req_id,
                    }))
                    # Send done with usage
                    usage = {}
                    cost = 0.0
                    if response.usage:
                        usage = {
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                            "total_tokens": response.usage.total_tokens,
                        }
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "result": {"type": "done", "usage": usage, "cost": cost},
                        "id": req_id,
                    }))
                else:
                    await ws.send(json.dumps(self._jsonrpc_error(
                        req_id, -32000, "No chat handler configured",
                    )))
        except (ConnectionError, OSError):
            # Connection closed; exit gracefully
            pass
        except Exception:
            try:
                await ws.send(json.dumps(self._jsonrpc_error(
                    None, -32603, "Internal error",
                )))
            except (ConnectionError, OSError):
                pass

    async def handle_sse(
        self,
        request: SSERequest,
        transport: SSETransport,
    ) -> None:
        """Handle an SSE request.

        Parses the request body as JSON, delegates to the chat handler,
        and sends results as SSE events via the transport.
        """
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            await transport.send_event(
                self._format_sse_event("error", {"message": "Invalid JSON body"})
            )
            await transport.close()
            return

        raw_messages = body.get("messages", [])
        if not isinstance(raw_messages, list):
            await transport.send_event(
                self._format_sse_event("error", {"message": "Invalid params: 'messages' must be a list"})
            )
            await transport.close()
            return

        for m in raw_messages:
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                await transport.send_event(
                    self._format_sse_event("error", {
                        "message": "Invalid params: each message must be an object with 'role' and 'content'",
                    })
                )
                await transport.close()
                return

        messages = [
            Message(role=m["role"], content=m["content"])
            for m in raw_messages
        ]
        model = body.get("model", "default")

        if self._chat_handler:
            response: Response = await self._chat_handler(messages, model)
            await transport.send_event(
                self._format_sse_event("chunk", {"content": response.content})
            )
            usage = {}
            if response.usage:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            await transport.send_event(
                self._format_sse_event("done", {"usage": usage, "cost": 0.0})
            )
        else:
            await transport.send_event(
                self._format_sse_event("error", {"message": "No chat handler"})
            )

        await transport.close()

    @staticmethod
    def _format_sse_event(event_type: str, data: Any) -> str:
        """Format an SSE event string.

        Returns a string in the standard SSE format:
            event: <type>\\ndata: <json>\\n\\n
        """
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event_type}\ndata: {payload}\n\n"

    @staticmethod
    def _parse_jsonrpc(raw: str) -> dict[str, Any] | None:
        """Parse and validate a JSON-RPC 2.0 request."""
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(msg, dict):
            return None
        if msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return None
        return msg

    @staticmethod
    def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        """Build a JSON-RPC 2.0 error response."""
        return {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
            "id": req_id,
        }
