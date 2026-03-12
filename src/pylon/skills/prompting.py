"""Prompt composition helpers for agent skills."""

from __future__ import annotations

from pylon.skills.models import SkillActivation


def build_skill_prompt_prefix(activations: tuple[SkillActivation, ...]) -> str:
    """Compose a deterministic system-prompt prefix from activated skills."""
    if not activations:
        return ""
    ordered = sorted(
        activations,
        key=lambda item: (item.skill.prompt_priority, item.skill.effective_alias, item.skill.id),
    )
    sections: list[str] = [
        "You have the following specialized skills available. Apply them when relevant.",
    ]
    for activation in ordered:
        skill = activation.skill
        content = skill.content[: skill.max_prompt_chars].strip()
        if not content:
            continue
        sections.extend(
            [
                "",
                f"=== Skill: {skill.name} ({skill.effective_alias}) ===",
                content,
            ]
        )
    return "\n".join(section for section in sections if section is not None).strip()
