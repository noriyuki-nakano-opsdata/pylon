"""Backend lifecycle coordination and next-action derivation."""

from __future__ import annotations

from typing import Any

from pylon.lifecycle.contracts import (
    EXECUTABLE_PHASES,
    build_phase_contracts,
    build_phase_readiness,
    lifecycle_phase_input,
)
from pylon.types import AutonomyLevel

ORCHESTRATION_MODES: tuple[str, ...] = ("workflow", "guided", "autonomous")
EXECUTABLE_ACTIONS: frozenset[str] = frozenset({"run_phase", "auto_approve", "run_deploy_checks", "create_release"})


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _has_critical_research_dissent(project_record: dict[str, Any]) -> bool:
    research = _as_dict(project_record.get("research"))
    return any(
        _as_dict(item).get("severity") == "critical"
        and _as_dict(item).get("resolved") is not True
        for item in _as_list(research.get("dissent"))
    )


def _has_critical_planning_findings(project_record: dict[str, Any]) -> bool:
    analysis = _as_dict(project_record.get("analysis"))
    return any(
        _as_dict(item).get("severity") == "critical"
        for item in _as_list(analysis.get("red_team_findings"))
    )


def _action(
    action_type: str,
    *,
    phase: str | None = None,
    title: str,
    reason: str,
    can_autorun: bool,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": action_type,
        "phase": phase,
        "title": title,
        "reason": reason,
        "canAutorun": can_autorun,
        "payload": dict(payload or {}),
    }


def resolve_lifecycle_autonomy_level(project_record: dict[str, Any]) -> AutonomyLevel:
    raw_level = str(project_record.get("autonomyLevel") or "A3").strip().upper()
    if raw_level not in {"A3", "A4"}:
        raise ValueError(
            f"Unsupported lifecycle autonomy level: {raw_level}. "
            "Expected one of ['A3', 'A4']."
        )
    return AutonomyLevel[raw_level]


def resolve_lifecycle_orchestration_mode(
    project_record: dict[str, Any],
    *,
    override: str | None = None,
) -> str:
    candidate = str(override or project_record.get("orchestrationMode") or "workflow").strip().lower()
    if candidate not in ORCHESTRATION_MODES:
        raise ValueError(
            f"Unsupported lifecycle orchestration mode: {candidate}. "
            f"Expected one of {list(ORCHESTRATION_MODES)}."
        )
    return candidate


def lifecycle_action_execution_budget(
    project_record: dict[str, Any],
    *,
    requested_steps: int,
    mode_override: str | None = None,
) -> int:
    mode = resolve_lifecycle_orchestration_mode(project_record, override=mode_override)
    if mode == "workflow":
        return 0
    if mode == "guided":
        return 1
    return max(1, requested_steps)


def _apply_orchestration_mode(
    action: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    patched = dict(action)
    executable = patched["type"] in EXECUTABLE_ACTIONS
    patched["orchestrationMode"] = mode
    patched["requiresTrigger"] = executable and mode in {"workflow", "guided"}
    patched["canAutorun"] = executable and mode == "autonomous"
    if executable and mode == "workflow":
        patched["reason"] = (
            f"{patched['reason']} Project is in workflow mode, so this step should be "
            "triggered explicitly through the phase workflow APIs."
        )
    elif executable and mode == "guided":
        patched["reason"] = (
            f"{patched['reason']} Guided mode allows this step to run only when "
            "the operator explicitly calls the lifecycle advance endpoint."
        )
    return patched


def build_lifecycle_approval_binding(project_record: dict[str, Any]) -> dict[str, Any]:
    """Build approval-bound plan/effect payloads for the development gate."""
    contracts = build_phase_contracts(project_record)
    development_input = lifecycle_phase_input(project_record, "development")
    autonomy_level = resolve_lifecycle_autonomy_level(project_record)
    selected_features = [
        item.get("feature")
        for item in _as_list(project_record.get("features"))
        if isinstance(item, dict) and item.get("selected", True)
    ]
    plan = {
        "project_id": project_record.get("projectId", project_record.get("id")),
        "spec": project_record.get("spec"),
        "orchestration_mode": project_record.get("orchestrationMode", "workflow"),
        "autonomy_level": autonomy_level.name,
        "selected_preset": project_record.get("selectedPreset"),
        "selected_design_id": project_record.get("selectedDesignId"),
        "selected_features": selected_features,
        "research_contract": contracts.get("research"),
        "planning_contract": contracts.get("planning"),
        "design_contract": contracts.get("design"),
    }
    effect_envelope = {
        "action": "run_phase",
        "phase": "development",
        "input": development_input,
        "target_quality_gate": "deploy_checks",
    }
    context = {
        "kind": "lifecycle_phase_gate",
        "phase": "approval",
        "target_phase": "development",
        "project_id": project_record.get("projectId", project_record.get("id")),
        "orchestration_mode": project_record.get("orchestrationMode", "workflow"),
        "autonomy_level": autonomy_level.name,
        "reason": (
            "Development phase changes require approval before autonomous execution continues."
            if autonomy_level < AutonomyLevel.A4
            else "Development phase changes are auto-approved under the A4 full-autonomy policy."
        ),
        "binding_plan": plan,
        "binding_effect_envelope": effect_envelope,
    }
    return {
        "action": "advance_to_development",
        "plan": plan,
        "effect_envelope": effect_envelope,
        "context": context,
    }


def _derive_candidate_action(project_record: dict[str, Any]) -> dict[str, Any]:
    """Determine the next backend action for a lifecycle project."""
    spec = str(project_record.get("spec", "") or "").strip()
    contracts = build_phase_contracts(project_record)
    readiness = build_phase_readiness(project_record)
    approval_status = str(project_record.get("approvalStatus", "pending") or "pending")
    releases = _as_list(project_record.get("releases"))
    deploy_checks = _as_list(project_record.get("deployChecks"))
    feedbacks = _as_list(project_record.get("feedbackItems"))

    if not spec:
        return _action(
            "collect_input",
            phase="research",
            title="Project spec is required",
            reason="Lifecycle autonomy cannot start until the project spec is defined.",
            can_autorun=False,
        )

    research_contract = contracts.get("research")
    if research_contract is None:
        return _action(
            "run_phase",
            phase="research",
            title="Run research swarm",
            reason="Research evidence must be generated before downstream planning can begin.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "research")},
        )
    if not research_contract["ready"]:
        return _action(
            "review_phase",
            phase="research",
            title="Research needs rework",
            reason="Research is missing evidence needed for planning handoff.",
            can_autorun=False,
            payload={"blockingIssues": readiness["research"]["blockingIssues"]},
        )

    planning_contract = contracts.get("planning")
    if planning_contract is None:
        return _action(
            "run_phase",
            phase="planning",
            title="Run planning council",
            reason="Planning can now turn research into scope, milestones, and IA.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "planning")},
        )
    if not planning_contract["ready"]:
        return _action(
            "review_phase",
            phase="planning",
            title="Planning needs rework",
            reason="Planning outputs are not yet sufficient for design and approval.",
            can_autorun=False,
            payload={"blockingIssues": readiness["planning"]["blockingIssues"]},
        )

    design_contract = contracts.get("design")
    if design_contract is None:
        return _action(
            "run_phase",
            phase="design",
            title="Run design jury",
            reason="Design variants and a baseline are required before approval.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "design")},
        )
    if not design_contract["ready"]:
        return _action(
            "review_phase",
            phase="design",
            title="Design needs review",
            reason="A build baseline is not yet ready to pass through approval.",
            can_autorun=False,
            payload={"blockingIssues": readiness["design"]["blockingIssues"]},
        )

    if _has_critical_research_dissent(project_record):
        return _action(
            "review_phase",
            phase="research",
            title="Research has unresolved critical dissent",
            reason="Critical research dissent must be resolved before approval or autonomous execution can continue.",
            can_autorun=False,
            payload={"blockingIssues": readiness["research"]["blockingIssues"]},
        )

    if _has_critical_planning_findings(project_record):
        return _action(
            "review_phase",
            phase="planning",
            title="Planning has critical red-team findings",
            reason="Critical planning findings must be addressed before approval or development can continue.",
            can_autorun=False,
            payload={"blockingIssues": readiness["planning"]["blockingIssues"]},
        )

    if approval_status in {"rejected", "revision_requested"}:
        return _action(
            "review_phase",
            phase="approval",
            title="Approval requested rework",
            reason="Approval was denied or sent back for revision, so the lifecycle must be updated before a new approval request is created.",
            can_autorun=False,
            payload={
                "approvalStatus": approval_status,
                "approvalRequestId": project_record.get("approvalRequestId"),
            },
        )

    if approval_status != "approved":
        autonomy_level = resolve_lifecycle_autonomy_level(project_record)
        if autonomy_level >= AutonomyLevel.A4:
            return _action(
                "auto_approve",
                phase="approval",
                title="Auto-approve lifecycle plan",
                reason="Project is configured for A4 full autonomy, so the approval gate will be recorded and auto-approved before development continues.",
                can_autorun=True,
                payload={
                    "approvalStatus": approval_status,
                    "approvalRequestId": project_record.get("approvalRequestId"),
                    "autonomyLevel": autonomy_level.name,
                },
            )
        return _action(
            "request_approval",
            phase="approval",
            title="Approval gate is blocking development",
            reason="Development is approval-gated and must not auto-run until approval is granted.",
            can_autorun=False,
            payload={
                "approvalStatus": approval_status,
                "approvalRequestId": project_record.get("approvalRequestId"),
            },
        )

    development_contract = contracts.get("development")
    if development_contract is None:
        return _action(
            "run_phase",
            phase="development",
            title="Run development mesh",
            reason="Approved planning and design context is ready for implementation.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "development")},
        )
    if not development_contract["ready"]:
        return _action(
            "review_phase",
            phase="development",
            title="Development needs rework",
            reason="Build output does not yet satisfy deployment gates.",
            can_autorun=False,
            payload={"blockingIssues": readiness["development"]["blockingIssues"]},
        )

    deploy_contract = contracts.get("deploy")
    if not deploy_checks:
        return _action(
            "run_deploy_checks",
            phase="deploy",
            title="Run deploy checks",
            reason="Deployment gates must be evaluated after a successful build.",
            can_autorun=True,
        )
    if deploy_contract is not None and not deploy_contract["qualityGates"][0]["passed"]:
        return _action(
            "review_phase",
            phase="deploy",
            title="Deploy is blocked",
            reason="Release blockers remain in deploy checks.",
            can_autorun=False,
            payload={"blockingIssues": readiness["deploy"]["blockingIssues"]},
        )
    if not releases:
        return _action(
            "create_release",
            phase="deploy",
            title="Create release record",
            reason="Deploy checks have passed and a release record can be created.",
            can_autorun=True,
        )
    if not feedbacks:
        return _action(
            "collect_feedback",
            phase="iterate",
            title="Collect iteration feedback",
            reason="The release exists, but no iteration feedback has been captured yet.",
            can_autorun=False,
        )

    return _action(
        "done",
        phase="iterate",
        title="Lifecycle loop is in iteration mode",
        reason="A release and feedback loop already exist; continue iterating within the backlog.",
        can_autorun=False,
    )


def derive_lifecycle_next_action(
    project_record: dict[str, Any],
    *,
    mode_override: str | None = None,
) -> dict[str, Any]:
    mode = resolve_lifecycle_orchestration_mode(project_record, override=mode_override)
    candidate = _derive_candidate_action(project_record)
    return _apply_orchestration_mode(candidate, mode=mode)


def build_lifecycle_autonomy_projection(project_record: dict[str, Any]) -> dict[str, Any]:
    """Project lifecycle state into an autonomy-oriented control view."""
    mode = resolve_lifecycle_orchestration_mode(project_record)
    contracts = build_phase_contracts(project_record)
    readiness = build_phase_readiness(project_record)
    next_action = derive_lifecycle_next_action(project_record, mode_override=mode)
    executable = [
        phase
        for phase in EXECUTABLE_PHASES
        if readiness[phase]["ready"]
    ]
    blocked = {
        phase: details["blockingIssues"]
        for phase, details in readiness.items()
        if details["blockingIssues"]
    }
    return {
        "contracts": contracts,
        "phaseReadiness": readiness,
        "nextAction": next_action,
        "orchestrationMode": mode,
        "completedExecutablePhases": executable,
        "blockedPhases": blocked,
        "approvalRequired": next_action["type"] == "request_approval",
        "canAdvanceAutonomously": next_action["canAutorun"],
    }
