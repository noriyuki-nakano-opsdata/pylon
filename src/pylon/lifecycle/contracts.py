"""Typed lifecycle contract and readiness helpers."""

from __future__ import annotations

import json
from typing import Any

from pylon.lifecycle.orchestrator import PHASE_ORDER

EXECUTABLE_PHASES: tuple[str, ...] = ("research", "planning", "design", "development")
_RESEARCH_INPUT_TOKEN_BUDGET = 6000
RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT = 2


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _estimate_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + int(non_ascii_chars / 1.5))


def _truncate_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _research_canonical_payload(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _as_dict(research.get("canonical"))
    return canonical or research


def _research_localized_payload(research: dict[str, Any]) -> dict[str, Any]:
    localized = _as_dict(research.get("localized"))
    return localized or research


def _research_failed_quality_gates(research: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = _research_canonical_payload(research)
    return [
        _as_dict(item)
        for item in _as_list(canonical.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ]


def research_autonomous_remediation_context(
    project_record: dict[str, Any],
) -> dict[str, Any]:
    research = _as_dict(project_record.get("research"))
    if not research:
        return {}
    canonical = _research_canonical_payload(research)
    failed_gates = _research_failed_quality_gates(research)
    remediation_plan = _as_dict(canonical.get("remediation_plan"))
    autonomous_state = _as_dict(canonical.get("autonomous_remediation"))
    attempt_count = int(autonomous_state.get("attemptCount", 0) or 0)
    max_attempts = int(
        autonomous_state.get("maxAttempts", RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT)
        or RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT
    )
    blocking_node_ids = [
        str(item)
        for gate in failed_gates
        for item in _as_list(gate.get("blockingNodeIds"))
        if str(item).strip()
    ]
    retry_node_ids = [
        str(item)
        for item in _as_list(remediation_plan.get("retryNodeIds"))
        if str(item).strip()
    ]
    if not failed_gates and not retry_node_ids:
        return {}
    if attempt_count >= max_attempts:
        return {}
    node_results = [
        _as_dict(item)
        for item in _as_list(canonical.get("node_results"))
        if _as_dict(item)
    ]
    missing_source_classes = [
        str(item)
        for node in node_results
        for item in _as_list(node.get("missingSourceClasses"))
        if str(item).strip()
    ]
    return {
        "trigger": "quality_gate_recovery",
        "attempt": attempt_count + 1,
        "previousAttemptCount": attempt_count,
        "maxAttempts": max_attempts,
        "remainingAttempts": max(0, max_attempts - attempt_count),
        "objective": str(
            remediation_plan.get("objective")
            or autonomous_state.get("objective")
            or "Close the remaining research gaps so planning can continue without operator intervention."
        ),
        "blockingGateIds": list(dict.fromkeys(str(gate.get("id", "")) for gate in failed_gates if str(gate.get("id", "")).strip()))[:6],
        "blockingNodeIds": list(dict.fromkeys(blocking_node_ids))[:6],
        "retryNodeIds": list(dict.fromkeys(retry_node_ids))[:6],
        "missingSourceClasses": list(dict.fromkeys(missing_source_classes))[:8],
        "previousSourceLinks": [
            _truncate_text(item, limit=180)
            for item in _as_list(canonical.get("source_links"))
            if str(item).strip()
        ][:6],
        "previousCompetitors": [
            _truncate_text(_as_dict(item).get("name"), limit=80)
            for item in _as_list(canonical.get("competitors"))
            if _truncate_text(_as_dict(item).get("name"), limit=80)
        ][:4],
        "blockingSummary": [
            _truncate_text(_as_dict(gate).get("reason"), limit=160)
            for gate in failed_gates
            if _truncate_text(_as_dict(gate).get("reason"), limit=160)
        ][:4],
        "lastBlockingSignature": "|".join(
            sorted(str(gate.get("id", "")) for gate in failed_gates if str(gate.get("id", "")).strip())
        ),
    }


def _compact_research_for_input(
    research: dict[str, Any],
    *,
    terse: bool,
) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    localized = _research_localized_payload(research)
    claim_limit = 3 if terse else 6
    dissent_limit = 3 if terse else 5
    question_limit = 4 if terse else 6
    source_limit = 3 if terse else 6
    competitor_limit = 2 if terse else 4
    failed_gates = [
        _as_dict(item)
        for item in _as_list(canonical.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ]
    compacted = {
        "summary_mode": "compact-terse" if terse else "compact",
        "display_language": str(research.get("display_language", "ja") or "ja"),
        "readiness": canonical.get("readiness"),
        "judge_summary": _truncate_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            limit=220 if terse else 320,
        ),
        "confidence_summary": _as_dict(canonical.get("confidence_summary")),
        "market_size": _truncate_text(
            canonical.get("market_size") or localized.get("market_size"),
            limit=180 if terse else 240,
        ),
        "trends": [
            _truncate_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("trends"))[: (2 if terse else 3)]
        ],
        "opportunities": [
            _truncate_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("opportunities"))[: (2 if terse else 3)]
        ],
        "threats": [
            _truncate_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("threats"))[: (2 if terse else 3)]
        ],
        "user_research": {
            "segment": _truncate_text(
                _as_dict(canonical.get("user_research")).get("segment")
                or _as_dict(localized.get("user_research")).get("segment"),
                limit=100 if terse else 140,
            ),
            "signals": [
                _truncate_text(item, limit=140 if terse else 180)
                for item in _as_list(_as_dict(canonical.get("user_research")).get("signals"))[: (2 if terse else 3)]
            ],
            "pain_points": [
                _truncate_text(item, limit=140 if terse else 180)
                for item in _as_list(_as_dict(canonical.get("user_research")).get("pain_points"))[: (2 if terse else 3)]
            ],
        },
        "winning_theses": [
            _truncate_text(item, limit=160 if terse else 220)
            for item in _as_list(canonical.get("winning_theses"))[: (2 if terse else 3)]
        ],
        "claims": [
            {
                "id": _as_dict(item).get("id"),
                "statement": _truncate_text(_as_dict(item).get("statement"), limit=180 if terse else 240),
                "owner": _as_dict(item).get("owner"),
                "category": _as_dict(item).get("category"),
                "confidence": _as_dict(item).get("confidence"),
                "status": _as_dict(item).get("status"),
            }
            for item in _as_list(canonical.get("claims"))[:claim_limit]
            if _as_dict(item)
        ],
        "dissent": [
            {
                "id": _as_dict(item).get("id"),
                "claim_id": _as_dict(item).get("claim_id"),
                "argument": _truncate_text(_as_dict(item).get("argument"), limit=160 if terse else 220),
                "severity": _as_dict(item).get("severity"),
                "recommended_test": _truncate_text(_as_dict(item).get("recommended_test"), limit=140 if terse else 180),
                "resolved": _as_dict(item).get("resolved"),
            }
            for item in _as_list(canonical.get("dissent"))
            if _as_dict(item)
        ][:dissent_limit],
        "open_questions": [
            _truncate_text(item, limit=160 if terse else 220)
            for item in _as_list(canonical.get("open_questions"))[:question_limit]
        ],
        "competitors": [
            {
                "name": _truncate_text(_as_dict(item).get("name"), limit=60),
                "url": _truncate_text(_as_dict(item).get("url"), limit=120 if terse else 180),
                "target": _truncate_text(_as_dict(item).get("target"), limit=80),
            }
            for item in _as_list(canonical.get("competitors"))[:competitor_limit]
            if _as_dict(item)
        ],
        "source_links": [
            _truncate_text(item, limit=120 if terse else 180)
            for item in _as_list(canonical.get("source_links"))[:source_limit]
        ],
        "quality_gates": [
            {
                "id": item.get("id"),
                "title": _truncate_text(item.get("title"), limit=80),
                "reason": _truncate_text(item.get("reason"), limit=140 if terse else 180),
                "blockingNodeIds": _as_list(item.get("blockingNodeIds"))[:4],
            }
            for item in failed_gates[:4]
        ],
    }
    if canonical.get("remediation_plan"):
        compacted["remediation_plan"] = {
            "objective": _truncate_text(_as_dict(canonical.get("remediation_plan")).get("objective"), limit=160 if terse else 220),
            "retryNodeIds": _as_list(_as_dict(canonical.get("remediation_plan")).get("retryNodeIds"))[:4],
        }
    return compacted


def _minimal_research_for_input(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    localized = _research_localized_payload(research)
    failed_gates = [
        _as_dict(item)
        for item in _as_list(canonical.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ][:2]
    claims = [
        _as_dict(item)
        for item in _as_list(canonical.get("claims"))
        if _as_dict(item)
    ][:2]
    return {
        "summary_mode": "compact-minimal",
        "display_language": str(research.get("display_language", "ja") or "ja"),
        "readiness": canonical.get("readiness"),
        "judge_summary": _truncate_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            limit=180,
        ),
        "winning_theses": [
            _truncate_text(item, limit=120)
            for item in _as_list(canonical.get("winning_theses"))[:1]
        ],
        "claims": [
            {
                "id": item.get("id"),
                "statement": _truncate_text(item.get("statement"), limit=120),
                "confidence": item.get("confidence"),
                "status": item.get("status"),
            }
            for item in claims
        ],
        "quality_gates": [
            {
                "id": item.get("id"),
                "reason": _truncate_text(item.get("reason"), limit=120),
                "blockingNodeIds": _as_list(item.get("blockingNodeIds"))[:3],
            }
            for item in failed_gates
        ],
        "open_questions": [
            _truncate_text(item, limit=120)
            for item in _as_list(canonical.get("open_questions"))[:2]
        ],
        "source_links": [
            _truncate_text(item, limit=120)
            for item in _as_list(canonical.get("source_links"))[:2]
        ],
    }


def _hard_cap_research_for_input(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    localized = _research_localized_payload(research)
    return {
        "summary_mode": "compact-hard-cap",
        "display_language": str(research.get("display_language", "ja") or "ja"),
        "readiness": canonical.get("readiness"),
        "judge_summary": _truncate_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            limit=120,
        ),
        "winning_theses": [
            _truncate_text(item, limit=80)
            for item in _as_list(canonical.get("winning_theses"))[:1]
        ],
        "quality_gates": [
            {
                "id": _as_dict(item).get("id"),
                "reason": _truncate_text(_as_dict(item).get("reason"), limit=80),
            }
            for item in _as_list(canonical.get("quality_gates"))
            if _as_dict(item) and _as_dict(item).get("passed") is not True
        ][:2],
        "research_context_notice": "Research context was aggressively summarized to fit the phase input budget.",
    }


def _research_phase_payload_for_input(project_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    research = _as_dict(project_record.get("research"))
    canonical = _research_canonical_payload(research)
    token_estimate = _estimate_tokens(canonical)
    if token_estimate <= _RESEARCH_INPUT_TOKEN_BUDGET:
        return canonical, {
            "source": "canonical",
            "compacted": False,
            "tokenEstimate": token_estimate,
            "tokenBudget": _RESEARCH_INPUT_TOKEN_BUDGET,
            "displayLanguage": str(research.get("display_language", "ja") or "ja"),
        }
    candidates = [
        _compact_research_for_input(research, terse=False),
        _compact_research_for_input(research, terse=True),
        _minimal_research_for_input(research),
        _hard_cap_research_for_input(research),
    ]
    compacted = candidates[-1]
    compacted_estimate = _estimate_tokens(compacted)
    for candidate in candidates:
        candidate_estimate = _estimate_tokens(candidate)
        compacted = candidate
        compacted_estimate = candidate_estimate
        if candidate_estimate <= _RESEARCH_INPUT_TOKEN_BUDGET:
            break
    return compacted, {
        "source": "canonical",
        "compacted": True,
        "summaryMode": str(compacted.get("summary_mode", "compact")),
        "tokenEstimate": compacted_estimate,
        "originalTokenEstimate": token_estimate,
        "tokenBudget": _RESEARCH_INPUT_TOKEN_BUDGET,
        "displayLanguage": str(research.get("display_language", "ja") or "ja"),
    }


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
    analysis = _as_dict(project_record.get("analysis"))
    features = _as_list(project_record.get("features"))
    milestones = _as_list(project_record.get("milestones"))
    design_variants = _as_list(project_record.get("designVariants"))
    selected_design = _selected_design_variant(project_record)

    if phase == "research":
        remediation_context = research_autonomous_remediation_context(project_record)
        payload = {
            "spec": spec,
            "competitor_urls": _as_list(research_config.get("competitorUrls")),
            "depth": str(research_config.get("depth", "standard") or "standard"),
            "output_language": str(research_config.get("outputLanguage", "ja") or "ja"),
        }
        if remediation_context:
            payload["remediation_context"] = remediation_context
        return payload
    if phase == "planning":
        phase_research, meta = _research_phase_payload_for_input(project_record)
        return {
            "spec": spec,
            "research": phase_research,
            "research_context_meta": meta,
        }
    if phase == "design":
        return {"spec": spec, "analysis": analysis, "features": features}
    if phase == "development":
        phase_research, meta = _research_phase_payload_for_input(project_record)
        return {
            "spec": spec,
            "research": phase_research,
            "research_context_meta": meta,
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
        stored_research = _as_dict(project_record.get("research"))
        if not stored_research:
            return None
        research = _research_canonical_payload(stored_research)
        user_research = _as_dict(research.get("user_research"))
        claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
        evidence = [_as_dict(item) for item in _as_list(research.get("evidence")) if _as_dict(item)]
        dissent = [_as_dict(item) for item in _as_list(research.get("dissent")) if _as_dict(item)]
        accepted_claims = [item for item in claims if item.get("status") == "accepted"]
        node_results = [_as_dict(item) for item in _as_list(research.get("node_results")) if _as_dict(item)]
        degraded_nodes = [
            item for item in node_results if str(item.get("status", "")) != "success"
        ]
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
            _quality_gate(
                "critical-node-health",
                "critical research nodes が degraded / failed ではない",
                not degraded_nodes,
                "critical research nodes must stay healthy enough to support handoff",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="ResearchArtifact",
            status=(
                "ready"
                if str(research.get("readiness", status)) == "ready"
                and not degraded_nodes
                else "rework"
            ),
            summary="Evidence bundle for planning.",
            outputs={
                "competitorCount": len(_as_list(research.get("competitors"))),
                "claimCount": len(claims),
                "acceptedClaimCount": len(accepted_claims),
                "evidenceCount": len(evidence),
                "dissentCount": len(dissent),
                "openQuestionCount": len(_as_list(research.get("open_questions"))),
                "segment": user_research.get("segment"),
                "degradedNodeCount": len(degraded_nodes),
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
