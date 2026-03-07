"""Tests for benchmark runner and result statistics."""

from __future__ import annotations

import pytest

from pylon.benchmarks.runner import BenchmarkResult, BenchmarkRunner


class TestBenchmarkResult:
    def test_summary_pass(self) -> None:
        result = BenchmarkResult(
            name="test_bench",
            iterations=100,
            p50_ms=1.0,
            p95_ms=2.0,
            p99_ms=3.0,
            min_ms=0.5,
            max_ms=4.0,
            mean_ms=1.5,
            throughput_ops_per_sec=666.0,
            passed=True,
        )
        summary = result.summary()
        assert "[PASS]" in summary
        assert "test_bench" in summary

    def test_summary_fail(self) -> None:
        result = BenchmarkResult(
            name="slow",
            iterations=10,
            p50_ms=50.0,
            p95_ms=100.0,
            p99_ms=150.0,
            min_ms=40.0,
            max_ms=200.0,
            mean_ms=75.0,
            throughput_ops_per_sec=13.3,
            passed=False,
        )
        assert "[FAIL]" in result.summary()


class TestBenchmarkRunner:
    @pytest.fixture
    def runner(self) -> BenchmarkRunner:
        return BenchmarkRunner()

    @pytest.mark.asyncio
    async def test_run_basic(self, runner: BenchmarkRunner) -> None:
        call_count = 0

        async def simple_fn() -> None:
            nonlocal call_count
            call_count += 1

        result = await runner.run("basic", simple_fn, iterations=20, warmup=5)
        assert result.name == "basic"
        assert result.iterations == 20
        assert call_count == 25  # 20 iterations + 5 warmup
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_statistics_ordering(self, runner: BenchmarkRunner) -> None:
        async def noop() -> None:
            pass

        result = await runner.run("stats", noop, iterations=50, warmup=2)
        assert result.min_ms <= result.p50_ms
        assert result.p50_ms <= result.p95_ms
        assert result.p95_ms <= result.p99_ms
        assert result.p99_ms <= result.max_ms
        assert result.mean_ms >= result.min_ms
        assert result.throughput_ops_per_sec > 0

    @pytest.mark.asyncio
    async def test_run_captures_timings(self, runner: BenchmarkRunner) -> None:
        async def noop() -> None:
            pass

        result = await runner.run("timing", noop, iterations=10, warmup=1)
        assert result.min_ms >= 0
        assert result.max_ms >= result.min_ms
        assert result.mean_ms > 0

    def test_compare_baseline_pass(self, runner: BenchmarkRunner) -> None:
        result = BenchmarkResult(
            name="fast",
            iterations=100,
            p50_ms=5.0,
            p95_ms=10.0,
            p99_ms=12.0,
            min_ms=3.0,
            max_ms=15.0,
            mean_ms=7.0,
            throughput_ops_per_sec=142.0,
            passed=True,
        )
        assert runner.compare_baseline(result, baseline_ms=10.0, tolerance_pct=10.0) is True

    def test_compare_baseline_fail(self, runner: BenchmarkRunner) -> None:
        result = BenchmarkResult(
            name="slow",
            iterations=100,
            p50_ms=50.0,
            p95_ms=100.0,
            p99_ms=120.0,
            min_ms=30.0,
            max_ms=150.0,
            mean_ms=70.0,
            throughput_ops_per_sec=14.0,
            passed=True,
        )
        assert runner.compare_baseline(result, baseline_ms=10.0, tolerance_pct=10.0) is False

    def test_compare_baseline_custom_tolerance(self, runner: BenchmarkRunner) -> None:
        result = BenchmarkResult(
            name="medium",
            iterations=100,
            p50_ms=8.0,
            p95_ms=15.0,
            p99_ms=18.0,
            min_ms=5.0,
            max_ms=20.0,
            mean_ms=10.0,
            throughput_ops_per_sec=100.0,
            passed=True,
        )
        # 15ms p95 vs 10ms baseline with 50% tolerance = 15ms threshold -> pass
        assert runner.compare_baseline(result, baseline_ms=10.0, tolerance_pct=50.0) is True
        # 15ms p95 vs 10ms baseline with 10% tolerance = 11ms threshold -> fail
        assert runner.compare_baseline(result, baseline_ms=10.0, tolerance_pct=10.0) is False

    def test_percentile_edge_cases(self) -> None:
        assert BenchmarkRunner._percentile([], 50) == 0.0
        assert BenchmarkRunner._percentile([5.0], 50) == 5.0
        assert BenchmarkRunner._percentile([1.0, 2.0], 0) == 1.0
        assert BenchmarkRunner._percentile([1.0, 2.0], 100) == 2.0

    @pytest.mark.asyncio
    async def test_zero_iterations_raises(self, runner: BenchmarkRunner) -> None:
        async def noop() -> None:
            pass

        with pytest.raises(ValueError, match="iterations must be >= 1"):
            await runner.run("zero", noop, iterations=0)
