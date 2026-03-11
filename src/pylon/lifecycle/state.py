"""Lifecycle state mutation helpers."""

from __future__ import annotations

from typing import Any

from pylon.lifecycle.orchestrator import PHASE_ORDER


def rebuild_lifecycle_phase_statuses(
    project_record: dict[str, Any],
    *,
    completed_until: str | None,
) -> list[dict[str, Any]]:
    existing = {
        str(item.get("phase")): dict(item)
        for item in project_record.get("phaseStatuses", [])
        if isinstance(item, dict) and item.get("phase")
    }
    completed_index = PHASE_ORDER.index(completed_until) if completed_until in PHASE_ORDER else -1
    statuses: list[dict[str, Any]] = []
    for index, phase in enumerate(PHASE_ORDER):
        entry = dict(existing.get(phase, {"phase": phase, "version": 1}))
        entry["phase"] = phase
        entry["version"] = int(entry.get("version", 1) or 1)
        if index <= completed_index:
            entry["status"] = "completed"
        elif index == completed_index + 1:
            entry["status"] = "available"
            entry.pop("completedAt", None)
        else:
            entry["status"] = "locked"
            entry.pop("completedAt", None)
        statuses.append(entry)
    return statuses


def prune_lifecycle_records_from_phase(
    project_record: dict[str, Any],
    *,
    phase: str,
) -> dict[str, list[dict[str, Any]]]:
    """Remove operator-console records for the supplied phase and everything downstream."""
    threshold = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else len(PHASE_ORDER)

    def _keep(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        record_phase = str(record.get("phase") or "")
        if record_phase not in PHASE_ORDER:
            return True
        return PHASE_ORDER.index(record_phase) < threshold

    return {
        "artifacts": [dict(item) for item in project_record.get("artifacts", []) if _keep(item)],
        "decisionLog": [dict(item) for item in project_record.get("decisionLog", []) if _keep(item)],
        "skillInvocations": [dict(item) for item in project_record.get("skillInvocations", []) if _keep(item)],
        "delegations": [dict(item) for item in project_record.get("delegations", []) if _keep(item)],
        "phaseRuns": [dict(item) for item in project_record.get("phaseRuns", []) if _keep(item)],
    }


def build_lifecycle_invalidation_patch(
    project_record: dict[str, Any],
    *,
    changed_fields: set[str],
) -> dict[str, Any]:
    """Build a deterministic downstream invalidation patch for changed upstream fields."""
    if not changed_fields:
        return {"reset_from": "", "reason": "", "patch": {}}

    patch: dict[str, Any] = {}
    reset_from = ""
    reason = ""
    if "spec" in changed_fields:
        reset_from = "research"
        reason = "Project spec changed; regenerate research and all downstream artifacts."
        patch.update(
            {
                "research": None,
                "analysis": None,
                "features": [],
                "milestones": [],
                "planEstimates": [],
                "designVariants": [],
                "selectedDesignId": None,
                "buildCode": None,
                "buildCost": 0.0,
                "buildIteration": 0,
                "milestoneResults": [],
                "deployChecks": [],
                "releases": [],
                "feedbackItems": [],
                "approvalStatus": "pending",
                "approvalComments": [],
                "approvalRequestId": None,
                "phaseStatuses": rebuild_lifecycle_phase_statuses(project_record, completed_until=None),
            }
        )
    elif "researchConfig" in changed_fields:
        reset_from = "research"
        reason = "Research execution inputs changed; regenerate research and all downstream artifacts."
        patch.update(
            {
                "research": None,
                "analysis": None,
                "features": [],
                "milestones": [],
                "planEstimates": [],
                "designVariants": [],
                "selectedDesignId": None,
                "buildCode": None,
                "buildCost": 0.0,
                "buildIteration": 0,
                "milestoneResults": [],
                "deployChecks": [],
                "releases": [],
                "feedbackItems": [],
                "approvalStatus": "pending",
                "approvalComments": [],
                "approvalRequestId": None,
                "phaseStatuses": rebuild_lifecycle_phase_statuses(project_record, completed_until=None),
            }
        )
    elif "research" in changed_fields:
        reset_from = "planning"
        reason = "Research evidence changed; planning and downstream artifacts were invalidated."
        patch.update(
            {
                "analysis": None,
                "features": [],
                "milestones": [],
                "planEstimates": [],
                "designVariants": [],
                "selectedDesignId": None,
                "buildCode": None,
                "buildCost": 0.0,
                "buildIteration": 0,
                "milestoneResults": [],
                "deployChecks": [],
                "releases": [],
                "feedbackItems": [],
                "approvalStatus": "pending",
                "approvalComments": [],
                "approvalRequestId": None,
                "phaseStatuses": rebuild_lifecycle_phase_statuses(project_record, completed_until="research"),
            }
        )
    elif changed_fields & {"analysis", "features", "milestones", "planEstimates", "selectedPreset"}:
        reset_from = "design"
        reason = "Planning inputs changed; design, approval, build, and deploy outputs were invalidated."
        patch.update(
            {
                "designVariants": [],
                "selectedDesignId": None,
                "buildCode": None,
                "buildCost": 0.0,
                "buildIteration": 0,
                "milestoneResults": [],
                "deployChecks": [],
                "releases": [],
                "feedbackItems": [],
                "approvalStatus": "pending",
                "approvalComments": [],
                "approvalRequestId": None,
                "phaseStatuses": rebuild_lifecycle_phase_statuses(project_record, completed_until="planning"),
            }
        )
    elif changed_fields & {"designVariants", "selectedDesignId"}:
        reset_from = "approval"
        reason = "Design baseline changed; approval, build, and deploy outputs were invalidated."
        patch.update(
            {
                "buildCode": None,
                "buildCost": 0.0,
                "buildIteration": 0,
                "milestoneResults": [],
                "deployChecks": [],
                "releases": [],
                "feedbackItems": [],
                "approvalStatus": "pending",
                "approvalComments": [],
                "approvalRequestId": None,
                "phaseStatuses": rebuild_lifecycle_phase_statuses(project_record, completed_until="design"),
            }
        )

    if reset_from:
        patch.update(prune_lifecycle_records_from_phase(project_record, phase=reset_from))

    return {
        "reset_from": reset_from,
        "reason": reason,
        "patch": patch,
    }
