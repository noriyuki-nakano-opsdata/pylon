"""Generic CLI tool subprocess wrapper base class.

Provides async subprocess management for wrapping CLI tools behind
the LLMProvider protocol. Subclass CLIBridge for specific tools.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

from pylon.providers.base import Chunk, Message, Response, TokenUsage


class CLIBridge:
    """Async subprocess wrapper for CLI tools.

    Manages a long-running subprocess, sending messages via stdin
    and reading responses from stdout.
    """

    def __init__(
        self,
        command: list[str],
        *,
        working_dir: str = ".",
        timeout: float = 300.0,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._working_dir = working_dir
        self._timeout = timeout
        self._env = {**os.environ, **env} if env else None
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        """Start the subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
            env=self._env,
        )

    async def stop(self) -> None:
        """Terminate the subprocess and wait for exit."""
        if self._process is None:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except (TimeoutError, ProcessLookupError):
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError, OSError):
                pass
        finally:
            self._process = None

    async def send(self, message: str) -> str:
        """Send a message via stdin and read the response from stdout.

        Messages are newline-delimited. Waits for a complete line response.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Process not started. Call start() first.")
        if self._process.stdout is None:
            raise RuntimeError("Process stdout not available.")

        data = (message.rstrip("\n") + "\n").encode()
        self._process.stdin.write(data)
        await self._process.stdin.drain()

        line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=self._timeout,
        )
        if not line:
            raise RuntimeError(
                f"Process exited unexpectedly (code={self._process.returncode})"
            )
        return line.decode().rstrip("\n")

    async def stream(self, message: str) -> AsyncIterator[str]:
        """Send a message and yield response lines as they arrive.

        Stops when an empty line or EOF is encountered.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Process not started. Call start() first.")
        if self._process.stdout is None:
            raise RuntimeError("Process stdout not available.")

        data = (message.rstrip("\n") + "\n").encode()
        self._process.stdin.write(data)
        await self._process.stdin.drain()

        while True:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._timeout,
            )
            if not line:
                break
            decoded = line.decode().rstrip("\n")
            if not decoded:
                break
            yield decoded

    @property
    def is_running(self) -> bool:
        """Check whether the subprocess is alive."""
        return self._process is not None and self._process.returncode is None


class CLIBridgeProvider:
    """Adapter that wraps a CLIBridge to satisfy the LLMProvider protocol.

    Converts Message lists to plain text, delegates to the bridge,
    and wraps raw output in Response / Chunk dataclasses.
    """

    def __init__(
        self,
        bridge: CLIBridge,
        provider_name_val: str,
        model_id_val: str,
    ) -> None:
        self._bridge = bridge
        self._provider_name_val = provider_name_val
        self._model_id_val = model_id_val

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send messages through the bridge and return a Response."""
        text = self._messages_to_text(messages)
        raw = await self._bridge.send(text)
        return Response(
            content=raw,
            model=self._model_id_val,
            usage=TokenUsage(),
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream messages through the bridge, yielding Chunks."""
        text = self._messages_to_text(messages)
        async for line in self._bridge.stream(text):
            yield Chunk(content=line)
        yield Chunk(content="", finish_reason="stop")

    @property
    def provider_name(self) -> str:
        return self._provider_name_val

    @property
    def model_id(self) -> str:
        return self._model_id_val

    @staticmethod
    def _messages_to_text(messages: list[Message]) -> str:
        """Flatten a message list into a single text prompt."""
        parts: list[str] = []
        for msg in messages:
            parts.append(f"[{msg.role}] {msg.content}")
        return "\n".join(parts)
