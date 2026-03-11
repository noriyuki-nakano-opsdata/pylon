"""Kimi Code CLI subprocess bridge.

Wraps the ``kimi`` CLI tool to execute prompts via ``--print`` mode
and parses output into the standard Response dataclass.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.providers.base import Chunk, Message, Response, TokenUsage


class KimiCodeBridge(CLIBridge):
    """Bridge for the Kimi Code CLI (``kimi --print``)."""

    def __init__(
        self,
        *,
        model: str = "kimi-latest",
        working_dir: str = ".",
        output_format: str = "text",
        timeout: float = 300.0,
    ) -> None:
        command = ["kimi", "--print"]
        if output_format == "stream-json":
            command.extend(["--output-format", "stream-json"])
        super().__init__(command, working_dir=working_dir, timeout=timeout)
        self._model = model
        self._output_format = output_format

    async def send(self, message: str) -> str:
        """Execute a one-shot prompt via ``kimi --print -p``."""
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
                f"Kimi Code process timed out after {self._timeout}s"
            )

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            raise RuntimeError(
                f"Kimi Code process exited with code {proc.returncode}"
                + (f": {stderr_text}" if stderr_text else "")
            )

        return stdout.decode()

    def _parse_response(self, raw: str) -> Response:
        """Parse output from Kimi Code CLI into a Response.

        Filters out debug/control lines (TurnBegin, LLM not set, etc.)
        that Kimi CLI may emit to stdout in --print mode.
        """
        if self._output_format == "stream-json":
            content_parts: list[str] = []
            for line in raw.strip().splitlines():
                try:
                    data = json.loads(line)
                    text = data.get("content", data.get("text", ""))
                    if text:
                        content_parts.append(text)
                except json.JSONDecodeError:
                    content_parts.append(line)
            return Response(
                content="".join(content_parts),
                model=self._model,
                usage=TokenUsage(),
                finish_reason="stop",
            )

        # Filter out Kimi CLI debug/control lines from text output.
        # Kimi --print emits TurnBegin(...), StepBegin(...),
        # StatusUpdate(...), TurnEnd(), and TextPart(...) blocks.
        # We extract content from TextPart lines and ignore the rest.
        import re

        lines = raw.strip().splitlines()
        text_parts: list[str] = []
        filtered: list[str] = []
        skip_block = False

        for line in lines:
            stripped = line.strip()

            # Extract text from TextPart(type='text', text='...')
            tp_match = re.match(
                r"TextPart\(type=['\"]text['\"],\s*text=['\"](.+?)['\"]\)\s*$",
                stripped,
            )
            if tp_match:
                text_parts.append(tp_match.group(1))
                continue

            # Skip known control blocks
            if any(
                stripped.startswith(prefix)
                for prefix in (
                    "TurnBegin(", "TurnEnd(", "StepBegin(",
                    "StatusUpdate(", "LLM not set",
                )
            ):
                # Single-line blocks (ending with ')') don't need multi-line skip
                if not stripped.endswith(")"):
                    skip_block = True
                continue
            if skip_block:
                if stripped == ")" or stripped == "":
                    skip_block = False
                continue

            filtered.append(line)

        # Prefer TextPart content if found, otherwise use filtered lines
        if text_parts:
            content = "\n".join(text_parts)
        else:
            content = "\n".join(filtered).strip()
        return Response(
            content=content,
            model=self._model,
            usage=TokenUsage(),
            finish_reason="stop",
        )


class KimiCodeProvider(CLIBridgeProvider):
    """LLMProvider adapter for Kimi Code CLI."""

    def __init__(
        self,
        bridge: KimiCodeBridge,
        *,
        model: str = "kimi-latest",
    ) -> None:
        super().__init__(bridge, provider_name_val="kimi-code", model_id_val=model)
        self._kimi_bridge = bridge

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send messages and parse the response.

        Uses the last user message content directly as the prompt,
        since Kimi CLI --print mode expects plain text, not role-tagged format.
        """
        # Extract last user message for CLI prompt
        user_msgs = [m for m in messages if m.role == "user"]
        text = user_msgs[-1].content if user_msgs else self._messages_to_text(messages)
        raw = await self._kimi_bridge.send(text)
        return self._kimi_bridge._parse_response(raw)

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream is not natively supported; falls back to single response."""
        response = await self.chat(messages, **kwargs)
        yield Chunk(content=response.content, finish_reason="stop")
