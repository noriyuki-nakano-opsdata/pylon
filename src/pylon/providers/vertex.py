"""Google Vertex AI / Gemini LLM Provider implementation (FR-02).

Implements LLMProvider Protocol using the google-genai unified SDK.
Supports both Vertex AI (project-based) and Google AI Studio (api_key) modes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

try:
    from google import genai
except ImportError:
    genai = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import Chunk, Message, Response, TokenUsage

_PYLON_INTERNAL_KWARGS = frozenset({
    "cache_strategy",
    "batch_eligible",
    "context_compacted",
    "original_input_tokens",
    "prepared_input_tokens",
})


def _to_gemini_contents(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """Convert Pylon messages to google-genai format.

    Returns (system_instruction, contents).
    """
    system_parts: list[str] = []
    contents: list[dict] = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        elif msg.role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"text": f"[Tool Result] {msg.content}"}],
            })
        else:
            role = "model" if msg.role == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}],
            })

    system_instruction = "\n\n".join(part for part in system_parts if part)
    return system_instruction or None, contents


def _extract_usage(usage_metadata: Any) -> TokenUsage:
    """Extract token usage from google-genai response."""
    return TokenUsage(
        input_tokens=getattr(usage_metadata, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage_metadata, "candidates_token_count", 0) or 0,
    )


def _pop_internal_kwargs(kwargs: dict[str, Any]) -> None:
    """Remove pylon-internal kwargs before forwarding to the API."""
    for key in _PYLON_INTERNAL_KWARGS:
        kwargs.pop(key, None)


class VertexProvider:
    """Google Vertex AI / Gemini LLM provider.

    Usage (Vertex AI):
        provider = VertexProvider(project="my-project", location="us-central1")
        response = await provider.chat(messages)

    Usage (Google AI Studio):
        provider = VertexProvider(api_key="...")
        response = await provider.chat(messages)
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        *,
        project: str | None = None,
        location: str = "us-central1",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        if genai is None:
            raise ProviderError(
                "google-genai package not installed. Run: pip install google-genai"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

        if api_key:
            self._client = genai.Client(api_key=api_key)
        elif project:
            self._client = genai.Client(
                vertexai=True, project=project, location=location,
            )
        else:
            raise ProviderError(
                "Either api_key or project must be provided for VertexProvider"
            )

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "google"

    def _build_config(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Build the generation config dict."""
        config: dict[str, Any] = {
            "max_output_tokens": kwargs.get("max_tokens", self._max_tokens),
            "temperature": kwargs.get("temperature", self._temperature),
        }
        return config

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat request to Google Gemini / Vertex AI."""
        _pop_internal_kwargs(kwargs)
        system_instruction, contents = _to_gemini_contents(messages)

        config = self._build_config(kwargs)
        if system_instruction:
            config["system_instruction"] = system_instruction

        model = kwargs.get("model", self._model)

        try:
            result = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(
                f"Google API error: {e}",
                details={"error_type": type(e).__name__},
            ) from e

        usage = _extract_usage(result.usage_metadata) if result.usage_metadata else None

        return Response(
            content=result.text or "",
            model=model,
            usage=usage,
            finish_reason="stop",
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any,
    ) -> AsyncIterator[Chunk]:
        """Stream a chat response from Google Gemini / Vertex AI."""
        _pop_internal_kwargs(kwargs)
        system_instruction, contents = _to_gemini_contents(messages)

        config = self._build_config(kwargs)
        if system_instruction:
            config["system_instruction"] = system_instruction

        model = kwargs.get("model", self._model)

        try:
            response_stream = await self._client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )
            async for chunk in response_stream:
                text = chunk.text or ""
                usage = None
                if chunk.usage_metadata:
                    usage = _extract_usage(chunk.usage_metadata)
                yield Chunk(content=text, usage=usage)
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(
                f"Google streaming error: {e}",
                details={"error_type": type(e).__name__},
            ) from e
