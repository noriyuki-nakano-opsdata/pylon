"""Resource quota management for tenants."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pylon.errors import PylonError


class QuotaResource(str, Enum):
    AGENTS = "agents"
    WORKFLOWS = "workflows"
    STORAGE_MB = "storage_mb"
    API_RPS = "api_rps"
    COST_USD = "cost_usd"


class QuotaExceededError(PylonError):
    """Raised when a tenant exceeds their resource quota."""
    code = "QUOTA_EXCEEDED"
    status_code = 429

    def __init__(self, tenant_id: str, resource: QuotaResource, current: float, limit: float) -> None:
        self.tenant_id = tenant_id
        self.resource = resource
        self.current = current
        self.limit = limit
        super().__init__(
            f"Tenant '{tenant_id}' exceeded {resource.value} quota: {current}/{limit}"
        )


@dataclass
class TenantQuota:
    max_agents: int = 5
    max_workflows: int = 10
    max_storage_mb: int = 512
    max_api_rps: float = 10.0
    max_cost_usd: float = 100.0


@dataclass
class TenantUsage:
    agents: int = 0
    workflows: int = 0
    storage_mb: float = 0.0
    api_requests: list[float] = field(default_factory=list)
    cost_usd: float = 0.0


@dataclass
class QuotaReport:
    tenant_id: str
    quota: TenantQuota
    usage: TenantUsage
    utilization: dict[str, float] = field(default_factory=dict)
    exceeded: list[str] = field(default_factory=list)


class QuotaManager:
    def __init__(self) -> None:
        self._quotas: dict[str, TenantQuota] = {}
        self._usage: dict[str, TenantUsage] = {}

    def set_quota(self, tenant_id: str, quota: TenantQuota) -> None:
        self._quotas[tenant_id] = quota

    def get_quota(self, tenant_id: str) -> TenantQuota | None:
        return self._quotas.get(tenant_id)

    def get_usage(self, tenant_id: str) -> TenantUsage:
        if tenant_id not in self._usage:
            self._usage[tenant_id] = TenantUsage()
        return self._usage[tenant_id]

    def record_usage(self, tenant_id: str, resource: QuotaResource, amount: float = 1.0) -> None:
        usage = self.get_usage(tenant_id)
        if resource == QuotaResource.AGENTS:
            usage.agents += int(amount)
        elif resource == QuotaResource.WORKFLOWS:
            usage.workflows += int(amount)
        elif resource == QuotaResource.STORAGE_MB:
            usage.storage_mb += amount
        elif resource == QuotaResource.API_RPS:
            usage.api_requests.append(time.time())
        elif resource == QuotaResource.COST_USD:
            usage.cost_usd += amount

    def release_usage(self, tenant_id: str, resource: QuotaResource, amount: float = 1.0) -> None:
        usage = self.get_usage(tenant_id)
        if resource == QuotaResource.AGENTS:
            usage.agents = max(0, usage.agents - int(amount))
        elif resource == QuotaResource.WORKFLOWS:
            usage.workflows = max(0, usage.workflows - int(amount))
        elif resource == QuotaResource.STORAGE_MB:
            usage.storage_mb = max(0.0, usage.storage_mb - amount)

    def _current_rps(self, tenant_id: str) -> float:
        usage = self.get_usage(tenant_id)
        now = time.time()
        # Count requests in the last 1 second
        usage.api_requests = [t for t in usage.api_requests if now - t < 1.0]
        return float(len(usage.api_requests))

    def check_quota(self, tenant_id: str, resource: QuotaResource) -> bool:
        quota = self._quotas.get(tenant_id)
        if quota is None:
            return True
        usage = self.get_usage(tenant_id)

        if resource == QuotaResource.AGENTS:
            return quota.max_agents < 0 or usage.agents < quota.max_agents
        elif resource == QuotaResource.WORKFLOWS:
            return quota.max_workflows < 0 or usage.workflows < quota.max_workflows
        elif resource == QuotaResource.STORAGE_MB:
            return quota.max_storage_mb < 0 or usage.storage_mb < quota.max_storage_mb
        elif resource == QuotaResource.API_RPS:
            return quota.max_api_rps < 0 or self._current_rps(tenant_id) < quota.max_api_rps
        elif resource == QuotaResource.COST_USD:
            return quota.max_cost_usd < 0 or usage.cost_usd < quota.max_cost_usd
        return True

    def enforce_quota(self, tenant_id: str, resource: QuotaResource) -> None:
        if not self.check_quota(tenant_id, resource):
            quota = self._quotas[tenant_id]
            usage = self.get_usage(tenant_id)
            limit_map = {
                QuotaResource.AGENTS: (usage.agents, quota.max_agents),
                QuotaResource.WORKFLOWS: (usage.workflows, quota.max_workflows),
                QuotaResource.STORAGE_MB: (usage.storage_mb, quota.max_storage_mb),
                QuotaResource.API_RPS: (self._current_rps(tenant_id), quota.max_api_rps),
                QuotaResource.COST_USD: (usage.cost_usd, quota.max_cost_usd),
            }
            current, limit = limit_map[resource]
            raise QuotaExceededError(tenant_id, resource, float(current), float(limit))

    def generate_report(self, tenant_id: str) -> QuotaReport:
        quota = self._quotas.get(tenant_id, TenantQuota())
        usage = self.get_usage(tenant_id)

        utilization: dict[str, float] = {}
        exceeded: list[str] = []

        checks = [
            ("agents", usage.agents, quota.max_agents),
            ("workflows", usage.workflows, quota.max_workflows),
            ("storage_mb", usage.storage_mb, quota.max_storage_mb),
            ("cost_usd", usage.cost_usd, quota.max_cost_usd),
        ]
        for name, current, limit in checks:
            if limit < 0:
                utilization[name] = 0.0
            elif limit == 0:
                utilization[name] = 100.0
                exceeded.append(name)
            else:
                pct = (current / limit) * 100
                utilization[name] = pct
                if pct >= 100:
                    exceeded.append(name)

        return QuotaReport(
            tenant_id=tenant_id,
            quota=quota,
            usage=usage,
            utilization=utilization,
            exceeded=exceeded,
        )

    def remove_tenant(self, tenant_id: str) -> None:
        self._quotas.pop(tenant_id, None)
        self._usage.pop(tenant_id, None)
