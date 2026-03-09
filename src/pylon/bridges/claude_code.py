"""Claude Code CLI subprocess bridge.

Wraps the ``claude`` CLI tool to execute prompts via ``--print`` mode
and parses JSON output into the standard Response dataclass.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.providers.base import Chunk, Message, Response, TokenUsage


class ClaudeCodeBridge(CLIBridge):
    """Bridge for the Claude Code CLI (``claude --print``)."""

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-4-6",
        working_dir: str = ".",
        allowed_tools: list[str] | None = None,
        max_turns: int = 10,
    ) -> None:
        command = ["claude", "--print", "--output-format", "json"]
        if model:
            command.extend(["--model", model])
        if allowed_tools:
            for tool in allowed_tools:
                command.extend(["--allowedTools", tool])
        if max_turns != 10:
            command.extend(["--max-turns", str(max_turns)])

        super().__init__(command, working_dir=working_dir)
        self._model = model
        self._allowed_tools = allowed_tools or []
        self._max_turns = max_turns

    async def send(self, message: str) -> str:
        """Execute a one-shot prompt via ``claude -p``."""
        import asyncio

        cmd = self._command + ["-p", message]
        # Allow launching from within a Claude Code session
        env = dict(self._env or os.environ)
        env.pop("CLAUDECODE", None)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            raise RuntimeError(
                f"Claude Code process timed out after {self._timeout}s"
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            raise RuntimeError(
                f"Claude Code process exited with code {proc.returncode}"
                + (f": {stderr_text}" if stderr_text else "")
            )

        return stdout.decode()

    def _parse_response(self, raw: str) -> Response:
        """Parse JSON output from Claude Code CLI into a Response."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return Response(content=raw.strip(), model=self._model)

        content = ""
        if isinstance(data, dict):
            content = data.get("result", data.get("content", raw.strip()))
            model = data.get("model", self._model)
            usage_data = data.get("usage", {})
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
            )
            return Response(
                content=str(content),
                model=model,
                usage=usage,
                finish_reason=data.get("stop_reason", "stop"),
            )

        return Response(content=raw.strip(), model=self._model)


class ClaudeCodeProvider(CLIBridgeProvider):
    """LLMProvider adapter for Claude Code CLI."""

    def __init__(
        self,
        bridge: ClaudeCodeBridge,
        *,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        super().__init__(bridge, provider_name_val="claude-code", model_id_val=model)
        self._cc_bridge = bridge

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send messages and parse the JSON response."""
        text = self._messages_to_text(messages)
        raw = await self._cc_bridge.send(text)
        return self._cc_bridge._parse_response(raw)

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream is not natively supported; falls back to single response."""
        response = await self.chat(messages, **kwargs)
        yield Chunk(content=response.content, finish_reason="stop")
