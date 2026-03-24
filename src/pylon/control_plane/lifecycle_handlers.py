"""Lifecycle workflow handler rehydration for durable control-plane runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pylon.runtime.llm import LLMRuntime, ProviderRegistry
from pylon.skills.runtime import SkillRuntime, get_default_skill_runtime

_EXECUTABLE_LIFECYCLE_PHASES = frozenset({"research", "planning", "design", "development"})


def parse_lifecycle_workflow_id(workflow_id: str) -> tuple[str, str] | None:
    prefix = "lifecycle-"
    if not workflow_id.startswith(prefix):
        return None
    phase, separator, project_id = workflow_id[len(prefix) :].partition("-")
    if not separator or not phase or not project_id:
        return None
    return phase, project_id


def ensure_lifecycle_workflow_handlers(
    store: Any,
    *,
    workflow_id: str,
    tenant_id: str = "default",
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
    skill_runtime: SkillRuntime | None = None,
) -> bool:
    """Re-register lifecycle node handlers after a process restart.

    Workflow definitions persist in the control-plane store, but handler registries do
    not. Without rehydration, rerunning a persisted lifecycle workflow falls back to the
    generic runtime path and loses the rich phase-specific state patch.
    """

    parsed = parse_lifecycle_workflow_id(str(workflow_id or ""))
    if parsed is None:
        return False
    phase, project_id = parsed
    if phase not in _EXECUTABLE_LIFECYCLE_PHASES:
        return False
    if not hasattr(store, "set_handlers"):
        return False
    existing_node_handlers = getattr(store, "get_node_handlers", lambda _workflow_id: None)(workflow_id) or {}
    if existing_node_handlers:
        return False

    from pylon.lifecycle.orchestrator import (
        build_lifecycle_phase_blueprints,
        build_lifecycle_workflow_handlers,
    )

    blueprint = build_lifecycle_phase_blueprints(project_id).get(phase, {})
    team_index = {
        str(item.get("id", "")).strip(): dict(item)
        for item in blueprint.get("team", [])
        if isinstance(item, Mapping) and str(item.get("id", "")).strip()
    } if isinstance(blueprint, Mapping) else {}

    list_surface_records = getattr(store, "list_surface_records", None)
    agent_records = []
    skill_records = []
    if callable(list_surface_records):
        agent_records = list_surface_records("agents", tenant_id=tenant_id) or []
        skill_records = list_surface_records("skills") or []

    control_plane_skills = {
        str(item.get("id", "")).strip(): dict(item)
        for item in skill_records
        if isinstance(item, Mapping) and str(item.get("id", "")).strip()
    }

    def _lifecycle_agent_skill_lookup(agent_id: str) -> list[str]:
        team_entry = team_index.get(agent_id, {})
        aliases = {
            str(agent_id).strip().lower(),
            str(team_entry.get("label", "")).strip().lower(),
        }
        aliases.discard("")
        matched: list[str] = []
        for agent in agent_records:
            if not isinstance(agent, Mapping):
                continue
            if str(agent.get("tenant_id", tenant_id) or tenant_id) != tenant_id:
                continue
            candidate_keys = {
                str(agent.get("id", "")).strip().lower(),
                str(agent.get("name", "")).strip().lower(),
                str(agent.get("role", "")).strip().lower(),
            }
            candidate_keys.discard("")
            if not aliases.intersection(candidate_keys):
                continue
            matched.extend(
                str(skill_id)
                for skill_id in agent.get("skills", [])
                if str(skill_id).strip()
            )
        return list(dict.fromkeys(matched))

    phase_handlers = build_lifecycle_workflow_handlers(
        phase,
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        skill_runtime=skill_runtime or get_default_skill_runtime(),
        tenant_id=tenant_id,
        agent_skill_lookup=_lifecycle_agent_skill_lookup,
        control_plane_skills=control_plane_skills,
    )
    store.set_handlers(
        workflow_id,
        node_handlers=phase_handlers,
        agent_handlers=phase_handlers,
    )
    return True
