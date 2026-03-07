"""Infrastructure sizing guide and resource calculator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InfraProfile(str, Enum):
    """Infrastructure sizing profile (matches Helm values)."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass(frozen=True)
class SizingSpec:
    """Resource specification for an infrastructure profile."""

    profile: InfraProfile
    description: str
    api_replicas: int
    worker_replicas: int
    api_cpu_request: str
    api_cpu_limit: str
    api_memory_request: str
    api_memory_limit: str
    worker_cpu_request: str
    worker_cpu_limit: str
    worker_memory_request: str
    worker_memory_limit: str
    postgres_storage_gi: int
    redis_storage_gi: int
    nats_memory_mb: int
    nats_file_storage_gi: int
    max_concurrent_agents: int
    max_tenants: int
    estimated_monthly_cost_usd: float


SIZING_PROFILES: dict[InfraProfile, SizingSpec] = {
    InfraProfile.SMALL: SizingSpec(
        profile=InfraProfile.SMALL,
        description="Development / small team (up to 5 agents, 3 tenants)",
        api_replicas=1,
        worker_replicas=1,
        api_cpu_request="250m",
        api_cpu_limit="500m",
        api_memory_request="256Mi",
        api_memory_limit="512Mi",
        worker_cpu_request="250m",
        worker_cpu_limit="1000m",
        worker_memory_request="512Mi",
        worker_memory_limit="1Gi",
        postgres_storage_gi=10,
        redis_storage_gi=1,
        nats_memory_mb=256,
        nats_file_storage_gi=5,
        max_concurrent_agents=5,
        max_tenants=3,
        estimated_monthly_cost_usd=150.0,
    ),
    InfraProfile.MEDIUM: SizingSpec(
        profile=InfraProfile.MEDIUM,
        description="Production / mid-size team (up to 25 agents, 10 tenants)",
        api_replicas=2,
        worker_replicas=3,
        api_cpu_request="500m",
        api_cpu_limit="1000m",
        api_memory_request="512Mi",
        api_memory_limit="1Gi",
        worker_cpu_request="500m",
        worker_cpu_limit="2000m",
        worker_memory_request="1Gi",
        worker_memory_limit="2Gi",
        postgres_storage_gi=50,
        redis_storage_gi=5,
        nats_memory_mb=512,
        nats_file_storage_gi=20,
        max_concurrent_agents=25,
        max_tenants=10,
        estimated_monthly_cost_usd=500.0,
    ),
    InfraProfile.LARGE: SizingSpec(
        profile=InfraProfile.LARGE,
        description="Enterprise / large team (up to 100 agents, 50 tenants)",
        api_replicas=3,
        worker_replicas=6,
        api_cpu_request="1000m",
        api_cpu_limit="2000m",
        api_memory_request="1Gi",
        api_memory_limit="2Gi",
        worker_cpu_request="1000m",
        worker_cpu_limit="4000m",
        worker_memory_request="2Gi",
        worker_memory_limit="4Gi",
        postgres_storage_gi=200,
        redis_storage_gi=10,
        nats_memory_mb=1024,
        nats_file_storage_gi=50,
        max_concurrent_agents=100,
        max_tenants=50,
        estimated_monthly_cost_usd=1500.0,
    ),
}


class SizingCalculator:
    """Recommends infrastructure profile based on workload."""

    def recommend(
        self, agents: int, tenants: int, daily_requests: int
    ) -> InfraProfile:
        for profile in (InfraProfile.SMALL, InfraProfile.MEDIUM, InfraProfile.LARGE):
            spec = SIZING_PROFILES[profile]
            if agents <= spec.max_concurrent_agents and tenants <= spec.max_tenants:
                return profile
        return InfraProfile.LARGE

    def get_spec(self, profile: InfraProfile) -> SizingSpec:
        return SIZING_PROFILES[profile]

    def estimate_resources(self, agents: int, tenants: int) -> dict:
        profile = self.recommend(agents, tenants, 0)
        spec = SIZING_PROFILES[profile]
        return {
            "recommended_profile": profile.value,
            "api_replicas": spec.api_replicas,
            "worker_replicas": spec.worker_replicas,
            "postgres_storage_gi": spec.postgres_storage_gi,
            "redis_storage_gi": spec.redis_storage_gi,
            "nats_memory_mb": spec.nats_memory_mb,
            "max_concurrent_agents": spec.max_concurrent_agents,
            "max_tenants": spec.max_tenants,
            "estimated_monthly_cost_usd": spec.estimated_monthly_cost_usd,
        }
