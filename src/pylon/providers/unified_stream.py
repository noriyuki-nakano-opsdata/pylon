"""Unified streaming layer for all LLM providers.

Normalizes provider-specific streaming responses into a consistent
``AsyncIterator[Chunk]`` interface and provides a streaming-first
``chat()`` implementation that collects the full response from the stream.

Design principle: streaming is the primary interface; non-streaming is
derived from streaming by collecting all chunks. This ensures behavioral
consistency between ``chat()`` and ``stream()`` code paths.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pylon.providers.base import (
    Chunk,
    LLMProvider,
    Message,
    ReasoningOutput,
    Response,
    TokenUsage,
)


@dataclass
class StreamAccumulator:
    """Accumulates streaming chunks into a complete Response.

    Handles incremental content building, tool call assembly, and
    token usage tracking across multiple chunks.
    """

    content_parts: list[str] = field(default_factory=list)
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    finish_reason: str = "stop"
    usage: TokenUsage = field(default_factory=TokenUsage)
    reasoning_parts: list[str] = field(default_factory=list)
    model: str = ""
    chunk_count: int = 0

    def add_chunk(self, chunk: Chunk) -> None:
        """Process a single streaming chunk."""
        self.chunk_count += 1

        if chunk.content:
            self.content_parts.append(chunk.content)

        if chunk.tool_calls:
            for tc in chunk.tool_calls:
                tc_id = tc.get("id", "")
                if tc_id and tc_id not in self.tool_calls:
                    self.tool_calls[tc_id] = {
                        "id": tc_id,
                        "name": tc.get("name", ""),
                        "input": tc.get("input", ""),
                    }
                elif tc_id and tc_id in self.tool_calls:
                    # Append incremental arguments
                    existing = self.tool_calls[tc_id]
                    existing["input"] = existing.get("input", "") + tc.get(
                        "input", ""
                    )
                    if tc.get("name"):
                        existing["name"] = tc["name"]

        if chunk.finish_reason:
            self.finish_reason = chunk.finish_reason

        if chunk.usage:
            self.usage = TokenUsage(
                input_tokens=chunk.usage.input_tokens or self.usage.input_tokens,
                output_tokens=chunk.usage.output_tokens or self.usage.output_tokens,
                cache_read_tokens=chunk.usage.cache_read_tokens
                or self.usage.cache_read_tokens,
                cache_write_tokens=chunk.usage.cache_write_tokens
                or self.usage.cache_write_tokens,
                reasoning_tokens=chunk.usage.reasoning_tokens
                or self.usage.reasoning_tokens,
            )

        reasoning = getattr(chunk, "reasoning_content", None)
        if reasoning:
            self.reasoning_parts.append(reasoning)

    def to_response(self) -> Response:
        """Build the final Response from accumulated chunks."""
        reasoning = None
        if self.reasoning_parts:
            reasoning = ReasoningOutput(
                content="".join(self.reasoning_parts),
                tokens=self.usage.reasoning_tokens,
            )

        return Response(
            content="".join(self.content_parts),
            model=self.model,
            usage=self.usage if self.usage.total_tokens > 0 else None,
            tool_calls=list(self.tool_calls.values()),
            finish_reason=self.finish_reason,
            reasoning=reasoning,
        )


@dataclass
class StreamMetrics:
    """Real-time streaming metrics for observability."""

    chunks_received: int = 0
    bytes_received: int = 0
    first_token_ms: float | None = None
    total_ms: float = 0.0
    tokens_per_second: float = 0.0


class UnifiedStreamCollector:
    """Streaming-first wrapper around any LLMProvider.

    Provides:
    - ``stream()``: passthrough with metrics collection
    - ``chat()``: streaming-derived non-streaming call
    - ``stream_with_callback()``: streaming with per-chunk callback
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        on_chunk: Any | None = None,
        on_complete: Any | None = None,
    ) -> None:
        self._provider = provider
        self._on_chunk = on_chunk
        self._on_complete = on_complete

    @property
    def model_id(self) -> str:
        return self._provider.model_id

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response:
        """Streaming-first chat: collects all chunks into a Response.

        This ensures behavioral consistency with stream() — the same
        provider code path is exercised regardless of whether the caller
        wants streaming or not.
        """
        accumulator = StreamAccumulator(model=self._provider.model_id)
        async for chunk in self.stream(messages, **kwargs):
            accumulator.add_chunk(chunk)
        return accumulator.to_response()

    async def stream(
        self, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[Chunk]:
        """Stream with optional per-chunk callback."""
        import time

        start = time.monotonic()
        first_token_time = None
        chunk_count = 0
        total_bytes = 0

        async for chunk in self._provider.stream(messages, **kwargs):
            chunk_count += 1
            total_bytes += len(chunk.content.encode("utf-8")) if chunk.content else 0

            if first_token_time is None and chunk.content:
                first_token_time = (time.monotonic() - start) * 1000

            if self._on_chunk is not None:
                self._on_chunk(chunk)

            yield chunk

        elapsed = (time.monotonic() - start) * 1000
        metrics = StreamMetrics(
            chunks_received=chunk_count,
            bytes_received=total_bytes,
            first_token_ms=first_token_time,
            total_ms=elapsed,
        )

        if self._on_complete is not None:
            self._on_complete(metrics)


async def collect_stream(
    provider: LLMProvider,
    messages: list[Message],
    **kwargs: Any,
) -> tuple[Response, StreamMetrics]:
    """Convenience function: stream and collect into Response + metrics."""
    import time

    start = time.monotonic()
    first_token_time = None
    chunk_count = 0
    total_bytes = 0
    accumulator = StreamAccumulator(model=provider.model_id)

    async for chunk in provider.stream(messages, **kwargs):
        accumulator.add_chunk(chunk)
        chunk_count += 1
        total_bytes += len(chunk.content.encode("utf-8")) if chunk.content else 0
        if first_token_time is None and chunk.content:
            first_token_time = (time.monotonic() - start) * 1000

    elapsed = (time.monotonic() - start) * 1000
    metrics = StreamMetrics(
        chunks_received=chunk_count,
        bytes_received=total_bytes,
        first_token_ms=first_token_time,
        total_ms=elapsed,
    )
    return accumulator.to_response(), metrics
