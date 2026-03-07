"""Resource usage monitoring and alerting."""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class Comparator(enum.Enum):
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"


@dataclass
class DataPoint:
    """A single metric data point."""

    timestamp: float
    value: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """Alert definition with threshold and callback."""

    threshold: float
    comparator: Comparator
    callback: Callable[[str, float, float], None]
    name: str = ""
    triggered: bool = False

    def check(self, resource: str, value: float) -> bool:
        """Check if the alert condition is met."""
        matched = False
        if self.comparator == Comparator.GT:
            matched = value > self.threshold
        elif self.comparator == Comparator.LT:
            matched = value < self.threshold
        elif self.comparator == Comparator.GTE:
            matched = value >= self.threshold
        elif self.comparator == Comparator.LTE:
            matched = value <= self.threshold

        if matched and not self.triggered:
            self.triggered = True
            self.callback(resource, value, self.threshold)
            return True
        if not matched:
            self.triggered = False
        return False


class ResourceMonitor:
    """Tracks resource metrics and triggers alerts."""

    def __init__(self, max_history: int = 1000) -> None:
        self._history: dict[str, list[DataPoint]] = {}
        self._current: dict[str, float] = {}
        self._alerts: dict[str, list[Alert]] = {}
        self._max_history = max_history

    def track(
        self,
        resource: str,
        value: float,
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> None:
        """Record a metric value."""
        now = now or time.monotonic()
        point = DataPoint(timestamp=now, value=value, labels=labels or {})

        if resource not in self._history:
            self._history[resource] = []
        self._history[resource].append(point)
        if len(self._history[resource]) > self._max_history:
            self._history[resource] = self._history[resource][-self._max_history:]

        self._current[resource] = value

    def get_current(self, resource: str) -> float | None:
        return self._current.get(resource)

    def get_history(
        self,
        resource: str,
        window_seconds: float | None = None,
        now: float | None = None,
    ) -> list[DataPoint]:
        """Get historical data points, optionally within a time window."""
        points = self._history.get(resource, [])
        if window_seconds is not None:
            now = now or time.monotonic()
            cutoff = now - window_seconds
            points = [p for p in points if p.timestamp >= cutoff]
        return list(points)

    def add_alert(self, resource: str, alert: Alert) -> None:
        if resource not in self._alerts:
            self._alerts[resource] = []
        self._alerts[resource].append(alert)

    def check_alerts(self) -> list[tuple[str, Alert]]:
        """Check all alerts against current values. Returns triggered alerts."""
        triggered: list[tuple[str, Alert]] = []
        for resource, alerts in self._alerts.items():
            value = self._current.get(resource)
            if value is None:
                continue
            for alert in alerts:
                if alert.check(resource, value):
                    triggered.append((resource, alert))
        return triggered

    def resources(self) -> list[str]:
        return list(self._current.keys())
