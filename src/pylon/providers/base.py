"""LLM Provider Protocol (FR-02).

Provider-agnostic interface for LLM interactions.
Built-in providers: Anthropic, OpenAI, Ollama, AWS Bedrock, Google Vertex.
"""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class HealthStatus(enum.Enum):
    """Provider endpoint health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthCheckResult:
    """Result of a provider health check."""

    status: HealthStatus
    latency_ms: float = 0.0
    model_id: str = ""
    provider_name: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """Chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    content_blocks: list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class ReasoningOutput:
    """Normalized reasoning/thinking output from any provider."""

    content: str
    tokens: int = 0
    redacted_for_resend: Any = None


@dataclass
class Response:
    """LLM response."""

    content: str
    model: str
    usage: TokenUsage | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    reasoning: ReasoningOutput | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """Streaming chunk."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    reasoning_content: str | None = None


@dataclass
class TokenUsage:
    """Token usage tracking for cost management."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    All providers must implement chat() and stream().
    Optionally implement health_check() for proactive health monitoring.
    Fallback chains are configurable (e.g., Anthropic -> OpenAI -> Ollama).
    """

    async def chat(self, messages: list[Message], **kwargs: Any) -> Response: ...

    async def stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[Chunk]: ...

    @property
    def model_id(self) -> str: ...

    @property
    def provider_name(self) -> str: ...

    async def health_check(self) -> HealthCheckResult:
        """Check if the provider endpoint is reachable and responsive.

        Default implementation returns UNKNOWN. Providers that support
        health checks should override this method.
        """
        return HealthCheckResult(
            status=HealthStatus.UNKNOWN,
            model_id=self.model_id,
            provider_name=self.provider_name,
        )
