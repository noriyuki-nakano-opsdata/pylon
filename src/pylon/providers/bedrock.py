"""AWS Bedrock LLM Provider implementation (FR-02).

Implements LLMProvider Protocol using the AWS Bedrock Converse API.
Supports chat() and stream() with TokenUsage tracking.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator
from typing import Any

try:
    import boto3
    import botocore.exceptions
except ImportError:
    boto3 = None  # type: ignore[assignment]
    botocore = None  # type: ignore[assignment]

from pylon.errors import ProviderError
from pylon.providers.base import Chunk, Message, Response, TokenUsage

_PYLON_INTERNAL_KWARGS = frozenset({
    "cache_strategy",
    "batch_eligible",
    "context_compacted",
    "original_input_tokens",
    "prepared_input_tokens",
})


def _to_bedrock_messages(
    messages: list[Message],
) -> tuple[list[dict] | None, list[dict]]:
    """Convert Pylon messages to Bedrock Converse format.

    Returns (system_blocks, messages_list).
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
                        "toolResult": {
                            "toolUseId": msg.tool_call_id or "",
                            "content": [{"text": msg.content}],
                        }
                    }
                ],
            })
        else:
            api_messages.append({
                "role": msg.role,
                "content": [{"text": msg.content}],
            })

    system_blocks = [{"text": part} for part in system_parts if part] or None
    return system_blocks, api_messages


def _pop_internal_kwargs(kwargs: dict[str, Any]) -> None:
    """Remove pylon-internal kwargs that must not reach the Bedrock API."""
    for key in _PYLON_INTERNAL_KWARGS:
        kwargs.pop(key, None)


class BedrockProvider:
    """AWS Bedrock LLM provider using the Converse API.

    Usage:
        provider = BedrockProvider(model="anthropic.claude-sonnet-4-20250514-v1:0")
        response = await provider.chat(messages)
    """

    def __init__(
        self,
        model: str = "anthropic.claude-sonnet-4-20250514-v1:0",
        *,
        region_name: str = "us-east-1",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        profile_name: str | None = None,
    ) -> None:
        if boto3 is None:
            raise ProviderError(
                "boto3 package not installed. Run: pip install boto3"
            )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

        session_kwargs: dict[str, Any] = {"region_name": region_name}
        if profile_name is not None:
            session_kwargs["profile_name"] = profile_name

        session = boto3.Session(**session_kwargs)
        self._client = session.client("bedrock-runtime")

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "bedrock"

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Send a chat request to AWS Bedrock Converse API."""
        _pop_internal_kwargs(kwargs)
        system_blocks, api_messages = _to_bedrock_messages(messages)

        converse_kwargs: dict[str, Any] = {
            "modelId": kwargs.get("model", self._model),
            "messages": api_messages,
            "inferenceConfig": {
                "maxTokens": kwargs.get("max_tokens", self._max_tokens),
                "temperature": kwargs.get("temperature", self._temperature),
            },
        }
        if system_blocks:
            converse_kwargs["system"] = system_blocks

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(self._client.converse, **converse_kwargs),
            )
        except botocore.exceptions.ClientError as e:
            raise ProviderError(
                f"Bedrock API error: {e}",
                details={"error_code": e.response["Error"]["Code"]},
            ) from e

        output_text = result["output"]["message"]["content"][0]["text"]
        usage = result.get("usage", {})

        return Response(
            content=output_text,
            model=self._model,
            usage=TokenUsage(
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
            ),
            finish_reason=result.get("stopReason", "stop"),
        )

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream a chat response from AWS Bedrock Converse API."""
        _pop_internal_kwargs(kwargs)
        system_blocks, api_messages = _to_bedrock_messages(messages)

        converse_kwargs: dict[str, Any] = {
            "modelId": kwargs.get("model", self._model),
            "messages": api_messages,
            "inferenceConfig": {
                "maxTokens": kwargs.get("max_tokens", self._max_tokens),
                "temperature": kwargs.get("temperature", self._temperature),
            },
        }
        if system_blocks:
            converse_kwargs["system"] = system_blocks

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    self._client.converse_stream, **converse_kwargs
                ),
            )
        except botocore.exceptions.ClientError as e:
            raise ProviderError(
                f"Bedrock streaming error: {e}",
                details={"error_code": e.response["Error"]["Code"]},
            ) from e

        event_stream = result["stream"]
        for event in event_stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield Chunk(content=text)
            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason", "stop")
                yield Chunk(finish_reason=stop_reason)
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                yield Chunk(
                    usage=TokenUsage(
                        input_tokens=usage.get("inputTokens", 0),
                        output_tokens=usage.get("outputTokens", 0),
                    ),
                )
