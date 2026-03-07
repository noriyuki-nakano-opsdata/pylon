"""Resource quota enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field

from pylon.errors import PylonError


class QuotaExceededError(PylonError):
    """Raised when a resource quota is exceeded."""

    code = "QUOTA_EXCEEDED"
    status_code = 429


@dataclass
class ResourceQuota:
    """Resource limits for a tenant."""

    max_cpu_cores: float = 4.0
    max_memory_gb: float = 16.0
    max_sandbox_count: int = 10
    max_llm_budget_usd_daily: float = 50.0
    max_concurrent_workflows: int = 5


class QuotaEnforcer:
    """Tracks and enforces resource quotas per tenant."""

    def __init__(self) -> None:
        self._quotas: dict[str, ResourceQuota] = {}
        self._usage: dict[str, dict[str, float]] = {}

    def set_quota(self, tenant_id: str, quota: ResourceQuota) -> None:
        self._quotas[tenant_id] = quota
        if tenant_id not in self._usage:
            self._usage[tenant_id] = {}

    def check_quota(self, tenant_id: str, resource: str, requested: float) -> bool:
        """Check if the requested resource amount is within quota."""
        quota = self._quotas.get(tenant_id)
        if quota is None:
            return False

        limit = self._get_limit(quota, resource)
        if limit is None:
            return False

        current = self._usage.get(tenant_id, {}).get(resource, 0.0)
        return (current + requested) <= limit

    def get_usage(self, tenant_id: str) -> dict[str, float]:
        return dict(self._usage.get(tenant_id, {}))

    def record_usage(self, tenant_id: str, resource: str, amount: float) -> None:
        if tenant_id not in self._usage:
            self._usage[tenant_id] = {}
        current = self._usage[tenant_id].get(resource, 0.0)
        self._usage[tenant_id][resource] = current + amount

    def reset_daily_usage(self, tenant_id: str) -> None:
        if tenant_id in self._usage:
            self._usage[tenant_id] = {}

    @staticmethod
    def _get_limit(quota: ResourceQuota, resource: str) -> float | None:
        mapping: dict[str, float] = {
            "cpu_cores": quota.max_cpu_cores,
            "memory_gb": quota.max_memory_gb,
            "sandbox_count": float(quota.max_sandbox_count),
            "llm_budget_usd_daily": quota.max_llm_budget_usd_daily,
            "concurrent_workflows": float(quota.max_concurrent_workflows),
        }
        return mapping.get(resource)
