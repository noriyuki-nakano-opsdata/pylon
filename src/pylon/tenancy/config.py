"""Tenant configuration and tier management."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TenantTier(str, Enum):
    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


@dataclass
class TenantLimits:
    max_agents: int = 5
    max_workflows: int = 10
    max_memory_mb: int = 512
    max_api_calls_per_hour: int = 1000


TIER_DEFAULTS: dict[TenantTier, TenantLimits] = {
    TenantTier.FREE: TenantLimits(
        max_agents=5,
        max_workflows=10,
        max_memory_mb=512,
        max_api_calls_per_hour=1000,
    ),
    TenantTier.PRO: TenantLimits(
        max_agents=50,
        max_workflows=100,
        max_memory_mb=4096,
        max_api_calls_per_hour=10000,
    ),
    TenantTier.ENTERPRISE: TenantLimits(
        max_agents=-1,  # unlimited
        max_workflows=-1,
        max_memory_mb=-1,
        max_api_calls_per_hour=-1,
    ),
}


def get_tier_defaults(tier: TenantTier) -> TenantLimits:
    return TIER_DEFAULTS[tier]


@dataclass
class TenantConfig:
    tenant_id: str = ""
    tier: TenantTier = TenantTier.FREE
    limits: TenantLimits = field(default_factory=TenantLimits)
    metadata: dict[str, Any] = field(default_factory=dict)


class ConfigStore:
    def __init__(self) -> None:
        self._configs: dict[str, TenantConfig] = {}

    def get_config(self, tenant_id: str) -> TenantConfig | None:
        return self._configs.get(tenant_id)

    def set_config(self, tenant_id: str, config: TenantConfig) -> None:
        config.tenant_id = tenant_id
        self._configs[tenant_id] = config

    def delete_config(self, tenant_id: str) -> bool:
        if tenant_id in self._configs:
            del self._configs[tenant_id]
            return True
        return False

    def list_configs(self) -> list[TenantConfig]:
        return list(self._configs.values())
