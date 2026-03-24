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


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _display_text(
    value: Any,
    *,
    target_language: str,
    fallback: str = "",
    char_limit: int = 180,
) -> str:
    text = _first_research_text(value, char_limit=char_limit)
    if not text:
        return fallback
    if target_language == "en" and _contains_japanese(text):
        return fallback
    return text


def _display_text_list(
    values: Any,
    *,
    target_language: str,
    limit: int,
    char_limit: int = 180,
) -> list[str]:
    items = _normalized_research_strings(values, limit=limit, char_limit=char_limit)
    if target_language != "en":
        return items
    return [item for item in items if not _contains_japanese(item)]


def _claim_statement_lookup(research: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in _as_list(research.get("claims")):
        claim = _as_dict(item)
        claim_id = _normalize_space(claim.get("id"))
        statement = _first_research_text(claim.get("statement"), char_limit=220)
        if claim_id and statement:
            lookup[claim_id] = statement
    return lookup


def _resolved_winning_theses(
    research: dict[str, Any],
    *,
    target_language: str,
    limit: int,
    char_limit: int,
) -> list[str]:
    claim_lookup = _claim_statement_lookup(research)
    resolved: list[str] = []
    raw_values = research.get("winning_theses")
    items = _as_list(raw_values) if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
    for item in items:
        record = _as_dict(item)
        claim_id = _normalize_space(record.get("claim_id") or record.get("id"))
        candidate = _first_research_text(item, char_limit=char_limit)
        if claim_id and claim_id in claim_lookup and (
            not candidate or _looks_like_machine_token(candidate) or candidate == claim_id
        ):
            candidate = claim_lookup[claim_id]
        elif candidate in claim_lookup:
            candidate = claim_lookup[candidate]
        if target_language == "en" and _contains_japanese(candidate):
            candidate = claim_lookup.get(claim_id or _normalize_space(item), "")
        candidate = _truncate_research_text(candidate, limit=char_limit)
        if candidate and candidate not in resolved:
            resolved.append(candidate)
        if len(resolved) >= limit:
            break
    return resolved


def _research_decision_stage(research: dict[str, Any]) -> str:
    readiness = _normalize_space(research.get("readiness")).lower()
    autonomous = _as_dict(research.get("autonomous_remediation"))
    if readiness == "ready":
        return "ready_for_planning"
    if autonomous.get("conditionalHandoffAllowed") is True:
        return "conditional_handoff"
    return "needs_research_rework"


def _research_decision_stage_label(stage: str, *, target_language: str) -> str:
    if target_language == "ja":
        return {
            "ready_for_planning": "企画へ渡せる状態",
            "conditional_handoff": "前提つきで企画に進める状態",
            "needs_research_rework": "再調査で根拠を補う状態",
        }.get(stage, "調査中")
    return {
        "ready_for_planning": "Ready for planning",
        "conditional_handoff": "Conditional handoff",
        "needs_research_rework": "Needs research rework",
    }.get(stage, "In research")


def _research_target_floor(research: dict[str, Any]) -> float:
    autonomous = _as_dict(research.get("autonomous_remediation"))
    return _float_value(autonomous.get("targetConfidenceFloor") or 0.6) or 0.6


def _research_source_count(research: dict[str, Any]) -> int:
    source_links = [
        str(item).strip()
        for item in _as_list(research.get("source_links"))
        if str(item).strip().lower().startswith(("http://", "https://"))
    ]
    evidence_links = [
        str(_as_dict(item).get("source_ref", "")).strip()
        for item in _as_list(research.get("evidence"))
        if str(_as_dict(item).get("source_type", "")).strip() == "url"
        and str(_as_dict(item).get("source_ref", "")).strip().lower().startswith(("http://", "https://"))
    ]
    return len(list(dict.fromkeys([*source_links, *evidence_links])))


def _research_blocking_summary(
    research: dict[str, Any],
    *,
    target_language: str,
) -> list[str]:
    quality_gates = [
        _as_dict(item)
        for item in _as_list(research.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ]
    reasons = [
        _display_text(
            item.get("reason"),
            target_language=target_language,
            fallback=(
                "Close the blocking evidence gap before planning."
                if target_language == "en"
                else "企画へ渡す前に、止まっている根拠ギャップを埋めます。"
            ),
            char_limit=180,
        )
        for item in quality_gates[:3]
    ]
    return [item for item in reasons if item]


def _research_evidence_priorities(
    research: dict[str, Any],
    *,
    target_language: str,
) -> list[str]:
    priorities: list[str] = []
    remediation = _as_dict(research.get("remediation_plan"))
    objective = _display_text(
        remediation.get("objective"),
        target_language=target_language,
        fallback="",
        char_limit=180,
    )
    if objective:
        priorities.append(objective)

    confidence_floor = _float_value(_as_dict(research.get("confidence_summary")).get("floor"))
    if confidence_floor < _research_target_floor(research):
        priorities.append(
            "Raise the weakest claims with better external grounding and conservative re-scoring."
            if target_language == "en"
            else "最も弱い主張を、外部根拠の追加と保守的な再採点で底上げします。"
        )

    quality_gate_ids = {
        str(_as_dict(item).get("id", "")).strip()
        for item in _as_list(research.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    }
    if "source-grounding" in quality_gate_ids or _research_source_count(research) == 0:
        priorities.append(
            "Add vendor pages, pricing pages, and independent reports before broadening scope."
            if target_language == "en"
            else "対象を広げる前に、ベンダーページ、料金ページ、第三者レポートを追加します。"
        )
    if "critical-node-health" in quality_gate_ids:
        priorities.append(
            "Recover degraded lanes locally instead of rerunning the entire swarm."
            if target_language == "en"
            else "swarm 全体をやり直さず、劣化しているレーンだけを局所的に回復します。"
        )

    if not priorities:
        priorities.append(
            "Keep the evidence set tight enough that planning can act on it without reopening the whole market."
            if target_language == "en"
            else "企画がそのまま使えるよう、根拠集合を広げすぎず意思決定に必要な厚みに絞ります。"
        )
    return _dedupe_strings(priorities)[:3]


def _research_planning_guardrails(
    research: dict[str, Any],
    *,
    target_language: str,
) -> list[str]:
    autonomous = _as_dict(research.get("autonomous_remediation"))
    guardrails = _display_text_list(
        autonomous.get("planningGuardrails"),
        target_language=target_language,
        limit=4,
        char_limit=180,
    )
    if guardrails:
        return guardrails[:3]
    defaults = [
        (
            "Carry unresolved questions as explicit assumptions, not hidden scope."
            if target_language == "en"
            else "未解決の問いは隠れた scope ではなく、明示的な前提条件として持ち込みます。"
        ),
        (
            "Treat low-confidence theses as validation tasks before they become roadmap commitments."
            if target_language == "en"
            else "信頼度の低い仮説は、ロードマップ確定前の検証タスクとして扱います。"
        ),
        (
            "Convert critical dissent into stop conditions or explicit exclusions."
            if target_language == "en"
            else "重大な反証は、中止条件か除外条件に変換して扱います。"
        ),
    ]
    return defaults[:3]


def research_context_payload(
    research: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    confidence = _as_dict(research.get("confidence_summary"))
    user = _as_dict(research.get("user_research"))
    winning_theses = _resolved_winning_theses(
        research,
        target_language=target_language,
        limit=3,
        char_limit=220,
    )
    top_thesis = winning_theses[0] if winning_theses else (
        "Validate the strongest remaining thesis before planning."
        if target_language == "en"
        else "企画へ渡す前に、最も強い仮説を検証します。"
    )
    segment = _display_text(
        user.get("segment"),
        target_language=target_language,
        fallback=("Target segment still needs sharpening." if target_language == "en" else "対象セグメントはまだ絞り込みが必要です。"),
        char_limit=90,
    )
    core_question = (
        f"Can the team defend this thesis with enough grounded evidence to plan against it: {top_thesis}"
        if target_language == "en"
        else f"この仮説を、企画に使える grounded evidence で防御できるか: {top_thesis}"
    )
    return {
        "decision_stage": _research_decision_stage(research),
        "decision_stage_label": _research_decision_stage_label(
            _research_decision_stage(research),
            target_language=target_language,
        ),
        "segment": segment,
        "core_question": core_question,
        "thesis_headline": top_thesis,
        "thesis_snapshot": winning_theses[:3],
        "confidence_floor": round(_float_value(confidence.get("floor")), 2),
        "target_confidence_floor": round(_research_target_floor(research), 2),
        "external_source_count": _research_source_count(research),
        "winning_thesis_count": len(
            _resolved_winning_theses(
                research,
                target_language=target_language,
                limit=8,
                char_limit=220,
            )
        ),
        "critical_dissent_count": _int_value(research.get("critical_dissent_count")),
        "evidence_priorities": _research_evidence_priorities(
            research,
            target_language=target_language,
        ),
        "blocking_summary": _research_blocking_summary(
            research,
            target_language=target_language,
        ),
        "planning_guardrails": _research_planning_guardrails(
            research,
            target_language=target_language,
        ),
        "user_pressures": {
            "signals": _display_text_list(
                user.get("signals"),
                target_language=target_language,
                limit=3,
                char_limit=180,
            ),
            "pain_points": _display_text_list(
                user.get("pain_points"),
                target_language=target_language,
                limit=3,
                char_limit=180,
            ),
        },
        "market_pressures": {
            "opportunities": _display_text_list(
                research.get("opportunities"),
                target_language=target_language,
                limit=3,
                char_limit=180,
            ),
            "threats": _display_text_list(
                research.get("threats"),
                target_language=target_language,
                limit=3,
                char_limit=180,
            ),
        },
    }


def _research_operator_copy(
    research: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    is_japanese = target_language == "ja"
    context = _as_dict(research.get("research_context")) or research_context_payload(
        research,
        target_language=target_language,
    )
    readiness = _normalize_space(research.get("readiness"))
    thesis_headline = _normalize_space(context.get("thesis_headline"))
    blocking_summary = _display_text_list(
        context.get("blocking_summary"),
        target_language=target_language,
        limit=3,
        char_limit=180,
    )
    evidence_priorities = _display_text_list(
        context.get("evidence_priorities"),
        target_language=target_language,
        limit=3,
        char_limit=180,
    )
    planning_guardrails = _display_text_list(
        context.get("planning_guardrails"),
        target_language=target_language,
        limit=3,
        char_limit=180,
    )
    council_cards: list[dict[str, Any]] = []

    if thesis_headline:
        council_cards.append(
            {
                "id": "thesis-council",
                "agent": "仮説評議" if is_japanese else "Thesis Council",
                "lens": "勝ち筋" if is_japanese else "Winning wedge",
                "title": thesis_headline,
                "summary": (
                    "いま最も defend すべき仮説です。企画はこの仮説を崩さずに scope を切る必要があります。"
                    if is_japanese
                    else "This is the thesis planning should preserve while narrowing scope."
                ),
                "action_label": "有力仮説へ" if is_japanese else "Open theses",
                "target_section": "winning-theses",
                "tone": "high" if readiness == "ready" else "medium",
            }
        )

    if evidence_priorities or blocking_summary:
        council_cards.append(
            {
                "id": "evidence-council",
                "agent": "根拠評議" if is_japanese else "Evidence Council",
                "lens": "回復戦略" if is_japanese else "Recovery strategy",
                "title": evidence_priorities[0] if evidence_priorities else (
                    "止まっている品質ゲートを先に解消します。"
                    if is_japanese
                    else "Close the blocking gate before broadening the search."
                ),
                "summary": blocking_summary[0] if blocking_summary else (
                    "根拠の薄い主張を増やすのではなく、最も弱い論点から先に補強します。"
                    if is_japanese
                    else "Strengthen the weakest evidence chain before adding more claims."
                ),
                "action_label": "回復方針へ" if is_japanese else "Open recovery plan",
                "target_section": "recovery",
                "tone": "high" if blocking_summary else "medium",
            }
        )

    if planning_guardrails:
        council_cards.append(
            {
                "id": "handoff-council",
                "agent": "引き継ぎ評議" if is_japanese else "Handoff Council",
                "lens": "企画への持ち込み方" if is_japanese else "Planning carryover",
                "title": planning_guardrails[0],
                "summary": (
                    "research をそのまま繰り返すのではなく、企画で前提条件と除外条件に変換します。"
                    if is_japanese
                    else "Convert research uncertainty into explicit planning assumptions and exclusions."
                ),
                "action_label": "引き継ぎ条件へ" if is_japanese else "Open guardrails",
                "target_section": "handoff",
                "tone": "medium",
            }
        )

    headline = (
        thesis_headline
        or (blocking_summary[0] if blocking_summary else "")
        or (
            "企画へ持ち込む research packet を整理しました。"
            if is_japanese
            else "The research handoff packet is ready."
        )
    )
    summary = (
        f"{context.get('decision_stage_label')}。企画では、未解決の論点を前提条件として管理しながら主導仮説を扱います。"
        if is_japanese
        else f"{context.get('decision_stage_label')}. Planning should keep the leading thesis while carrying unresolved questions as explicit assumptions."
    )
    bullets = [
        (
            f"主導仮説: {thesis_headline}"
            if is_japanese
            else f"Lead thesis: {thesis_headline}"
        )
        if thesis_headline
        else None,
        (
            f"次に補強する根拠: {evidence_priorities[0]}"
            if is_japanese
            else f"Strengthen next: {evidence_priorities[0]}"
        )
        if evidence_priorities
        else None,
        (
            f"未解決の論点: {blocking_summary[0]}"
            if is_japanese
            else f"Open blocker: {blocking_summary[0]}"
        )
        if blocking_summary
        else None,
        (
            f"企画のガードレール: {planning_guardrails[0]}"
            if is_japanese
            else f"Planning guardrail: {planning_guardrails[0]}"
        )
        if planning_guardrails
        else None,
    ]
    payload: dict[str, Any] = {}
    if council_cards:
        payload["council_cards"] = council_cards
    payload["handoff_brief"] = {
        "headline": headline,
        "summary": summary,
        "bullets": [item for item in bullets if item][:4],
    }
    return payload


def with_research_operator_copy(
    research: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    enriched = dict(research)
    enriched["research_context"] = research_context_payload(
        enriched,
        target_language=target_language,
    )
    operator_copy = _research_operator_copy(
        enriched,
        target_language=target_language,
    )
    if operator_copy:
        enriched["operator_copy"] = operator_copy
    return enriched


def _seed_fixed_research_display_text(
    research: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    localized = dict(research)
    localized["judge_summary"] = translate_fixed_research_text(
        localized.get("judge_summary"),
        target_language=target_language,
    )
    localized["quality_gates"] = [
        {
            **_as_dict(item),
            "reason": translate_fixed_research_text(
                _as_dict(item).get("reason"),
                target_language=target_language,
            ),
        }
        for item in _as_list(localized.get("quality_gates"))
    ]
    remediation_plan = _as_dict(localized.get("remediation_plan"))
    if remediation_plan:
        localized["remediation_plan"] = {
            **remediation_plan,
            "objective": translate_fixed_research_text(
                remediation_plan.get("objective"),
                target_language=target_language,
            ),
        }
    localized["execution_trace"] = [
        {
            **_as_dict(item),
            "objective": translate_fixed_research_text(
                _as_dict(item).get("objective"),
                target_language=target_language,
            ),
        }
        for item in _as_list(localized.get("execution_trace"))
    ]
    return localized


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
    assign(
        "winning_theses",
        [
            text
            for text in _resolved_winning_theses(
                research,
                target_language="en",
                limit=4,
                char_limit=280,
            )
            if text and not _contains_japanese(text) and not _looks_like_machine_token(text)
        ],
    )
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


def backfill_research_localization(
    research: dict[str, Any],
    *,
    target_language: str = "ja",
) -> dict[str, Any]:
    canonical_source = _as_dict(research.get("canonical")) or dict(research)
    canonical = with_research_operator_copy(
        _seed_fixed_research_display_text(
            dict(canonical_source),
            target_language="en",
        ),
        target_language="en",
    )
    localized_existing = _as_dict(research.get("localized"))
    if target_language != "ja":
        localized = with_research_operator_copy(
            _seed_fixed_research_display_text(
                dict(localized_existing),
                target_language=target_language,
            ),
            target_language=target_language,
        )
        return {
            **dict(research),
            "canonical": canonical,
            "localized": localized,
            "display_language": target_language,
            "localization_status": str(research.get("localization_status") or "skipped"),
        }

    if localized_existing:
        localized = with_research_operator_copy(
            _seed_fixed_research_display_text(
                dict(localized_existing),
                target_language=target_language,
            ),
            target_language=target_language,
        )
        display_language = str(
            research.get("display_language")
            or localized.get("display_language")
            or target_language
        )
        localization_status = str(
            research.get("localization_status")
            or localized.get("localization_status")
            or "strict"
        )
        localized["display_language"] = display_language
        localized["localization_status"] = localization_status
        return {
            **dict(research),
            **localized,
            "canonical": canonical,
            "localized": localized,
            "display_language": display_language,
            "localization_status": localization_status,
        }

    localized = with_research_operator_copy(
        _seed_fixed_research_display_text(
            dict(canonical_source),
            target_language=target_language,
        ),
        target_language=target_language,
    )
    localization_status = str(research.get("localization_status") or "best_effort")
    localized["display_language"] = target_language
    localized["localization_status"] = localization_status
    return {
        **localized,
        "canonical": canonical,
        "localized": dict(localized),
        "display_language": target_language,
        "localization_status": localization_status,
    }
