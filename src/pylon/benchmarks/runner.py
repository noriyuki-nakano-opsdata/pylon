"""Benchmark runner — measures function performance with percentile statistics."""

from __future__ import annotations

import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    throughput_ops_per_sec: float
    passed: bool

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.name}: p50={self.p50_ms:.2f}ms "
            f"p95={self.p95_ms:.2f}ms p99={self.p99_ms:.2f}ms "
            f"throughput={self.throughput_ops_per_sec:.1f} ops/s"
        )


class BenchmarkRunner:
    """Runs benchmarks and computes percentile statistics."""

    async def run(
        self,
        name: str,
        fn: Callable[[], Awaitable[Any]],
        *,
        iterations: int = 100,
        warmup: int = 10,
    ) -> BenchmarkResult:
        if iterations < 1:
            raise ValueError(f"iterations must be >= 1, got {iterations}")

        # Warmup
        for _ in range(warmup):
            await fn()

        # Measure
        timings_ms: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            await fn()
            elapsed = (time.perf_counter() - start) * 1000.0
            timings_ms.append(elapsed)

        timings_ms.sort()
        total_sec = sum(timings_ms) / 1000.0

        return BenchmarkResult(
            name=name,
            iterations=iterations,
            p50_ms=self._percentile(timings_ms, 50),
            p95_ms=self._percentile(timings_ms, 95),
            p99_ms=self._percentile(timings_ms, 99),
            min_ms=timings_ms[0],
            max_ms=timings_ms[-1],
            mean_ms=statistics.mean(timings_ms),
            throughput_ops_per_sec=iterations / total_sec if total_sec > 0 else 0.0,
            passed=True,
        )

    def compare_baseline(
        self, result: BenchmarkResult, baseline_ms: float, tolerance_pct: float = 10.0
    ) -> bool:
        """Check if p95 is within tolerance of baseline."""
        threshold = baseline_ms * (1.0 + tolerance_pct / 100.0)
        return result.p95_ms <= threshold

    @staticmethod
    def _percentile(sorted_data: list[float], pct: int) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (pct / 100.0)
        f = int(k)
        c = f + 1
        if c >= len(sorted_data):
            return sorted_data[f]
        d = k - f
        return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])
