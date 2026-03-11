"""Typed lifecycle contract and readiness helpers."""

from __future__ import annotations

from typing import Any

from pylon.lifecycle.orchestrator import PHASE_ORDER


EXECUTABLE_PHASES: tuple[str, ...] = ("research", "planning", "design", "development")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _phase_status(project_record: dict[str, Any], phase: str) -> str:
    for item in _as_list(project_record.get("phaseStatuses")):
        entry = _as_dict(item)
        if entry.get("phase") == phase:
            return str(entry.get("status", "locked") or "locked")
    return "locked"


def _selected_design_variant(project_record: dict[str, Any]) -> dict[str, Any]:
    selected_id = str(project_record.get("selectedDesignId") or "")
    variants = _as_list(project_record.get("designVariants"))
    for variant in variants:
        record = _as_dict(variant)
        if selected_id and record.get("id") == selected_id:
            return record
    return _as_dict(variants[0]) if variants else {}


def _prototype_screen_count(variant: dict[str, Any]) -> int:
    prototype = _as_dict(variant.get("prototype"))
    return len(_as_list(prototype.get("screens")))


def _prototype_flow_count(variant: dict[str, Any]) -> int:
    prototype = _as_dict(variant.get("prototype"))
    return len(_as_list(prototype.get("flows")))


def _prototype_navigation_count(variant: dict[str, Any]) -> int:
    prototype = _as_dict(variant.get("prototype"))
    shell = _as_dict(prototype.get("app_shell"))
    return len(_as_list(shell.get("primary_navigation")))


def _looks_like_prototype_html(code: str) -> bool:
    lowered = str(code or "").lower()
    return (
        "<html" in lowered
        and "<main" in lowered
        and "data-prototype-kind" in lowered
        and "data-screen-id" in lowered
        and "primary navigation" in lowered
    )


def lifecycle_phase_input(project_record: dict[str, Any], phase: str) -> dict[str, Any]:
    """Build normalized workflow input for the requested lifecycle phase."""
    spec = str(project_record.get("spec", "") or "")
    research_config = _as_dict(project_record.get("researchConfig"))
    research = _as_dict(project_record.get("research"))
    analysis = _as_dict(project_record.get("analysis"))
    features = _as_list(project_record.get("features"))
    milestones = _as_list(project_record.get("milestones"))
    design_variants = _as_list(project_record.get("designVariants"))
    selected_design = _selected_design_variant(project_record)

    if phase == "research":
        return {
            "spec": spec,
            "competitor_urls": _as_list(research_config.get("competitorUrls")),
            "depth": str(research_config.get("depth", "standard") or "standard"),
        }
    if phase == "planning":
        return {"spec": spec, "research": research}
    if phase == "design":
        return {"spec": spec, "analysis": analysis, "features": features}
    if phase == "development":
        return {
            "spec": spec,
            "research": research,
            "analysis": analysis,
            "selected_features": features,
            "milestones": milestones,
            "designVariants": design_variants,
            "selectedDesignId": project_record.get("selectedDesignId"),
            "selected_design": selected_design,
            "design": {"selected": selected_design, "variants": design_variants},
        }
    raise ValueError(f"Unsupported lifecycle phase input: {phase}")


def _quality_gate(gate_id: str, title: str, passed: bool, detail: str) -> dict[str, Any]:
    return {
        "id": gate_id,
        "title": title,
        "passed": passed,
        "detail": detail,
    }


def _contract(
    *,
    phase: str,
    contract_type: str,
    status: str,
    summary: str,
    outputs: dict[str, Any],
    quality_gates: list[dict[str, Any]],
    handoff_targets: list[str],
) -> dict[str, Any]:
    passed = sum(1 for item in quality_gates if item["passed"])
    total = len(quality_gates) or 1
    return {
        "phase": phase,
        "contractType": contract_type,
        "contractVersion": "1",
        "status": status,
        "ready": passed == len(quality_gates),
        "confidence": round(passed / total, 2),
        "summary": summary,
        "outputs": outputs,
        "qualityGates": quality_gates,
        "handoffTargets": handoff_targets,
    }


def build_phase_contract(project_record: dict[str, Any], phase: str) -> dict[str, Any] | None:
    status = _phase_status(project_record, phase)

    if phase == "research":
        research = _as_dict(project_record.get("research"))
        if not research:
            return None
        user_research = _as_dict(research.get("user_research"))
        claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
        evidence = [_as_dict(item) for item in _as_list(research.get("evidence")) if _as_dict(item)]
        dissent = [_as_dict(item) for item in _as_list(research.get("dissent")) if _as_dict(item)]
        accepted_claims = [item for item in claims if item.get("status") == "accepted"]
        critical_unresolved = [
            item for item in dissent
            if item.get("severity") == "critical" and item.get("resolved") is not True
        ]
        floor = float(_as_dict(research.get("confidence_summary")).get("floor", 0.0) or 0.0)
        gates = [
            _quality_gate(
                "source-grounding",
                "採択 thesis が evidence と source に接地している",
                bool(accepted_claims or claims)
                and bool(evidence)
                and all(bool(_as_list(item.get("evidence_ids"))) for item in (accepted_claims or claims[:2])),
                "research should keep accepted claims grounded in evidence",
            ),
            _quality_gate(
                "counterclaim-coverage",
                "主要 claim に対する反証が残っている",
                bool(dissent),
                "research should preserve dissent instead of collapsing into consensus only",
            ),
            _quality_gate(
                "critical-dissent-resolved",
                "重大な dissent が未解決のまま残っていない",
                not critical_unresolved,
                "critical research dissent must be resolved before planning",
            ),
            _quality_gate(
                "confidence-floor",
                "planning に渡す信頼度の下限を満たしている",
                floor >= 0.6 and bool(_as_list(research.get("winning_theses"))),
                "research should carry at least one sufficiently supported thesis into planning",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="ResearchArtifact",
            status=status,
            summary="Evidence bundle for planning.",
            outputs={
                "competitorCount": len(_as_list(research.get("competitors"))),
                "claimCount": len(claims),
                "acceptedClaimCount": len(accepted_claims),
                "evidenceCount": len(evidence),
                "dissentCount": len(dissent),
                "openQuestionCount": len(_as_list(research.get("open_questions"))),
                "segment": user_research.get("segment"),
            },
            quality_gates=gates,
            handoff_targets=["planning"],
        )

    if phase == "planning":
        analysis = _as_dict(project_record.get("analysis"))
        features = _as_list(project_record.get("features"))
        estimates = _as_list(project_record.get("planEstimates"))
        milestones = _as_list(project_record.get("milestones"))
        traceability = _as_list(analysis.get("traceability"))
        assumptions = _as_list(analysis.get("assumptions"))
        negative_personas = _as_list(analysis.get("negative_personas"))
        kill_criteria = _as_list(analysis.get("kill_criteria"))
        selected_features = [
            _as_dict(item)
            for item in features
            if _as_dict(item).get("selected") is True
        ]
        if not analysis and not features and not estimates:
            return None
        gates = [
            _quality_gate(
                "feature-traceability",
                "主要 feature が research claim と use case に接続されている",
                bool(selected_features)
                and len(traceability) >= len(selected_features),
                "planning should connect selected features to claim and use-case lineage",
            ),
            _quality_gate(
                "assumption-audit",
                "主要前提に対する監査結果が残っている",
                bool(assumptions) and bool(_as_list(analysis.get("red_team_findings"))),
                "planning should include explicit assumptions and red-team findings",
            ),
            _quality_gate(
                "negative-persona-coverage",
                "失敗しやすい利用文脈が明示されている",
                bool(negative_personas),
                "planning should keep at least one negative persona or failure scenario",
            ),
            _quality_gate(
                "milestone-falsifiability",
                "milestone が検証条件と失敗条件を持っている",
                bool(milestones) and bool(estimates) and len(kill_criteria) >= min(len(milestones), 1),
                "planning should include falsifiable milestones and effort presets",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="PlanningArtifact",
            status=status,
            summary="Decision-ready scope and delivery plan.",
            outputs={
                "personaCount": len(_as_list(analysis.get("personas"))),
                "featureCount": len(features),
                "selectedFeatureCount": len(selected_features),
                "rejectedFeatureCount": len(_as_list(analysis.get("rejected_features"))),
                "useCaseCount": len(_as_list(analysis.get("use_cases"))),
                "milestoneCount": len(milestones),
                "estimatePresetCount": len(estimates),
                "redTeamFindingCount": len(_as_list(analysis.get("red_team_findings"))),
            },
            quality_gates=gates,
            handoff_targets=["design", "approval"],
        )

    if phase == "design":
        variants = _as_list(project_record.get("designVariants"))
        selected = _selected_design_variant(project_record)
        if not variants:
            return None
        screen_count = _prototype_screen_count(selected)
        flow_count = _prototype_flow_count(selected)
        navigation_count = _prototype_navigation_count(selected)
        gates = [
            _quality_gate(
                "variant-exploration",
                "複数のデザイン案が比較可能である",
                len(variants) >= 2,
                "design should contain at least two candidate variants",
            ),
            _quality_gate(
                "baseline-selection",
                "build に渡す baseline が決まっている",
                bool(selected),
                "a selected design baseline should be identifiable",
            ),
            _quality_gate(
                "prototype-coverage",
                "selected design に複数 screen の prototype がある",
                screen_count >= 2 and navigation_count >= 2,
                "design should include an application shell and more than one prototype screen",
            ),
            _quality_gate(
                "workflow-fidelity",
                "selected design に主要 workflow が定義されている",
                flow_count >= 1,
                "design should carry at least one primary workflow into development",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="DesignArtifact",
            status=status,
            summary="Design options and chosen baseline for approval/build.",
            outputs={
                "variantCount": len(variants),
                "selectedDesignId": selected.get("id"),
                "selectedPattern": selected.get("pattern_name"),
                "screenCount": screen_count,
                "flowCount": flow_count,
            },
            quality_gates=gates,
            handoff_targets=["approval", "development"],
        )

    if phase == "approval":
        approval_status = str(project_record.get("approvalStatus", "pending") or "pending")
        comments = _as_list(project_record.get("approvalComments"))
        if approval_status == "pending" and not comments:
            return None
        gates = [
            _quality_gate(
                "approval-granted",
                "approval decision is approved",
                approval_status == "approved",
                "development must not auto-run without approval",
            )
        ]
        return _contract(
            phase=phase,
            contract_type="ApprovalPacket",
            status=_phase_status(project_record, phase),
            summary="Approval state for gated progression.",
            outputs={"approvalStatus": approval_status, "commentCount": len(comments)},
            quality_gates=gates,
            handoff_targets=["development"] if approval_status == "approved" else [],
        )

    if phase == "development":
        milestone_results = _as_list(project_record.get("milestoneResults"))
        build_code = str(project_record.get("buildCode") or "")
        build_cost = float(project_record.get("buildCost", 0.0) or 0.0)
        if not build_code and not milestone_results:
            return None
        satisfied = sum(
            1
            for item in milestone_results
            if _as_dict(item).get("status") == "satisfied"
        )
        total = len(milestone_results)
        gates = [
            _quality_gate(
                "build-artifact",
                "previewable prototype artifact exists",
                _looks_like_prototype_html(build_code),
                "development should produce prototype-grade HTML with app shell markers",
            ),
            _quality_gate(
                "navigation-shell",
                "build に prototype navigation と screen surfaces がある",
                "primary navigation" in build_code.lower() and "data-screen-id" in build_code.lower(),
                "development should preserve navigation and multiple screen surfaces from design",
            ),
            _quality_gate(
                "milestone-coverage",
                "all milestone checks are satisfied",
                total > 0 and satisfied == total,
                "all milestone results should be satisfied before deploy",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="BuildArtifact",
            status=status,
            summary="Integrated build output and review result.",
            outputs={
                "buildBytes": len(build_code.encode("utf-8")),
                "milestonesSatisfied": satisfied,
                "milestonesTotal": total,
                "buildCostUsd": build_cost,
                "buildIteration": int(project_record.get("buildIteration", 0) or 0),
            },
            quality_gates=gates,
            handoff_targets=["deploy"],
        )

    if phase == "deploy":
        checks = _as_list(project_record.get("deployChecks"))
        releases = _as_list(project_record.get("releases"))
        if not checks and not releases:
            return None
        failing = [
            _as_dict(item)
            for item in checks
            if _as_dict(item).get("status") == "fail"
        ]
        gates = [
            _quality_gate(
                "deploy-checks",
                "release gate checks are green",
                bool(checks) and not failing,
                "deploy requires checks and no failing blockers",
            ),
            _quality_gate(
                "release-record",
                "at least one release has been created",
                bool(releases),
                "deploy is only complete after a release record exists",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="ReleaseArtifact",
            status=_phase_status(project_record, phase),
            summary="Release readiness and published release state.",
            outputs={
                "deployCheckCount": len(checks),
                "failingCheckCount": len(failing),
                "releaseCount": len(releases),
            },
            quality_gates=gates,
            handoff_targets=["iterate"] if releases else [],
        )

    if phase == "iterate":
        feedbacks = _as_list(project_record.get("feedbackItems"))
        recommendations = _as_list(project_record.get("recommendations"))
        if not feedbacks and not recommendations:
            return None
        gates = [
            _quality_gate(
                "feedback-loop",
                "iteration backlog or recommendations exist",
                bool(feedbacks) or bool(recommendations),
                "iterate should capture feedback or explicit follow-up recommendations",
            )
        ]
        return _contract(
            phase=phase,
            contract_type="IterationBacklog",
            status=_phase_status(project_record, phase),
            summary="Feedback loop and next iteration candidates.",
            outputs={"feedbackCount": len(feedbacks), "recommendationCount": len(recommendations)},
            quality_gates=gates,
            handoff_targets=[],
        )

    return None


def build_phase_contracts(project_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for phase in PHASE_ORDER:
        contract = build_phase_contract(project_record, phase)
        if contract is not None:
            contracts[phase] = contract
    return contracts


def build_phase_readiness(project_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contracts = build_phase_contracts(project_record)
    readiness: dict[str, dict[str, Any]] = {}
    for phase in PHASE_ORDER:
        contract = contracts.get(phase)
        readiness[phase] = {
            "phase": phase,
            "status": _phase_status(project_record, phase),
            "ready": bool(contract and contract.get("ready")),
            "blockingIssues": [
                gate["title"]
                for gate in _as_list(_as_dict(contract).get("qualityGates"))
                if not _as_dict(gate).get("passed", False)
            ],
            "contractType": _as_dict(contract).get("contractType") if contract else None,
        }
    return readiness
