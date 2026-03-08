from __future__ import annotations

import io
import json
import time

import pytest

from pylon.observability.execution_summary import build_execution_summary
from pylon.observability.exporters import (
    ConsoleExporter,
    ExporterProtocol,
    InMemoryExporter,
)
from pylon.observability.logging import LogLevel, StructuredLogger
from pylon.observability.metrics import (
    PREDEFINED_METRICS,
    MetricsCollector,
)
from pylon.observability.tracing import Span, SpanStatus, Tracer
from pylon.types import RunStatus, RunStopReason

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetricsCounter:
    def test_counter_increment(self) -> None:
        mc = MetricsCollector()
        mc.counter("requests", 1)
        metrics = mc.get_metrics()
        match = [c for c in metrics["counters"] if c["name"] == "requests"]
        assert len(match) == 1
        assert match[0]["value"] == 1

    def test_counter_accumulates(self) -> None:
        mc = MetricsCollector()
        mc.counter("requests", 3)
        mc.counter("requests", 7)
        match = [c for c in mc.get_metrics()["counters"] if c["name"] == "requests"]
        assert match[0]["value"] == 10

    def test_counter_with_labels(self) -> None:
        mc = MetricsCollector()
        mc.counter("requests", 1, labels={"method": "GET"})
        mc.counter("requests", 2, labels={"method": "POST"})
        counters = [
            c for c in mc.get_metrics()["counters"] if c["name"] == "requests"
        ]
        assert len(counters) == 2
        values = sorted(c["value"] for c in counters)
        assert values == [1, 2]

    def test_counter_rejects_negative(self) -> None:
        mc = MetricsCollector()
        with pytest.raises(ValueError, match="non-negative"):
            mc.counter("bad", -1)


class TestMetricsHistogram:
    def test_histogram_single_value(self) -> None:
        mc = MetricsCollector()
        mc.histogram("latency", 0.5)
        histograms = [
            h for h in mc.get_metrics()["histograms"] if h["name"] == "latency"
        ]
        assert histograms[0]["count"] == 1
        assert histograms[0]["total"] == 0.5

    def test_histogram_multiple_values(self) -> None:
        mc = MetricsCollector()
        for v in [1.0, 2.0, 3.0]:
            mc.histogram("latency", v)
        h = [x for x in mc.get_metrics()["histograms"] if x["name"] == "latency"][0]
        assert h["count"] == 3
        assert h["min"] == 1.0
        assert h["max"] == 3.0
        assert h["mean"] == pytest.approx(2.0)


class TestMetricsGauge:
    def test_gauge_set(self) -> None:
        mc = MetricsCollector()
        mc.gauge("cpu", 42.5)
        gauges = [g for g in mc.get_metrics()["gauges"] if g["name"] == "cpu"]
        assert gauges[0]["value"] == 42.5

    def test_gauge_overwrites(self) -> None:
        mc = MetricsCollector()
        mc.gauge("cpu", 10)
        mc.gauge("cpu", 90)
        gauges = [g for g in mc.get_metrics()["gauges"] if g["name"] == "cpu"]
        assert gauges[0]["value"] == 90


class TestPredefinedMetrics:
    def test_predefined_metric_names(self) -> None:
        expected = {
            "agent_task_duration",
            "agent_task_count",
            "llm_cost_usd",
            "llm_token_usage",
            "model_route_count",
            "workflow_step_count",
        }
        assert set(PREDEFINED_METRICS.keys()) == expected

    def test_predefined_metrics_initialized(self) -> None:
        mc = MetricsCollector()
        metrics = mc.get_metrics()
        counter_names = {c["name"] for c in metrics["counters"]}
        histogram_names = {h["name"] for h in metrics["histograms"]}
        assert "agent_task_count" in counter_names
        assert "llm_cost_usd" in counter_names
        assert "llm_token_usage" in counter_names
        assert "model_route_count" in counter_names
        assert "workflow_step_count" in counter_names
        assert "agent_task_duration" in histogram_names

    def test_predefined_counter_increments(self) -> None:
        mc = MetricsCollector()
        mc.counter("agent_task_count", 5)
        match = [
            c for c in mc.get_metrics()["counters"] if c["name"] == "agent_task_count"
        ]
        assert match[0]["value"] == 5


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


class TestSpanLifecycle:
    def test_start_and_end_span(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("op")
        assert span.end_time is None
        tracer.end_span(span.span_id)
        assert span.end_time is not None
        assert span.status == SpanStatus.OK

    def test_span_duration(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("op")
        time.sleep(0.01)
        tracer.end_span(span.span_id)
        assert span.duration is not None
        assert span.duration >= 0.01

    def test_span_add_event(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("op")
        span.add_event("cache_hit", {"key": "abc"})
        assert len(span.events) == 1
        assert span.events[0].name == "cache_hit"
        assert span.events[0].attributes == {"key": "abc"}

    def test_span_set_attribute(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("op", attributes={"init": True})
        span.set_attribute("extra", 42)
        assert span.attributes == {"init": True, "extra": 42}

    def test_end_span_twice_raises(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("op")
        tracer.end_span(span.span_id)
        with pytest.raises(ValueError, match="already ended"):
            tracer.end_span(span.span_id)

    def test_end_unknown_span_raises(self) -> None:
        tracer = Tracer()
        with pytest.raises(ValueError, match="not found"):
            tracer.end_span("nonexistent")


class TestNestedSpans:
    def test_parent_child(self) -> None:
        tracer = Tracer()
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent_id=parent.span_id)
        assert child.trace_id == parent.trace_id
        assert child.parent_id == parent.span_id

    def test_get_trace_returns_ordered(self) -> None:
        tracer = Tracer()
        root = tracer.start_span("root")
        tracer.start_span("child", parent_id=root.span_id)
        spans = tracer.get_trace(root.trace_id)
        assert len(spans) == 2
        assert spans[0].name == "root"
        assert spans[1].name == "child"

    def test_invalid_parent_raises(self) -> None:
        tracer = Tracer()
        with pytest.raises(ValueError, match="not found"):
            tracer.start_span("orphan", parent_id="missing")

    def test_get_trace_empty(self) -> None:
        tracer = Tracer()
        assert tracer.get_trace("nonexistent") == []

    def test_error_status(self) -> None:
        tracer = Tracer()
        span = tracer.start_span("failing")
        tracer.end_span(span.span_id, status=SpanStatus.ERROR)
        assert span.status == SpanStatus.ERROR


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestStructuredLogger:
    def test_log_entry_fields(self) -> None:
        logger = StructuredLogger()
        entry = logger.info("hello", user="alice")
        assert entry.level == LogLevel.INFO
        assert entry.message == "hello"
        assert entry.context["user"] == "alice"
        assert entry.timestamp > 0

    def test_log_levels(self) -> None:
        logger = StructuredLogger()
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        logs = logger.get_logs()
        assert len(logs) == 5

    def test_get_logs_filter_by_level(self) -> None:
        logger = StructuredLogger()
        logger.debug("d")
        logger.info("i")
        logger.error("e")
        errors = logger.get_logs(level=LogLevel.ERROR)
        assert len(errors) == 1
        assert errors[0].message == "e"

    def test_get_logs_limit(self) -> None:
        logger = StructuredLogger()
        for i in range(10):
            logger.info(f"msg-{i}")
        logs = logger.get_logs(limit=3)
        assert len(logs) == 3
        assert logs[0].message == "msg-9"

    def test_with_context_propagation(self) -> None:
        logger = StructuredLogger(context={"trace_id": "abc"})
        child = logger.with_context(span_id="s1")
        entry = child.info("step done")
        assert entry.context["trace_id"] == "abc"
        assert entry.context["span_id"] == "s1"

    def test_with_context_shares_storage(self) -> None:
        logger = StructuredLogger()
        child = logger.with_context(component="auth")
        child.info("from child")
        assert len(logger.get_logs()) == 1

    def test_context_override(self) -> None:
        logger = StructuredLogger(context={"env": "prod"})
        entry = logger.info("msg", env="staging")
        assert entry.context["env"] == "staging"


class TestExecutionSummary:
    def test_replan_count_falls_back_to_autonomy_state(self) -> None:
        summary = build_execution_summary(
            status=RunStatus.RUNNING,
            stop_reason=RunStopReason.NONE,
            suspension_reason=RunStopReason.NONE,
            state={"autonomy": {"replan_count": 2}},
            event_log=[],
        )

        assert summary["replan_count"] == 2


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


class TestExporterProtocol:
    def test_console_satisfies_protocol(self) -> None:
        assert isinstance(ConsoleExporter(), ExporterProtocol)

    def test_inmemory_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryExporter(), ExporterProtocol)


class TestConsoleExporter:
    def test_export_metrics(self) -> None:
        buf = io.StringIO()
        exporter = ConsoleExporter(stream=buf)
        exporter.export_metrics({"counters": [], "histograms": [], "gauges": []})
        line = buf.getvalue().strip()
        data = json.loads(line)
        assert data["type"] == "metrics"

    def test_export_span(self) -> None:
        buf = io.StringIO()
        exporter = ConsoleExporter(stream=buf)
        tracer = Tracer()
        span = tracer.start_span("op")
        tracer.end_span(span.span_id)
        exporter.export_span(span)
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "span"
        assert data["data"]["name"] == "op"

    def test_export_log(self) -> None:
        buf = io.StringIO()
        exporter = ConsoleExporter(stream=buf)
        logger = StructuredLogger()
        entry = logger.error("boom")
        exporter.export_log(entry)
        data = json.loads(buf.getvalue().strip())
        assert data["type"] == "log"
        assert data["data"]["level"] == "ERROR"


class TestInMemoryExporter:
    def test_stores_metrics(self) -> None:
        exp = InMemoryExporter()
        exp.export_metrics({"counters": [{"name": "x", "value": 1}]})
        assert len(exp.metrics) == 1

    def test_stores_spans(self) -> None:
        exp = InMemoryExporter()
        tracer = Tracer()
        span = tracer.start_span("op")
        exp.export_span(span)
        assert len(exp.spans) == 1

    def test_stores_logs(self) -> None:
        exp = InMemoryExporter()
        logger = StructuredLogger()
        entry = logger.info("hi")
        exp.export_log(entry)
        assert len(exp.logs) == 1

    def test_clear(self) -> None:
        exp = InMemoryExporter()
        exp.export_metrics({})
        exp.export_span(Span(trace_id="t", span_id="s", name="x"))
        exp.export_log(StructuredLogger().info("x"))
        exp.clear()
        assert exp.metrics == []
        assert exp.spans == []
        assert exp.logs == []
