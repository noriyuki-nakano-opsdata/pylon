"""Tenant lifecycle management."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pylon.tenancy.config import ConfigStore, TenantConfig, TenantLimits, TenantTier
from pylon.tenancy.context import TenantContext
from pylon.tenancy.isolation import IsolationLevel, TenantIsolation
from pylon.tenancy.quota import QuotaManager, TenantQuota


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING_DELETE = "PENDING_DELETE"
    DELETED = "DELETED"


class TenantStatusError(Exception):
    """Raised on invalid tenant status transition."""

    def __init__(self, tenant_id: str, current: TenantStatus, target: TenantStatus) -> None:
        self.tenant_id = tenant_id
        self.current_status = current
        self.target_status = target
        super().__init__(
            f"Tenant '{tenant_id}' cannot transition from {current.value} to {target.value}"
        )


class TenantNotFoundError(LookupError):
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"Tenant not found: {tenant_id}")


class TenantAlreadyExistsError(ValueError):
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        super().__init__(f"Tenant already exists: {tenant_id}")


_VALID_STATUS_TRANSITIONS: dict[TenantStatus, set[TenantStatus]] = {
    TenantStatus.ACTIVE: {TenantStatus.SUSPENDED, TenantStatus.PENDING_DELETE},
    TenantStatus.SUSPENDED: {TenantStatus.ACTIVE, TenantStatus.PENDING_DELETE},
    TenantStatus.PENDING_DELETE: {TenantStatus.DELETED},
    TenantStatus.DELETED: set(),
}


@dataclass
class Tenant:
    tenant_id: str
    name: str
    status: TenantStatus = TenantStatus.ACTIVE
    config: TenantConfig = field(default_factory=TenantConfig)
    quota: TenantQuota = field(default_factory=TenantQuota)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    suspended_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# Hook type: async callable that receives (tenant_id, action, tenant)
LifecycleHook = Callable[..., Any]


class TenantLifecycleManager:
    def __init__(
        self,
        config_store: ConfigStore | None = None,
        quota_manager: QuotaManager | None = None,
        isolation: TenantIsolation | None = None,
    ) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._config_store = config_store or ConfigStore()
        self._quota_manager = quota_manager or QuotaManager()
        self._isolation = isolation or TenantIsolation()
        self._hooks: dict[str, list[LifecycleHook]] = {}

    def register_hook(self, action: str, hook: LifecycleHook) -> None:
        self._hooks.setdefault(action, []).append(hook)

    async def _run_hooks(self, action: str, tenant: Tenant) -> None:
        for hook in self._hooks.get(action, []):
            result = hook(tenant.tenant_id, action, tenant)
            if hasattr(result, "__await__"):
                await result

    async def create_tenant(
        self,
        tenant_id: str,
        name: str,
        tier: TenantTier = TenantTier.FREE,
        quota: TenantQuota | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Tenant:
        if tenant_id in self._tenants:
            raise TenantAlreadyExistsError(tenant_id)

        config = TenantConfig(
            tenant_id=tenant_id,
            tier=tier,
        )
        self._config_store.set_config(tenant_id, config)

        effective_quota = quota or TenantQuota()
        self._quota_manager.set_quota(tenant_id, effective_quota)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            config=config,
            quota=effective_quota,
            metadata=metadata or {},
        )
        self._tenants[tenant_id] = tenant

        await self._run_hooks("create", tenant)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(tenant_id)
        return tenant

    def list_tenants(self, status: TenantStatus | None = None) -> list[Tenant]:
        if status is None:
            return [t for t in self._tenants.values() if t.status != TenantStatus.DELETED]
        return [t for t in self._tenants.values() if t.status == status]

    def _validate_transition(self, tenant: Tenant, target: TenantStatus) -> None:
        valid = _VALID_STATUS_TRANSITIONS.get(tenant.status, set())
        if target not in valid:
            raise TenantStatusError(tenant.tenant_id, tenant.status, target)

    async def suspend_tenant(self, tenant_id: str, reason: str = "") -> Tenant:
        tenant = self.get_tenant(tenant_id)
        self._validate_transition(tenant, TenantStatus.SUSPENDED)
        tenant.status = TenantStatus.SUSPENDED
        tenant.suspended_reason = reason
        tenant.updated_at = time.time()
        await self._run_hooks("suspend", tenant)
        return tenant

    async def resume_tenant(self, tenant_id: str) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        self._validate_transition(tenant, TenantStatus.ACTIVE)
        tenant.status = TenantStatus.ACTIVE
        tenant.suspended_reason = ""
        tenant.updated_at = time.time()
        await self._run_hooks("resume", tenant)
        return tenant

    async def delete_tenant(self, tenant_id: str) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        # Allow transition to PENDING_DELETE first, then DELETED
        if tenant.status not in (TenantStatus.PENDING_DELETE,):
            self._validate_transition(tenant, TenantStatus.PENDING_DELETE)
            tenant.status = TenantStatus.PENDING_DELETE
            tenant.updated_at = time.time()

        await self._run_hooks("pre_delete", tenant)

        # Cleanup
        self._config_store.delete_config(tenant_id)
        self._quota_manager.remove_tenant(tenant_id)

        tenant.status = TenantStatus.DELETED
        tenant.updated_at = time.time()
        await self._run_hooks("delete", tenant)
        return tenant

    def to_context(self, tenant_id: str) -> TenantContext:
        tenant = self.get_tenant(tenant_id)
        return TenantContext(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.name,
            tier=tenant.config.tier,
            limits=tenant.config.limits,
            metadata=tenant.metadata,
        )
