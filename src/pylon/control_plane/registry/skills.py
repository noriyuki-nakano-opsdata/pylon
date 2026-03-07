"""Skill composition and dependency resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from pylon.control_plane.registry.tools import ToolDefinition, ToolRegistry
from pylon.errors import PylonError


class SkillRegistryError(PylonError):
    """Error raised by the skill registry."""

    code = "SKILL_REGISTRY_ERROR"
    status_code = 400


@dataclass(frozen=True)
class SkillDefinition:
    """A skill composed of multiple tools."""

    name: str
    version: str
    tools: list[str] = field(default_factory=list)
    description: str = ""


class SkillRegistry:
    """Registry for skill definitions with tool dependency resolution."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._tool_registry = tool_registry

    def register(self, skill: SkillDefinition) -> None:
        if skill.name in self._skills:
            raise SkillRegistryError(
                f"Skill '{skill.name}' is already registered",
                details={"skill": skill.name},
            )
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def resolve_dependencies(self, skill_name: str) -> list[ToolDefinition]:
        """Resolve all tool dependencies for a skill."""
        skill = self._skills.get(skill_name)
        if skill is None:
            raise SkillRegistryError(
                f"Skill '{skill_name}' not found",
                details={"skill": skill_name},
            )
        resolved: list[ToolDefinition] = []
        for tool_name in skill.tools:
            tool_def = self._tool_registry.get(tool_name)
            if tool_def is None:
                raise SkillRegistryError(
                    f"Tool '{tool_name}' required by skill '{skill_name}' not found",
                    details={"skill": skill_name, "missing_tool": tool_name},
                )
            resolved.append(tool_def)
        return resolved

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())
