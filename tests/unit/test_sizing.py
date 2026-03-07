"""Tests for infrastructure sizing module."""

from __future__ import annotations

import pytest

from pylon.infrastructure.sizing import (
    SIZING_PROFILES,
    InfraProfile,
    SizingCalculator,
)


class TestSizingProfiles:
    def test_all_profiles_defined(self) -> None:
        for profile in InfraProfile:
            assert profile in SIZING_PROFILES

    def test_profiles_ordered_by_capacity(self) -> None:
        small = SIZING_PROFILES[InfraProfile.SMALL]
        medium = SIZING_PROFILES[InfraProfile.MEDIUM]
        large = SIZING_PROFILES[InfraProfile.LARGE]

        assert small.max_concurrent_agents < medium.max_concurrent_agents
        assert medium.max_concurrent_agents < large.max_concurrent_agents
        assert small.max_tenants < medium.max_tenants
        assert medium.max_tenants < large.max_tenants


class TestSizingCalculator:
    @pytest.fixture()
    def calc(self) -> SizingCalculator:
        return SizingCalculator()

    def test_recommend_small(self, calc: SizingCalculator) -> None:
        assert calc.recommend(3, 2, 100) == InfraProfile.SMALL

    def test_recommend_medium(self, calc: SizingCalculator) -> None:
        assert calc.recommend(10, 5, 1000) == InfraProfile.MEDIUM

    def test_recommend_large(self, calc: SizingCalculator) -> None:
        assert calc.recommend(50, 20, 10000) == InfraProfile.LARGE

    def test_recommend_exceeds_all(self, calc: SizingCalculator) -> None:
        assert calc.recommend(500, 200, 100000) == InfraProfile.LARGE

    def test_get_spec(self, calc: SizingCalculator) -> None:
        spec = calc.get_spec(InfraProfile.MEDIUM)
        assert spec.profile == InfraProfile.MEDIUM
        assert spec.api_replicas == 2
        assert spec.worker_replicas == 3

    def test_estimate_resources(self, calc: SizingCalculator) -> None:
        result = calc.estimate_resources(agents=3, tenants=2)
        assert result["recommended_profile"] == "small"
        assert "api_replicas" in result
        assert "estimated_monthly_cost_usd" in result

    def test_estimate_resources_large(self, calc: SizingCalculator) -> None:
        result = calc.estimate_resources(agents=80, tenants=40)
        assert result["recommended_profile"] == "large"
