"""Backend lifecycle coordination and next-action derivation."""

from __future__ import annotations

from typing import Any

from pylon.lifecycle.contracts import (
    EXECUTABLE_PHASES,
    build_phase_contracts,
    build_phase_readiness,
    lifecycle_phase_input,
    research_autonomous_remediation_context,
    research_operator_guidance_context,
)
from pylon.lifecycle.services.decision_context import build_lifecycle_decision_context
from pylon.lifecycle.services.native_artifacts import (
    normalize_dcs_analysis,
    normalize_requirements_bundle,
    normalize_reverse_engineering_result,
    normalize_task_decomposition,
    normalize_technical_design_bundle,
)
from pylon.types import AutonomyLevel

ORCHESTRATION_MODES: tuple[str, ...] = ("workflow", "guided", "autonomous")
GOVERNANCE_MODES: tuple[str, ...] = ("governed", "complete_autonomy")
EXECUTABLE_ACTIONS: frozenset[str] = frozenset({"run_phase", "auto_approve", "run_deploy_checks", "create_release"})


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _phase_status(project_record: dict[str, Any], phase: str) -> str:
    for item in _as_list(project_record.get("phaseStatuses")):
        payload = _as_dict(item)
        if str(payload.get("phase") or "") == phase:
            return str(payload.get("status") or "")
    return ""


def _phase_ready_or_completed(
    project_record: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
    phase: str,
) -> bool:
    contract = _as_dict(contracts.get(phase))
    if contract.get("ready") is True:
        return True
    return _phase_status(project_record, phase) == "completed"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _approval_binding_selected_feature_name(item: dict[str, Any]) -> str:
    return _normalize_text(item.get("feature") or item.get("name") or item.get("title"))


def _approval_binding_selected_features(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for item in _as_list(project_record.get("features")):
        record = _as_dict(item)
        name = _approval_binding_selected_feature_name(record)
        if not name or record.get("selected") is False:
            continue
        features.append(
            {
                "name": name,
                "priority": _normalize_text(record.get("priority")) or None,
                "category": _normalize_text(record.get("category")) or None,
            }
        )
    return features


def _approval_binding_milestones(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    milestones: list[dict[str, Any]] = []
    for item in _as_list(project_record.get("milestones")):
        record = _as_dict(item)
        milestone_id = _normalize_text(record.get("id"))
        name = _normalize_text(record.get("name") or record.get("title"))
        phase = _normalize_text(record.get("phase"))
        criteria = _normalize_text(record.get("criteria"))
        if not any((milestone_id, name, phase, criteria)):
            continue
        milestones.append(
            {
                "id": milestone_id or None,
                "name": name or None,
                "phase": phase or None,
                "criteria": criteria or None,
            }
        )
    return milestones


def _approval_binding_plan_estimate(project_record: dict[str, Any]) -> dict[str, Any]:
    selected_preset = _normalize_text(project_record.get("selectedPreset")) or "standard"
    estimates = [_as_dict(item) for item in _as_list(project_record.get("planEstimates")) if _as_dict(item)]
    selected_estimate = next(
        (
            item
            for item in estimates
            if _normalize_text(item.get("preset")) == selected_preset
        ),
        estimates[0] if estimates else {},
    )
    if not selected_estimate:
        return {"preset": selected_preset}
    epics = [
        {
            "id": _normalize_text(item.get("id")) or None,
            "title": _normalize_text(item.get("title") or item.get("name")) or None,
        }
        for item in _as_list(selected_estimate.get("epics"))
        if _as_dict(item) and (
            _normalize_text(_as_dict(item).get("id"))
            or _normalize_text(_as_dict(item).get("title") or _as_dict(item).get("name"))
        )
    ][:8]
    work_packages = [
        {
            "id": _normalize_text(item.get("id")) or None,
            "title": _normalize_text(item.get("title") or item.get("name")) or None,
            "lane": _normalize_text(item.get("lane")) or None,
            "depends_on": [
                _normalize_text(dep)
                for dep in _as_list(item.get("depends_on"))
                if _normalize_text(dep)
            ][:6],
        }
        for item in _as_list(selected_estimate.get("wbs"))
        if _as_dict(item) and (
            _normalize_text(_as_dict(item).get("id"))
            or _normalize_text(_as_dict(item).get("title") or _as_dict(item).get("name"))
        )
    ][:12]
    return {
        "preset": _normalize_text(selected_estimate.get("preset")) or selected_preset,
        "duration_weeks": int(selected_estimate.get("duration_weeks", 0) or 0),
        "epic_count": len(_as_list(selected_estimate.get("epics"))),
        "work_package_count": len(_as_list(selected_estimate.get("wbs"))),
        "epics": epics,
        "work_packages": work_packages,
    }


def _approval_binding_selected_design(project_record: dict[str, Any]) -> dict[str, Any]:
    selected_design_id = _normalize_text(project_record.get("selectedDesignId"))
    variants = [_as_dict(item) for item in _as_list(project_record.get("designVariants")) if _as_dict(item)]
    selected = next(
        (
            item
            for item in variants
            if selected_design_id and _normalize_text(item.get("id")) == selected_design_id
        ),
        variants[0] if variants else {},
    )
    if not selected:
        return {}
    prototype = _as_dict(selected.get("prototype"))
    implementation_brief = _as_dict(selected.get("implementation_brief"))
    prototype_spec = _as_dict(selected.get("prototype_spec"))
    prototype_app = _as_dict(selected.get("prototype_app"))
    screens = [
        {
            "id": _normalize_text(item.get("id")) or None,
            "title": _normalize_text(item.get("title")) or None,
            "purpose": _normalize_text(item.get("purpose")) or None,
        }
        for item in _as_list(prototype.get("screens"))
        if _as_dict(item)
    ][:8]
    flows = [
        {
            "id": _normalize_text(item.get("id")) or None,
            "title": _normalize_text(item.get("title") or item.get("name")) or None,
            "step_count": len(_as_list(item.get("steps"))),
            "outcome": _normalize_text(item.get("outcome") or item.get("success_state")) or None,
        }
        for item in _as_list(prototype.get("flows"))
        if _as_dict(item)
    ][:6]
    delivery_slices = [
        {
            "slice": _normalize_text(item.get("slice")) or None,
            "title": _normalize_text(item.get("title")) or None,
            "milestone": _normalize_text(item.get("milestone")) or None,
        }
        for item in _as_list(implementation_brief.get("delivery_slices"))
        if _as_dict(item)
    ][:8]
    primary_workflows = [
        {
            "id": _normalize_text(item.get("id")) or None,
            "title": _normalize_text(item.get("title") or item.get("name")) or None,
            "outcome": _normalize_text(item.get("outcome")) or None,
        }
        for item in _as_list(selected.get("primary_workflows"))
        if _as_dict(item)
    ][:6]
    app_shell = _as_dict(prototype.get("app_shell"))
    return {
        "id": _normalize_text(selected.get("id")) or selected_design_id,
        "model": _normalize_text(selected.get("model")) or None,
        "pattern_name": _normalize_text(selected.get("pattern_name")) or None,
        "description": _normalize_text(selected.get("description")) or None,
        "prototype_kind": _normalize_text(prototype.get("kind")) or None,
        "screen_count": len(_as_list(prototype.get("screens"))),
        "flow_count": len(_as_list(prototype.get("flows"))),
        "navigation_items": [
            _normalize_text(item.get("label") or item.get("name") or item.get("title"))
            for item in _as_list(app_shell.get("primary_navigation"))
            if _as_dict(item)
            and _normalize_text(_as_dict(item).get("label") or _as_dict(item).get("name") or _as_dict(item).get("title"))
        ][:8],
        "screens": screens,
        "flows": flows,
        "primary_workflows": primary_workflows,
        "delivery_slices": delivery_slices,
        "framework_target": _normalize_text(prototype_spec.get("framework_target")) or None,
        "route_paths": [
            _normalize_text(item.get("path"))
            for item in _as_list(prototype_spec.get("routes"))
            if _as_dict(item) and _normalize_text(_as_dict(item).get("path"))
        ][:8],
        "app_framework": _normalize_text(prototype_app.get("framework")) or None,
        "decision_context_fingerprint": _normalize_text(selected.get("decision_context_fingerprint")) or None,
    }


def _approval_binding_development_input(project_record: dict[str, Any]) -> dict[str, Any]:
    decision_context = build_lifecycle_decision_context(project_record, target_language="en", compact=True)
    decision_graph = _as_dict(decision_context.get("decision_graph"))
    return {
        "spec": str(project_record.get("spec", "") or ""),
        "selected_features": _approval_binding_selected_features(project_record),
        "milestones": _approval_binding_milestones(project_record),
        "selectedPreset": _normalize_text(project_record.get("selectedPreset")) or "standard",
        "planEstimate": _approval_binding_plan_estimate(project_record),
        "selectedDesignId": _normalize_text(project_record.get("selectedDesignId")) or None,
        "selected_design": _approval_binding_selected_design(project_record),
        "requirements": normalize_requirements_bundle(project_record.get("requirements")),
        "requirementsConfig": _as_dict(project_record.get("requirementsConfig")),
        "reverseEngineering": normalize_reverse_engineering_result(project_record.get("reverseEngineering")),
        "taskDecomposition": normalize_task_decomposition(project_record.get("taskDecomposition")),
        "dcsAnalysis": normalize_dcs_analysis(project_record.get("dcsAnalysis")),
        "technicalDesign": normalize_technical_design_bundle(project_record.get("technicalDesign")),
        "githubRepo": _normalize_text(project_record.get("githubRepo")) or None,
        "decision_context": {
            "fingerprint": str(decision_context.get("fingerprint") or ""),
            "project_frame": _as_dict(decision_context.get("project_frame")),
            "decision_graph": {
                "stats": _as_dict(decision_graph.get("stats")),
                "critical_paths": _as_list(decision_graph.get("critical_paths")),
                "open_links": _as_list(decision_graph.get("open_links")),
            },
        },
    }


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


def _research_operator_decision(project_record: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(project_record.get("researchOperatorDecision"))


def _approval_binding_contract_snapshot(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = _as_dict(contract)
    if not payload:
        return None
    return {
        "phase": payload.get("phase"),
        "contractType": payload.get("contractType"),
        "contractVersion": payload.get("contractVersion"),
        "summary": payload.get("summary"),
        "outputs": payload.get("outputs"),
        "qualityGates": [
            {
                "id": _as_dict(item).get("id"),
                "passed": _as_dict(item).get("passed"),
                "detail": _as_dict(item).get("detail"),
            }
            for item in _as_list(payload.get("qualityGates"))
            if _as_dict(item)
        ],
        "handoffTargets": _as_list(payload.get("handoffTargets")),
    }


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


def _is_self_healing_research_recovery(action: dict[str, Any]) -> bool:
    payload = _as_dict(action.get("payload"))
    remediation = _as_dict(payload.get("remediation"))
    return (
        action.get("type") == "run_phase"
        and action.get("phase") == "research"
        and str(remediation.get("trigger", "")) == "quality_gate_recovery"
    )


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


def resolve_lifecycle_governance_mode(
    project_record: dict[str, Any],
    *,
    override: str | None = None,
) -> str:
    candidate = str(override or project_record.get("governanceMode") or "governed").strip().lower()
    if candidate not in GOVERNANCE_MODES:
        raise ValueError(
            f"Unsupported lifecycle governance mode: {candidate}. "
            f"Expected one of {list(GOVERNANCE_MODES)}."
        )
    return candidate


def lifecycle_action_execution_budget(
    project_record: dict[str, Any],
    *,
    requested_steps: int,
    mode_override: str | None = None,
) -> int:
    mode = resolve_lifecycle_orchestration_mode(project_record, override=mode_override)
    candidate = _derive_candidate_action(project_record)
    if _is_self_healing_research_recovery(candidate):
        return 1 if requested_steps > 0 else 0
    if mode == "workflow":
        return 0
    if mode == "guided":
        return 1
    return max(1, requested_steps)


def _apply_orchestration_mode(
    action: dict[str, Any],
    *,
    mode: str,
    governance_mode: str,
) -> dict[str, Any]:
    patched = dict(action)
    executable = patched["type"] in EXECUTABLE_ACTIONS
    self_healing = _is_self_healing_research_recovery(patched)
    patched["orchestrationMode"] = mode
    patched["governanceMode"] = governance_mode
    patched["requiresHumanDecision"] = patched["type"] in {
        "request_approval",
        "request_release_decision",
        "request_iteration_triage",
        "review_phase",
    }
    patched["requiresTrigger"] = executable and mode in {"workflow", "guided"} and not self_healing
    patched["canAutorun"] = executable and (mode == "autonomous" or self_healing)
    if executable and mode == "workflow" and not self_healing:
        patched["reason"] = (
            f"{patched['reason']} workflow モードのため、このステップは "
            "phase workflow API から明示的に起動してください。"
        )
    elif executable and mode == "guided" and not self_healing:
        patched["reason"] = (
            f"{patched['reason']} guided モードのため、このステップは "
            "operator が lifecycle advance endpoint を明示的に呼んだときだけ実行されます。"
        )
    elif self_healing:
        patched["reason"] = (
            f"{patched['reason']} research の自動回復は継続し、"
            "ブロックされたフェーズでユーザーが足止めされないようにします。"
        )
    return patched


def _phase_review_decisions(phase: str) -> list[str]:
    decisions: dict[str, list[str]] = {
        "research": ["clarify_scope", "rerun_research", "conditional_handoff"],
        "planning": ["request_rework", "accept_scope", "trim_scope"],
        "design": ["request_rework", "select_baseline", "accept_design_risk"],
        "approval": ["approve", "request_changes", "reject"],
        "development": ["request_rework", "retry_wave", "accept_delivery_risk"],
        "deploy": ["hold_release", "request_fix", "approve_release"],
        "iterate": ["prioritize_feedback", "defer_iteration", "request_more_signal"],
    }
    return decisions.get(phase, ["request_rework", "continue"])


def _phase_governance_policy(phase: str, *, governance_mode: str) -> dict[str, Any]:
    governed = governance_mode == "governed"
    shared = {
        "phase": phase,
        "allowHumanEdits": True,
        "allowHumanOverride": True,
        "allowReentry": True,
        "continuousDeliveryMode": (
            "human_governed_continuous_delivery"
            if governed
            else "autonomous_continuous_delivery_with_human_override"
        ),
    }
    if phase == "research":
        return {
            **shared,
            "executionPolicy": "auto_with_human_override",
            "humanDecisionGates": [],
            "optionalHumanDecisions": ["reframe_problem", "stop_research", "conditional_handoff"],
            "humanReviewTriggers": ["critical_dissent", "confidence_shortfall", "operator_requested_review"],
            "summary": "調査は自律継続しつつ、人は問いの切り直しや条件付き handoff を判断できます。",
        }
    if phase == "planning":
        return {
            **shared,
            "executionPolicy": "auto_with_human_override",
            "humanDecisionGates": [],
            "optionalHumanDecisions": ["trim_scope", "resequence_milestones", "accept_scope_risk"],
            "humanReviewTriggers": ["planning_quality_gap", "critical_red_team_finding"],
            "summary": "企画案は自律生成し、人はスコープや優先度の再調整をいつでも差し込めます。",
        }
    if phase == "design":
        return {
            **shared,
            "executionPolicy": "auto_with_human_override",
            "humanDecisionGates": [],
            "optionalHumanDecisions": ["select_baseline", "request_variant_merge", "accept_design_tradeoff"],
            "humanReviewTriggers": ["design_quality_gap", "baseline_not_selected"],
            "summary": "デザインは自律評価しつつ、人は baseline 選定や差し戻しを明示的に行えます。",
        }
    if phase == "approval":
        return {
            **shared,
            "executionPolicy": "human_required" if governed else "auto_with_human_override",
            "humanDecisionGates": ["approve_scope_package", "request_changes", "reject_package"] if governed else [],
            "optionalHumanDecisions": [] if governed else ["override_auto_approval", "request_changes"],
            "humanReviewTriggers": ["approval_denied", "approval_revision_requested"],
            "summary": (
                "承認は人が開発開始を確定します。"
                if governed
                else "完全自律では承認を自動記録しつつ、人はいつでも差し戻せます。"
            ),
        }
    if phase == "development":
        return {
            **shared,
            "executionPolicy": "autonomous_work_unit_loops",
            "humanDecisionGates": [],
            "optionalHumanDecisions": ["edit_scope", "override_retry_scope", "request_manual_fix"],
            "humanReviewTriggers": ["non_retryable_quality_block", "security_block", "stale_topology_override"],
            "summary": "開発は WU / wave 単位で自律進行し、非局所的な詰まりだけを人に上げます。",
        }
    if phase == "deploy":
        return {
            **shared,
            "executionPolicy": "human_required" if governed else "auto_release_candidate_with_optional_hold",
            "humanDecisionGates": ["approve_release", "hold_release", "request_fix"] if governed else [],
            "optionalHumanDecisions": [] if governed else ["hold_release", "request_fix"],
            "humanReviewTriggers": ["deploy_blockers", "release_hold_requested"],
            "summary": (
                "公開判断は人が最終責任を持ちます。"
                if governed
                else "完全自律では release record を自動作成しつつ、人は hold を掛けられます。"
            ),
        }
    return {
        **shared,
        "executionPolicy": (
            "auto_synthesis_with_human_prioritization"
            if governed
            else "continuous_autonomous_iteration"
        ),
        "humanDecisionGates": ["prioritize_feedback", "commit_iteration_scope"] if governed else [],
        "optionalHumanDecisions": [] if governed else ["reprioritize_backlog", "pause_iteration"],
        "humanReviewTriggers": ["high_impact_feedback", "release_regression_signal"],
        "summary": (
            "改善は人が backlog の優先順位を確定します。"
            if governed
            else "改善は継続的に自律合成し、人のフィードバックはいつでも上書きできます。"
        ),
    }


def _build_phase_governance_policies(governance_mode: str) -> dict[str, dict[str, Any]]:
    return {
        phase: _phase_governance_policy(phase, governance_mode=governance_mode)
        for phase in ("research", "planning", "design", "approval", "development", "deploy", "iterate")
    }


def _required_human_decisions(
    next_action: dict[str, Any],
    *,
    phase_policies: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    phase = str(next_action.get("phase") or "").strip()
    if not phase:
        return []
    policy = _as_dict(phase_policies.get(phase))
    payload = _as_dict(next_action.get("payload"))
    if next_action.get("type") == "request_approval":
        return [
            {
                "phase": phase,
                "decisionId": "approval_gate",
                "title": "開発へ進めるかを判断",
                "reason": str(next_action.get("reason", "")).strip(),
                "availableDecisions": ["approve", "request_changes", "reject"],
                "required": True,
            }
        ]
    if next_action.get("type") == "request_release_decision":
        return [
            {
                "phase": phase,
                "decisionId": "release_promotion",
                "title": "release candidate を公開するかを判断",
                "reason": str(next_action.get("reason", "")).strip(),
                "availableDecisions": ["approve_release", "hold_release", "request_fix"],
                "required": True,
            }
        ]
    if next_action.get("type") == "request_iteration_triage":
        return [
            {
                "phase": phase,
                "decisionId": "iteration_triage",
                "title": "次の iteration scope を確定",
                "reason": str(next_action.get("reason", "")).strip(),
                "availableDecisions": ["prioritize_feedback", "defer_iteration", "request_more_signal"],
                "required": True,
            }
        ]
    if next_action.get("type") == "review_phase":
        return [
            {
                "phase": phase,
                "decisionId": f"{phase}_review",
                "title": f"{phase} の差し戻し方針を判断",
                "reason": str(next_action.get("reason", "")).strip(),
                "availableDecisions": _phase_review_decisions(phase),
                "required": True,
                "blockingIssues": [
                    str(item).strip()
                    for item in _as_list(payload.get("blockingIssues"))
                    if str(item).strip()
                ][:4],
                "reviewTriggers": [
                    str(item).strip()
                    for item in _as_list(policy.get("humanReviewTriggers"))
                    if str(item).strip()
                ][:4],
            }
        ]
    return []


def build_lifecycle_approval_binding(project_record: dict[str, Any]) -> dict[str, Any]:
    """Build approval-bound plan/effect payloads for the development gate."""
    contracts = build_phase_contracts(project_record)
    development_input = _approval_binding_development_input(project_record)
    autonomy_level = resolve_lifecycle_autonomy_level(project_record)
    governance_mode = resolve_lifecycle_governance_mode(project_record)
    selected_features = [item.get("name") for item in _approval_binding_selected_features(project_record)]
    plan = {
        "project_id": project_record.get("projectId", project_record.get("id")),
        "spec": project_record.get("spec"),
        "orchestration_mode": project_record.get("orchestrationMode", "workflow"),
        "governance_mode": governance_mode,
        "autonomy_level": autonomy_level.name,
        "selected_preset": project_record.get("selectedPreset"),
        "selected_design_id": project_record.get("selectedDesignId"),
        "selected_features": selected_features,
        "research_contract": _approval_binding_contract_snapshot(contracts.get("research")),
        "planning_contract": _approval_binding_contract_snapshot(contracts.get("planning")),
        "design_contract": _approval_binding_contract_snapshot(contracts.get("design")),
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
        "governance_mode": governance_mode,
        "autonomy_level": autonomy_level.name,
        "reason": (
            "Governed mode requires a human approval decision before development execution continues."
            if governance_mode == "governed"
            else "Development phase changes are auto-approved under the A4 full-autonomy policy."
            if autonomy_level >= AutonomyLevel.A4
            else "Development phase changes still require a human approval decision until the project is promoted to A4."
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


def _development_retry_context(project_record: dict[str, Any]) -> dict[str, Any]:
    execution = _as_dict(project_record.get("developmentExecution"))
    if not execution:
        return {}
    work_units = [_as_dict(item) for item in _as_list(execution.get("workUnits")) if _as_dict(item)]
    work_unit_lookup = {
        _normalize_text(item.get("id")): item
        for item in work_units
        if _normalize_text(item.get("id"))
    }
    work_unit_ids = [
        _normalize_text(item)
        for item in _as_list(execution.get("focusWorkUnitIds"))
        if _normalize_text(item)
    ] or [
        _normalize_text(item)
        for item in _as_list(execution.get("blockedWorkUnitIds"))
        if _normalize_text(item)
    ]
    retry_node_ids = [
        _normalize_text(item)
        for item in _as_list(execution.get("retryNodeIds"))
        if _normalize_text(item)
    ]
    return {
        "waveIndex": execution.get("currentWaveIndex"),
        "workUnitIds": work_unit_ids,
        "retryNodeIds": retry_node_ids,
        "topologyFingerprint": _normalize_text(execution.get("topologyFingerprint")),
        "runtimeGraphFingerprint": _normalize_text(execution.get("runtimeGraphFingerprint")),
        "topologyFresh": execution.get("topologyFresh") is not False,
        "topologyIssues": [
            _normalize_text(item)
            for item in _as_list(execution.get("topologyIssues"))
            if _normalize_text(item)
        ],
        "blockedTitles": [
            _normalize_text(work_unit_lookup.get(work_unit_id, {}).get("title"))
            for work_unit_id in work_unit_ids
            if _normalize_text(work_unit_lookup.get(work_unit_id, {}).get("title"))
        ],
    }


def _derive_candidate_action(project_record: dict[str, Any]) -> dict[str, Any]:
    """Determine the next backend action for a lifecycle project."""
    spec = str(project_record.get("spec", "") or "").strip()
    contracts = build_phase_contracts(project_record)
    readiness = build_phase_readiness(project_record)
    approval_status = str(project_record.get("approvalStatus", "pending") or "pending")
    governance_mode = resolve_lifecycle_governance_mode(project_record)
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
    planning_contract = contracts.get("planning")
    design_contract = contracts.get("design")
    downstream_progress_exists = (
        _phase_ready_or_completed(project_record, contracts, "planning")
        or _phase_ready_or_completed(project_record, contracts, "design")
    )
    if research_contract is None and not downstream_progress_exists:
        return _action(
            "run_phase",
            phase="research",
            title="Run research swarm",
            reason="Research evidence must be generated before downstream planning can begin.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "research")},
        )
    if research_contract is not None and not research_contract["ready"]:
        remediation_context = research_autonomous_remediation_context(project_record)
        operator_guidance = research_operator_guidance_context(project_record)
        operator_decision = _research_operator_decision(project_record)
        if remediation_context:
            attempt = int(remediation_context.get("attempt", 1) or 1)
            max_attempts = int(remediation_context.get("maxAttempts", attempt) or attempt)
            retry_node_ids = [
                str(item)
                for item in _as_list(remediation_context.get("retryNodeIds"))
                if str(item).strip()
            ]
            retry_summary = (
                "対象ノード: "
                + ", ".join(retry_node_ids[:3])
                if retry_node_ids
                else "対象ノード: quality gate で止まっている research ノード"
            )
            recovery_mode = str(remediation_context.get("recoveryMode", "deepen_evidence") or "deepen_evidence")
            strategy_label = (
                "観点を切り替える"
                if recovery_mode == "reframe_research"
                else "外部根拠を厚くする"
            )
            return _action(
                "run_phase",
                phase="research",
                title="自動 research 回復を継続",
                reason=(
                    "企画に渡すための根拠がまだ不足しているため、"
                    f"自動回復 ({attempt}/{max_attempts}) を継続し、{strategy_label} で {retry_summary} を進めます。"
                ),
                can_autorun=True,
                payload={
                    "input": lifecycle_phase_input(project_record, "research"),
                    "blockingIssues": readiness["research"]["blockingIssues"],
                    "remediation": remediation_context,
                    "operatorGuidance": operator_guidance,
                },
            )
        if (
            str(operator_decision.get("mode", "")) == "conditional_handoff"
            and operator_guidance.get("conditionalHandoffAllowed") is True
        ):
            return _action(
                "review_phase",
                phase="planning",
                title="条件付きで企画へ進めます",
                reason=(
                    "信頼度の厳格基準は未達ですが、未解決の前提を明示すれば"
                    "企画へ進めるだけの接地した根拠は揃っています。"
                ),
                can_autorun=False,
                payload={
                    "blockingIssues": readiness["research"]["blockingIssues"],
                    "operatorGuidance": operator_guidance,
                },
            )
        if operator_guidance:
            title = "次の進め方を選んでください"
            reason = str(operator_guidance.get("strategySummary") or "企画に渡すための根拠がまだ不足しています。")
            if operator_guidance.get("conditionalHandoffAllowed") is True:
                title = "条件付きで企画へ進めます"
                reason = (
                    "品質ゲートはまだ未達ですが、前提を明示すれば"
                    "企画へ進めるだけの接地した根拠は揃っています。"
                )
            elif str(operator_guidance.get("recommendedAction", "")) == "clarify_scope":
                title = "問いを絞ってから再調査してください"
            return _action(
                "review_phase",
                phase="research",
                title=title,
                reason=reason,
                can_autorun=False,
                payload={
                    "blockingIssues": readiness["research"]["blockingIssues"],
                    "operatorGuidance": operator_guidance,
                },
            )
        return _action(
            "review_phase",
            phase="research",
            title="調査の見直しが必要です",
            reason="企画に渡すための根拠がまだ不足しています。",
            can_autorun=False,
            payload={"blockingIssues": readiness["research"]["blockingIssues"]},
        )

    if planning_contract is None:
        if (
            research_contract is None
            or not research_contract.get("ready")
            or research_contract.get("status") != "ready"
        ):
            return _action(
                "review_phase",
                phase="research",
                title="調査の見直しが必要です",
                reason="企画に進む前に調査フェーズの完了が必要です。",
                can_autorun=False,
                payload={"blockingIssues": []},
            )
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
        if governance_mode == "complete_autonomy" and autonomy_level >= AutonomyLevel.A4:
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
            reason=(
                "Governed mode keeps the approval decision with a human reviewer before development can start."
                if governance_mode == "governed"
                else "Development remains approval-gated until the project is promoted to A4 complete autonomy."
            ),
            can_autorun=False,
            payload={
                "approvalStatus": approval_status,
                "approvalRequestId": project_record.get("approvalRequestId"),
                "decisionType": "approval_gate",
                "availableDecisions": ["approve", "request_changes", "reject"],
            },
        )

    development_contract = contracts.get("development")
    if development_contract is None:
        return _action(
            "run_phase",
            phase="development",
            title="Run autonomous delivery mesh",
            reason="Approved planning and design context is ready to be expanded into a dependency-aware delivery graph and completed through deploy handoff.",
            can_autorun=True,
            payload={"input": lifecycle_phase_input(project_record, "development")},
        )
    if not development_contract["ready"]:
        retry_context = _development_retry_context(project_record)
        if retry_context.get("retryNodeIds") or retry_context.get("topologyIssues"):
            wave_index = retry_context.get("waveIndex")
            wave_label = (
                f"wave {int(wave_index or 0) + 1}"
                if isinstance(wave_index, int)
                else "current wave"
            )
            blocked_titles = retry_context.get("blockedTitles") or []
            if retry_context.get("topologyFresh") is False:
                title = "Rebuild development topology and retry"
                reason = (
                    "The active delivery topology is stale against the latest decision context, "
                    "so development should re-materialize the runtime graph before retrying blocked work."
                )
                execution_mode = "replan_with_fresh_topology"
            else:
                title = "Retry the blocked development wave"
                reason = (
                    f"{wave_label} is blocked and should be retried locally"
                    + (f" ({', '.join(blocked_titles[:2])})." if blocked_titles else ".")
                )
                execution_mode = "resume_current_wave"
            return _action(
                "run_phase",
                phase="development",
                title=title,
                reason=reason,
                can_autorun=True,
                payload={
                    "input": lifecycle_phase_input(project_record, "development"),
                    "blockingIssues": readiness["development"]["blockingIssues"],
                    "waveIndex": wave_index,
                    "workUnitIds": retry_context.get("workUnitIds", []),
                    "retryNodeIds": retry_context.get("retryNodeIds", []),
                    "topologyFingerprint": retry_context.get("topologyFingerprint"),
                    "runtimeGraphFingerprint": retry_context.get("runtimeGraphFingerprint"),
                    "executionMode": execution_mode,
                },
            )
        return _action(
            "review_phase",
            phase="development",
            title="Development needs rework",
            reason="Delivery graph, build output, or deploy handoff is not yet ready for release gates.",
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
        if governance_mode == "governed":
            return _action(
                "request_release_decision",
                phase="deploy",
                title="Review release candidate",
                reason="Deploy checks passed, but governed mode requires a human release decision before the release record is created.",
                can_autorun=False,
                payload={
                    "decisionType": "release_promotion",
                    "availableDecisions": ["approve_release", "hold_release", "request_fix"],
                    "deployChecksPassed": True,
                },
            )
        return _action(
            "create_release",
            phase="deploy",
            title="Create release record",
            reason="Deploy checks have passed and a release record can be created.",
            can_autorun=True,
        )
    if not feedbacks:
        if governance_mode == "governed":
            return _action(
                "request_iteration_triage",
                phase="iterate",
                title="Review the next iteration",
                reason="A release exists, and governed mode expects a human to prioritize backlog changes before the next iteration is committed.",
                can_autorun=False,
                payload={
                    "decisionType": "iteration_triage",
                    "availableDecisions": ["prioritize_feedback", "defer_iteration", "request_more_signal"],
                    "recommendationCount": len(_as_list(project_record.get("recommendations"))),
                },
            )
        return _action(
            "done",
            phase="iterate",
            title="Lifecycle loop is in continuous iteration mode",
            reason="A release exists and the autonomous loop can continue synthesizing backlog signals while humans add feedback whenever needed.",
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
    governance_mode = resolve_lifecycle_governance_mode(project_record)
    candidate = _derive_candidate_action(project_record)
    return _apply_orchestration_mode(candidate, mode=mode, governance_mode=governance_mode)


def build_lifecycle_autonomy_projection(project_record: dict[str, Any]) -> dict[str, Any]:
    """Project lifecycle state into an autonomy-oriented control view."""
    mode = resolve_lifecycle_orchestration_mode(project_record)
    governance_mode = resolve_lifecycle_governance_mode(project_record)
    contracts = build_phase_contracts(project_record)
    readiness = build_phase_readiness(project_record)
    next_action = derive_lifecycle_next_action(project_record, mode_override=mode)
    phase_policies = _build_phase_governance_policies(governance_mode)
    required_decisions = _required_human_decisions(next_action, phase_policies=phase_policies)
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
        "governanceMode": governance_mode,
        "completedExecutablePhases": executable,
        "blockedPhases": blocked,
        "approvalRequired": next_action["type"] == "request_approval",
        "humanDecisionRequired": bool(required_decisions),
        "requiredHumanDecisions": required_decisions,
        "phasePolicies": phase_policies,
        "humanOverrideAlwaysAllowed": True,
        "continuousDeliveryMode": (
            "human_governed_continuous_delivery"
            if governance_mode == "governed"
            else "autonomous_continuous_delivery_with_human_override"
        ),
        "canAdvanceAutonomously": next_action["canAutorun"],
    }
