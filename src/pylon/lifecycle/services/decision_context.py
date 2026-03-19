"""Shared lifecycle decision-context builders.

This module provides a compact, cross-phase contract that can be passed to LLM
inputs and surfaced in operator payloads without relying on a specific phase UI.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_CANONICAL_THESIS_FALLBACKS: dict[str, dict[str, str]] = {
    "claim-competitive-gap": {
        "en": "A differentiated competitive gap may still exist, but external proof remains thin.",
        "ja": "差別化できる競争余地は残るものの、外部証拠はまだ薄い状態です。",
    },
    "claim-market-demand": {
        "en": "Demand exists, but differentiation depends on proving operational quality.",
        "ja": "需要はあるものの、差別化には運用品質を証明する必要があります。",
    },
    "claim-user-trust": {
        "en": "User trust and governance remain the main adoption gate.",
        "ja": "ユーザー信頼とガバナンスが、依然として導入の主な関門です。",
    },
    "claim-technical-feasibility": {
        "en": "Technical feasibility is plausible, but implementation risk remains material.",
        "ja": "技術的実現性は見込める一方で、実装リスクは依然として大きい状態です。",
    },
}


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


def _looks_like_machine_token(value: Any) -> bool:
    normalized = _normalize_space(value)
    return bool(
        normalized
        and (
            normalized.startswith(("http://", "https://", "project://"))
            or re.fullmatch(r"[a-z0-9_.:-]+", normalized)
        )
    )


def _contains_non_ascii(value: Any) -> bool:
    return any(ord(ch) > 127 for ch in str(value or ""))


def _slug(value: Any, *, prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return f"{prefix}:{normalized or 'item'}"


def _first_text(value: Any, *, limit: int = 180) -> str:
    if isinstance(value, Mapping):
        for key in (
            "title",
            "name",
            "statement",
            "summary",
            "description",
            "action",
            "condition",
            "question",
            "headline",
            "role",
        ):
            if key in value:
                text = _first_text(value.get(key), limit=limit)
                if text:
                    return text
        return ""
    if isinstance(value, list):
        for item in value:
            text = _first_text(item, limit=limit)
            if text:
                return text
        return ""
    return _truncate_text(value, limit=limit)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = _normalize_space(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _payload_for_language(payload: dict[str, Any], *, target_language: str) -> dict[str, Any]:
    if target_language == "ja":
        localized = _as_dict(payload.get("localized"))
        return localized or payload
    canonical = _as_dict(payload.get("canonical"))
    return canonical or payload


def canonical_thesis_fallback(value: Any, *, target_language: str = "en") -> str:
    thesis_id = _normalize_space(value)
    if not thesis_id:
        return ""
    fallback = _as_dict(_CANONICAL_THESIS_FALLBACKS.get(thesis_id)).get(target_language)
    if fallback:
        return str(fallback)
    if target_language == "en" and thesis_id.startswith("claim-"):
        return "This thesis still needs english canonicalization."
    return ""


def _analysis_payload(project_record: dict[str, Any], *, target_language: str) -> dict[str, Any]:
    return _payload_for_language(_as_dict(project_record.get("analysis")), target_language=target_language)


def _research_payload(project_record: dict[str, Any], *, target_language: str) -> dict[str, Any]:
    return _payload_for_language(_as_dict(project_record.get("research")), target_language=target_language)


def _selected_features(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    features = [_as_dict(item) for item in _as_list(project_record.get("features")) if _as_dict(item)]
    selected = [
        item
        for item in features
        if item.get("selected") is True and _normalize_space(item.get("feature"))
    ]
    if selected:
        return selected
    analysis = _analysis_payload(project_record, target_language=target_language)
    return [
        {
            "feature": _normalize_space(item.get("feature")),
            "priority": item.get("priority"),
            "category": item.get("category"),
            "selected": item.get("selected", True),
        }
        for item in _as_list(analysis.get("feature_decisions"))
        if _as_dict(item) and _normalize_space(_as_dict(item).get("feature"))
    ]


def _milestones(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    project_milestones = [_as_dict(item) for item in _as_list(project_record.get("milestones")) if _as_dict(item)]
    analysis = _analysis_payload(project_record, target_language=target_language)
    analysis_milestones = [_as_dict(item) for item in _as_list(analysis.get("recommended_milestones")) if _as_dict(item)]
    if not project_milestones:
        return analysis_milestones
    if not analysis_milestones:
        return project_milestones

    analysis_by_key = {
        _normalize_space(item.get("id")) or _normalize_space(item.get("name")): item
        for item in analysis_milestones
        if _normalize_space(item.get("id")) or _normalize_space(item.get("name"))
    }
    merged: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    for item in project_milestones:
        key = _normalize_space(item.get("id")) or _normalize_space(item.get("name"))
        base = analysis_by_key.get(key, {})
        merged_item = dict(base)
        merged_item.update(item)
        if not _normalize_space(merged_item.get("phase")) and _normalize_space(base.get("phase")):
            merged_item["phase"] = base.get("phase")
        if (
            target_language == "en"
            and _contains_non_ascii(merged_item.get("criteria"))
            and _normalize_space(base.get("criteria"))
        ):
            merged_item["criteria"] = base.get("criteria")
        elif not _normalize_space(merged_item.get("criteria")) and _normalize_space(base.get("criteria")):
            merged_item["criteria"] = base.get("criteria")
        if not _as_list(merged_item.get("depends_on_use_cases")) and _as_list(base.get("depends_on_use_cases")):
            merged_item["depends_on_use_cases"] = list(_as_list(base.get("depends_on_use_cases")))
        merged.append(merged_item)
        if key:
            used_keys.add(key)
    for item in analysis_milestones:
        key = _normalize_space(item.get("id")) or _normalize_space(item.get("name"))
        if key and key in used_keys:
            continue
        merged.append(dict(item))
    return merged


def _selected_design(
    project_record: dict[str, Any],
    *,
    include_selected_design: bool = True,
) -> dict[str, Any]:
    if not include_selected_design:
        return {}
    selected_id = _normalize_space(project_record.get("selectedDesignId"))
    variants = [_as_dict(item) for item in _as_list(project_record.get("designVariants")) if _as_dict(item)]
    for variant in variants:
        if selected_id and str(variant.get("id", "")).strip() == selected_id:
            return variant
    return _as_dict(variants[0]) if variants else {}


def _product_kind(project_record: dict[str, Any], *, target_language: str) -> str:
    analysis = _analysis_payload(project_record, target_language=target_language)
    planning_context = _as_dict(analysis.get("planning_context"))
    return _normalize_space(planning_context.get("product_kind")) or "generic"


def _research_context(project_record: dict[str, Any], *, target_language: str) -> dict[str, Any]:
    research = _research_payload(project_record, target_language=target_language)
    return _as_dict(research.get("research_context"))


def _planning_context(project_record: dict[str, Any], *, target_language: str) -> dict[str, Any]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    return _as_dict(analysis.get("planning_context"))


def _risk_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    findings = [_as_dict(item) for item in _as_list(analysis.get("red_team_findings")) if _as_dict(item)]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(findings):
        title = _first_text(item.get("title"), limit=120) or _first_text(item.get("recommendation"), limit=120)
        if not title:
            continue
        normalized.append(
            {
                "id": _normalize_space(item.get("id")) or f"risk-{index + 1}",
                "title": title,
                "severity": _normalize_space(item.get("severity")) or "medium",
                "summary": _first_text(item.get("recommendation"), limit=180),
            }
        )
    return normalized[:4]


def _assumption_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    records = [_as_dict(item) for item in _as_list(analysis.get("assumptions")) if _as_dict(item)]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        text = _first_text(item.get("assumption"), limit=180) or _first_text(item, limit=180)
        if not text:
            continue
        normalized.append(
            {
                "id": _normalize_space(item.get("id")) or f"assumption-{index + 1}",
                "title": text,
                "summary": _first_text(item.get("impact"), limit=180) or _first_text(item.get("test"), limit=180),
            }
        )
    return normalized[:4]


def _stop_condition_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    records = [_as_dict(item) for item in _as_list(analysis.get("kill_criteria")) if _as_dict(item)]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        condition = _first_text(item.get("condition"), limit=180)
        if not condition:
            continue
        normalized.append(
            {
                "id": _normalize_space(item.get("id")) or f"stop-{index + 1}",
                "milestone_id": _normalize_space(item.get("milestone_id")),
                "title": condition,
                "summary": _first_text(item.get("rationale"), limit=180),
            }
        )
    return normalized[:4]


def _use_case_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    use_cases = [_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)]
    milestones = _milestones(project_record, target_language=target_language)
    milestone_use_case_ids = {
        _normalize_space(use_case_id)
        for milestone in milestones
        for use_case_id in _as_list(_as_dict(milestone).get("depends_on_use_cases"))
        if _normalize_space(use_case_id)
    }
    required = [
        item
        for item in use_cases
        if _normalize_space(item.get("id"))
        and (
            _normalize_space(item.get("priority")) in {"must", "should"}
            or _normalize_space(item.get("id")) in milestone_use_case_ids
        )
    ]
    return (required or use_cases)[:6]


def _traceability_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    analysis = _analysis_payload(project_record, target_language=target_language)
    return [_as_dict(item) for item in _as_list(analysis.get("traceability")) if _as_dict(item)]


def _thesis_records(project_record: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    research = _research_payload(project_record, target_language=target_language)
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    claim_by_id = {
        _normalize_space(item.get("id")): item
        for item in claims
        if _normalize_space(item.get("id")) and _first_text(item.get("statement"), limit=180)
    }
    claim_by_statement = {
        _first_text(item.get("statement"), limit=180): item
        for item in claims
        if _first_text(item.get("statement"), limit=180)
    }
    winning: list[dict[str, str]] = []
    for item in _as_list(research.get("winning_theses")):
        record = _as_dict(item)
        claim_id = _normalize_space(record.get("claim_id") or record.get("id"))
        candidate = _first_text(item, limit=180)
        fallback_title = canonical_thesis_fallback(claim_id or candidate, target_language=target_language)
        if claim_id and claim_id in claim_by_id and (
            not candidate or _looks_like_machine_token(candidate) or candidate == claim_id
        ):
            claim_title = _first_text(claim_by_id[claim_id].get("statement"), limit=180)
            winning.append(
                {
                    "claim_id": claim_id,
                    "title": (
                        fallback_title
                        if target_language == "en" and (not claim_title or _contains_non_ascii(claim_title))
                        else claim_title
                    ),
                }
            )
            continue
        if candidate in claim_by_id:
            claim_title = _first_text(claim_by_id[candidate].get("statement"), limit=180)
            winning.append(
                {
                    "claim_id": candidate,
                    "title": (
                        fallback_title
                        if target_language == "en" and (not claim_title or _contains_non_ascii(claim_title))
                        else claim_title
                    ),
                }
            )
            continue
        matched = claim_by_statement.get(candidate)
        if matched:
            winning.append(
                {
                    "claim_id": _normalize_space(matched.get("id")),
                    "title": _first_text(matched.get("statement"), limit=180),
                }
            )
            continue
        if candidate and not _looks_like_machine_token(candidate):
            winning.append({"claim_id": "", "title": candidate})
    records: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, thesis in enumerate(winning[:4]):
        thesis_title = _normalize_space(thesis.get("title"))
        thesis_claim_id = _normalize_space(thesis.get("claim_id"))
        matched = (
            claim_by_id.get(thesis_claim_id)
            or claim_by_statement.get(thesis_title)
            or {}
        )
        claim_id = thesis_claim_id or _normalize_space(matched.get("id")) or f"thesis-{index + 1}"
        used_ids.add(claim_id)
        fallback_title = canonical_thesis_fallback(claim_id, target_language=target_language)
        matched_statement = _first_text(matched.get("statement"), limit=180)
        resolved_title = thesis_title
        if target_language == "en" and (_contains_non_ascii(resolved_title) or _looks_like_machine_token(resolved_title)):
            resolved_title = fallback_title or matched_statement or resolved_title
        resolved_summary = matched_statement or resolved_title
        if target_language == "en" and _contains_non_ascii(resolved_summary):
            resolved_summary = fallback_title or resolved_summary
        records.append(
            {
                "id": claim_id,
                "title": resolved_title,
                "summary": resolved_summary,
                "status": _normalize_space(matched.get("status")) or "accepted",
            }
        )
    if records:
        return records
    for index, claim in enumerate(claims[:4]):
        claim_id = _normalize_space(claim.get("id")) or f"thesis-{index + 1}"
        fallback_title = canonical_thesis_fallback(claim_id, target_language=target_language)
        claim_title = _first_text(claim.get("statement"), limit=180)
        if target_language == "en" and (not claim_title or _contains_non_ascii(claim_title)):
            claim_title = fallback_title or claim_title
        records.append(
            {
                "id": claim_id,
                "title": claim_title,
                "summary": claim_title,
                "status": _normalize_space(claim.get("status")) or "accepted",
            }
        )
    return [item for item in records if item.get("title")]


def build_project_frame(
    project_record: dict[str, Any],
    *,
    target_language: str = "en",
    include_selected_design: bool = True,
) -> dict[str, Any]:
    research_context = _research_context(project_record, target_language=target_language)
    planning_context = _planning_context(project_record, target_language=target_language)
    features = _selected_features(project_record, target_language=target_language)
    use_cases = _use_case_records(project_record, target_language=target_language)
    milestones = _milestones(project_record, target_language=target_language)
    risks = _risk_records(project_record, target_language=target_language)
    assumptions = _assumption_records(project_record, target_language=target_language)
    analysis = _analysis_payload(project_record, target_language=target_language)
    selected_design = _selected_design(project_record, include_selected_design=include_selected_design)
    personas = [_as_dict(item) for item in _as_list(analysis.get("personas")) if _as_dict(item)]
    thesis_records = _thesis_records(project_record, target_language=target_language)
    thesis_snapshot = [
        _first_text(item, limit=180)
        for item in _as_list(research_context.get("thesis_snapshot"))[:3]
        if _first_text(item, limit=180)
        and not _looks_like_machine_token(_first_text(item, limit=180))
        and not (target_language == "en" and _contains_non_ascii(_first_text(item, limit=180)))
    ] or [str(item.get("title")) for item in thesis_records[:3] if str(item.get("title", "")).strip()]
    lead_thesis = _first_text(research_context.get("thesis_headline"), limit=220)
    if (
        not lead_thesis
        or _looks_like_machine_token(lead_thesis)
        or (target_language == "en" and _contains_non_ascii(lead_thesis))
    ):
        lead_thesis = _first_text(thesis_records[:1], limit=220)
    return {
        "schema_version": 1,
        "display_language": target_language,
        "product_kind": _product_kind(project_record, target_language=target_language),
        "decision_stage": _normalize_space(research_context.get("decision_stage"))
        or (_normalize_space(_research_payload(project_record, target_language=target_language).get("readiness")) or "unknown"),
        "segment": _first_text(research_context.get("segment"), limit=100)
        or _first_text(planning_context.get("segment"), limit=100),
        "north_star": _first_text(planning_context.get("north_star"), limit=180),
        "core_loop": _first_text(planning_context.get("core_loop"), limit=220),
        "lead_thesis": lead_thesis,
        "thesis_snapshot": thesis_snapshot,
        "key_risks": risks[:3],
        "key_assumptions": assumptions[:3],
        "selected_features": [
            {
                "name": _truncate_text(item.get("feature"), limit=80),
                "priority": item.get("priority"),
                "category": item.get("category"),
            }
            for item in features[:6]
        ],
        "primary_use_cases": [
            {
                "id": _normalize_space(item.get("id")),
                "title": _first_text(item.get("title"), limit=120),
                "priority": item.get("priority"),
            }
            for item in use_cases[:5]
        ],
        "milestones": [
            {
                "id": _normalize_space(item.get("id")),
                "name": _first_text(item.get("name"), limit=80),
                "phase": _normalize_space(item.get("phase")),
            }
            for item in milestones[:4]
        ],
        "primary_personas": [
            {
                "name": _first_text(item.get("name"), limit=64),
                "role": _first_text(item.get("role"), limit=120),
            }
            for item in personas[:2]
        ],
        "selected_design": (
            {
                "id": _normalize_space(selected_design.get("id")),
                "name": _first_text(selected_design.get("pattern_name"), limit=80),
                "description": _first_text(selected_design.get("description"), limit=160),
            }
            if selected_design
            else {}
        ),
        "summary": _first_text(analysis.get("judge_summary"), limit=220)
        or _first_text(_research_payload(project_record, target_language=target_language).get("judge_summary"), limit=220),
    }


def build_decision_graph(
    project_record: dict[str, Any],
    *,
    target_language: str = "en",
    compact: bool = False,
    include_selected_design: bool = True,
) -> dict[str, Any]:
    thesis_records = _thesis_records(project_record, target_language=target_language)
    risk_records = _risk_records(project_record, target_language=target_language)
    assumption_records = _assumption_records(project_record, target_language=target_language)
    stop_records = _stop_condition_records(project_record, target_language=target_language)
    use_cases = _use_case_records(project_record, target_language=target_language)
    features = _selected_features(project_record, target_language=target_language)
    milestones = _milestones(project_record, target_language=target_language)
    traceability = _traceability_records(project_record, target_language=target_language)
    selected_design = _selected_design(project_record, include_selected_design=include_selected_design)

    feature_node_ids = {
        _normalize_space(item.get("feature")): _slug(item.get("feature"), prefix="feature")
        for item in features
        if _normalize_space(item.get("feature"))
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_node(node_id: str, node_type: str, label: str, *, phase: str, summary: str = "", priority: str = "") -> None:
        if not node_id or not label or any(item["id"] == node_id for item in nodes):
            return
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": _truncate_text(label, limit=120),
                "phase": phase,
                "summary": _truncate_text(summary or label, limit=180),
                "priority": priority or None,
            }
        )

    def add_edge(source: str, target: str, relation: str) -> None:
        if not source or not target or source == target:
            return
        edge_id = f"{source}->{relation}->{target}"
        if any(item["id"] == edge_id for item in edges):
            return
        edges.append({"id": edge_id, "from": source, "to": target, "relation": relation})

    thesis_limit = 3 if compact else 4
    use_case_limit = 5 if compact else 6
    feature_limit = 5 if compact else 6
    milestone_limit = 3 if compact else 4

    for item in thesis_records[:thesis_limit]:
        add_node(item["id"], "thesis", item["title"], phase="research", summary=item.get("summary", ""), priority=item.get("status", ""))
    for item in risk_records[: (3 if compact else 4)]:
        add_node(item["id"], "risk", item["title"], phase="planning", summary=item.get("summary", ""), priority=item.get("severity", ""))
    for item in assumption_records[: (3 if compact else 4)]:
        add_node(item["id"], "assumption", item["title"], phase="planning", summary=item.get("summary", ""))
    for item in stop_records[: (2 if compact else 4)]:
        add_node(item["id"], "stop_condition", item["title"], phase="planning", summary=item.get("summary", ""))
    for item in use_cases[:use_case_limit]:
        use_case_id = _normalize_space(item.get("id"))
        add_node(use_case_id, "use_case", _first_text(item.get("title"), limit=120), phase="planning", priority=_normalize_space(item.get("priority")))
    for item in features[:feature_limit]:
        feature_name = _normalize_space(item.get("feature"))
        add_node(feature_node_ids.get(feature_name, ""), "feature", feature_name, phase="planning", priority=_normalize_space(item.get("priority")))
    for item in milestones[:milestone_limit]:
        milestone_id = _normalize_space(item.get("id"))
        add_node(milestone_id, "milestone", _first_text(item.get("name"), limit=80), phase="planning", summary=_first_text(item.get("criteria"), limit=180))
    if selected_design:
        design_id = f"design:{_normalize_space(selected_design.get('id')) or 'selected'}"
        add_node(
            design_id,
            "design",
            _first_text(selected_design.get("pattern_name"), limit=80) or "Selected design",
            phase="design",
            summary=_first_text(selected_design.get("description"), limit=180),
        )

    for record in traceability[: (8 if not compact else 6)]:
        thesis_id = _normalize_space(record.get("claim_id"))
        use_case_id = _normalize_space(record.get("use_case_id"))
        feature_name = _normalize_space(record.get("feature"))
        milestone_id = _normalize_space(record.get("milestone_id"))
        feature_id = feature_node_ids.get(feature_name, _slug(feature_name, prefix="feature")) if feature_name else ""
        if thesis_id and not any(item["id"] == thesis_id for item in nodes) and _first_text(record.get("claim"), limit=120):
            add_node(thesis_id, "thesis", _first_text(record.get("claim"), limit=120), phase="research")
        if feature_name and feature_id and not any(item["id"] == feature_id for item in nodes):
            add_node(feature_id, "feature", feature_name, phase="planning")
        add_edge(thesis_id, use_case_id, "supports")
        add_edge(use_case_id, feature_id, "implemented_by")
        add_edge(feature_id, milestone_id, "proves")

    milestone_ids = {_normalize_space(item.get("id")) for item in milestones}
    for milestone in milestones[:milestone_limit]:
        milestone_id = _normalize_space(milestone.get("id"))
        for use_case_id in _as_list(milestone.get("depends_on_use_cases")):
            add_edge(_normalize_space(use_case_id), milestone_id, "required_for")

    for stop in stop_records[: (2 if compact else 4)]:
        add_edge(stop["id"], _normalize_space(stop.get("milestone_id")), "halts")
    for risk, stop in zip(risk_records, stop_records, strict=False):
        add_edge(risk["id"], stop["id"], "constrains")
    for assumption, thesis in zip(assumption_records, thesis_records, strict=False):
        add_edge(assumption["id"], thesis["id"], "tests")

    if selected_design:
        design_node_id = f"design:{_normalize_space(selected_design.get('id')) or 'selected'}"
        screen_count = len(_as_list(_as_dict(selected_design.get("prototype")).get("screens"))) or 3
        for use_case in use_cases[: min(screen_count, 3)]:
            add_edge(design_node_id, _normalize_space(use_case.get("id")), "expresses")
        for feature in features[:3]:
            add_edge(design_node_id, feature_node_ids.get(_normalize_space(feature.get("feature")), ""), "highlights")

    coverage_summary = _as_dict(_analysis_payload(project_record, target_language=target_language).get("coverage_summary"))
    missing_traceability = [
        _normalize_space(item)
        for item in _as_list(
            coverage_summary.get("required_use_cases_without_traceability")
            or coverage_summary.get("use_cases_without_traceability")
        )
        if _normalize_space(item)
    ]
    open_links = []
    if missing_traceability:
        open_links.append(
            {
                "id": "missing-required-traceability",
                "title": "Required use cases still need traceability links",
                "details": missing_traceability[:4],
            }
        )
    if milestones and not stop_records:
        open_links.append(
            {
                "id": "missing-stop-conditions",
                "title": "Milestones are missing explicit stop conditions",
                "details": [_first_text(item.get("name"), limit=80) for item in milestones[:3]],
            }
        )
    if selected_design and not any(edge["from"].startswith("design:") for edge in edges):
        open_links.append(
            {
                "id": "unlinked-selected-design",
                "title": "Selected design is not linked to primary use cases yet",
                "details": [_first_text(selected_design.get("pattern_name"), limit=80)],
            }
        )

    critical_paths = []
    for index, record in enumerate(traceability[:3]):
        node_ids = [
            _normalize_space(record.get("claim_id")),
            _normalize_space(record.get("use_case_id")),
            feature_node_ids.get(_normalize_space(record.get("feature")), ""),
            _normalize_space(record.get("milestone_id")),
        ]
        node_ids = [item for item in node_ids if item]
        if len(node_ids) < 2:
            continue
        critical_paths.append(
            {
                "id": f"path-{index + 1}",
                "title": _truncate_text(
                    f"{_first_text(record.get('claim'), limit=80)} -> {_first_text(record.get('use_case'), limit=80)}",
                    limit=140,
                ),
                "node_ids": node_ids,
            }
        )

    return {
        "schema_version": 1,
        "display_language": target_language,
        "nodes": nodes[: (18 if compact else 28)],
        "edges": edges[: (28 if compact else 44)],
        "critical_paths": critical_paths[:3],
        "open_links": open_links[:4],
        "stats": {
            "node_count": len(nodes[: (18 if compact else 28)]),
            "edge_count": len(edges[: (28 if compact else 44)]),
            "open_link_count": len(open_links[:4]),
        },
    }


def build_consistency_snapshot(
    project_record: dict[str, Any],
    *,
    target_language: str = "en",
    decision_graph: dict[str, Any] | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    graph = decision_graph or build_decision_graph(project_record, target_language=target_language, compact=True)
    current_fingerprint = fingerprint or ""
    coverage_summary = _as_dict(_analysis_payload(project_record, target_language=target_language).get("coverage_summary"))
    milestones = _milestones(project_record, target_language=target_language)
    selected_design = _selected_design(project_record)
    variants = [_as_dict(item) for item in _as_list(project_record.get("designVariants")) if _as_dict(item)]
    build_fingerprint = _normalize_space(project_record.get("buildDecisionFingerprint"))
    issues: list[dict[str, Any]] = []

    missing_traceability = [
        _normalize_space(item)
        for item in _as_list(
            coverage_summary.get("required_use_cases_without_traceability")
            or coverage_summary.get("use_cases_without_traceability")
        )
        if _normalize_space(item)
    ]
    if missing_traceability:
        issues.append(
            {
                "id": "required-use-case-traceability",
                "severity": "high",
                "title": "Required use cases are not fully connected",
                "detail": ", ".join(missing_traceability[:4]),
            }
        )
    if milestones and not _stop_condition_records(project_record, target_language=target_language):
        issues.append(
            {
                "id": "milestones-without-stop-conditions",
                "severity": "high",
                "title": "Milestones still lack explicit stop conditions",
                "detail": ", ".join(_first_text(item.get("name"), limit=80) for item in milestones[:3]),
            }
        )
    if variants and not selected_design:
        issues.append(
            {
                "id": "missing-selected-design",
                "severity": "medium",
                "title": "A selected design baseline is missing",
                "detail": "Design comparison exists, but no baseline is locked for downstream delivery.",
            }
        )
    if selected_design:
        selected_design_fingerprint = _normalize_space(selected_design.get("decision_context_fingerprint"))
        if current_fingerprint and selected_design_fingerprint and selected_design_fingerprint != current_fingerprint:
            issues.append(
                {
                    "id": "stale-selected-design",
                    "severity": "medium",
                    "title": "Selected design was generated from an older decision context",
                    "detail": _first_text(selected_design.get("pattern_name"), limit=80),
                }
            )
        design_edges = [
            item
            for item in _as_list(graph.get("edges"))
            if str(_as_dict(item).get("from", "")).startswith("design:")
        ]
        if not design_edges:
            issues.append(
                {
                    "id": "selected-design-without-links",
                    "severity": "medium",
                    "title": "Selected design is not linked to scope decisions",
                    "detail": "Connect the chosen design to primary use cases and selected features.",
                }
            )
    if build_fingerprint and current_fingerprint and build_fingerprint != current_fingerprint:
        issues.append(
            {
                "id": "stale-build-context",
                "severity": "high",
                "title": "Build artifact was generated from an older decision context",
                "detail": "Re-run development so the build reflects the latest research and planning decisions.",
            }
        )

    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    top_severity = max((severity_rank.get(str(item.get("severity")), 0) for item in issues), default=0)
    return {
        "status": "critical" if top_severity >= 3 else "attention" if top_severity >= 1 else "healthy",
        "issues": issues[:6],
        "stats": {
            "node_count": int(_as_dict(graph.get("stats")).get("node_count", 0) or 0),
            "edge_count": int(_as_dict(graph.get("stats")).get("edge_count", 0) or 0),
            "issue_count": len(issues[:6]),
        },
    }


def build_lifecycle_decision_context(
    project_record: dict[str, Any],
    *,
    target_language: str = "en",
    compact: bool = False,
) -> dict[str, Any]:
    fingerprint_frame = build_project_frame(
        project_record,
        target_language="en",
        include_selected_design=False,
    )
    fingerprint_graph = build_decision_graph(
        project_record,
        target_language="en",
        compact=True,
        include_selected_design=False,
    )
    english_frame = build_project_frame(project_record, target_language="en")
    english_graph = build_decision_graph(project_record, target_language="en", compact=compact)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "project_frame": fingerprint_frame,
                "decision_graph": fingerprint_graph,
            },
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    display_frame = english_frame if target_language == "en" else build_project_frame(project_record, target_language=target_language)
    display_graph = english_graph if target_language == "en" else build_decision_graph(project_record, target_language=target_language, compact=compact)
    consistency = build_consistency_snapshot(
        project_record,
        target_language=target_language,
        decision_graph=display_graph,
        fingerprint=fingerprint,
    )
    return {
        "schema_version": 1,
        "display_language": target_language,
        "fingerprint": fingerprint,
        "project_frame": display_frame,
        "decision_graph": display_graph,
        "consistency_snapshot": consistency,
    }
