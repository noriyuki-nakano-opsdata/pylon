"""Tenant lifecycle management (FR-11)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from pylon.control_plane.tenant.quota import ResourceQuota
from pylon.errors import PylonError


class TenantError(PylonError):
    """Error raised by tenant management."""

    code = "TENANT_ERROR"
    status_code = 400


class TenantStatus(enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


@dataclass
class TenantConfig:
    """Tenant configuration."""

    id: str
    name: str
    schema_name: str = ""
    resource_quota: ResourceQuota = field(default_factory=ResourceQuota)
    status: TenantStatus = TenantStatus.ACTIVE


class TenantManager:
    """In-memory tenant lifecycle manager."""

    def __init__(self) -> None:
        self._tenants: dict[str, TenantConfig] = {}

    def create_tenant(self, config: TenantConfig) -> TenantConfig:
        if config.id in self._tenants:
            raise TenantError(
                f"Tenant '{config.id}' already exists",
                details={"tenant_id": config.id},
            )
        if not config.schema_name:
            config.schema_name = f"tenant_{config.id}"
        self._tenants[config.id] = config
        return config

    def get_tenant(self, tenant_id: str) -> TenantConfig | None:
        tenant = self._tenants.get(tenant_id)
        if tenant is not None and tenant.status == TenantStatus.DELETED:
            return None
        return tenant

    def update_tenant(self, tenant_id: str, **updates: object) -> TenantConfig:
        tenant = self._tenants.get(tenant_id)
        if tenant is None or tenant.status == TenantStatus.DELETED:
            raise TenantError(
                f"Tenant '{tenant_id}' not found",
                details={"tenant_id": tenant_id},
            )
        for key, value in updates.items():
            if not hasattr(tenant, key):
                raise TenantError(
                    f"Invalid field '{key}'",
                    details={"tenant_id": tenant_id, "field": key},
                )
            setattr(tenant, key, value)
        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """Soft delete a tenant."""
        tenant = self._tenants.get(tenant_id)
        if tenant is None or tenant.status == TenantStatus.DELETED:
            return False
        tenant.status = TenantStatus.DELETED
        return True

    def list_tenants(self) -> list[TenantConfig]:
        return [t for t in self._tenants.values() if t.status != TenantStatus.DELETED]

    def suspend_tenant(self, tenant_id: str) -> TenantConfig:
        tenant = self._tenants.get(tenant_id)
        if tenant is None or tenant.status == TenantStatus.DELETED:
            raise TenantError(
                f"Tenant '{tenant_id}' not found",
                details={"tenant_id": tenant_id},
            )
        if tenant.status == TenantStatus.SUSPENDED:
            raise TenantError(
                f"Tenant '{tenant_id}' is already suspended",
                details={"tenant_id": tenant_id},
            )
        tenant.status = TenantStatus.SUSPENDED
        return tenant

    def activate_tenant(self, tenant_id: str) -> TenantConfig:
        tenant = self._tenants.get(tenant_id)
        if tenant is None or tenant.status == TenantStatus.DELETED:
            raise TenantError(
                f"Tenant '{tenant_id}' not found",
                details={"tenant_id": tenant_id},
            )
        if tenant.status == TenantStatus.ACTIVE:
            raise TenantError(
                f"Tenant '{tenant_id}' is already active",
                details={"tenant_id": tenant_id},
            )
        tenant.status = TenantStatus.ACTIVE
        return tenant
