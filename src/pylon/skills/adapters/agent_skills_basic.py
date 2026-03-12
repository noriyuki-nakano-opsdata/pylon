"""Generic adapter for Agent Skills spec repositories."""

from __future__ import annotations

from pathlib import Path

from pylon.skills.adapters.base import CompatibilityAdapter


class AgentSkillsBasicAdapter(CompatibilityAdapter):
    profile_name = "agent-skills-basic"
    source_format = "agent-skills-spec"
    priority = 10

    def matches_repository(self, root: Path) -> bool:
        return (root / "skills").is_dir() and any((root / "skills").glob("*/SKILL.md"))
