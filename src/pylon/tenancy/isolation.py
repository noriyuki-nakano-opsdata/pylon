"""Tenant data isolation enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IsolationLevel(str, Enum):
    SHARED = "SHARED"
    SCHEMA = "SCHEMA"
    DATABASE = "DATABASE"


class ResourceType(str, Enum):
    AGENT = "AGENT"
    WORKFLOW = "WORKFLOW"
    MEMORY = "MEMORY"
    AUDIT = "AUDIT"
    CHECKPOINT = "CHECKPOINT"


class CrossTenantAccessError(PermissionError):
    """Raised when a tenant attempts to access another tenant's resources."""

    def __init__(self, tenant_id: str, resource_type: str, resource_id: str) -> None:
        self.tenant_id = tenant_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(
            f"Tenant '{tenant_id}' denied access to {resource_type}:{resource_id}"
        )


@dataclass
class ResourceOwnership:
    resource_type: ResourceType
    resource_id: str
    owner_tenant_id: str


class TenantIsolation:
    def __init__(self, level: IsolationLevel = IsolationLevel.SCHEMA) -> None:
        self.level = level
        self._ownership: dict[str, ResourceOwnership] = {}  # key: "type:id"
        self._cross_tenant_allowlist: set[tuple[str, str, str]] = set()  # (tenant_id, resource_type, resource_id)

    def register_resource(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> None:
        key = f"{resource_type.value}:{resource_id}"
        self._ownership[key] = ResourceOwnership(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_tenant_id=tenant_id,
        )

    def validate_access(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> bool:
        key = f"{resource_type.value}:{resource_id}"
        ownership = self._ownership.get(key)
        if ownership is None:
            return True  # unregistered resources are accessible
        if ownership.owner_tenant_id == tenant_id:
            return True
        # Check allowlist
        if (tenant_id, resource_type.value, resource_id) in self._cross_tenant_allowlist:
            return True
        return False

    def enforce_access(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> None:
        if not self.validate_access(tenant_id, resource_type, resource_id):
            raise CrossTenantAccessError(tenant_id, resource_type.value, resource_id)

    def enforce_isolation(self, tenant_id: str, query: dict[str, Any]) -> dict[str, Any]:
        filtered = dict(query)
        filtered["tenant_id"] = tenant_id
        if self.level == IsolationLevel.SCHEMA:
            filtered["schema"] = f"tenant_{tenant_id}"
        elif self.level == IsolationLevel.DATABASE:
            filtered["database"] = f"db_{tenant_id}"
        return filtered

    def allow_cross_tenant(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> None:
        self._cross_tenant_allowlist.add(
            (tenant_id, resource_type.value, resource_id)
        )

    def revoke_cross_tenant(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> None:
        self._cross_tenant_allowlist.discard(
            (tenant_id, resource_type.value, resource_id)
        )
