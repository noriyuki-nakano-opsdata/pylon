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
        gates = [
            _quality_gate(
                "competitor-coverage",
                "競合または市場の比較材料が揃っている",
                bool(_as_list(research.get("competitors"))) or bool(_as_list(research.get("trends"))),
                "research should include competitive or trend evidence",
            ),
            _quality_gate(
                "user-signal-coverage",
                "ユーザーシグナルが planning に渡せる",
                bool(_as_list(user_research.get("signals"))) and bool(_as_list(user_research.get("pain_points"))),
                "user research must retain signals and pain points",
            ),
            _quality_gate(
                "feasibility",
                "技術実現性が明示されている",
                float(_as_dict(research.get("tech_feasibility")).get("score", 0.0) or 0.0) > 0.0,
                "tech feasibility score must be present",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="ResearchArtifact",
            status=status,
            summary="Evidence bundle for planning.",
            outputs={
                "competitorCount": len(_as_list(research.get("competitors"))),
                "trendCount": len(_as_list(research.get("trends"))),
                "signalCount": len(_as_list(user_research.get("signals"))),
                "painPointCount": len(_as_list(user_research.get("pain_points"))),
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
        if not analysis and not features and not estimates:
            return None
        gates = [
            _quality_gate(
                "persona-coverage",
                "ペルソナと利用文脈が定義されている",
                bool(_as_list(analysis.get("personas"))) and bool(_as_list(analysis.get("user_journeys"))),
                "planning should include personas and journeys",
            ),
            _quality_gate(
                "scope-definition",
                "feature scope と use case が揃っている",
                bool(features) and bool(_as_list(analysis.get("use_cases"))),
                "planning should include selected features and use cases",
            ),
            _quality_gate(
                "delivery-plan",
                "milestone と plan estimate が揃っている",
                bool(milestones) and bool(estimates),
                "planning should include milestones and effort presets",
            ),
            _quality_gate(
                "design-tokens",
                "design system の前提が揃っている",
                bool(_as_dict(analysis.get("design_tokens"))),
                "design tokens should be available before design/development",
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
                "useCaseCount": len(_as_list(analysis.get("use_cases"))),
                "milestoneCount": len(milestones),
                "estimatePresetCount": len(estimates),
            },
            quality_gates=gates,
            handoff_targets=["design", "approval"],
        )

    if phase == "design":
        variants = _as_list(project_record.get("designVariants"))
        selected = _selected_design_variant(project_record)
        if not variants:
            return None
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
                "previewable build artifact exists",
                "<html" in build_code.lower(),
                "development should produce previewable HTML output",
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
