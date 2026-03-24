"""Metric parsing and comparison helpers for experiment campaigns."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    """Describes how experiment output should be interpreted as a metric."""

    name: str
    direction: str = "minimize"
    unit: str = ""
    parser: str = "metric-line"
    regex: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, object] | None) -> "MetricSpec":
        source = payload or {}
        name = str(source.get("name", "")).strip() or "value"
        direction = str(source.get("direction", "minimize")).strip().lower() or "minimize"
        unit = str(source.get("unit", "")).strip()
        parser = str(source.get("parser", source.get("source", "metric-line"))).strip().lower()
        regex = str(source.get("regex", "")).strip()
        if direction not in {"minimize", "maximize"}:
            msg = f"Unsupported metric direction: {direction}"
            raise ValueError(msg)
        if parser not in {"metric-line", "regex"}:
            msg = f"Unsupported metric parser: {parser}"
            raise ValueError(msg)
        if parser == "regex" and not regex:
            raise ValueError("Metric parser 'regex' requires a regex pattern")
        return cls(
            name=name,
            direction=direction,
            unit=unit,
            parser=parser,
            regex=regex,
        )


def extract_metric_value(
    stdout: str,
    *,
    spec: MetricSpec,
) -> tuple[float, str]:
    """Extract a floating-point metric value from command stdout."""

    if spec.parser == "regex":
        match = re.search(spec.regex, stdout, flags=re.MULTILINE)
        if match is None:
            raise ValueError(f"Metric regex did not match output for {spec.name}")
        raw = match.group(1) if match.groups() else match.group(0)
        return _parse_float(raw, metric_name=spec.name), raw

    observed: dict[str, float] = {}
    evidence: dict[str, str] = {}
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("METRIC "):
            continue
        payload = stripped[len("METRIC "):]
        for part in payload.split():
            name, sep, raw_value = part.partition("=")
            if not sep:
                continue
            metric_name = name.strip()
            if not metric_name:
                continue
            observed[metric_name] = _parse_float(raw_value.strip(), metric_name=metric_name)
            evidence[metric_name] = raw_value.strip()

    if spec.name in observed:
        return observed[spec.name], evidence[spec.name]
    if len(observed) == 1:
        metric_name = next(iter(observed))
        return observed[metric_name], evidence[metric_name]
    if not observed:
        raise ValueError(f"No METRIC lines were found for {spec.name}")
    raise ValueError(
        f"Metric {spec.name} was not present in METRIC output; observed {sorted(observed)}"
    )


def metric_is_better(spec: MetricSpec, candidate: float, incumbent: float | None) -> bool:
    """Return True when the candidate metric improves on the incumbent."""

    if incumbent is None:
        return True
    if spec.direction == "minimize":
        return candidate < incumbent
    return candidate > incumbent


def metric_delta(spec: MetricSpec, candidate: float, reference: float | None) -> float | None:
    """Return the signed improvement delta relative to the reference."""

    if reference is None:
        return None
    if spec.direction == "minimize":
        return reference - candidate
    return candidate - reference


def metric_improvement_ratio(
    spec: MetricSpec,
    candidate: float,
    reference: float | None,
) -> float | None:
    """Return normalized improvement ratio relative to the reference."""

    delta = metric_delta(spec, candidate, reference)
    if delta is None:
        return None
    denominator = abs(reference or 0.0)
    if math.isclose(denominator, 0.0):
        return None
    return delta / denominator


def _parse_float(raw: str, *, metric_name: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        msg = f"Metric {metric_name} value is not numeric: {raw}"
        raise ValueError(msg) from exc
