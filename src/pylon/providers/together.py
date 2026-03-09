"""Together AI LLM Provider (OpenAI-compatible API)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

try:
    import openai
except ImportError:
    openai = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import Chunk, Message, Response, TokenUsage

_PYLON_INTERNAL_KWARGS = frozenset({
    "cache_strategy",
    "batch_eligible",
    "context_compacted",
    "original_input_tokens",
    "prepared_input_tokens",
})


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Pylon messages to OpenAI-compatible format."""
    api_messages: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.role == "tool" and msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.role == "assistant" and msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        api_messages.append(entry)
    return api_messages


def _extract_usage(usage: Any) -> TokenUsage:
    """Extract token usage from Together AI response."""
    return TokenUsage(
        input_tokens=getattr(usage, "prompt_tokens", 0),
        output_tokens=getattr(usage, "completion_tokens", 0),
    )


class TogetherProvider:
    """Together AI LLM provider.

    Usage:
        provider = TogetherProvider(model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo")
        response = await provider.chat(messages)
    """

    def __init__(
        self,
        model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        *,
        api_key: str | None = None,
        base_url: str = "https://api.together.xyz/v1",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        if openai is None:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "together"

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat request to Together AI API."""
        api_messages = _to_openai_messages(messages)
        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
            "messages": api_messages,
        }

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools

        try:
            result = await self._client.chat.completions.create(**create_kwargs)
        except openai.APIError as e:
            raise ProviderError(
                f"Together API error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e

        if not result.choices:
            raise ProviderError("Together returned no choices", details={"model": result.model})
        choice = result.choices[0]
        content = choice.message.content or ""
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tc.function.arguments,
                })

        return Response(
            content=content,
            model=result.model,
            usage=_extract_usage(result.usage) if result.usage else None,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream a chat response from Together AI API."""
        api_messages = _to_openai_messages(messages)
        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools

        try:
            stream = await self._client.chat.completions.create(**create_kwargs)
            async for chunk in stream:
                if not chunk.choices and chunk.usage:
                    yield Chunk(usage=_extract_usage(chunk.usage))
                    continue
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason
                content = delta.content or ""
                tool_calls = []
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        tool_calls.append({
                            "id": tc.id or "",
                            "name": getattr(tc.function, "name", "") or "",
                            "input": getattr(tc.function, "arguments", "") or "",
                        })

                if content or tool_calls or finish_reason:
                    yield Chunk(
                        content=content,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                        usage=_extract_usage(chunk.usage) if chunk.usage else None,
                    )
        except openai.APIError as e:
            raise ProviderError(
                f"Together streaming error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e
