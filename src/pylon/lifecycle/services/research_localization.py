"""Pure research localization helpers for lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_RESEARCH_LOCALIZATION_FIXED_JA = {
    "external url evidence is present": "外部 URL に grounded された evidence があります。",
    "external url evidence is missing": "外部 URL に grounded された evidence が不足しています。",
    "dissent coverage present": "主要仮説に対する反証が生成されています。",
    "dissent coverage missing": "主要仮説に対する反証が不足しています。",
    "confidence floor satisfied": "confidence floor は planning の閾値を満たしています。",
    "all critical nodes healthy": "critical node はすべて正常です。",
    "Address degraded nodes, strengthen source grounding, and re-evaluate blocked claims.": "degraded node を補修し、source grounding を補強したうえで、blocked claim を再評価します。",
    "Claims that survived dissent are passed to planning together with unresolved questions.": "反証を踏まえて残った仮説を、未解決の問いと一緒に planning に引き渡します。",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate_research_text(value: Any, *, limit: int = 220) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{(clipped or text[:limit].strip())}..."


def _contains_japanese(text: str) -> bool:
    return any((("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")) for ch in text)


def _looks_like_machine_token(text: str) -> bool:
    normalized = text.strip()
    return bool(
        normalized
        and (
            normalized.startswith(("http://", "https://", "project://"))
            or all(ch.islower() or ch.isdigit() or ch in "_.:-" for ch in normalized)
        )
    )


def _first_research_text(value: Any, *, default: str = "", char_limit: int = 180) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_research_text(item, char_limit=char_limit)
            if text:
                return text
        return default
    if isinstance(value, Mapping):
        for key in (
            "question",
            "statement",
            "thesis",
            "claim_statement",
            "core_claim",
            "primary",
            "signal",
            "pain_point",
            "segment",
            "summary",
            "title",
            "name",
            "text",
            "draft",
            "argument",
            "recommendation",
            "rationale",
            "target",
            "notes",
        ):
            if key in value:
                text = _first_research_text(value.get(key), char_limit=char_limit)
                if text:
                    return text
        return default
    text = _truncate_research_text(value, limit=char_limit)
    return text or default


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalized_research_strings(values: Any, *, limit: int = 3, char_limit: int = 180) -> list[str]:
    if isinstance(values, list):
        flattened = [_first_research_text(item, char_limit=char_limit) for item in values]
    else:
        flattened = [_first_research_text(values, char_limit=char_limit)]
    return _dedupe_strings([item for item in flattened if item])[:limit]


def translate_fixed_research_text(value: Any, *, target_language: str) -> Any:
    text = str(value or "").strip()
    if not text or target_language != "ja":
        return value
    translated = _RESEARCH_LOCALIZATION_FIXED_JA.get(text)
    if translated:
        return translated
    if text.startswith("confidence floor="):
        return text.replace("confidence floor=", "confidence floor は ").replace(", winning_theses=", "、winning thesis 数は ") + " です。"
    if text.endswith(" unresolved critical dissent remain"):
        count = text.split(" ", 1)[0]
        return f"未解決の critical dissent が {count} 件残っています。"
    if text.startswith("degraded nodes: "):
        return f"degraded node: {text.removeprefix('degraded nodes: ')}"
    return value


def _translatable_research_text(value: Any, *, char_limit: int) -> str:
    text = _first_research_text(value, char_limit=char_limit)
    if not text or _contains_japanese(text) or _looks_like_machine_token(text):
        return ""
    return text


def research_localization_payload(research: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    def assign(key: str, value: Any) -> None:
        if value:
            payload[key] = value

    def translated_list(values: Any, *, limit: int = 8) -> list[str]:
        return [
            text
            for text in _normalized_research_strings(values, limit=limit, char_limit=280)
            if text and not _contains_japanese(text) and not _looks_like_machine_token(text)
        ]

    assign("market_size", _translatable_research_text(research.get("market_size"), char_limit=220))
    assign("trends", translated_list(research.get("trends"), limit=4))
    assign("opportunities", translated_list(research.get("opportunities"), limit=4))
    assign("threats", translated_list(research.get("threats"), limit=4))
    tech = _as_dict(research.get("tech_feasibility"))
    tech_notes = _translatable_research_text(tech.get("notes"), char_limit=280)
    if tech_notes:
        assign("tech_feasibility", {"notes": tech_notes})
    user = _as_dict(research.get("user_research"))
    user_payload = {
        "signals": translated_list(user.get("signals"), limit=4),
        "pain_points": translated_list(user.get("pain_points"), limit=4),
    }
    segment = _translatable_research_text(user.get("segment"), char_limit=80)
    if segment:
        user_payload["segment"] = segment
    if any(user_payload.values()):
        assign("user_research", user_payload)
    claims = []
    for item in _as_list(research.get("claims")):
        claim = _as_dict(item)
        statement = _first_research_text(claim.get("statement"), char_limit=220)
        if not statement or _contains_japanese(statement) or _looks_like_machine_token(statement):
            continue
        claims.append({"id": str(claim.get("id", "")), "statement": statement})
    assign("claims", claims)
    dissent = []
    for item in _as_list(research.get("dissent")):
        record = _as_dict(item)
        translated = {
            "id": str(record.get("id", "")),
            "argument": _first_research_text(record.get("argument"), char_limit=220),
            "recommended_test": _first_research_text(record.get("recommended_test"), char_limit=220),
            "resolution": _first_research_text(record.get("resolution"), char_limit=220),
        }
        if any(
            text and not _contains_japanese(text) and not _looks_like_machine_token(text)
            for text in translated.values()
            if isinstance(text, str)
        ):
            dissent.append(translated)
    assign("dissent", dissent)
    assign("open_questions", translated_list(research.get("open_questions"), limit=8))
    assign("winning_theses", translated_list(research.get("winning_theses"), limit=4))
    assign("judge_summary", _translatable_research_text(research.get("judge_summary"), char_limit=280))
    quality_gates = []
    for item in _as_list(research.get("quality_gates")):
        gate = _as_dict(item)
        reason = _first_research_text(gate.get("reason"), char_limit=220)
        if not reason or _contains_japanese(reason):
            continue
        quality_gates.append({"id": str(gate.get("id", "")), "reason": reason})
    assign("quality_gates", quality_gates)
    remediation_plan = _as_dict(research.get("remediation_plan"))
    objective = _first_research_text(remediation_plan.get("objective"), char_limit=220)
    if objective and not _contains_japanese(objective):
        assign("remediation_plan", {"objective": objective})
    execution_trace = []
    for item in _as_list(research.get("execution_trace")):
        trace = _as_dict(item)
        objective = _first_research_text(trace.get("objective"), char_limit=220)
        if objective and not _contains_japanese(objective):
            execution_trace.append({"iteration": trace.get("iteration"), "objective": objective})
    assign("execution_trace", execution_trace)
    return payload


def merge_research_localization(
    research: dict[str, Any],
    translated: dict[str, Any],
) -> dict[str, Any]:
    localized = dict(research)
    if translated.get("market_size"):
        localized["market_size"] = translated["market_size"]
    for key in ("trends", "opportunities", "threats", "open_questions", "winning_theses"):
        values = _normalized_research_strings(translated.get(key), limit=8, char_limit=280)
        if values:
            localized[key] = values
    tech = _as_dict(localized.get("tech_feasibility"))
    translated_tech = _as_dict(translated.get("tech_feasibility"))
    if translated_tech.get("notes"):
        localized["tech_feasibility"] = {**tech, "notes": _first_research_text(translated_tech.get("notes"), char_limit=280)}
    user = _as_dict(localized.get("user_research"))
    translated_user = _as_dict(translated.get("user_research"))
    if translated_user:
        localized["user_research"] = {
            **user,
            "signals": _normalized_research_strings(translated_user.get("signals"), limit=4, char_limit=220) or _normalized_research_strings(user.get("signals"), limit=4, char_limit=220),
            "pain_points": _normalized_research_strings(translated_user.get("pain_points"), limit=4, char_limit=220) or _normalized_research_strings(user.get("pain_points"), limit=4, char_limit=220),
            "segment": _first_research_text(translated_user.get("segment"), default=str(user.get("segment", "")), char_limit=80),
        }
    translated_claims = {
        str(_as_dict(item).get("id", "")): _first_research_text(_as_dict(item).get("statement"), char_limit=220)
        for item in _as_list(translated.get("claims"))
        if str(_as_dict(item).get("id", "")).strip()
    }
    if translated_claims:
        localized["claims"] = [
            {
                **_as_dict(item),
                "statement": translated_claims.get(str(_as_dict(item).get("id", "")), _as_dict(item).get("statement")),
            }
            for item in _as_list(localized.get("claims"))
        ]
    translated_dissent = {
        str(_as_dict(item).get("id", "")): _as_dict(item)
        for item in _as_list(translated.get("dissent"))
        if str(_as_dict(item).get("id", "")).strip()
    }
    if translated_dissent:
        localized["dissent"] = [
            {
                **_as_dict(item),
                **{
                    key: value
                    for key, value in translated_dissent.get(str(_as_dict(item).get("id", "")), {}).items()
                    if key in {"argument", "recommended_test", "resolution"} and value
                },
            }
            for item in _as_list(localized.get("dissent"))
        ]
    if translated.get("judge_summary"):
        localized["judge_summary"] = _first_research_text(translated.get("judge_summary"), char_limit=280)
    translated_gate_reasons = {
        str(_as_dict(item).get("id", "")): _first_research_text(_as_dict(item).get("reason"), char_limit=220)
        for item in _as_list(translated.get("quality_gates"))
        if str(_as_dict(item).get("id", "")).strip()
    }
    if translated_gate_reasons:
        localized["quality_gates"] = [
            {
                **_as_dict(item),
                "reason": translated_gate_reasons.get(str(_as_dict(item).get("id", "")), _as_dict(item).get("reason")),
            }
            for item in _as_list(localized.get("quality_gates"))
        ]
    remediation_plan = _as_dict(localized.get("remediation_plan"))
    translated_plan = _as_dict(translated.get("remediation_plan"))
    if remediation_plan and translated_plan.get("objective"):
        localized["remediation_plan"] = {
            **remediation_plan,
            "objective": _first_research_text(translated_plan.get("objective"), char_limit=220),
        }
    translated_trace = {
        str(_as_dict(item).get("iteration", "")): _first_research_text(_as_dict(item).get("objective"), char_limit=220)
        for item in _as_list(translated.get("execution_trace"))
        if str(_as_dict(item).get("iteration", "")).strip()
    }
    if translated_trace:
        localized["execution_trace"] = [
            {
                **_as_dict(item),
                "objective": translated_trace.get(str(_as_dict(item).get("iteration", "")), _as_dict(item).get("objective")),
            }
            for item in _as_list(localized.get("execution_trace"))
        ]
    return localized
