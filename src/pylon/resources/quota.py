"""Resource quota management."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pylon.errors import PylonError


class QuotaError(PylonError):
    """Error raised by quota management."""

    code = "QUOTA_ERROR"
    status_code = 429


class ResourceType(enum.Enum):
    API_CALLS = "api_calls"
    TOKENS = "tokens"
    AGENTS = "agents"
    WORKFLOWS = "workflows"
    STORAGE = "storage"


class QuotaPeriod(enum.Enum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


@dataclass(frozen=True)
class QuotaDefinition:
    """Defines a resource quota."""

    resource_type: ResourceType
    limit: float
    period: QuotaPeriod = QuotaPeriod.DAY


@dataclass
class UsageInfo:
    """Current usage information for a resource."""

    used: float
    limit: float
    reset_at: datetime | None = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


class QuotaManager:
    """Manages resource quotas per tenant."""

    def __init__(self) -> None:
        self._quotas: dict[str, dict[ResourceType, QuotaDefinition]] = {}
        self._usage: dict[str, dict[ResourceType, float]] = {}

    def set_quota(self, tenant_id: str, definition: QuotaDefinition) -> None:
        if tenant_id not in self._quotas:
            self._quotas[tenant_id] = {}
            self._usage[tenant_id] = {}
        self._quotas[tenant_id][definition.resource_type] = definition

    def allocate(self, tenant_id: str, resource: ResourceType, amount: float) -> bool:
        """Try to allocate resource. Returns True if within quota."""
        quota = self._get_quota(tenant_id, resource)
        if quota is None:
            return False
        current = self._usage.get(tenant_id, {}).get(resource, 0.0)
        if current + amount > quota.limit:
            return False
        if tenant_id not in self._usage:
            self._usage[tenant_id] = {}
        self._usage[tenant_id][resource] = current + amount
        return True

    def release(self, tenant_id: str, resource: ResourceType, amount: float) -> None:
        """Release previously allocated resource."""
        if tenant_id not in self._usage:
            return
        current = self._usage[tenant_id].get(resource, 0.0)
        self._usage[tenant_id][resource] = max(0.0, current - amount)

    def get_usage(self, tenant_id: str) -> dict[ResourceType, UsageInfo]:
        quotas = self._quotas.get(tenant_id, {})
        usage = self._usage.get(tenant_id, {})
        result: dict[ResourceType, UsageInfo] = {}
        for rtype, qdef in quotas.items():
            result[rtype] = UsageInfo(
                used=usage.get(rtype, 0.0),
                limit=qdef.limit,
            )
        return result

    def reset(self, tenant_id: str, resource: ResourceType | None = None) -> None:
        """Reset usage for a tenant, optionally for a specific resource."""
        if tenant_id not in self._usage:
            return
        if resource is not None:
            self._usage[tenant_id][resource] = 0.0
        else:
            self._usage[tenant_id] = {}

    def _get_quota(self, tenant_id: str, resource: ResourceType) -> QuotaDefinition | None:
        return self._quotas.get(tenant_id, {}).get(resource)
