"""Ollama LLM Provider implementation (FR-02).

Implements LLMProvider Protocol using Ollama's HTTP API.
Supports chat() and stream() with TokenUsage tracking.
No external SDK required — uses httpx for HTTP calls.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import Chunk, Message, Response, TokenUsage

_PYLON_INTERNAL_KWARGS = frozenset({
    "cache_strategy",
    "batch_eligible",
    "context_compacted",
    "original_input_tokens",
    "prepared_input_tokens",
})


def _to_ollama_messages(messages: list[Message]) -> list[dict[str, str]]:
    """Convert Pylon messages to Ollama format.

    Ollama supports system/user/assistant roles.
    Tool-result messages are mapped to user role with a prefix.
    """
    api_messages: list[dict[str, str]] = []
    for msg in messages:
        if msg.role == "tool":
            api_messages.append({
                "role": "user",
                "content": f"[Tool Result] {msg.content}",
            })
        else:
            api_messages.append({"role": msg.role, "content": msg.content})
    return api_messages


def _extract_usage(data: dict[str, Any]) -> TokenUsage:
    """Extract token usage from Ollama response."""
    return TokenUsage(
        input_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
    )


class OllamaProvider:
    """Ollama LLM provider.

    Usage:
        provider = OllamaProvider(model="llama3.1")
        response = await provider.chat(messages)
    """

    def __init__(
        self,
        model: str = "llama3.1",
        *,
        base_url: str = "http://localhost:11434",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        if httpx is None:
            raise ProviderError(
                "httpx package not installed. Run: pip install httpx"
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat request to Ollama API."""
        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        api_messages = _to_ollama_messages(messages)
        payload: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "messages": api_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self._temperature),
                "num_predict": kwargs.get("max_tokens", self._max_tokens),
            },
        }

        try:
            resp = await self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(
                f"Ollama API error: {e}",
                details={
                    "status_code": (
                        getattr(e.response, "status_code", None)
                        if hasattr(e, "response")
                        else None
                    ),
                },
            ) from e

        data = resp.json()
        content = data.get("message", {}).get("content", "")

        return Response(
            content=content,
            model=data.get("model", self._model),
            usage=_extract_usage(data),
            tool_calls=[],
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[Chunk]:
        """Stream a chat response from Ollama API."""
        for key in _PYLON_INTERNAL_KWARGS:
            kwargs.pop(key, None)

        api_messages = _to_ollama_messages(messages)
        payload: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "messages": api_messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self._temperature),
                "num_predict": kwargs.get("max_tokens", self._max_tokens),
            },
        }

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    done = data.get("done", False)

                    if content:
                        yield Chunk(content=content)

                    if done:
                        yield Chunk(
                            finish_reason="stop",
                            usage=_extract_usage(data),
                        )
        except httpx.HTTPError as e:
            raise ProviderError(
                f"Ollama streaming error: {e}",
                details={
                    "status_code": (
                        getattr(e.response, "status_code", None)
                        if hasattr(e, "response")
                        else None
                    ),
                },
            ) from e
