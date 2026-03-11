"""Gemini CLI subprocess bridge.

Wraps the ``gemini`` CLI tool to execute prompts via ``-p`` flag
and parses output into the standard Response dataclass.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.providers.base import Chunk, Message, Response, TokenUsage


class GeminiCLIBridge(CLIBridge):
    """Bridge for the Gemini CLI (``gemini -p``)."""

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-pro",
        working_dir: str = ".",
        sandbox: bool = False,
        yolo: bool = True,
        timeout: float = 300.0,
    ) -> None:
        command = ["gemini"]
        if model:
            command.extend(["-m", model])
        if sandbox:
            command.append("-s")
        if yolo:
            command.append("-y")
        super().__init__(command, working_dir=working_dir, timeout=timeout)
        self._model = model

    async def send(self, message: str) -> str:
        """Execute a one-shot prompt via ``gemini -p``."""
        cmd = self._command + ["-p", message]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
            env=self._env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except TimeoutError:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            raise RuntimeError(
                f"Gemini CLI process timed out after {self._timeout}s"
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            raise RuntimeError(
                f"Gemini CLI process exited with code {proc.returncode}"
                + (f": {stderr_text}" if stderr_text else "")
            )

        return stdout.decode()

    def _parse_response(self, raw: str) -> Response:
        """Parse text output from Gemini CLI into a Response."""
        return Response(
            content=raw.strip(),
            model=self._model,
            usage=TokenUsage(),
            finish_reason="stop",
        )


class GeminiCLIProvider(CLIBridgeProvider):
    """LLMProvider adapter for Gemini CLI."""

    def __init__(
        self,
        bridge: GeminiCLIBridge,
        *,
        model: str = "gemini-2.5-pro",
    ) -> None:
        super().__init__(bridge, provider_name_val="gemini-cli", model_id_val=model)
        self._gemini_bridge = bridge

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send messages and parse the response."""
        text = self._messages_to_text(messages)
        raw = await self._gemini_bridge.send(text)
        return self._gemini_bridge._parse_response(raw)

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream is not natively supported; falls back to single response."""
        response = await self.chat(messages, **kwargs)
        yield Chunk(content=response.content, finish_reason="stop")
