"""Operator-console records for Product Lifecycle runs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pylon.lifecycle.contracts import build_phase_contract
from pylon.lifecycle.orchestrator import PHASE_ORDER, build_lifecycle_phase_blueprints
from pylon.protocols.a2a.card import AgentCardRegistry, generate_card
from pylon.protocols.a2a.types import (
    A2AMessage,
    A2ATask,
    AgentCapabilities,
    AgentSkill,
    Part,
    TaskState,
)
from pylon.protocols.a2a.types import (
    Artifact as A2AArtifact,
)
from pylon.providers.base import TokenUsage
from pylon.runtime.llm import estimate_cost_from_usage


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:64] or prefix


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 2:
        if isinstance(value, str):
            return value[:280]
        if isinstance(value, list):
            return f"{len(value)} items"
        if isinstance(value, dict):
            return f"{len(value)} fields"
        return value
    if isinstance(value, str):
        return value[:280]
    if isinstance(value, list):
        return [_compact_value(item, depth=depth + 1) for item in value[:6]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 10:
                compacted["_truncated"] = True
                break
            compacted[str(key)] = _compact_value(item, depth=depth + 1)
        return compacted
    return value


def _phase_statuses_with_status(
    existing: Iterable[dict[str, Any]],
    *,
    phase: str,
    status: str,
) -> list[dict[str, Any]]:
    statuses = [dict(item) for item in existing if isinstance(item, dict)]
    phase_index = PHASE_ORDER.index(phase)
    for item in statuses:
        if item.get("phase") == phase:
            item["status"] = status
            if status == "completed":
                item["completedAt"] = _utc_now_iso()
            break
    if status == "completed" and phase_index + 1 < len(PHASE_ORDER):
        next_phase = PHASE_ORDER[phase_index + 1]
        for item in statuses:
            if item.get("phase") == next_phase and item.get("status") == "locked":
                item["status"] = "available"
                break
    return statuses


def _merge_records(
    existing: Iterable[dict[str, Any]] | None,
    updates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in existing or []:
        if isinstance(item, dict) and item.get("id"):
            merged[str(item["id"])] = dict(item)
    for item in updates:
        if isinstance(item, dict) and item.get("id"):
            merged[str(item["id"])] = dict(item)
    return sorted(
        merged.values(),
        key=lambda record: str(record.get("createdAt", record.get("completedAt", ""))),
        reverse=True,
    )


def merge_operator_records(
    project_record: dict[str, Any],
    *,
    artifacts: Iterable[dict[str, Any]] = (),
    decisions: Iterable[dict[str, Any]] = (),
    skill_invocations: Iterable[dict[str, Any]] = (),
    delegations: Iterable[dict[str, Any]] = (),
    phase_runs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "artifacts": _merge_records(project_record.get("artifacts"), artifacts),
        "decisionLog": _merge_records(project_record.get("decisionLog"), decisions),
        "skillInvocations": _merge_records(project_record.get("skillInvocations"), skill_invocations),
        "delegations": _merge_records(project_record.get("delegations"), delegations),
        "phaseRuns": _merge_records(project_record.get("phaseRuns"), phase_runs),
    }


def lifecycle_artifact(
    *,
    artifact_id: str,
    phase: str,
    kind: str,
    title: str,
    summary: str,
    created_at: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    producer: str | None = None,
    skill_ids: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "phase": phase,
        "kind": kind,
        "title": title,
        "summary": summary,
        "createdAt": created_at or _utc_now_iso(),
        "runId": run_id,
        "nodeId": node_id,
        "producer": producer,
        "skillIds": list(skill_ids or []),
        "payload": _compact_value(payload or {}),
    }


def lifecycle_decision(
    *,
    decision_id: str,
    phase: str,
    kind: str,
    title: str,
    rationale: str,
    created_at: str | None = None,
    run_id: str | None = None,
    status: str = "recorded",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": decision_id,
        "phase": phase,
        "kind": kind,
        "title": title,
        "rationale": rationale,
        "status": status,
        "runId": run_id,
        "createdAt": created_at or _utc_now_iso(),
        "details": _compact_value(details or {}),
    }


def build_lifecycle_skill_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    blueprints = build_lifecycle_phase_blueprints("catalog")
    for phase, blueprint in blueprints.items():
        for agent in blueprint.get("team", []):
            if not isinstance(agent, dict):
                continue
            agent_tools = list(agent.get("tools", []))
            artifact_ids = [item.get("id", "") for item in blueprint.get("artifacts", []) if isinstance(item, dict)]
            for skill in agent.get("skills", []):
                if not isinstance(skill, str) or not skill:
                    continue
                catalog.setdefault(
                    skill,
                    {
                        "id": skill,
                        "name": skill.replace("-", " ").title(),
                        "description": f"{phase} phase skill executed by {agent.get('label', agent.get('id', 'agent'))}.",
                        "category": phase,
                        "source": "builtin",
                        "tags": [phase, "lifecycle", "multi-agent"],
                        "tools": agent_tools,
                        "trust_class": "external-read" if any(tool in {"http", "browser"} for tool in agent_tools) else "internal",
                        "approval_class": "review" if phase in {"design", "development", "deploy"} else "auto",
                        "cost_class": "medium" if phase in {"design", "development"} else "low",
                        "artifact_type": artifact_ids[0] if artifact_ids else phase,
                        "quality_metric": [gate.get("title", "") for gate in blueprint.get("quality_gates", []) if isinstance(gate, dict)],
                        "content_preview": f"Use {skill} to advance the {phase} phase while producing typed artifacts.",
                    },
                )
    return catalog


def build_lifecycle_peer_registry() -> AgentCardRegistry:
    registry = AgentCardRegistry()
    peers = [
        generate_card(
            "research-fabric",
            "https://agents.pylon.local/research-fabric",
            description="External research specialists for market sizing and competitive analysis.",
            provider="pylon",
            capabilities=AgentCapabilities(streaming=True, state_transition_history=True),
            skills=[
                AgentSkill(name="market-sizing", description="Validate market demand and sizing"),
                AgentSkill(name="competitive-intelligence", description="Compare competitors"),
                AgentSkill(name="persona-research", description="Strengthen persona hypotheses"),
            ],
        ),
        generate_card(
            "design-critic",
            "https://agents.pylon.local/design-critic",
            description="External UX and design quality critic.",
            provider="pylon",
            capabilities=AgentCapabilities(streaming=True, state_transition_history=True),
            skills=[
                AgentSkill(name="accessibility-review", description="Review accessible patterns"),
                AgentSkill(name="performance-review", description="Review perceived performance"),
                AgentSkill(name="design-critique", description="Critique design quality"),
            ],
        ),
        generate_card(
            "safety-guardian",
            "https://agents.pylon.local/safety-guardian",
            description="Security and safety peer for release risk review.",
            provider="pylon",
            capabilities=AgentCapabilities(state_transition_history=True),
            skills=[
                AgentSkill(name="security-review", description="Validate security posture"),
                AgentSkill(name="safety-review", description="Validate safe autonomy posture"),
            ],
        ),
        generate_card(
            "build-craft",
            "https://agents.pylon.local/build-craft",
            description="Implementation craft peer for frontend, integration, and code review.",
            provider="pylon",
            capabilities=AgentCapabilities(streaming=True, state_transition_history=True),
            skills=[
                AgentSkill(name="frontend-implementation", description="Raise implementation craft"),
                AgentSkill(name="responsive-ui", description="Improve responsive behavior"),
                AgentSkill(name="artifact-assembly", description="Review integrated build coherence"),
                AgentSkill(name="code-review", description="Review code and release quality"),
                AgentSkill(name="delivery-review", description="Validate delivery readiness"),
            ],
        ),
        generate_card(
            "quality-lab",
            "https://agents.pylon.local/quality-lab",
            description="Quality peer for acceptance, release criteria, and milestone readiness.",
            provider="pylon",
            capabilities=AgentCapabilities(streaming=True, state_transition_history=True),
            skills=[
                AgentSkill(name="acceptance-testing", description="Review milestone acceptance"),
                AgentSkill(name="quality-assurance", description="Validate product quality"),
                AgentSkill(name="delivery-review", description="Check release readiness"),
            ],
        ),
        generate_card(
            "release-ops",
            "https://agents.pylon.local/release-ops",
            description="Release and roadmap peer for deploy and iteration gates.",
            provider="pylon",
            capabilities=AgentCapabilities(state_transition_history=True),
            skills=[
                AgentSkill(name="release-management", description="Manage release readiness"),
                AgentSkill(name="quality-gating", description="Judge release gates"),
                AgentSkill(name="roadmap-optimization", description="Optimize next iteration roadmap"),
            ],
        ),
    ]
    for peer in peers:
        registry.register(peer)
    return registry


def _artifact_summary(raw: dict[str, Any]) -> str:
    if isinstance(raw.get("description"), str) and raw["description"]:
        return str(raw["description"])[:180]
    if isinstance(raw.get("notes"), str) and raw["notes"]:
        return str(raw["notes"])[:180]
    if "variants" in raw and isinstance(raw["variants"], list):
        return f"{len(raw['variants'])} candidate variants were produced."
    if "items" in raw and isinstance(raw["items"], list):
        return f"{len(raw['items'])} items captured for this artifact."
    keys = [str(key) for key in raw.keys() if key not in {"name", "kind"}][:4]
    return ", ".join(keys) if keys else "Structured artifact emitted by workflow node."


def _phase_output_patch(
    project_record: dict[str, Any],
    *,
    phase: str,
    run_state: dict[str, Any],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if phase == "research":
        research = _as_dict(run_state.get("research"))
        if research:
            patch["research"] = research
    elif phase == "planning":
        patch["analysis"] = _as_dict(run_state.get("analysis"))
        patch["features"] = _as_list(run_state.get("features"))
        patch["planEstimates"] = _as_list(run_state.get("planEstimates"))
        if not project_record.get("milestones"):
            analysis = _as_dict(run_state.get("analysis"))
            recommended = _as_list(analysis.get("recommended_milestones"))
            patch["milestones"] = [
                {
                    "id": item.get("id", f"ms-{index + 1}"),
                    "name": item.get("name", "Milestone"),
                    "criteria": item.get("criteria", ""),
                }
                for index, item in enumerate(recommended)
                if isinstance(item, dict)
            ]
    elif phase == "design":
        variants = _as_list(run_state.get("variants"))
        patch["designVariants"] = variants
        selected_id = str(run_state.get("selected_design_id") or "")
        if selected_id:
            patch["selectedDesignId"] = selected_id
        elif variants and not project_record.get("selectedDesignId"):
            first = _as_dict(variants[0])
            if first.get("id"):
                patch["selectedDesignId"] = first["id"]
    elif phase == "development":
        development = _as_dict(run_state.get("development"))
        patch["buildCode"] = str(development.get("code", "") or "")
        patch["buildCost"] = float(run_state.get("estimated_cost_usd", 0.0) or 0.0)
        patch["buildIteration"] = int(run_state.get("_build_iteration", 0) or 0)
        patch["milestoneResults"] = _as_list(development.get("milestone_results"))
    return patch


def _contract_blocking_issues(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return ["Phase outputs did not produce a valid handoff contract."]
    issues = []
    for gate in _as_list(contract.get("qualityGates")):
        if not isinstance(gate, dict) or gate.get("passed") is True:
            continue
        title = str(gate.get("title", "") or "Quality gate failed")
        detail = str(gate.get("detail", "") or "").strip()
        issues.append(f"{title}: {detail}" if detail else title)
    return issues or ["Phase outputs did not pass readiness checks."]


def _is_external_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _research_stub_run_issues(
    run_record: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> list[str]:
    runtime_metrics = _as_dict(run_record.get("runtime_metrics"))
    if not runtime_metrics:
        runtime_metrics = _as_dict(_as_dict(run_record.get("state")).get("runtime_metrics"))
    if not runtime_metrics:
        return []
    token_usage = _as_dict(runtime_metrics.get("token_usage"))
    total_tokens = int(token_usage.get("total_tokens", 0) or 0)
    model_routes = _as_list(runtime_metrics.get("model_routes"))
    if total_tokens > 0 or model_routes:
        return []
    research = _as_dict(candidate.get("research"))
    source_links = [item for item in _as_list(research.get("source_links")) if _is_external_url(item)]
    grounded_evidence = [
        item for item in _as_list(research.get("evidence"))
        if isinstance(item, dict)
        and str(item.get("source_type", "")).strip() == "url"
        and _is_external_url(item.get("source_ref"))
    ]
    if source_links or grounded_evidence:
        return []
    return ["Research run finished without model activity or external URL evidence."]


def _resolve_phase_sync_status(
    project_record: dict[str, Any],
    *,
    phase: str,
    run_record: dict[str, Any],
    patch: dict[str, Any],
) -> tuple[str, list[str]]:
    run_status = str(run_record.get("status", "completed") or "completed")
    if run_status != "completed":
        return "available", [f"Run finished with status '{run_status}'."]
    if (
        phase == "research"
        and "research" not in patch
        and _as_dict(project_record.get("research"))
    ):
        current_status = next(
            (
                str(entry.get("status", "available"))
                for entry in _as_list(project_record.get("phaseStatuses"))
                if isinstance(entry, dict) and entry.get("phase") == phase
            ),
            "completed",
        )
        return current_status, []
    candidate = dict(project_record)
    candidate.update(patch)
    if phase == "research" and not _as_dict(candidate.get("research")):
        return "available", ["Research run completed without a persisted research artifact."]
    contract = build_phase_contract(candidate, phase)
    if contract is None:
        return "completed", []
    if contract.get("ready") is True:
        if phase == "research":
            stub_issues = _research_stub_run_issues(run_record, candidate=candidate)
            if stub_issues:
                return "available", stub_issues
        return "completed", []
    return "available", _contract_blocking_issues(contract)


def _phase_artifacts(
    project_id: str,
    *,
    phase: str,
    run_record: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    blueprints = build_lifecycle_phase_blueprints(project_id)
    team_lookup = {
        str(agent.get("id", "")): dict(agent)
        for agent in blueprints.get(phase, {}).get("team", [])
        if isinstance(agent, dict)
    }
    run_id = str(run_record.get("id", ""))
    for checkpoint in checkpoints:
        checkpoint_events = _as_list(checkpoint.get("event_log"))
        checkpoint_created_at = str(checkpoint.get("created_at", "") or _utc_now_iso())
        for event in checkpoint_events:
            if not isinstance(event, dict):
                continue
            node_id = str(event.get("node_id", ""))
            agent = team_lookup.get(node_id, {})
            for index, raw_artifact in enumerate(_as_list(event.get("artifacts"))):
                artifact = _as_dict(raw_artifact)
                name = str(artifact.get("name", artifact.get("id", f"artifact-{index}")) or f"artifact-{index}")
                kind = str(artifact.get("kind", phase) or phase)
                artifact_id = f"{run_id}:{node_id}:{_slug(name, prefix='artifact')}"
                artifacts.append(
                    lifecycle_artifact(
                        artifact_id=artifact_id,
                        phase=phase,
                        kind=kind,
                        title=name.replace("-", " ").title(),
                        summary=_artifact_summary(artifact),
                        created_at=str(event.get("timestamp", checkpoint_created_at)),
                        run_id=run_id,
                        node_id=node_id,
                        producer=node_id,
                        skill_ids=list(agent.get("skills", [])),
                        payload=artifact,
                    )
                )
    if artifacts:
        return artifacts
    return [
        lifecycle_artifact(
            artifact_id=f"{run_id}:{phase}:summary",
            phase=phase,
            kind=phase,
            title=f"{phase.title()} summary",
            summary=f"{phase.title()} phase completed without explicit checkpoint artifacts.",
            run_id=run_id,
            producer=phase,
            payload=_as_dict(run_record.get("state")),
        )
    ]


def _runtime_skill_plans(run_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    suffix = "_skill_plan"
    for key, value in run_state.items():
        if not key.endswith(suffix) or not isinstance(value, dict):
            continue
        plans[key[: -len(suffix)]] = dict(value)
    return plans


def _runtime_delegations(run_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    delegations: dict[str, list[dict[str, Any]]] = {}
    suffix = "_delegations"
    for key, value in run_state.items():
        if not key.endswith(suffix) or not isinstance(value, list):
            continue
        delegations[key[: -len(suffix)]] = [dict(item) for item in value if isinstance(item, dict)]
    return delegations


def _phase_decisions(
    project_id: str,
    *,
    phase: str,
    run_record: dict[str, Any],
    phase_status: str,
    blocking_issues: list[str] | None = None,
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    run_id = str(run_record.get("id", ""))
    execution_summary = _as_dict(run_record.get("execution_summary"))
    for index, point in enumerate(_as_list(execution_summary.get("decision_points"))):
        point_data = _as_dict(point)
        source_node = str(point_data.get("source_node", phase) or phase)
        decisions.append(
            lifecycle_decision(
                decision_id=f"{run_id}:{source_node}:decision:{index}",
                phase=phase,
                kind=str(point_data.get("type", "edge_decision")),
                title=f"{source_node} routing decision",
                rationale=str(point_data.get("edges", []))[:220] or "Workflow edge decision recorded.",
                run_id=run_id,
                details=point_data,
            )
        )
    blueprint = build_lifecycle_phase_blueprints(project_id).get(phase, {})
    outcome_completed = phase_status == "completed"
    decisions.append(
        lifecycle_decision(
            decision_id=f"{run_id}:{phase}:outcome",
            phase=phase,
            kind="phase_outcome",
            title=(
                f"{blueprint.get('title', phase.title())} completed"
                if outcome_completed
                else f"{blueprint.get('title', phase.title())} requires rework"
            ),
            rationale=(
                str(blueprint.get("summary", "Phase completed and produced operator-ready outputs."))
                if outcome_completed
                else "; ".join(blocking_issues or ["Phase outputs did not satisfy readiness checks."])
            ),
            run_id=run_id,
            status="approved" if outcome_completed else "blocked",
            details={
                "workflow_id": run_record.get("workflow_id"),
                "status": run_record.get("status"),
                "phase_status": phase_status,
                "blocking_issues": list(blocking_issues or []),
            },
        )
    )
    return decisions


def _skill_and_delegation_records(
    project_id: str,
    *,
    phase: str,
    run_record: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run_id = str(run_record.get("id", ""))
    peer_registry = build_lifecycle_peer_registry()
    blueprints = build_lifecycle_phase_blueprints(project_id)
    skill_catalog = build_lifecycle_skill_catalog()
    run_state = _as_dict(run_record.get("state"))
    runtime_skill_plans = _runtime_skill_plans(run_state)
    runtime_delegation_records = _runtime_delegations(run_state)
    skill_invocations: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    for agent in blueprints.get(phase, {}).get("team", []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("id", ""))
        agent_artifact_ids = [item["id"] for item in artifacts if item.get("producer") == agent_id]
        plan = _as_dict(runtime_skill_plans.get(agent_id))
        selected_skills = [
            str(item)
            for item in _as_list(plan.get("selected_skills"))
            if str(item).strip()
        ] or [str(item) for item in _as_list(agent.get("skills")) if str(item).strip()]
        runtime_delegations = runtime_delegation_records.get(agent_id, [])
        for skill_name in selected_skills:
            if not isinstance(skill_name, str) or not skill_name:
                continue
            delegated = [item for item in runtime_delegations if str(item.get("skill", "")) == skill_name]
            peers = peer_registry.find_by_skill(skill_name)
            mode = "a2a" if delegated else "local"
            peer_name = str(delegated[0].get("peer", "")) if delegated else (peers[0].name if peers else None)
            skill_record = skill_catalog.get(skill_name, {})
            invocation_id = f"{run_id}:{agent_id}:{skill_name}"
            skill_invocations.append(
                {
                    "id": invocation_id,
                    "phase": phase,
                    "agentId": agent_id,
                    "agentLabel": str(agent.get("label", agent_id)),
                    "skill": skill_name,
                    "status": "completed",
                    "mode": mode,
                    "provider": str(plan.get("mode") or (str(agent.get("label", "deterministic-reference")) if phase == "design" else "deterministic-reference")),
                    "toolIds": list(agent.get("tools", [])),
                    "outputArtifactIds": agent_artifact_ids,
                    "delegatedTo": peer_name,
                    "createdAt": str(run_record.get("completed_at", run_record.get("started_at", _utc_now_iso()))),
                    "summary": str(plan.get("execution_note") or skill_record.get("description", "")),
                }
            )
        if runtime_delegations:
            for index, item in enumerate(runtime_delegations):
                peer_name = str(item.get("peer", ""))
                peer_card = _as_dict(item.get("peerCard")) or (
                    peer_registry.get(peer_name).to_dict() if peer_name and peer_registry.get(peer_name) is not None else {}
                )
                delegations.append(
                    {
                        "id": f"{run_id}:{agent_id}:{str(item.get('skill', 'delegation'))}:{index}",
                        "phase": phase,
                        "agentId": agent_id,
                        "peer": peer_name,
                        "peerCard": peer_card,
                        "skill": str(item.get("skill", "")),
                        "status": str(item.get("status", "completed") or "completed"),
                        "runId": run_id,
                        "createdAt": str(run_record.get("completed_at", run_record.get("started_at", _utc_now_iso()))),
                        "task": _as_dict(item.get("task")),
                    }
                )
            continue
        for skill_name in _as_list(agent.get("skills")):
            if not isinstance(skill_name, str) or not skill_name:
                continue
            peers = peer_registry.find_by_skill(skill_name)
            if not peers:
                continue
            peer = peers[0]
            related_artifact = next((item for item in artifacts if item.get("producer") == agent_id), None)
            task = A2ATask(
                id=f"{run_id}:{agent_id}:{skill_name}:a2a",
                state=TaskState.COMPLETED,
                messages=[
                    A2AMessage(
                        role="agent",
                        parts=[
                            Part(
                                type="text",
                                content=f"Delegate {skill_name} for lifecycle phase {phase} on project {project_id}.",
                            )
                        ],
                    )
                ],
                artifacts=(
                    [
                        A2AArtifact(
                            name=str(related_artifact.get("title", "artifact")),
                            description=str(related_artifact.get("summary", "")),
                            parts=[Part(type="data", content=_compact_value(related_artifact.get("payload", {})))],
                            metadata={"artifact_id": related_artifact.get("id")},
                        )
                    ]
                    if related_artifact is not None
                    else []
                ),
                metadata={
                    "phase": phase,
                    "project_id": project_id,
                    "skill": skill_name,
                    "sender": agent_id,
                    "receiver": peer.name,
                },
            )
            delegations.append(
                {
                    "id": f"{run_id}:{agent_id}:{skill_name}:delegation",
                    "phase": phase,
                    "agentId": agent_id,
                    "peer": peer.name,
                    "peerCard": peer.to_dict(),
                    "skill": skill_name,
                    "status": "completed",
                    "runId": run_id,
                    "createdAt": str(run_record.get("completed_at", run_record.get("started_at", _utc_now_iso()))),
                    "task": task.to_dict(),
                }
            )
    return skill_invocations, delegations


def _phase_run_summary(
    project_id: str,
    *,
    phase: str,
    run_record: dict[str, Any],
    checkpoints: list[dict[str, Any]],
    artifact_count: int,
    decision_count: int,
) -> dict[str, Any]:
    runtime_metrics = _as_dict(run_record.get("runtime_metrics"))
    token_usage = _as_dict(runtime_metrics.get("token_usage"))
    input_tokens = int(token_usage.get("input_tokens", 0) or 0)
    output_tokens = int(token_usage.get("output_tokens", 0) or 0)
    cache_read_tokens = int(token_usage.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(token_usage.get("cache_write_tokens", 0) or 0)
    reasoning_tokens = int(token_usage.get("reasoning_tokens", 0) or 0)
    total_tokens = int(token_usage.get("total_tokens", input_tokens + output_tokens) or 0)
    metered_tokens = int(
        token_usage.get(
            "metered_tokens",
            total_tokens + cache_read_tokens + cache_write_tokens + reasoning_tokens,
        ) or 0
    )
    cost_usd = float(runtime_metrics.get("estimated_cost_usd", 0.0) or 0.0)
    checkpoint_input_tokens = 0
    checkpoint_output_tokens = 0
    checkpoint_cache_read_tokens = 0
    checkpoint_cache_write_tokens = 0
    checkpoint_reasoning_tokens = 0
    checkpoint_cost_usd = 0.0
    for checkpoint in checkpoints:
        for event in _as_list(checkpoint.get("event_log")):
            if not isinstance(event, dict):
                continue
            for llm_event in _as_list(event.get("llm_events")):
                if not isinstance(llm_event, dict):
                    continue
                event_usage = _as_dict(llm_event.get("usage"))
                usage = TokenUsage(
                    input_tokens=int(event_usage.get("input_tokens", 0) or 0),
                    output_tokens=int(event_usage.get("output_tokens", 0) or 0),
                    cache_read_tokens=int(event_usage.get("cache_read_tokens", 0) or 0),
                    cache_write_tokens=int(event_usage.get("cache_write_tokens", 0) or 0),
                    reasoning_tokens=int(event_usage.get("reasoning_tokens", 0) or 0),
                )
                checkpoint_input_tokens += usage.input_tokens
                checkpoint_output_tokens += usage.output_tokens
                checkpoint_cache_read_tokens += usage.cache_read_tokens
                checkpoint_cache_write_tokens += usage.cache_write_tokens
                checkpoint_reasoning_tokens += usage.reasoning_tokens
                event_cost = float(llm_event.get("estimated_cost_usd", llm_event.get("cost_usd", 0.0)) or 0.0)
                if event_cost <= 0.0:
                    event_cost = estimate_cost_from_usage(
                        str(llm_event.get("provider", "") or ""),
                        str(llm_event.get("model", "") or ""),
                        usage,
                    )
                checkpoint_cost_usd += event_cost
    checkpoint_total_tokens = checkpoint_input_tokens + checkpoint_output_tokens
    checkpoint_metered_tokens = (
        checkpoint_total_tokens
        + checkpoint_cache_read_tokens
        + checkpoint_cache_write_tokens
        + checkpoint_reasoning_tokens
    )
    if checkpoint_total_tokens > total_tokens:
        input_tokens = checkpoint_input_tokens
        output_tokens = checkpoint_output_tokens
        cache_read_tokens = checkpoint_cache_read_tokens
        cache_write_tokens = checkpoint_cache_write_tokens
        reasoning_tokens = checkpoint_reasoning_tokens
        total_tokens = checkpoint_total_tokens
        metered_tokens = checkpoint_metered_tokens
    elif checkpoint_metered_tokens > metered_tokens:
        metered_tokens = checkpoint_metered_tokens
    if checkpoint_cost_usd > cost_usd:
        cost_usd = checkpoint_cost_usd
    cost_measured = checkpoint_cost_usd > 0.0 or cost_usd > 0.0
    return {
        "id": str(run_record.get("id", "")),
        "runId": str(run_record.get("id", "")),
        "projectId": project_id,
        "phase": phase,
        "workflowId": str(run_record.get("workflow_id", "")),
        "status": str(run_record.get("status", "")),
        "startedAt": run_record.get("started_at"),
        "completedAt": run_record.get("completed_at"),
        "createdAt": str(run_record.get("completed_at", run_record.get("started_at", _utc_now_iso()))),
        "artifactCount": artifact_count,
        "decisionCount": decision_count,
        "costUsd": round(cost_usd, 6),
        "costMeasured": cost_measured,
        "totalTokens": total_tokens,
        "meteredTokens": metered_tokens,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheReadTokens": cache_read_tokens,
        "cacheWriteTokens": cache_write_tokens,
        "reasoningTokens": reasoning_tokens,
        "executionSummary": _compact_value(_as_dict(run_record.get("execution_summary"))),
    }


def sync_lifecycle_project_with_run(
    project_record: dict[str, Any],
    *,
    phase: str,
    run_record: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    project_id = str(project_record.get("projectId", project_record.get("id", "")))
    run_state = _as_dict(run_record.get("state"))
    patch = _phase_output_patch(project_record, phase=phase, run_state=run_state)
    phase_status, blocking_issues = _resolve_phase_sync_status(
        project_record,
        phase=phase,
        run_record=run_record,
        patch=patch,
    )
    patch["phaseStatuses"] = _phase_statuses_with_status(
        _as_list(project_record.get("phaseStatuses")),
        phase=phase,
        status=phase_status,
    )
    artifacts = _phase_artifacts(project_id, phase=phase, run_record=run_record, checkpoints=checkpoints)
    decisions = _phase_decisions(
        project_id,
        phase=phase,
        run_record=run_record,
        phase_status=phase_status,
        blocking_issues=blocking_issues,
    )
    skill_invocations, delegations = _skill_and_delegation_records(
        project_id,
        phase=phase,
        run_record=run_record,
        artifacts=artifacts,
    )
    phase_run = _phase_run_summary(
        project_id,
        phase=phase,
        run_record=run_record,
        checkpoints=checkpoints,
        artifact_count=len(artifacts),
        decision_count=len(decisions),
    )
    patch.update(
        merge_operator_records(
            project_record,
            artifacts=artifacts,
            decisions=decisions,
            skill_invocations=skill_invocations,
            delegations=delegations,
            phase_runs=[phase_run],
        )
    )
    return patch
