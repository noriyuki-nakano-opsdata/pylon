"""OpenTelemetry GenAI Semantic Conventions instrumentation."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pylon.observability.metrics import MetricsCollector
from pylon.observability.tracing import Span, SpanStatus, Tracer

# GenAI span attribute constants
GENAI_SYSTEM = "gen_ai.system"
GENAI_REQUEST_MODEL = "gen_ai.request.model"
GENAI_RESPONSE_MODEL = "gen_ai.response.model"
GENAI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GENAI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GENAI_REQUEST_TOP_P = "gen_ai.request.top_p"
GENAI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GENAI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GENAI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GENAI_ERROR_TYPE = "gen_ai.error.type"

# GenAI span event names
GENAI_CONTENT_PROMPT = "gen_ai.content.prompt"
GENAI_CONTENT_COMPLETION = "gen_ai.content.completion"

# Error types
ERROR_RATE_LIMIT = "rate_limit"
ERROR_AUTH = "auth"
ERROR_CONTEXT_LENGTH = "context_length"
ERROR_CONTENT_FILTER = "content_filter"

# GenAI-specific predefined metrics
GENAI_METRICS = {
    "genai.token.usage": "counter",
    "genai.request.duration": "histogram",
    "genai.request.count": "counter",
    "genai.request.error_count": "counter",
    "genai.cost.total": "counter",
}


class RedactionPolicy(Enum):
    NONE = "none"
    HASH = "hash"
    FULL = "full"


def _redact(content: str, policy: RedactionPolicy) -> str:
    if policy is RedactionPolicy.NONE:
        return content
    if policy is RedactionPolicy.HASH:
        return hashlib.sha256(content.encode()).hexdigest()
    return "[REDACTED]"


@dataclass
class GenAISpanBuilder:
    """Helper to create properly attributed GenAI spans."""

    tracer: Tracer
    operation_name: str
    system: str
    model: str
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    parent_id: str | None = None
    extra_attributes: dict[str, Any] = field(default_factory=dict)

    def build(self) -> Span:
        attrs: dict[str, Any] = {
            GENAI_SYSTEM: self.system,
            GENAI_REQUEST_MODEL: self.model,
        }
        if self.max_tokens is not None:
            attrs[GENAI_REQUEST_MAX_TOKENS] = self.max_tokens
        if self.temperature is not None:
            attrs[GENAI_REQUEST_TEMPERATURE] = self.temperature
        if self.top_p is not None:
            attrs[GENAI_REQUEST_TOP_P] = self.top_p
        attrs.update(self.extra_attributes)

        return self.tracer.start_span(
            name=self.operation_name,
            parent_id=self.parent_id,
            attributes=attrs,
        )


class GenAIInstrumentor:
    """Tracks GenAI calls, auto-records metrics (token usage, duration, cost)."""

    def __init__(
        self,
        tracer: Tracer,
        metrics: MetricsCollector,
        redaction_policy: RedactionPolicy = RedactionPolicy.FULL,
    ) -> None:
        self._tracer = tracer
        self._metrics = metrics
        self._redaction_policy = redaction_policy

    @property
    def redaction_policy(self) -> RedactionPolicy:
        return self._redaction_policy

    @redaction_policy.setter
    def redaction_policy(self, policy: RedactionPolicy) -> None:
        self._redaction_policy = policy

    def start_call(
        self,
        *,
        system: str,
        model: str,
        prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        parent_id: str | None = None,
    ) -> Span:
        builder = GenAISpanBuilder(
            tracer=self._tracer,
            operation_name=f"{system}.chat",
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            parent_id=parent_id,
        )
        span = builder.build()

        if prompt is not None:
            redacted = _redact(prompt, self._redaction_policy)
            span.add_event(GENAI_CONTENT_PROMPT, {"content": redacted})

        self._metrics.counter(
            "genai.request.count",
            labels={"model": model, "system": system},
        )
        return span

    def end_call(
        self,
        span: Span,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        finish_reasons: list[str] | None = None,
        completion: str | None = None,
        response_model: str | None = None,
        error_type: str | None = None,
        cost_usd: float | None = None,
    ) -> None:
        model = span.attributes.get(GENAI_REQUEST_MODEL, "unknown")
        system = span.attributes.get(GENAI_SYSTEM, "unknown")
        labels = {"model": model, "system": system}

        span.set_attribute(GENAI_USAGE_INPUT_TOKENS, input_tokens)
        span.set_attribute(GENAI_USAGE_OUTPUT_TOKENS, output_tokens)

        if finish_reasons is not None:
            span.set_attribute(GENAI_RESPONSE_FINISH_REASONS, finish_reasons)
        if response_model is not None:
            span.set_attribute(GENAI_RESPONSE_MODEL, response_model)

        if completion is not None:
            redacted = _redact(completion, self._redaction_policy)
            span.add_event(GENAI_CONTENT_COMPLETION, {"content": redacted})

        if error_type is not None:
            span.set_attribute(GENAI_ERROR_TYPE, error_type)
            self._metrics.counter("genai.request.error_count", labels=labels)
            self._tracer.end_span(span.span_id, status=SpanStatus.ERROR)
        else:
            self._tracer.end_span(span.span_id, status=SpanStatus.OK)

        self._metrics.counter(
            "genai.token.usage",
            value=input_tokens,
            labels={**labels, "type": "input"},
        )
        self._metrics.counter(
            "genai.token.usage",
            value=output_tokens,
            labels={**labels, "type": "output"},
        )

        duration = span.duration or 0.0
        self._metrics.histogram("genai.request.duration", duration, labels=labels)

        if cost_usd is not None:
            self._metrics.counter("genai.cost.total", value=cost_usd, labels=labels)


def record_genai_call(
    tracer: Tracer,
    metrics: MetricsCollector,
    *,
    system: str,
    model: str,
    prompt: str | None = None,
    completion: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    finish_reasons: list[str] | None = None,
    response_model: str | None = None,
    error_type: str | None = None,
    cost_usd: float | None = None,
    redaction_policy: RedactionPolicy = RedactionPolicy.FULL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    parent_id: str | None = None,
) -> Span:
    """Create a span and record metrics for a GenAI call in one shot."""
    instrumentor = GenAIInstrumentor(tracer, metrics, redaction_policy=redaction_policy)
    span = instrumentor.start_call(
        system=system,
        model=model,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        parent_id=parent_id,
    )
    instrumentor.end_call(
        span,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reasons=finish_reasons,
        completion=completion,
        response_model=response_model,
        error_type=error_type,
        cost_usd=cost_usd,
    )
    return span
