"""Tests for LLM cost tracking."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from pylon.observability.cost import (
    CostReport,
    CostTracker,
    LLMPriceTable,
    ModelPricing,
)


class TestModelPricing:
    def test_calculate_cost(self):
        pricing = ModelPricing(input_price_per_1k=0.01, output_price_per_1k=0.03)
        cost = pricing.calculate(input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.01 + 0.015)

    def test_calculate_zero_tokens(self):
        pricing = ModelPricing(input_price_per_1k=0.01, output_price_per_1k=0.03)
        assert pricing.calculate(0, 0) == 0.0

    def test_estimate(self):
        pricing = ModelPricing(input_price_per_1k=0.01, output_price_per_1k=0.03)
        est = pricing.estimate(max_tokens=2000)
        assert est == pytest.approx(0.06)


class TestLLMPriceTable:
    def test_default_models_exist(self):
        table = LLMPriceTable()
        models = table.list_models()
        assert "openai/gpt-4o" in models
        assert "anthropic/claude-sonnet-4-6" in models

    def test_get_known_model(self):
        table = LLMPriceTable()
        pricing = table.get_price("openai/gpt-4o")
        assert pricing is not None
        assert pricing.input_price_per_1k > 0

    def test_get_unknown_model_returns_none(self):
        table = LLMPriceTable()
        assert table.get_price("unknown/model") is None

    def test_set_custom_price(self):
        table = LLMPriceTable()
        custom = ModelPricing(0.1, 0.2)
        table.set_price("custom/model", custom)
        assert table.get_price("custom/model") is custom


class TestCostTracker:
    @pytest.fixture
    def tracker(self):
        return CostTracker()

    def test_pre_estimate_known_model(self, tracker):
        est = tracker.pre_estimate("openai/gpt-4o", max_tokens=1000)
        assert est > 0

    def test_pre_estimate_unknown_model(self, tracker):
        assert tracker.pre_estimate("unknown/model", 1000) == 0.0

    def test_record_actual_returns_cost(self, tracker):
        cost = tracker.record_actual("tenant-1", "openai/gpt-4o", 1000, 500)
        assert cost > 0

    def test_record_actual_unknown_model(self, tracker):
        cost = tracker.record_actual("tenant-1", "unknown/model", 1000, 500)
        assert cost == 0.0

    def test_daily_summary_empty(self, tracker):
        report = tracker.get_daily_summary("tenant-1")
        assert isinstance(report, CostReport)
        assert report.total_cost_usd == 0.0
        assert report.by_model == {}
        assert report.by_provider == {}

    def test_daily_summary_with_records(self, tracker):
        tracker.record_actual("tenant-1", "openai/gpt-4o", 1000, 500)
        tracker.record_actual("tenant-1", "anthropic/claude-sonnet-4-6", 2000, 1000)

        report = tracker.get_daily_summary("tenant-1")
        assert report.total_cost_usd > 0
        assert "openai/gpt-4o" in report.by_model
        assert "anthropic/claude-sonnet-4-6" in report.by_model
        assert "openai" in report.by_provider
        assert "anthropic" in report.by_provider

    def test_budget_alert_at_80_percent(self, tracker):
        tracker.set_budget("tenant-1", 1.0)
        # Record enough to exceed 80%
        table = LLMPriceTable()
        pricing = table.get_price("openai/gpt-4o")
        # Need cost >= 0.80
        tokens_needed = int(0.85 / (pricing.output_price_per_1k / 1000))
        tracker.record_actual("tenant-1", "openai/gpt-4o", 0, tokens_needed)

        alerts = tracker.check_budget("tenant-1")
        assert len(alerts) == 1
        assert "WARNING" in alerts[0] or "CRITICAL" in alerts[0]

    def test_budget_alert_at_100_percent(self, tracker):
        tracker.set_budget("tenant-1", 0.01)
        tracker.record_actual("tenant-1", "openai/gpt-4o", 10000, 10000)

        alerts = tracker.check_budget("tenant-1")
        assert any("CRITICAL" in a for a in alerts)

    def test_no_alert_under_budget(self, tracker):
        tracker.set_budget("tenant-1", 1000.0)
        tracker.record_actual("tenant-1", "openai/gpt-4o", 100, 50)
        alerts = tracker.check_budget("tenant-1")
        assert alerts == []

    def test_no_alert_without_budget(self, tracker):
        tracker.record_actual("tenant-1", "openai/gpt-4o", 1000, 500)
        alerts = tracker.check_budget("tenant-1")
        assert alerts == []

    def test_utilization_percentage(self, tracker):
        tracker.set_budget("tenant-1", 1.0)
        table = LLMPriceTable()
        pricing = table.get_price("openai/gpt-4o")
        # Record $0.50 worth
        tokens = int(0.50 / (pricing.output_price_per_1k / 1000))
        tracker.record_actual("tenant-1", "openai/gpt-4o", 0, tokens)

        report = tracker.get_daily_summary("tenant-1")
        assert report.utilization_pct == pytest.approx(50.0, rel=0.1)

    def test_specific_date_summary(self, tracker):
        with patch("pylon.observability.cost.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            tracker.record_actual("t1", "openai/gpt-4o", 1000, 500)

        report = tracker.get_daily_summary("t1", day="2026-01-15")
        assert report.total_cost_usd > 0
        assert report.date == "2026-01-15"

    def test_multiple_tenants_isolated(self, tracker):
        tracker.record_actual("tenant-a", "openai/gpt-4o", 1000, 500)
        tracker.record_actual("tenant-b", "openai/gpt-4o", 2000, 1000)

        report_a = tracker.get_daily_summary("tenant-a")
        report_b = tracker.get_daily_summary("tenant-b")
        assert report_a.total_cost_usd < report_b.total_cost_usd

    def test_custom_price_table(self):
        table = LLMPriceTable()
        table.set_price("custom/model", ModelPricing(0.1, 0.2))
        tracker = CostTracker(price_table=table)

        cost = tracker.record_actual("t1", "custom/model", 1000, 1000)
        assert cost == pytest.approx(0.1 + 0.2)

    def test_provider_extraction(self, tracker):
        tracker.record_actual("t1", "openai/gpt-4o", 1000, 500)
        report = tracker.get_daily_summary("t1")
        assert "openai" in report.by_provider

    def test_provider_extraction_no_slash(self, tracker):
        table = LLMPriceTable()
        table.set_price("localmodel", ModelPricing(0.001, 0.002))
        tracker_custom = CostTracker(price_table=table)
        tracker_custom.record_actual("t1", "localmodel", 1000, 1000)
        report = tracker_custom.get_daily_summary("t1")
        assert "localmodel" in report.by_provider
