"""Registry for compatibility adapters."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pylon.skills.adapters.agency_agents import AgencyAgentsAdapter
from pylon.skills.adapters.agent_skills_basic import AgentSkillsBasicAdapter
from pylon.skills.adapters.base import CompatibilityAdapter
from pylon.skills.adapters.marketingskills import MarketingskillsAdapter


class CompatibilityAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CompatibilityAdapter] = {}

    def register(self, adapter: CompatibilityAdapter) -> None:
        self._adapters[adapter.profile_name] = adapter

    def get(self, profile_name: str) -> CompatibilityAdapter:
        profile = str(profile_name).strip()
        if profile in self._adapters:
            return self._adapters[profile]
        return self._adapters["agent-skills-basic"]

    def classify(self, root: Path) -> tuple[str, str]:
        for adapter in sorted(
            self._adapters.values(),
            key=lambda item: item.priority,
            reverse=True,
        ):
            if adapter.matches_repository(root):
                return adapter.source_format, adapter.profile_name
        return "custom", "agent-skills-basic"


@lru_cache(maxsize=1)
def get_default_adapter_registry() -> CompatibilityAdapterRegistry:
    registry = CompatibilityAdapterRegistry()
    registry.register(AgentSkillsBasicAdapter())
    registry.register(AgencyAgentsAdapter())
    registry.register(MarketingskillsAdapter())
    return registry
