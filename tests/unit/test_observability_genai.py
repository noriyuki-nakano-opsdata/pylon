"""Tests for GenAI OpenTelemetry instrumentation."""

from __future__ import annotations

import hashlib

import pytest

from pylon.observability.genai import (
    ERROR_RATE_LIMIT,
    GENAI_CONTENT_COMPLETION,
    GENAI_CONTENT_PROMPT,
    GENAI_ERROR_TYPE,
    GENAI_REQUEST_MAX_TOKENS,
    GENAI_REQUEST_MODEL,
    GENAI_REQUEST_TEMPERATURE,
    GENAI_REQUEST_TOP_P,
    GENAI_RESPONSE_FINISH_REASONS,
    GENAI_RESPONSE_MODEL,
    GENAI_SYSTEM,
    GENAI_USAGE_INPUT_TOKENS,
    GENAI_USAGE_OUTPUT_TOKENS,
    GenAIInstrumentor,
    GenAISpanBuilder,
    RedactionPolicy,
    _redact,
    record_genai_call,
)
from pylon.observability.metrics import MetricsCollector
from pylon.observability.tracing import SpanStatus, Tracer


@pytest.fixture
def tracer():
    return Tracer()


@pytest.fixture
def metrics():
    return MetricsCollector()


@pytest.fixture
def instrumentor(tracer, metrics):
    return GenAIInstrumentor(tracer, metrics)


class TestRedaction:
    def test_none_returns_original(self):
        assert _redact("secret", RedactionPolicy.NONE) == "secret"

    def test_hash_returns_sha256(self):
        expected = hashlib.sha256(b"secret").hexdigest()
        assert _redact("secret", RedactionPolicy.HASH) == expected

    def test_full_returns_redacted(self):
        assert _redact("secret", RedactionPolicy.FULL) == "[REDACTED]"


class TestGenAISpanBuilder:
    def test_build_basic_span(self, tracer):
        builder = GenAISpanBuilder(
            tracer=tracer,
            operation_name="openai.chat",
            system="openai",
            model="gpt-4o",
        )
        span = builder.build()
        assert span.attributes[GENAI_SYSTEM] == "openai"
        assert span.attributes[GENAI_REQUEST_MODEL] == "gpt-4o"
        assert GENAI_REQUEST_MAX_TOKENS not in span.attributes

    def test_build_with_all_params(self, tracer):
        builder = GenAISpanBuilder(
            tracer=tracer,
            operation_name="anthropic.chat",
            system="anthropic",
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.7,
            top_p=0.9,
        )
        span = builder.build()
        assert span.attributes[GENAI_REQUEST_MAX_TOKENS] == 1024
        assert span.attributes[GENAI_REQUEST_TEMPERATURE] == 0.7
        assert span.attributes[GENAI_REQUEST_TOP_P] == 0.9

    def test_build_with_extra_attributes(self, tracer):
        builder = GenAISpanBuilder(
            tracer=tracer,
            operation_name="openai.chat",
            system="openai",
            model="gpt-4o",
            extra_attributes={"custom.key": "value"},
        )
        span = builder.build()
        assert span.attributes["custom.key"] == "value"


class TestGenAIInstrumentor:
    def test_start_and_end_call(self, instrumentor, tracer):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        assert span.attributes[GENAI_SYSTEM] == "openai"
        assert span.name == "openai.chat"

        instrumentor.end_call(
            span, input_tokens=100, output_tokens=50, finish_reasons=["stop"]
        )
        assert span.attributes[GENAI_USAGE_INPUT_TOKENS] == 100
        assert span.attributes[GENAI_USAGE_OUTPUT_TOKENS] == 50
        assert span.attributes[GENAI_RESPONSE_FINISH_REASONS] == ["stop"]
        assert span.status == SpanStatus.OK
        assert span.end_time is not None

    def test_prompt_redaction_full(self, instrumentor):
        span = instrumentor.start_call(
            system="openai", model="gpt-4o", prompt="Tell me a secret"
        )
        prompt_event = span.events[0]
        assert prompt_event.name == GENAI_CONTENT_PROMPT
        assert prompt_event.attributes["content"] == "[REDACTED]"

    def test_prompt_redaction_none(self, tracer, metrics):
        inst = GenAIInstrumentor(tracer, metrics, redaction_policy=RedactionPolicy.NONE)
        span = inst.start_call(
            system="openai", model="gpt-4o", prompt="visible prompt"
        )
        assert span.events[0].attributes["content"] == "visible prompt"

    def test_completion_redaction(self, instrumentor):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        instrumentor.end_call(span, completion="secret output")
        completion_event = [e for e in span.events if e.name == GENAI_CONTENT_COMPLETION]
        assert len(completion_event) == 1
        assert completion_event[0].attributes["content"] == "[REDACTED]"

    def test_error_tracking(self, instrumentor, metrics):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        instrumentor.end_call(span, error_type=ERROR_RATE_LIMIT)
        assert span.status == SpanStatus.ERROR
        assert span.attributes[GENAI_ERROR_TYPE] == ERROR_RATE_LIMIT

    def test_response_model_attribute(self, instrumentor):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        instrumentor.end_call(span, response_model="gpt-4o-2024-08-06")
        assert span.attributes[GENAI_RESPONSE_MODEL] == "gpt-4o-2024-08-06"

    def test_metrics_recorded(self, instrumentor, metrics):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        instrumentor.end_call(span, input_tokens=200, output_tokens=100)

        data = metrics.get_metrics()
        counter_names = [c["name"] for c in data["counters"]]
        assert "genai.request.count" in counter_names
        assert "genai.token.usage" in counter_names

        histogram_names = [h["name"] for h in data["histograms"]]
        assert "genai.request.duration" in histogram_names

    def test_cost_metric_recorded(self, instrumentor, metrics):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        instrumentor.end_call(span, cost_usd=0.05)

        data = metrics.get_metrics()
        cost_counters = [
            c for c in data["counters"] if c["name"] == "genai.cost.total"
        ]
        assert len(cost_counters) == 1
        assert cost_counters[0]["value"] == 0.05

    def test_redaction_policy_property(self, instrumentor):
        assert instrumentor.redaction_policy == RedactionPolicy.FULL
        instrumentor.redaction_policy = RedactionPolicy.NONE
        assert instrumentor.redaction_policy == RedactionPolicy.NONE

    def test_no_prompt_event_when_none(self, instrumentor):
        span = instrumentor.start_call(system="openai", model="gpt-4o")
        assert len(span.events) == 0


class TestRecordGenAICall:
    def test_one_shot_call(self, tracer, metrics):
        span = record_genai_call(
            tracer,
            metrics,
            system="anthropic",
            model="claude-sonnet-4-6",
            prompt="Hello",
            completion="Hi there",
            input_tokens=10,
            output_tokens=5,
            finish_reasons=["end_turn"],
            max_tokens=512,
            temperature=0.5,
        )
        assert span.status == SpanStatus.OK
        assert span.end_time is not None
        assert span.attributes[GENAI_SYSTEM] == "anthropic"
        assert span.attributes[GENAI_USAGE_INPUT_TOKENS] == 10

    def test_one_shot_with_error(self, tracer, metrics):
        span = record_genai_call(
            tracer,
            metrics,
            system="openai",
            model="gpt-4o",
            error_type=ERROR_RATE_LIMIT,
        )
        assert span.status == SpanStatus.ERROR

    def test_custom_redaction_policy(self, tracer, metrics):
        span = record_genai_call(
            tracer,
            metrics,
            system="openai",
            model="gpt-4o",
            prompt="visible",
            redaction_policy=RedactionPolicy.NONE,
        )
        prompt_events = [e for e in span.events if e.name == GENAI_CONTENT_PROMPT]
        assert prompt_events[0].attributes["content"] == "visible"
