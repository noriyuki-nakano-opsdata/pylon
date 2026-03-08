from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MetricType(Enum):
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


# Pre-defined metric names for the Pylon platform.
PREDEFINED_METRICS: dict[str, MetricType] = {
    "agent_task_duration": MetricType.HISTOGRAM,
    "agent_task_count": MetricType.COUNTER,
    "llm_token_usage": MetricType.COUNTER,
    "llm_cost_usd": MetricType.COUNTER,
    "model_route_count": MetricType.COUNTER,
    "workflow_step_count": MetricType.COUNTER,
}


@dataclass
class MetricPoint:
    """A single metric data point."""

    name: str
    metric_type: MetricType
    value: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class HistogramData:
    """Aggregated histogram data."""

    count: int = 0
    total: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")
    values: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else 0.0


def _label_key(labels: dict[str, str] | None) -> str:
    """Create a deterministic string key from a label dict."""
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


class MetricsCollector:
    """In-memory metric collector supporting counters, histograms, and gauges.

    Thread-safe. All public methods can be called from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {(name, label_key): value}
        self._counters: dict[tuple[str, str], float] = {}
        self._histograms: dict[tuple[str, str], HistogramData] = {}
        self._gauges: dict[tuple[str, str], float] = {}
        # Track label dicts for export.
        self._label_map: dict[tuple[str, str], dict[str, str]] = {}

        # Register pre-defined metrics (ensures they exist even before first write).
        for name in PREDEFINED_METRICS:
            mt = PREDEFINED_METRICS[name]
            key = (name, "")
            if mt is MetricType.COUNTER:
                self._counters[key] = 0.0
            elif mt is MetricType.HISTOGRAM:
                self._histograms[key] = HistogramData()
            elif mt is MetricType.GAUGE:
                self._gauges[key] = 0.0
            self._label_map[key] = {}

    # -- public API ----------------------------------------------------------

    def counter(
        self,
        name: str,
        value: float = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter by *value* (must be >= 0)."""
        if value < 0:
            raise ValueError("Counter value must be non-negative")
        lk = _label_key(labels)
        key = (name, lk)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value
            self._label_map.setdefault(key, labels or {})

    def histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a value in a histogram distribution."""
        lk = _label_key(labels)
        key = (name, lk)
        with self._lock:
            hd = self._histograms.get(key)
            if hd is None:
                hd = HistogramData()
                self._histograms[key] = hd
            hd.count += 1
            hd.total += value
            hd.min = min(hd.min, value)
            hd.max = max(hd.max, value)
            hd.values.append(value)
            self._label_map.setdefault(key, labels or {})

    def gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set the current value of a gauge."""
        lk = _label_key(labels)
        key = (name, lk)
        with self._lock:
            self._gauges[key] = value
            self._label_map.setdefault(key, labels or {})

    def get_metrics(self) -> dict[str, Any]:
        """Return a snapshot of all collected metrics.

        Returns a dict with keys ``counters``, ``histograms``, ``gauges``.
        Each value is a list of dicts describing the individual metric series.
        """
        with self._lock:
            return {
                "counters": [
                    {"name": k[0], "labels": self._label_map.get(k, {}), "value": v}
                    for k, v in self._counters.items()
                ],
                "histograms": [
                    {
                        "name": k[0],
                        "labels": self._label_map.get(k, {}),
                        "count": v.count,
                        "total": v.total,
                        "min": v.min if v.count else None,
                        "max": v.max if v.count else None,
                        "mean": v.mean,
                    }
                    for k, v in self._histograms.items()
                ],
                "gauges": [
                    {"name": k[0], "labels": self._label_map.get(k, {}), "value": v}
                    for k, v in self._gauges.items()
                ],
            }
