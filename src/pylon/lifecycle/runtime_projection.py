"""Lifecycle runtime projections for operator-facing APIs and SSE payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pylon.lifecycle.orchestrator import build_lifecycle_phase_blueprints

LIFECYCLE_RUNTIME_EXECUTABLE_PHASES: tuple[str, ...] = (
    "research",
    "planning",
    "design",
    "development",
)


def _phase_blueprint(project: Mapping[str, Any], phase: str) -> dict[str, Any]:
    blueprints = project.get("blueprints")
    if isinstance(blueprints, Mapping):
        blueprint = blueprints.get(phase)
        if isinstance(blueprint, Mapping):
            return dict(blueprint)
    project_id = str(project.get("projectId", project.get("id", "catalog")) or "catalog")
    return dict(build_lifecycle_phase_blueprints(project_id).get(phase, {}))


def _phase_team(project: Mapping[str, Any], phase: str) -> list[dict[str, Any]]:
    team = _phase_blueprint(project, phase).get("team")
    return [dict(item) for item in team if isinstance(item, Mapping)] if isinstance(team, list) else []


def _phase_team_index(project: Mapping[str, Any], phase: str) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id", "")).strip(): item
        for item in _phase_team(project, phase)
        if str(item.get("id", "")).strip()
    }


def _run_node_status_map(run: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(run, Mapping):
        return {}
    node_status = run.get("node_status")
    if isinstance(node_status, Mapping):
        return {str(key): str(value) for key, value in node_status.items()}
    state = run.get("state")
    if not isinstance(state, Mapping):
        return {}
    execution = state.get("execution")
    if not isinstance(execution, Mapping):
        return {}
    node_status = execution.get("node_status")
    if isinstance(node_status, Mapping):
        return {str(key): str(value) for key, value in node_status.items()}
    return {}


def _run_event_log(run: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(run, Mapping):
        return []
    event_log = run.get("event_log")
    return [dict(item) for item in event_log if isinstance(item, Mapping)] if isinstance(event_log, list) else []


def _phase_records_for_run(
    records: Any,
    *,
    phase: str,
    run_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    phase_records = [dict(item) for item in records if isinstance(item, Mapping) and item.get("phase") == phase]
    if not run_id:
        return phase_records
    run_records = [item for item in phase_records if str(item.get("runId", "")) == run_id]
    return run_records or phase_records


def _latest_record_by_agent(
    records: Iterable[dict[str, Any]],
    *,
    agent_key: str = "agentId",
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in reversed(list(records)):
        agent_id = str(item.get(agent_key, "")).strip()
        if agent_id and agent_id not in latest:
            latest[agent_id] = item
    return latest


def _delegation_focus(delegation: Mapping[str, Any]) -> str:
    skill = str(delegation.get("skill", "")).strip()
    peer = str(delegation.get("peer", "")).strip()
    task = delegation.get("task")
    if isinstance(task, Mapping):
        metadata = task.get("metadata")
        if isinstance(metadata, Mapping):
            skill = skill or str(metadata.get("skill", "")).strip()
            peer = peer or str(metadata.get("receiver", "")).strip()
    if skill and peer:
        return f"{skill} を {peer} に委譲"
    if skill:
        return f"{skill} を委譲"
    if peer:
        return f"{peer} と連携"
    return "委譲を実行"


def _resolve_runtime_agent_id(
    project: Mapping[str, Any],
    phase: str,
    *,
    node_id: str,
    agent_hint: str = "",
) -> str:
    team_index = _phase_team_index(project, phase)
    hint = agent_hint.strip()
    node = node_id.strip()
    if hint and hint in team_index:
        return hint
    if node and node in team_index:
        return node
    return hint or node


def _runtime_agent_status_from_nodes(statuses: list[str], *, observed: bool) -> str:
    normalized = [status.strip() for status in statuses if status.strip()]
    if any(status == "running" for status in normalized):
        return "running"
    if any(status == "failed" for status in normalized):
        return "failed"
    if any(status in {"completed", "succeeded"} for status in normalized) or observed:
        return "completed"
    return "idle"


def _runtime_node_focus(node_id: str, agent: Mapping[str, Any] | None) -> str:
    label = str((agent or {}).get("label", "")).strip()
    if label and node_id and node_id != str((agent or {}).get("id", "")).strip():
        return f"{label} の {node_id}"
    return node_id or label


def _runtime_human_task_summary(text: str, fallback: str = "") -> str:
    value = " ".join(str(text or "").strip().split())
    if not value:
        return fallback
    lowered = value.lower()
    if lowered.startswith("research phase skill executed by "):
        return "調査タスクを実行"
    if value.startswith("{") or value.startswith("["):
        return "構造化タスクを整理中"
    if len(value) > 180:
        return f"{value[:177].rstrip()}..."
    return value


def runtime_safe_next_action(next_action: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(next_action, Mapping):
        return None
    payload = next_action.get("payload")
    payload_summary: dict[str, Any] = {}
    if isinstance(payload, Mapping):
        remediation = payload.get("remediation")
        if isinstance(remediation, Mapping):
            payload_summary["remediation"] = {
                "trigger": str(remediation.get("trigger", "")).strip() or None,
                "attempt": int(remediation.get("attempt", 0) or 0),
                "maxAttempts": int(remediation.get("maxAttempts", 0) or 0),
                "retryNodeIds": [
                    str(item).strip()
                    for item in remediation.get("retryNodeIds", [])
                    if str(item).strip()
                ][:6],
                "blockingSummary": [
                    str(item).strip()
                    for item in remediation.get("blockingSummary", [])
                    if str(item).strip()
                ][:4],
            }
        blocking_issues = [
            str(item).strip()
            for item in payload.get("blockingIssues", [])
            if str(item).strip()
        ]
        if blocking_issues:
            payload_summary["blockingIssues"] = blocking_issues[:4]
    return {
        "type": str(next_action.get("type", "")),
        "phase": next_action.get("phase"),
        "title": str(next_action.get("title", "")),
        "reason": str(next_action.get("reason", "")),
        "canAutorun": bool(next_action.get("canAutorun")),
        "requiresTrigger": bool(next_action.get("requiresTrigger")),
        "orchestrationMode": next_action.get("orchestrationMode"),
        "payload": payload_summary,
    }


def runtime_active_phase(project: Mapping[str, Any], requested_phase: str) -> str:
    for entry in project.get("phaseStatuses", []):
        if (
            isinstance(entry, Mapping)
            and str(entry.get("phase", "")).strip() in LIFECYCLE_RUNTIME_EXECUTABLE_PHASES
            and str(entry.get("status", "")).strip() == "in_progress"
        ):
            return str(entry.get("phase", "")).strip()
    next_action = project.get("nextAction")
    if (
        isinstance(next_action, Mapping)
        and bool(next_action.get("canAutorun"))
        and str(next_action.get("phase", "")).strip() in LIFECYCLE_RUNTIME_EXECUTABLE_PHASES
    ):
        return str(next_action.get("phase", "")).strip()
    return requested_phase


def _phase_runtime_agents(
    project: Mapping[str, Any],
    phase: str,
    latest_run: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    team_index = _phase_team_index(project, phase)
    team = list(team_index.values())
    if not team_index:
        return []
    run_id = str(latest_run.get("id", "")) if isinstance(latest_run, Mapping) else ""
    phase_status = "available"
    for entry in project.get("phaseStatuses", []):
        if isinstance(entry, Mapping) and entry.get("phase") == phase:
            phase_status = str(entry.get("status", phase_status))
            break
    node_status = _run_node_status_map(latest_run)
    event_log = _run_event_log(latest_run)
    latest_event_by_agent: dict[str, dict[str, Any]] = {}
    latest_event_by_node: dict[str, dict[str, Any]] = {}
    node_status_by_agent: dict[str, list[str]] = {}
    for event in event_log:
        node_id = str(event.get("node_id", "")).strip()
        agent_id = _resolve_runtime_agent_id(
            project,
            phase,
            node_id=node_id,
            agent_hint=str(event.get("agent", "")),
        )
        if node_id:
            latest_event_by_node[node_id] = event
        if agent_id in team_index:
            latest_event_by_agent[agent_id] = event
    for node_id, status in node_status.items():
        agent_id = _resolve_runtime_agent_id(
            project,
            phase,
            node_id=str(node_id),
            agent_hint=str(latest_event_by_node.get(str(node_id), {}).get("agent", "")),
        )
        if agent_id in team_index:
            node_status_by_agent.setdefault(agent_id, []).append(str(status))
    skill_records = _phase_records_for_run(project.get("skillInvocations"), phase=phase, run_id=run_id)
    delegation_records = _phase_records_for_run(project.get("delegations"), phase=phase, run_id=run_id)
    artifact_records = _phase_records_for_run(project.get("artifacts"), phase=phase, run_id=run_id)
    latest_skill_by_agent = _latest_record_by_agent(skill_records)
    latest_delegation_by_agent = _latest_record_by_agent(delegation_records)
    latest_artifact_by_agent = _latest_record_by_agent(artifact_records, agent_key="producer")
    status_priority = {"running": 0, "failed": 1, "completed": 2, "idle": 3}
    agents: list[dict[str, Any]] = []
    for agent in team:
        agent_id = str(agent.get("id", "")).strip()
        if not agent_id:
            continue
        status = _runtime_agent_status_from_nodes(
            node_status_by_agent.get(agent_id, []),
            observed=(
                agent_id in latest_event_by_agent
                or (
                    phase_status == "completed"
                    and (agent_id in latest_skill_by_agent or agent_id in latest_artifact_by_agent)
                )
            ),
        )
        latest_delegation = latest_delegation_by_agent.get(agent_id)
        latest_skill = latest_skill_by_agent.get(agent_id)
        latest_artifact = latest_artifact_by_agent.get(agent_id)
        current_task = str(agent.get("role", "")).strip() or f"{str(agent.get('label', agent_id))} task"
        if isinstance(latest_skill, Mapping):
            summary = str(latest_skill.get("summary", "")).strip()
            if summary:
                current_task = _runtime_human_task_summary(summary, current_task)
        if isinstance(latest_delegation, Mapping):
            current_task = _delegation_focus(latest_delegation)
        if status == "running" and not isinstance(latest_delegation, Mapping) and not isinstance(latest_skill, Mapping):
            event = latest_event_by_agent.get(agent_id) or {}
            node_id = str(event.get("node_id", "")).strip()
            current_focus = _runtime_node_focus(node_id, agent)
            if current_focus:
                current_task = f"{current_focus} を実行中"
        current_task = _runtime_human_task_summary(current_task, str(agent.get("role", "")).strip())
        agents.append(
            {
                "agentId": agent_id,
                "label": str(agent.get("label", agent_id)),
                "role": str(agent.get("role", "")).strip(),
                "status": status,
                "currentTask": current_task,
                "delegatedTo": (
                    str(latest_delegation.get("peer", "")).strip()
                    if isinstance(latest_delegation, Mapping) and str(latest_delegation.get("peer", "")).strip()
                    else None
                ),
                "lastArtifactTitle": (
                    str(latest_artifact.get("title", "")).strip()
                    if isinstance(latest_artifact, Mapping) and str(latest_artifact.get("title", "")).strip()
                    else None
                ),
            }
        )
    agents.sort(key=lambda item: (status_priority.get(str(item.get("status", "idle")), 9), str(item.get("label", ""))))
    return agents


def _phase_runtime_recent_actions(
    project: Mapping[str, Any],
    phase: str,
    latest_run: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    event_log = _run_event_log(latest_run)
    team_index = _phase_team_index(project, phase)
    agents = {str(item.get("agentId", "")): item for item in _phase_runtime_agents(project, phase, latest_run)}
    if not event_log:
        planned_actions: list[dict[str, Any]] = []
        status_priority = {"running": 0, "failed": 1, "completed": 2, "idle": 3}
        for agent in agents.values():
            agent_id = str(agent.get("agentId", "")).strip()
            if not agent_id:
                continue
            summary = str(agent.get("currentTask", "")).strip()
            if not summary:
                continue
            planned_actions.append(
                {
                    "nodeId": agent_id,
                    "label": str(agent.get("label", "")).strip() or agent_id,
                    "status": str(agent.get("status", "idle") or "idle"),
                    "summary": summary,
                    "agent": agent_id,
                    "agentLabel": str(agent.get("label", "")).strip() or None,
                    "nodeLabel": _runtime_node_focus(agent_id, team_index.get(agent_id)),
                }
            )
        planned_actions.sort(
            key=lambda item: (
                status_priority.get(str(item.get("status", "idle")), 9),
                str(item.get("label", "")),
            )
        )
        return planned_actions[:5]
    node_status = _run_node_status_map(latest_run)
    recent_actions: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for event in reversed(event_log):
        node_id = str(event.get("node_id", "")).strip()
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        agent_id = _resolve_runtime_agent_id(
            project,
            phase,
            node_id=node_id,
            agent_hint=str(event.get("agent", "")),
        )
        agent = agents.get(agent_id, {})
        label = (
            str(agent.get("label", "")).strip()
            or str(team_index.get(agent_id, {}).get("label", "")).strip()
            or node_id
        )
        summary = _runtime_human_task_summary(
            str(agent.get("currentTask", "")).strip() or str(event.get("agent", "")).strip() or node_id,
            node_id,
        )
        recent_actions.append(
            {
                "nodeId": node_id,
                "label": label,
                "status": str(node_status.get(node_id, "completed") or "completed"),
                "summary": summary,
                "agent": str(agent_id).strip() or None,
                "agentLabel": str(agent.get("label", "")).strip() or None,
                "nodeLabel": _runtime_node_focus(node_id, team_index.get(agent_id)),
            }
        )
        if len(recent_actions) == 5:
            break
    return recent_actions


def lifecycle_phase_runtime_summary(
    project: Mapping[str, Any],
    phase: str,
    *,
    latest_run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    phase_status = "available"
    for entry in project.get("phaseStatuses", []):
        if isinstance(entry, Mapping) and entry.get("phase") == phase:
            phase_status = str(entry.get("status", phase_status))
            break
    summary: dict[str, Any] = {
        "phase": phase,
        "status": phase_status,
        "blockingSummary": [],
        "canAutorun": bool((project.get("nextAction") or {}).get("canAutorun")),
    }
    next_action = project.get("nextAction")
    if isinstance(next_action, Mapping) and next_action.get("phase") == phase:
        objective = next_action.get("title") or next_action.get("reason")
        if isinstance(objective, str) and objective.strip():
            summary["objective"] = objective.strip()
        reason = str(next_action.get("reason", "")).strip()
        if reason:
            summary["nextAutomaticAction"] = reason
    summary["agents"] = _phase_runtime_agents(project, phase, latest_run)
    summary["recentActions"] = _phase_runtime_recent_actions(project, phase, latest_run)
    if phase != "research":
        return summary
    research = project.get("research")
    if not isinstance(research, Mapping):
        return summary
    readiness = research.get("readiness")
    if isinstance(readiness, str) and readiness:
        summary["readiness"] = readiness
    quality_gates = research.get("quality_gates")
    if isinstance(quality_gates, list):
        failed_gates = [gate for gate in quality_gates if isinstance(gate, Mapping) and gate.get("passed") is not True]
        summary["failedGateCount"] = len(failed_gates)
        if not summary["blockingSummary"]:
            summary["blockingSummary"] = [
                str(gate.get("reason", "")).strip()
                for gate in failed_gates
                if str(gate.get("reason", "")).strip()
            ][:3]
    node_results = research.get("node_results")
    if isinstance(node_results, list):
        summary["degradedNodeCount"] = len([
            item
            for item in node_results
            if isinstance(item, Mapping) and str(item.get("status", "success")) != "success"
        ])
    autonomous_remediation = research.get("autonomous_remediation")
    if isinstance(autonomous_remediation, Mapping):
        if isinstance(autonomous_remediation.get("objective"), str) and autonomous_remediation.get("objective", "").strip():
            summary["objective"] = str(autonomous_remediation["objective"]).strip()
        if isinstance(autonomous_remediation.get("attemptCount"), int):
            summary["attemptCount"] = int(autonomous_remediation["attemptCount"])
        if isinstance(autonomous_remediation.get("maxAttempts"), int):
            summary["maxAttempts"] = int(autonomous_remediation["maxAttempts"])
        if not summary["blockingSummary"]:
            summary["blockingSummary"] = [
                str(item).strip()
                for item in autonomous_remediation.get("blockingSummary", [])
                if str(item).strip()
            ][:3]
    remediation_plan = research.get("remediation_plan")
    if isinstance(remediation_plan, Mapping) and not summary.get("objective"):
        objective = str(remediation_plan.get("objective", "")).strip()
        if objective:
            summary["objective"] = objective
    return summary


def lifecycle_runtime_payload(
    project: Mapping[str, Any],
    *,
    phase: str,
    active_phase: str,
    latest_run: Mapping[str, Any] | None = None,
    observed_run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "updatedAt": project.get("updatedAt", project.get("createdAt", "")),
        "savedAt": project.get("savedAt", project.get("updatedAt", project.get("createdAt", ""))),
        "phaseStatuses": list(project.get("phaseStatuses", [])),
        "nextAction": runtime_safe_next_action(
            project.get("nextAction") if isinstance(project.get("nextAction"), Mapping) else None
        ),
        "autonomyState": (
            dict(project.get("autonomyState") or {})
            if project.get("autonomyState") is not None
            else None
        ),
        "observedPhase": phase,
        "activePhase": active_phase,
        "phaseSummary": lifecycle_phase_runtime_summary(project, phase, latest_run=observed_run),
        "activePhaseSummary": lifecycle_phase_runtime_summary(
            project,
            active_phase or phase,
            latest_run=latest_run,
        ),
    }
