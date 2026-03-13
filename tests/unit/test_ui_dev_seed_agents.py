from __future__ import annotations

from ui.scripts.dev_seed_agents import SEED_AGENT_SOURCE, seed_agent_id, upsert_seeded_agents


def _team_for_name(name: str) -> str:
    if "audit-" in name:
        return "advertising"
    return "development"


def test_upsert_seeded_agents_is_idempotent_and_removes_legacy_duplicates() -> None:
    agents = {
        "legacy-1": {
            "id": "legacy-1",
            "tenant_id": "default",
            "name": "reviewer",
            "model": "anthropic/claude-haiku-4-5-20251001",
            "role": "Code review, quality checks and standards enforcement",
            "autonomy": "A2",
            "tools": [],
            "sandbox": "gvisor",
            "team": "product",
        },
        "legacy-2": {
            "id": "legacy-2",
            "tenant_id": "default",
            "name": "reviewer",
            "model": "anthropic/claude-haiku-4-5-20251001",
            "role": "Code review, quality checks and standards enforcement",
            "autonomy": "A2",
            "tools": [],
            "sandbox": "gvisor",
            "team": "development",
        },
    }
    agent_specs = [
        ("core:reviewer", {
            "name": "reviewer",
            "model": "anthropic/claude-haiku-4-5-20251001",
            "role": "Code review, quality checks and standards enforcement",
            "autonomy": "A2",
            "tools": [],
            "sandbox": "gvisor",
        }),
    ]
    skills = {"reviewer": ["code-review", "security-scan"]}

    summary = upsert_seeded_agents(
        agents,
        agent_specs,
        tenant_id="default",
        team_for_name=_team_for_name,
        default_skills_by_name=skills,
        prune_prefixes=("core:",),
    )

    assert summary == {"desired": 1, "updated": 1, "removed_duplicates": 2, "pruned": 0}
    assert list(agents) == [seed_agent_id("core:reviewer")]
    reviewer = agents[seed_agent_id("core:reviewer")]
    assert reviewer["team"] == "development"
    assert reviewer["skills"] == ["code-review", "security-scan"]
    assert reviewer["seed_source"] == SEED_AGENT_SOURCE

    summary = upsert_seeded_agents(
        agents,
        agent_specs,
        tenant_id="default",
        team_for_name=_team_for_name,
        default_skills_by_name=skills,
        prune_prefixes=("core:",),
    )

    assert summary == {"desired": 1, "updated": 1, "removed_duplicates": 0, "pruned": 0}
    assert list(agents) == [seed_agent_id("core:reviewer")]


def test_upsert_seeded_agents_updates_existing_seed_record_and_prunes_stale_prefix() -> None:
    reviewer_id = seed_agent_id("workflow:autonomous-builder:reviewer")
    agents = {
        reviewer_id: {
            "id": reviewer_id,
            "tenant_id": "default",
            "name": "reviewer",
            "model": "anthropic/claude-sonnet-4-6",
            "role": "QA reviewer evaluating code against milestones",
            "autonomy": "A3",
            "tools": [],
            "sandbox": "gvisor",
            "team": "development",
            "skills": ["code-review", "security-scan"],
            "seed_source": SEED_AGENT_SOURCE,
            "seed_key": "workflow:autonomous-builder:reviewer",
        },
        seed_agent_id("workflow:autonomous-builder:stale"): {
            "id": seed_agent_id("workflow:autonomous-builder:stale"),
            "tenant_id": "default",
            "name": "stale-agent",
            "model": "anthropic/claude-sonnet-4-6",
            "role": "obsolete",
            "autonomy": "A1",
            "tools": [],
            "sandbox": "gvisor",
            "team": "development",
            "skills": [],
            "seed_source": SEED_AGENT_SOURCE,
            "seed_key": "workflow:autonomous-builder:stale",
        },
    }

    summary = upsert_seeded_agents(
        agents,
        [("workflow:autonomous-builder:reviewer", {
            "name": "milestone-reviewer",
            "model": "anthropic/claude-sonnet-4-6",
            "role": "QA reviewer evaluating code against milestones",
            "autonomy": "A3",
            "tools": [],
            "sandbox": "gvisor",
        })],
        tenant_id="default",
        team_for_name=_team_for_name,
        default_skills_by_name={"milestone-reviewer": ["code-review", "security-scan"]},
        prune_prefixes=("workflow:autonomous-builder:",),
    )

    assert summary == {"desired": 1, "updated": 1, "removed_duplicates": 0, "pruned": 1}
    assert list(agents) == [reviewer_id]
    assert agents[reviewer_id]["name"] == "milestone-reviewer"
