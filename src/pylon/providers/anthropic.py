"""Anthropic LLM Provider implementation (FR-02).

Implements LLMProvider Protocol using the Anthropic SDK.
Supports chat() and stream() with TokenUsage tracking.
"""

from __future__ import annotations

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
    system_prompt: str | None = None
    api_messages: list[dict] = []

    for msg in messages:
        if msg.role == "system":
            system_prompt = msg.content
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
        else:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            api_messages.append(entry)

    return system_prompt, api_messages


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
            create_kwargs["tools"] = tools

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

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
            "messages": api_messages,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt

        try:
            async with self._client.messages.stream(**create_kwargs) as stream:
                async for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "text"):
                                yield Chunk(content=delta.text)
                        elif event.type == "message_stop":
                            yield Chunk(finish_reason="stop")
        except anthropic.APIError as e:
            raise ProviderError(
                f"Anthropic streaming error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e
