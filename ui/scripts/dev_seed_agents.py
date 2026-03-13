from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, MutableMapping, Sequence

SEED_AGENT_SOURCE = "ui-dev-seed"


def normalize_tools(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def seed_agent_id(seed_key: str) -> str:
    return hashlib.sha1(f"ui-dev-agent:{seed_key}".encode("utf-8")).hexdigest()[:12]


def agent_signature(agent: Mapping[str, object]) -> tuple[str, str, str, str, str, tuple[str, ...], str, str]:
    return (
        str(agent.get("tenant_id", "")),
        str(agent.get("name", "")),
        str(agent.get("model", "")),
        str(agent.get("role", "")),
        str(agent.get("autonomy", "")),
        tuple(normalize_tools(agent.get("tools"))),
        str(agent.get("sandbox", "")),
        str(agent.get("team", "")),
    )


def agent_signature_without_team(agent: Mapping[str, object]) -> tuple[str, str, str, str, str, tuple[str, ...], str]:
    return (
        str(agent.get("tenant_id", "")),
        str(agent.get("name", "")),
        str(agent.get("model", "")),
        str(agent.get("role", "")),
        str(agent.get("autonomy", "")),
        tuple(normalize_tools(agent.get("tools"))),
        str(agent.get("sandbox", "")),
    )


def seeded_agent_payload(
    seed_key: str,
    agent_def: Mapping[str, object],
    *,
    tenant_id: str,
    team: str,
    skills: Sequence[str],
) -> dict[str, object]:
    return {
        "id": seed_agent_id(seed_key),
        "name": str(agent_def["name"]),
        "model": str(agent_def["model"]),
        "role": str(agent_def["role"]),
        "autonomy": str(agent_def["autonomy"]),
        "tools": list(normalize_tools(agent_def.get("tools"))),
        "sandbox": str(agent_def["sandbox"]),
        "status": "ready",
        "tenant_id": tenant_id,
        "team": team,
        "skills": list(skills),
        "seed_source": SEED_AGENT_SOURCE,
        "seed_key": seed_key,
    }


def upsert_seeded_agents(
    agents_by_id: MutableMapping[str, dict[str, object]],
    agent_specs: Sequence[tuple[str, Mapping[str, object]]],
    *,
    tenant_id: str,
    team_for_name: Callable[[str], str],
    default_skills_by_name: Mapping[str, Sequence[str]],
    prune_prefixes: Sequence[str] = (),
) -> dict[str, int]:
    existing_agents = list(agents_by_id.values())
    desired_seed_keys = {seed_key for seed_key, _ in agent_specs}
    removed_duplicates = 0
    pruned = 0
    created_or_updated = 0

    for seed_key, agent_def in agent_specs:
        agent_name = str(agent_def["name"])
        desired = seeded_agent_payload(
            seed_key,
            agent_def,
            tenant_id=tenant_id,
            team=team_for_name(agent_name),
            skills=default_skills_by_name.get(agent_name, ()),
        )
        desired_signature = agent_signature(desired)
        desired_signature_without_team = agent_signature_without_team(desired)
        duplicate_ids: list[str] = []

        for agent in existing_agents:
            if str(agent.get("tenant_id", "")) != tenant_id:
                continue
            agent_id = str(agent.get("id", ""))
            if not agent_id:
                continue
            if (
                agent.get("seed_source") == SEED_AGENT_SOURCE
                and agent.get("seed_key") == seed_key
            ) or agent_signature(agent) == desired_signature or agent_signature_without_team(agent) == desired_signature_without_team:
                duplicate_ids.append(agent_id)

        agents_by_id[str(desired["id"])] = desired
        created_or_updated += 1

        for agent_id in duplicate_ids:
            if agent_id == desired["id"]:
                continue
            if agents_by_id.get(agent_id) is None:
                continue
            del agents_by_id[agent_id]
            removed_duplicates += 1

    if prune_prefixes:
        for agent in list(agents_by_id.values()):
            if str(agent.get("tenant_id", "")) != tenant_id:
                continue
            if agent.get("seed_source") != SEED_AGENT_SOURCE:
                continue
            seed_key = str(agent.get("seed_key", ""))
            if seed_key in desired_seed_keys:
                continue
            if not any(seed_key.startswith(prefix) for prefix in prune_prefixes):
                continue
            agent_id = str(agent.get("id", ""))
            if not agent_id or agents_by_id.get(agent_id) is None:
                continue
            del agents_by_id[agent_id]
            pruned += 1

    return {
        "desired": len(agent_specs),
        "updated": created_or_updated,
        "removed_duplicates": removed_duplicates,
        "pruned": pruned,
    }
