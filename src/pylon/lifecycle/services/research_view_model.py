"""Stable user-facing research DTOs for lifecycle UIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate_text(value: Any, *, limit: int = 220) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{(clipped or text[:limit].strip())}..."


def _text_value(value: Any, default: str = "", *, limit: int = 220) -> str:
    text = _truncate_text(value, limit=limit)
    return text or default


def _text_list(value: Any, *, limit: int = 6, char_limit: int = 220) -> list[str]:
    items: list[str] = []
    for entry in _as_list(value):
        text = _text_value(entry, limit=char_limit)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def build_research_view_model(research: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(research)
    technical = _as_dict(payload.get("tech_feasibility"))
    confidence = _as_dict(payload.get("confidence_summary"))
    user_research = _as_dict(payload.get("user_research"))
    remediation_plan = _as_dict(payload.get("remediation_plan"))
    autonomous = _as_dict(payload.get("autonomous_remediation"))
    research_context = _as_dict(payload.get("research_context"))
    operator_copy = _as_dict(payload.get("operator_copy"))

    competitors = []
    for item in _as_list(payload.get("competitors")):
        competitor = _as_dict(item)
        name = _text_value(competitor.get("name"), limit=64)
        if not name:
            continue
        competitors.append(
            {
                "name": name,
                "url": _text_value(competitor.get("url"), limit=240) or None,
                "strengths": _text_list(competitor.get("strengths"), limit=2, char_limit=150),
                "weaknesses": _text_list(competitor.get("weaknesses"), limit=2, char_limit=150),
                "pricing": _text_value(competitor.get("pricing"), "非公開", limit=80),
                "target": _text_value(competitor.get("target"), limit=80),
            }
        )

    claims = []
    for item in _as_list(payload.get("claims")):
        claim = _as_dict(item)
        claim_id = _text_value(claim.get("id"), limit=64)
        statement = _text_value(claim.get("statement"), limit=220)
        if not claim_id or not statement:
            continue
        claims.append(
            {
                "id": claim_id,
                "statement": statement,
                "owner": _text_value(claim.get("owner"), "research", limit=64),
                "category": _text_value(claim.get("category"), "research", limit=48),
                "evidence_ids": _text_list(claim.get("evidence_ids"), limit=8, char_limit=64),
                "counterevidence_ids": _text_list(
                    claim.get("counterevidence_ids"),
                    limit=8,
                    char_limit=64,
                ),
                "confidence": float(claim.get("confidence", 0.0) or 0.0),
                "status": _text_value(claim.get("status"), "contested", limit=24),
            }
        )

    dissent = []
    for item in _as_list(payload.get("dissent")):
        record = _as_dict(item)
        dissent_id = _text_value(record.get("id"), limit=64)
        claim_id = _text_value(record.get("claim_id"), limit=64)
        argument = _text_value(record.get("argument"), limit=220)
        if not dissent_id or not claim_id or not argument:
            continue
        dissent.append(
            {
                "id": dissent_id,
                "claim_id": claim_id,
                "challenger": _text_value(record.get("challenger"), "reviewer", limit=64),
                "argument": argument,
                "severity": _text_value(record.get("severity"), "medium", limit=24),
                "resolved": record.get("resolved") is True,
                "recommended_test": _text_value(record.get("recommended_test"), limit=220)
                or None,
                "resolution": _text_value(record.get("resolution"), limit=220) or None,
            }
        )

    node_results = []
    for item in _as_list(payload.get("node_results")):
        node = _as_dict(item)
        node_id = _text_value(node.get("nodeId"), limit=64)
        if not node_id:
            continue
        node_results.append(
            {
                "nodeId": node_id,
                "status": _text_value(node.get("status"), "degraded", limit=24),
                "parseStatus": _text_value(node.get("parseStatus"), "fallback", limit=24),
                "degradationReasons": _text_list(
                    node.get("degradationReasons"),
                    limit=8,
                    char_limit=220,
                ),
                "sourceClassesSatisfied": _text_list(
                    node.get("sourceClassesSatisfied"),
                    limit=8,
                    char_limit=80,
                ),
                "missingSourceClasses": _text_list(
                    node.get("missingSourceClasses"),
                    limit=8,
                    char_limit=80,
                ),
                "artifact": _as_dict(node.get("artifact")),
                "rawPreview": _text_value(node.get("rawPreview"), limit=400) or None,
                "llmModel": _text_value(node.get("llmModel"), limit=80) or None,
                "llmProvider": _text_value(node.get("llmProvider"), limit=80) or None,
                "retryCount": int(node.get("retryCount", 0) or 0),
            }
        )

    quality_gates = []
    for item in _as_list(payload.get("quality_gates")):
        gate = _as_dict(item)
        gate_id = _text_value(gate.get("id"), limit=64)
        title = _text_value(gate.get("title"), limit=120)
        if not gate_id or not title:
            continue
        quality_gates.append(
            {
                "id": gate_id,
                "title": title,
                "passed": gate.get("passed") is True,
                "reason": _text_value(gate.get("reason"), limit=220),
                "blockingNodeIds": _text_list(gate.get("blockingNodeIds"), limit=8, char_limit=80),
            }
        )

    view_model = {
        "competitors": competitors,
        "market_size": _text_value(
            payload.get("market_size"),
            "調査結果を取得できませんでした",
            limit=220,
        ),
        "trends": _text_list(payload.get("trends"), limit=4, char_limit=220),
        "opportunities": _text_list(payload.get("opportunities"), limit=4, char_limit=220),
        "threats": _text_list(payload.get("threats"), limit=4, char_limit=220),
        "tech_feasibility": {
            "score": float(technical.get("score", 0.0) or 0.0),
            "notes": _text_value(
                technical.get("notes"),
                "データが不完全なため、調査結果を再取得してください。",
                limit=280,
            ),
        },
        "user_research": (
            {
                "signals": _text_list(user_research.get("signals"), limit=4, char_limit=220),
                "pain_points": _text_list(
                    user_research.get("pain_points"),
                    limit=4,
                    char_limit=220,
                ),
                "segment": _text_value(user_research.get("segment"), limit=80),
            }
            if user_research
            else None
        ),
        "claims": claims,
        "evidence": [dict(item) for item in _as_list(payload.get("evidence")) if isinstance(item, Mapping)],
        "dissent": dissent,
        "open_questions": _text_list(payload.get("open_questions"), limit=8, char_limit=220),
        "winning_theses": _text_list(payload.get("winning_theses"), limit=4, char_limit=220),
        "confidence_summary": {
            "average": float(confidence.get("average", 0.0) or 0.0),
            "floor": float(confidence.get("floor", 0.0) or 0.0),
            "accepted": int(confidence.get("accepted", 0) or 0),
        },
        "source_links": _text_list(payload.get("source_links"), limit=8, char_limit=240),
        "judge_summary": _text_value(payload.get("judge_summary"), limit=280) or None,
        "critical_dissent_count": int(payload.get("critical_dissent_count", 0) or 0),
        "resolved_dissent_count": int(payload.get("resolved_dissent_count", 0) or 0),
        "node_results": node_results,
        "quality_gates": quality_gates,
        "readiness": _text_value(payload.get("readiness"), limit=24) or None,
        "remediation_plan": (
            {
                "objective": _text_value(remediation_plan.get("objective"), limit=220),
                "retryNodeIds": _text_list(
                    remediation_plan.get("retryNodeIds"),
                    limit=8,
                    char_limit=80,
                ),
                "maxIterations": int(remediation_plan.get("maxIterations", 0) or 0),
            }
            if remediation_plan
            else None
        ),
        "autonomous_remediation": (
            {
                "status": _text_value(autonomous.get("status"), "not_needed", limit=24),
                "attemptCount": int(autonomous.get("attemptCount", 0) or 0),
                "maxAttempts": int(autonomous.get("maxAttempts", 0) or 0),
                "remainingAttempts": int(autonomous.get("remainingAttempts", 0) or 0),
                "autoRunnable": autonomous.get("autoRunnable") is True,
                "objective": _text_value(autonomous.get("objective"), limit=220),
                "retryNodeIds": _text_list(autonomous.get("retryNodeIds"), limit=8, char_limit=80),
                "blockingGateIds": _text_list(
                    autonomous.get("blockingGateIds"),
                    limit=8,
                    char_limit=80,
                ),
                "blockingNodeIds": _text_list(
                    autonomous.get("blockingNodeIds"),
                    limit=8,
                    char_limit=80,
                ),
                "missingSourceClasses": _text_list(
                    autonomous.get("missingSourceClasses"),
                    limit=8,
                    char_limit=80,
                ),
                "blockingSummary": _text_list(
                    autonomous.get("blockingSummary"),
                    limit=4,
                    char_limit=180,
                ),
                "recoveryMode": _text_value(autonomous.get("recoveryMode"), limit=32) or None,
                "recommendedOperatorAction": _text_value(autonomous.get("recommendedOperatorAction"), limit=40) or None,
                "conditionalHandoffAllowed": autonomous.get("conditionalHandoffAllowed") is True,
                "strategySummary": _text_value(autonomous.get("strategySummary"), limit=220) or None,
                "strategyChecklist": _text_list(
                    autonomous.get("strategyChecklist"),
                    limit=4,
                    char_limit=180,
                ),
                "planningGuardrails": _text_list(
                    autonomous.get("planningGuardrails"),
                    limit=4,
                    char_limit=180,
                ),
                "followUpQuestion": _text_value(autonomous.get("followUpQuestion"), limit=180) or None,
                "stalledSignature": autonomous.get("stalledSignature") is True,
                "confidenceFloor": float(autonomous.get("confidenceFloor", 0.0) or 0.0),
                "targetConfidenceFloor": float(autonomous.get("targetConfidenceFloor", 0.0) or 0.0),
                "stopReason": _text_value(autonomous.get("stopReason"), limit=180) or None,
            }
            if autonomous
            else None
        ),
        "display_language": _text_value(payload.get("display_language"), "ja", limit=8),
        "localization_status": _text_value(payload.get("localization_status"), limit=32) or None,
    }
    if research_context:
        view_model["research_context"] = {
            "decision_stage": _text_value(research_context.get("decision_stage"), limit=48),
            "decision_stage_label": _text_value(research_context.get("decision_stage_label"), limit=80),
            "segment": _text_value(research_context.get("segment"), limit=80),
            "core_question": _text_value(research_context.get("core_question"), limit=220),
            "thesis_headline": _text_value(research_context.get("thesis_headline"), limit=220),
            "thesis_snapshot": _text_list(research_context.get("thesis_snapshot"), limit=3, char_limit=220),
            "confidence_floor": float(research_context.get("confidence_floor", 0.0) or 0.0),
            "target_confidence_floor": float(research_context.get("target_confidence_floor", 0.0) or 0.0),
            "external_source_count": int(research_context.get("external_source_count", 0) or 0),
            "winning_thesis_count": int(research_context.get("winning_thesis_count", 0) or 0),
            "critical_dissent_count": int(research_context.get("critical_dissent_count", 0) or 0),
            "evidence_priorities": _text_list(research_context.get("evidence_priorities"), limit=3, char_limit=180),
            "blocking_summary": _text_list(research_context.get("blocking_summary"), limit=3, char_limit=180),
            "planning_guardrails": _text_list(research_context.get("planning_guardrails"), limit=3, char_limit=180),
        }
    if operator_copy:
        view_model["operator_copy"] = {
            "council_cards": [
                {
                    "id": _text_value(_as_dict(item).get("id"), limit=64),
                    "agent": _text_value(_as_dict(item).get("agent"), limit=64),
                    "lens": _text_value(_as_dict(item).get("lens"), limit=64),
                    "title": _text_value(_as_dict(item).get("title"), limit=180),
                    "summary": _text_value(_as_dict(item).get("summary"), limit=220),
                    "action_label": _text_value(_as_dict(item).get("action_label"), limit=80),
                    "target_section": _text_value(_as_dict(item).get("target_section"), limit=64) or None,
                    "tone": _text_value(_as_dict(item).get("tone"), limit=24) or None,
                }
                for item in _as_list(operator_copy.get("council_cards"))
                if _as_dict(item)
            ],
            "handoff_brief": {
                "headline": _text_value(_as_dict(operator_copy.get("handoff_brief")).get("headline"), limit=180),
                "summary": _text_value(_as_dict(operator_copy.get("handoff_brief")).get("summary"), limit=220),
                "bullets": _text_list(_as_dict(operator_copy.get("handoff_brief")).get("bullets"), limit=4, char_limit=180),
            } if _as_dict(operator_copy.get("handoff_brief")) else None,
        }
    if not view_model["user_research"]:
        view_model.pop("user_research")
    if not view_model["remediation_plan"]:
        view_model.pop("remediation_plan")
    if not view_model["autonomous_remediation"]:
        view_model.pop("autonomous_remediation")
    if not view_model["judge_summary"]:
        view_model.pop("judge_summary")
    if "operator_copy" in view_model:
        if not view_model["operator_copy"]["council_cards"]:
            view_model["operator_copy"].pop("council_cards")
        if not view_model["operator_copy"].get("handoff_brief"):
            view_model["operator_copy"].pop("handoff_brief", None)
        if not view_model["operator_copy"]:
            view_model.pop("operator_copy")
    return view_model
