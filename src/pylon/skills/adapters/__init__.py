"""Compatibility adapters for external skill repositories."""

from pylon.skills.adapters.agency_agents import AgencyAgentsAdapter
from pylon.skills.adapters.agent_skills_basic import AgentSkillsBasicAdapter
from pylon.skills.adapters.base import CompatibilityAdapter
from pylon.skills.adapters.marketingskills import MarketingskillsAdapter
from pylon.skills.adapters.registry import (
    CompatibilityAdapterRegistry,
    get_default_adapter_registry,
)

__all__ = [
    "AgencyAgentsAdapter",
    "AgentSkillsBasicAdapter",
    "CompatibilityAdapter",
    "CompatibilityAdapterRegistry",
    "MarketingskillsAdapter",
    "get_default_adapter_registry",
]
