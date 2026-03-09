"""Codex app-server JSON-RPC bridge.

Wraps the ``codex app-server`` subprocess using JSON-RPC 2.0 over stdio
for session management, turn execution, and approval handling.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.providers.base import Chunk, Message, Response, TokenUsage


class CodexBridge(CLIBridge):
    """Bridge for the Codex app-server (JSON-RPC over stdio)."""

    def __init__(
        self,
        *,
        model: str = "codex-mini",
        approval_policy: str = "on-failure",
        sandbox_mode: str = "workspace-write",
    ) -> None:
        command = ["codex", "app-server"]
        super().__init__(command)
        self._model = model
        self._approval_policy = approval_policy
        self._sandbox_mode = sandbox_mode
        self._request_id = 0

    def _next_id(self) -> int:
        """Return the next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_jsonrpc(self, method: str, params: dict[str, Any]) -> dict:
        """Send a JSON-RPC 2.0 request and return the parsed result."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        raw = await self.send(json.dumps(request, separators=(",", ":")))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"error": raw}

        if "error" in data:
            error = data["error"]
            code = error.get("code", -1) if isinstance(error, dict) else -1
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise RuntimeError(f"JSON-RPC error {code}: {message}")
        return data.get("result", data)

    async def start_session(self, workspace: str) -> str:
        """Create a new Codex session and return the session ID."""
        result = await self._send_jsonrpc(
            "session.start",
            {
                "workspace": workspace,
                "model": self._model,
                "approval_policy": self._approval_policy,
                "sandbox_mode": self._sandbox_mode,
            },
        )
        return str(result.get("session_id", ""))

    async def send_turn(self, message: str) -> str:
        """Send a conversational turn and return the response text."""
        result = await self._send_jsonrpc(
            "turn.send",
            {"message": message},
        )
        return str(result.get("response", result.get("content", "")))

    async def approve(self, request_id: str, decision: str) -> None:
        """Submit an approval decision for a pending request."""
        await self._send_jsonrpc(
            "approval.respond",
            {"request_id": request_id, "decision": decision},
        )

    async def interrupt(self) -> None:
        """Interrupt the current turn."""
        await self._send_jsonrpc("turn.interrupt", {})


class CodexProvider(CLIBridgeProvider):
    """LLMProvider adapter for Codex app-server."""

    def __init__(
        self,
        bridge: CodexBridge,
        *,
        model: str = "codex-mini",
    ) -> None:
        super().__init__(bridge, provider_name_val="codex", model_id_val=model)
        self._codex_bridge = bridge

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send messages as a turn and return the response."""
        text = self._messages_to_text(messages)
        raw = await self._codex_bridge.send_turn(text)
        return Response(
            content=raw,
            model=self._model_id_val,
            usage=TokenUsage(),
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream is not natively supported; falls back to single response."""
        response = await self.chat(messages, **kwargs)
        yield Chunk(content=response.content, finish_reason="stop")
