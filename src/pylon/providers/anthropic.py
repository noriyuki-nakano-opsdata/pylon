"""Anthropic LLM Provider implementation (FR-02).

Implements LLMProvider Protocol using the Anthropic SDK.
Supports chat() and stream() with TokenUsage tracking.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import Chunk, Message, Response, TokenUsage


def _to_anthropic_messages(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """Convert Pylon messages to Anthropic format.

    Returns (system_prompt, messages_list).
    """
    system_parts: list[str] = []
    api_messages: list[dict] = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        elif msg.role == "tool":
            api_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }
                ],
            })
        elif msg.role == "assistant" and msg.tool_calls:
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tool_call in msg.tool_calls:
                tool_input = tool_call.get("input", {})
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except json.JSONDecodeError:
                        tool_input = {"raw": tool_input}
                if not isinstance(tool_input, dict):
                    tool_input = {"raw": tool_input}
                blocks.append({
                    "type": "tool_use",
                    "id": str(tool_call.get("id", "")),
                    "name": str(tool_call.get("name", "")),
                    "input": tool_input,
                })
            api_messages.append({"role": "assistant", "content": blocks})
        else:
            content: Any = msg.content
            if msg.content_blocks:
                content = msg.content_blocks
            entry: dict[str, Any] = {"role": msg.role, "content": content}
            api_messages.append(entry)

    system_prompt = "\n\n".join(part for part in system_parts if part)
    return system_prompt or None, api_messages


def _normalize_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = dict(tool["function"])
            normalized.append({
                "name": str(fn.get("name", "")),
                "description": str(fn.get("description", "")),
                "input_schema": (
                    dict(fn.get("parameters"))
                    if isinstance(fn.get("parameters"), dict)
                    else {"type": "object", "properties": {}}
                ),
            })
        else:
            normalized.append(tool)
    return normalized


def _extract_usage(usage: Any) -> TokenUsage:
    """Extract token usage from Anthropic response."""
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0),
    )


class AnthropicProvider:
    """Anthropic Claude LLM provider.

    Usage:
        provider = AnthropicProvider(model="claude-sonnet-4-20250514")
        response = await provider.chat(messages)
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        *,
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        if anthropic is None:
            raise ProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat request to Anthropic API."""
        system_prompt, api_messages = _to_anthropic_messages(messages)
        kwargs.pop("cache_strategy", None)
        kwargs.pop("batch_eligible", None)
        kwargs.pop("context_compacted", None)
        kwargs.pop("original_input_tokens", None)
        kwargs.pop("prepared_input_tokens", None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
            "messages": api_messages,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _normalize_anthropic_tools(list(tools))

        try:
            result = await self._client.messages.create(**create_kwargs)
        except anthropic.APIError as e:
            raise ProviderError(
                f"Anthropic API error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e

        content_parts = []
        tool_calls = []
        for block in result.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return Response(
            content="\n".join(content_parts),
            model=result.model,
            usage=_extract_usage(result.usage),
            tool_calls=tool_calls,
            finish_reason=result.stop_reason or "stop",
        )

    async def stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[Chunk]:
        """Stream a chat response from Anthropic API."""
        system_prompt, api_messages = _to_anthropic_messages(messages)
        kwargs.pop("cache_strategy", None)
        kwargs.pop("batch_eligible", None)
        kwargs.pop("context_compacted", None)
        kwargs.pop("original_input_tokens", None)
        kwargs.pop("prepared_input_tokens", None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
            "messages": api_messages,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt
        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _normalize_anthropic_tools(list(tools))

        try:
            partial_tool_inputs: dict[int, str] = {}
            tool_call_meta: dict[int, tuple[str, str]] = {}  # index -> (id, name)
            async with self._client.messages.stream(**create_kwargs) as stream:
                async for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "text"):
                                yield Chunk(content=delta.text)
                            elif getattr(delta, "type", None) == "input_json_delta":
                                index = int(getattr(event, "index", 0))
                                partial_tool_inputs[index] = (
                                    partial_tool_inputs.get(index, "")
                                    + str(getattr(delta, "partial_json", ""))
                                )
                        elif event.type == "content_block_start":
                            block = getattr(event, "content_block", None)
                            if getattr(block, "type", None) == "tool_use":
                                index = int(getattr(event, "index", 0))
                                tc_id = getattr(block, "id", "")
                                tc_name = getattr(block, "name", "")
                                tool_call_meta[index] = (tc_id, tc_name)
                                yield Chunk(
                                    tool_calls=[
                                        {
                                            "id": tc_id,
                                            "name": tc_name,
                                            "input": getattr(block, "input", {}),
                                        }
                                    ]
                                )
                        elif event.type == "content_block_stop":
                            index = int(getattr(event, "index", 0))
                            partial_json = partial_tool_inputs.pop(index, "")
                            if partial_json:
                                tc_id, tc_name = tool_call_meta.pop(index, ("", ""))
                                yield Chunk(
                                    tool_calls=[
                                        {
                                            "id": tc_id,
                                            "name": tc_name,
                                            "input": partial_json,
                                        }
                                    ]
                                )
                            else:
                                tool_call_meta.pop(index, None)
                        elif event.type == "message_delta":
                            usage = getattr(event, "usage", None)
                            finish_reason = getattr(
                                getattr(event, "delta", None),
                                "stop_reason",
                                None,
                            )
                            if usage is not None or finish_reason is not None:
                                yield Chunk(
                                    finish_reason=finish_reason,
                                    usage=_extract_usage(usage) if usage is not None else None,
                                )
                        elif event.type == "message_stop":
                            yield Chunk(finish_reason="stop")
        except anthropic.APIError as e:
            raise ProviderError(
                f"Anthropic streaming error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e
