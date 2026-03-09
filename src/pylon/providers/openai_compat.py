"""OpenAI-compatible LLM Provider base class.

Thin base class for providers that expose an OpenAI Chat Completions API.
Subclasses override hook methods for provider-specific behavior (auth,
request transformation, reasoning extraction, usage parsing).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

try:
    import openai
except ImportError:
    openai = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import (
    Chunk,
    Message,
    ReasoningOutput,
    Response,
    TokenUsage,
)

_PYLON_INTERNAL_KWARGS = frozenset({
    "cache_strategy",
    "batch_eligible",
    "context_compacted",
    "original_input_tokens",
    "prepared_input_tokens",
})


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Pylon messages to OpenAI format."""
    api_messages: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.role == "tool" and msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.role == "assistant" and msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        api_messages.append(entry)
    return api_messages


class OpenAICompatibleProvider:
    """Base class for OpenAI Chat Completions API-compatible providers.

    Subclasses customize behavior by overriding hook methods:
    - ``_build_auth_headers()``: extra HTTP headers (SDK handles Bearer by default)
    - ``_transform_request()``: modify the request dict before sending
    - ``_extract_reasoning()``: pull reasoning/thinking from a response choice
    - ``_extract_usage()``: convert SDK usage object to ``TokenUsage``
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str,
        provider_name: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        if openai is None:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._provider_name = provider_name

        headers = {**self._build_auth_headers(), **(default_headers or {})}
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=headers if headers else None,
        )

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return self._provider_name

    # ------------------------------------------------------------------
    # Hook methods (override in subclasses)
    # ------------------------------------------------------------------

    def _build_auth_headers(self) -> dict[str, str]:
        """Return extra auth headers. Default: empty (SDK handles Bearer)."""
        return {}

    def _transform_request(self, create_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Hook to modify the request payload before sending."""
        return create_kwargs

    def _extract_reasoning(
        self, choice: Any, raw_response: Any
    ) -> ReasoningOutput | None:
        """Extract reasoning output from a response choice.

        Default implementation checks for a ``reasoning_content`` attribute
        on the message, which is the convention used by DeepSeek, xAI, etc.
        """
        reasoning_content = getattr(
            getattr(choice, "message", None), "reasoning_content", None
        )
        if reasoning_content:
            return ReasoningOutput(content=reasoning_content)
        return None

    def _extract_usage(self, usage: Any) -> TokenUsage:
        """Convert SDK usage object to ``TokenUsage``."""
        return TokenUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )

    # ------------------------------------------------------------------
    # Core API methods
    # ------------------------------------------------------------------

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat completion request."""
        api_messages = _to_openai_messages(messages)

        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.pop("model", self._model),
            "max_tokens": kwargs.pop("max_tokens", self._max_tokens),
            "temperature": kwargs.pop("temperature", self._temperature),
            "messages": api_messages,
        }

        tools = kwargs.pop("tools", None)
        if tools:
            create_kwargs["tools"] = tools

        create_kwargs = self._transform_request(create_kwargs)

        try:
            result = await self._client.chat.completions.create(**create_kwargs)
        except openai.APIError as e:
            raise ProviderError(
                f"{self._provider_name} API error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e

        if not result.choices:
            raise ProviderError(
                f"{self._provider_name} returned no choices",
                details={"model": result.model},
            )
        choice = result.choices[0]
        content = choice.message.content or ""

        tool_calls: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tc.function.arguments,
                })

        reasoning = self._extract_reasoning(choice, result)
        usage = self._extract_usage(result.usage) if result.usage else None

        return Response(
            content=content,
            model=result.model,
            usage=usage,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            reasoning=reasoning,
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream a chat completion response."""
        api_messages = _to_openai_messages(messages)

        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        create_kwargs: dict[str, Any] = {
            "model": kwargs.pop("model", self._model),
            "max_tokens": kwargs.pop("max_tokens", self._max_tokens),
            "temperature": kwargs.pop("temperature", self._temperature),
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        tools = kwargs.pop("tools", None)
        if tools:
            create_kwargs["tools"] = tools

        create_kwargs = self._transform_request(create_kwargs)

        try:
            stream = await self._client.chat.completions.create(**create_kwargs)
            async for chunk in stream:
                if not chunk.choices and chunk.usage:
                    yield Chunk(usage=self._extract_usage(chunk.usage))
                    continue

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                content = delta.content or ""
                tool_calls: list[dict[str, Any]] = []
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
                        usage=(
                            self._extract_usage(chunk.usage)
                            if chunk.usage
                            else None
                        ),
                    )
        except openai.APIError as e:
            raise ProviderError(
                f"{self._provider_name} streaming error: {e}",
                details={"status_code": getattr(e, "status_code", None)},
            ) from e
