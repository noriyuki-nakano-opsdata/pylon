"""Shared runtime shaping helpers for lifecycle research output."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_RESEARCH_TEXT_KEYS = (
    "summary",
    "statement",
    "title",
    "name",
    "label",
    "question",
    "reason",
    "rationale",
    "opportunity",
    "pain_point",
    "pain",
    "threat",
    "finding",
    "notes",
    "description",
    "segment",
    "market_size",
    "pricing",
    "target",
    "trend",
    "argument",
    "recommended_test",
    "context",
    "text",
    "value",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def truncate_research_text(value: Any, *, limit: int = 220) -> str:
    text = normalize_space(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    clipped = clipped or text[:limit].strip()
    return f"{clipped}..."


def parse_research_structured_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    raw = str(value or "").strip()
    if not raw or raw[0] not in "{[":
        return value
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(raw)
        except Exception:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return value


def research_text_fragments(
    value: Any,
    *,
    max_items: int = 6,
    char_limit: int = 180,
) -> list[str]:
    items: list[str] = []

    def _visit(current: Any) -> None:
        if len(items) >= max_items:
            return
        parsed = parse_research_structured_value(current)
        if isinstance(parsed, list):
            for child in parsed:
                _visit(child)
                if len(items) >= max_items:
                    break
            return
        if isinstance(parsed, dict):
            preferred: list[str] = []
            for key in _RESEARCH_TEXT_KEYS:
                if key not in parsed:
                    continue
                for fragment in research_text_fragments(parsed.get(key), max_items=1, char_limit=char_limit):
                    if fragment:
                        preferred.append(fragment)
            if preferred:
                items.extend(preferred[: max_items - len(items)])
                return
            for child in parsed.values():
                _visit(child)
                if len(items) >= max_items:
                    break
            return
        text = truncate_research_text(parsed, limit=char_limit)
        if text:
            items.append(text)

    _visit(value)
    return dedupe_strings(items)[:max_items]


def first_research_text(value: Any, *, default: str = "", char_limit: int = 180) -> str:
    fragments = research_text_fragments(value, max_items=1, char_limit=char_limit)
    return fragments[0] if fragments else default


def claim_confidence_overrides(value: Any) -> dict[str, Any]:
    parsed = parse_research_structured_value(value)
    overrides: dict[str, Any] = {}
    if isinstance(parsed, dict):
        for claim_id, confidence in parsed.items():
            normalized_id = first_research_text(claim_id, char_limit=64)
            if normalized_id:
                overrides[normalized_id] = confidence
        return overrides
    if not isinstance(parsed, list):
        return overrides
    for item in parsed:
        payload = _as_dict(parse_research_structured_value(item))
        claim_id = first_research_text(payload.get("claim_id") or payload.get("id"), char_limit=64)
        confidence = payload.get("confidence", payload.get("score"))
        if claim_id and confidence is not None:
            overrides[claim_id] = confidence
    return overrides


def normalized_research_strings(values: Any, *, limit: int = 3, char_limit: int = 180) -> list[str]:
    return research_text_fragments(values, max_items=limit, char_limit=char_limit)


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def research_runtime_output(research: dict[str, Any]) -> dict[str, Any]:
    quality_gates = [
        {
            "id": _as_dict(item).get("id"),
            "passed": _as_dict(item).get("passed"),
            "reason": first_research_text(_as_dict(item).get("reason"), char_limit=160),
        }
        for item in _as_list(research.get("quality_gates"))[:4]
        if _as_dict(item)
    ]
    claims = [
        {
            "id": _as_dict(item).get("id"),
            "statement": first_research_text(_as_dict(item).get("statement"), char_limit=180),
            "status": _as_dict(item).get("status"),
            "confidence": _as_dict(item).get("confidence"),
        }
        for item in _as_list(research.get("claims"))[:4]
        if _as_dict(item)
    ]
    remediation_plan = _as_dict(research.get("remediation_plan"))
    autonomous_remediation = _as_dict(research.get("autonomous_remediation"))
    return {
        "kind": "research-runtime-output",
        "readiness": research.get("readiness"),
        "display_language": research.get("display_language", "ja"),
        "localization_status": research.get("localization_status"),
        "judge_summary": first_research_text(research.get("judge_summary"), char_limit=220),
        "winning_theses": normalized_research_strings(
            research.get("winning_theses"),
            limit=3,
            char_limit=180,
        ),
        "claims": claims,
        "quality_gates": quality_gates,
        "source_links": _as_list(research.get("source_links"))[:4],
        "remediation_plan": (
            {
                "objective": first_research_text(remediation_plan.get("objective"), char_limit=180),
                "retryNodeIds": _as_list(remediation_plan.get("retryNodeIds"))[:4],
            }
            if remediation_plan
            else None
        ),
        "autonomous_remediation": (
            {
                "status": autonomous_remediation.get("status"),
                "attemptCount": autonomous_remediation.get("attemptCount"),
                "maxAttempts": autonomous_remediation.get("maxAttempts"),
                "remainingAttempts": autonomous_remediation.get("remainingAttempts"),
                "objective": first_research_text(autonomous_remediation.get("objective"), char_limit=180),
                "retryNodeIds": _as_list(autonomous_remediation.get("retryNodeIds"))[:4],
                "blockingGateIds": _as_list(autonomous_remediation.get("blockingGateIds"))[:4],
                "stopReason": first_research_text(autonomous_remediation.get("stopReason"), char_limit=180),
            }
            if autonomous_remediation
            else None
        ),
    }


def research_autonomous_remediation_state(
    research: dict[str, Any],
    *,
    quality_gates: list[dict[str, Any]],
    remediation_plan: dict[str, Any] | None,
    remediation_context: dict[str, Any],
    readiness: str,
) -> dict[str, Any]:
    failed_gates = [
        _as_dict(item)
        for item in quality_gates
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ]
    blocking_node_ids = [
        str(item)
        for gate in failed_gates
        for item in _as_list(gate.get("blockingNodeIds"))
        if str(item).strip()
    ]
    retry_node_ids = [
        str(item)
        for item in _as_list(_as_dict(remediation_plan).get("retryNodeIds"))
        if str(item).strip()
    ]
    if not retry_node_ids:
        retry_node_ids = [
            str(item)
            for item in _as_list(remediation_context.get("retryNodeIds"))
            if str(item).strip()
        ]
    missing_source_classes = [
        str(item)
        for node in _as_list(research.get("node_results"))
        for item in _as_list(_as_dict(node).get("missingSourceClasses"))
        if str(item).strip()
    ]
    attempt_count = int(remediation_context.get("attempt", 0) or 0)
    max_attempts = int(remediation_context.get("maxAttempts", 2) or 2)
    remaining_attempts = max(0, max_attempts - attempt_count)
    auto_runnable = readiness != "ready" and bool(failed_gates) and remaining_attempts > 0
    if readiness == "ready":
        status = "resolved" if attempt_count > 0 else "not_needed"
        stop_reason = ""
    elif auto_runnable:
        status = "retrying" if attempt_count > 0 else "queued"
        stop_reason = ""
    else:
        status = "blocked"
        stop_reason = (
            "Autonomous remediation budget is exhausted."
            if failed_gates and remaining_attempts == 0
            else "The current research blockers need operator guidance."
        )
    return {
        "status": status,
        "attemptCount": attempt_count,
        "maxAttempts": max_attempts,
        "remainingAttempts": remaining_attempts,
        "autoRunnable": auto_runnable,
        "objective": str(
            _as_dict(remediation_plan).get("objective")
            or remediation_context.get("objective")
            or ""
        ),
        "retryNodeIds": list(dict.fromkeys(retry_node_ids))[:6],
        "blockingGateIds": list(
            dict.fromkeys(
                str(gate.get("id", ""))
                for gate in failed_gates
                if str(gate.get("id", "")).strip()
            )
        )[:6],
        "blockingNodeIds": list(dict.fromkeys(blocking_node_ids))[:6],
        "missingSourceClasses": list(dict.fromkeys(missing_source_classes))[:8],
        "blockingSummary": [
            first_research_text(_as_dict(gate).get("reason"), char_limit=180)
            for gate in failed_gates
            if first_research_text(_as_dict(gate).get("reason"), char_limit=180)
        ][:4],
        "lastBlockingSignature": "|".join(
            sorted(
                str(gate.get("id", ""))
                for gate in failed_gates
                if str(gate.get("id", "")).strip()
            )
        ),
        "stopReason": stop_reason,
    }


def research_judgement_artifact(research: dict[str, Any]) -> dict[str, Any]:
    node_results = [
        {
            "nodeId": _as_dict(item).get("nodeId"),
            "status": _as_dict(item).get("status"),
            "parseStatus": _as_dict(item).get("parseStatus"),
            "retryCount": _as_dict(item).get("retryCount"),
            "degradationReasons": _as_list(_as_dict(item).get("degradationReasons"))[:4],
            "missingSourceClasses": _as_list(_as_dict(item).get("missingSourceClasses"))[:4],
        }
        for item in _as_list(research.get("node_results"))[:8]
        if _as_dict(item)
    ]
    return {
        "name": "research-judgement",
        "kind": "research",
        **research_runtime_output(research),
        "node_results": node_results,
    }
