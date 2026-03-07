"""Tenant data isolation enforcement with audit logging."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


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


@dataclass
class AuditEntry:
    timestamp: float
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str
    allowed: bool
    owner_tenant_id: str | None = None


class TenantIsolation:
    def __init__(self, level: IsolationLevel = IsolationLevel.SCHEMA) -> None:
        self.level = level
        self._ownership: dict[str, ResourceOwnership] = {}
        self._cross_tenant_allowlist: set[tuple[str, str, str]] = set()
        self._audit_log: list[AuditEntry] = []

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
            return True
        if ownership.owner_tenant_id == tenant_id:
            return True
        if (tenant_id, resource_type.value, resource_id) in self._cross_tenant_allowlist:
            return True
        return False

    def enforce_access(
        self, tenant_id: str, resource_type: ResourceType, resource_id: str
    ) -> None:
        allowed = self.validate_access(tenant_id, resource_type, resource_id)
        key = f"{resource_type.value}:{resource_id}"
        ownership = self._ownership.get(key)
        self._audit_log.append(
            AuditEntry(
                timestamp=time.time(),
                tenant_id=tenant_id,
                resource_type=resource_type.value,
                resource_id=resource_id,
                action="access",
                allowed=allowed,
                owner_tenant_id=ownership.owner_tenant_id if ownership else None,
            )
        )
        if not allowed:
            logger.warning(
                "Cross-tenant access breach: tenant=%s tried to access %s:%s owned by %s",
                tenant_id,
                resource_type.value,
                resource_id,
                ownership.owner_tenant_id if ownership else "unknown",
            )
            raise CrossTenantAccessError(tenant_id, resource_type.value, resource_id)

    def enforce_isolation(self, tenant_id: str, query: dict[str, Any]) -> dict[str, Any]:
        """Inject tenant filter into query (automatic WHERE tenant_id = ?)."""
        filtered = dict(query)
        filtered["tenant_id"] = tenant_id
        if self.level == IsolationLevel.SCHEMA:
            filtered["schema"] = f"tenant_{tenant_id}"
        elif self.level == IsolationLevel.DATABASE:
            filtered["database"] = f"db_{tenant_id}"
        return filtered

    def get_schema_prefix(self, tenant_id: str) -> str:
        """Return schema-level isolation prefix for a tenant."""
        return f"tenant_{tenant_id}"

    def detect_cross_tenant_access(
        self, tenant_id: str, query: dict[str, Any]
    ) -> bool:
        """Detect if a query targets a different tenant's data."""
        query_tenant = query.get("tenant_id")
        if query_tenant and query_tenant != tenant_id:
            return True
        query_schema = query.get("schema", "")
        if query_schema and not query_schema.endswith(f"_{tenant_id}"):
            return True
        return False

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

    def get_audit_log(self, tenant_id: str | None = None) -> list[AuditEntry]:
        if tenant_id is None:
            return list(self._audit_log)
        return [e for e in self._audit_log if e.tenant_id == tenant_id]

    def get_breach_log(self) -> list[AuditEntry]:
        return [e for e in self._audit_log if not e.allowed]
