"""Typed lifecycle contract and readiness helpers."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Status / phase Literal types
# ---------------------------------------------------------------------------
PhaseStatus = Literal["locked", "active", "done", "skipped"]
QualityGateStatus = Literal["pass", "warning", "fail"]
CompletenessStatus = Literal["complete", "partial", "missing", "unknown"]
ReadinessStatus = Literal["ready_for_deploy", "blocked", "in_progress", "unknown"]
DissenterSeverity = Literal["critical", "major", "minor"]
SourceType = Literal["url", "document", "interview", "observation", "codebase"]
BuildStatus = Literal["passed", "failed", "skipped", "unknown"]

from pylon.lifecycle.orchestrator import PHASE_ORDER
from pylon.lifecycle.services.decision_context import (
    build_lifecycle_decision_context,
    canonical_thesis_fallback,
)
from pylon.lifecycle.services.native_artifacts import (
    backfill_native_artifacts,
    normalize_dcs_analysis,
    normalize_requirements_bundle,
    normalize_reverse_engineering_result,
    normalize_task_decomposition,
    normalize_technical_design_bundle,
)
from pylon.lifecycle.services.research_localization import research_context_payload
from pylon.lifecycle.services.value_contracts import (
    OUTCOME_TELEMETRY_CONTRACT_ID,
    REQUIRED_DELIVERY_CONTRACT_IDS,
    VALUE_CONTRACT_ID,
    outcome_telemetry_contract_ready,
    value_contract_ready,
)

EXECUTABLE_PHASES: tuple[str, ...] = ("research", "planning", "design", "development")
_RESEARCH_INPUT_TOKEN_BUDGET = 6000
_PLANNING_INPUT_TOKEN_BUDGET = 6500
RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT = 2
RESEARCH_CONDITIONAL_HANDOFF_FLOOR = 0.45


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _check_status(value: Any, expected: str) -> bool:
    """Type-safe status comparison with normalization."""
    return str(value or "").strip().lower() == expected.lower()


def _is_valid_source_url(value: Any) -> bool:
    """Validate source URL using urllib.parse instead of string prefix matching."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _estimate_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + int(non_ascii_chars / 1.5))


def _contains_non_ascii(value: Any) -> bool:
    text = str(value or "")
    return any(ord(ch) > 127 for ch in text)


def _payload_has_non_ascii(value: Any) -> bool:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return _contains_non_ascii(text)


def _truncate_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _looks_like_machine_token(value: Any) -> bool:
    """Check if value is a machine-readable token (slug format)."""
    text = str(value or "").strip()
    if not text or len(text) > 256:
        return False
    # Validate against a defined token character set
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_.:-]*", text))


def _englishish_text(value: Any, *, fallback: str = "", limit: int = 220) -> str:
    text = _truncate_text(value, limit=limit)
    if text and not _contains_non_ascii(text):
        return text
    return _truncate_text(fallback, limit=limit)


def _canonical_research_claim_statement(claim: dict[str, Any], *, limit: int) -> str:
    claim_id = str(_as_dict(claim).get("id", "")).strip()
    fallback = canonical_thesis_fallback(claim_id, target_language="en")
    return _englishish_text(
        _as_dict(claim).get("statement"),
        fallback=fallback or "This claim still needs english canonicalization.",
        limit=limit,
    )


def _canonical_research_winning_theses(research: dict[str, Any], *, limit: int, char_limit: int) -> list[str]:
    canonical = _research_canonical_payload(research)
    claims = [_as_dict(item) for item in _as_list(canonical.get("claims")) if _as_dict(item)]
    claim_lookup = {
        str(item.get("id", "")).strip(): _canonical_research_claim_statement(item, limit=char_limit)
        for item in claims
        if str(item.get("id", "")).strip()
    }
    theses: list[str] = []
    for item in _as_list(canonical.get("winning_theses")):
        raw = str(item or "").strip()
        fallback = (
            claim_lookup.get(raw)
            or canonical_thesis_fallback(raw, target_language="en")
            or "Leading thesis still needs english canonicalization."
        )
        text = (
            _truncate_text(fallback, limit=char_limit)
            if _looks_like_machine_token(raw)
            else _englishish_text(item, fallback=fallback, limit=char_limit)
        )
        if text and text not in theses:
            theses.append(text)
        if len(theses) >= limit:
            break
    if theses:
        return theses
    for claim in claims[:limit]:
        text = _canonical_research_claim_statement(claim, limit=char_limit)
        if text and text not in theses:
            theses.append(text)
    return theses


def _research_canonical_payload(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _as_dict(research.get("canonical"))
    return canonical or research


def _research_localized_payload(research: dict[str, Any]) -> dict[str, Any]:
    localized = _as_dict(research.get("localized"))
    return localized or research


def _research_context_for_input(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    context = _as_dict(canonical.get("research_context"))
    if context:
        return context
    return research_context_payload(canonical, target_language="en")


def _planning_canonical_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    canonical = _as_dict(analysis.get("canonical"))
    return canonical or analysis


def _planning_required_traceability_use_case_ids(analysis: dict[str, Any]) -> set[str]:
    use_cases = [_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(analysis.get("recommended_milestones")) if _as_dict(item)]
    milestone_use_case_ids = {
        str(use_case_id).strip()
        for milestone in milestones
        for use_case_id in _as_list(milestone.get("depends_on_use_cases"))
        if str(use_case_id).strip()
    }
    return {
        str(item.get("id", "")).strip()
        for item in use_cases
        if str(item.get("id", "")).strip()
        and (
            str(item.get("priority", "should") or "should") in {"must", "should"}
            or str(item.get("id", "")).strip() in milestone_use_case_ids
        )
    }


def _research_failed_quality_gates(research: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = _research_canonical_payload(research)
    return [
        _as_dict(item)
        for item in _as_list(canonical.get("quality_gates"))
        if _as_dict(item) and _as_dict(item).get("passed") is not True
    ]


def _research_external_source_count(research: dict[str, Any]) -> int:
    canonical = _research_canonical_payload(research)
    source_links = [
        str(item).strip()
        for item in _as_list(canonical.get("source_links"))
        if _is_valid_source_url(item)
    ]
    evidence_links = [
        str(_as_dict(item).get("source_ref", "")).strip()
        for item in _as_list(canonical.get("evidence"))
        if _check_status(_as_dict(item).get("source_type"), "url")
        and _is_valid_source_url(_as_dict(item).get("source_ref"))
    ]
    return len(list(dict.fromkeys([*source_links, *evidence_links])))


def _research_winning_thesis_count(research: dict[str, Any]) -> int:
    canonical = _research_canonical_payload(research)
    return len([item for item in _as_list(canonical.get("winning_theses")) if str(item).strip()])


def _research_confidence_floor(research: dict[str, Any]) -> float:
    canonical = _research_canonical_payload(research)
    return float(_as_dict(canonical.get("confidence_summary")).get("floor", 0.0) or 0.0)


def _research_critical_dissent_count(research: dict[str, Any]) -> int:
    canonical = _research_canonical_payload(research)
    count = canonical.get("critical_dissent_count")
    if isinstance(count, int):
        return count
    return sum(
        1
        for item in _as_list(canonical.get("dissent"))
        if _as_dict(item).get("severity") == "critical" and _as_dict(item).get("resolved") is not True
    )


def research_operator_guidance_context(project_record: dict[str, Any]) -> dict[str, Any]:
    research = _as_dict(project_record.get("research"))
    if not research:
        return {}
    canonical = _research_canonical_payload(research)
    failed_gates = _research_failed_quality_gates(research)
    if not failed_gates:
        return {}
    autonomous_state = _as_dict(canonical.get("autonomous_remediation"))
    attempt_count = int(autonomous_state.get("attemptCount", 0) or 0)
    max_attempts = int(
        autonomous_state.get("maxAttempts", RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT)
        or RESEARCH_AUTONOMOUS_REMEDIATION_LIMIT
    )
    confidence_floor = _research_confidence_floor(research)
    external_source_count = _research_external_source_count(research)
    winning_thesis_count = _research_winning_thesis_count(research)
    critical_dissent_count = _research_critical_dissent_count(research)
    open_question_count = len([
        item
        for item in _as_list(canonical.get("open_questions"))
        if str(item).strip()
    ])
    degraded_node_ids = [
        str(_as_dict(item).get("nodeId", "")).strip()
        for item in _as_list(canonical.get("node_results"))
        if str(_as_dict(item).get("status", "success")) != "success"
        and str(_as_dict(item).get("nodeId", "")).strip()
    ]
    stalled_signature = autonomous_state.get("stalledSignature") is True
    auto_recovery_mode = "deepen_evidence"
    auto_recovery_summary = "外部根拠の厚みを増やし、弱い主張を再採点します。"
    auto_recovery_checklist = [
        "ベンダーページ、料金ページ、第三者レポートを優先して追加する",
        "信頼度の低い主張だけを再採点して floor を引き上げる",
    ]
    if (attempt_count > 0 or stalled_signature) and winning_thesis_count > 0 and external_source_count > 0:
        auto_recovery_mode = "reframe_research"
        auto_recovery_summary = "同じ問いを繰り返さず、対象セグメントや評価軸を切り替えて再調査します。"
        auto_recovery_checklist = [
            "別セグメント / 別ユースケースの仮説を明示的に試す",
            "機能比較ではなく導入障壁、運用統制、切替コストで再評価する",
        ]
    has_minimum_handoff_evidence = (
        winning_thesis_count > 0
        and external_source_count > 0
    )
    exhausted_retry_budget = max_attempts > 0 and attempt_count >= max_attempts
    strict_handoff_allowed = (
        has_minimum_handoff_evidence
        and confidence_floor >= RESEARCH_CONDITIONAL_HANDOFF_FLOOR
        and critical_dissent_count == 0
    )
    conditional_handoff_allowed = strict_handoff_allowed or (
        has_minimum_handoff_evidence and exhausted_retry_budget
    )
    if not has_minimum_handoff_evidence:
        recommended_action = "deepen_evidence"
        strategy_summary = "まずは企画に渡す最低限の根拠を補うべき状態です。"
        follow_up_question = "どの顧客像や利用文脈を優先するかを短く決めると、再調査の改善幅が大きくなります。"
    elif critical_dissent_count > 0 and not exhausted_retry_budget:
        recommended_action = "clarify_scope"
        strategy_summary = "重大な反証が残っているため、問いを絞り直してから再開するべき状態です。"
        follow_up_question = "優先する制約は何ですか。速度、統制、導入容易性のどれを最優先にしますか。"
    elif confidence_floor < RESEARCH_CONDITIONAL_HANDOFF_FLOOR and not exhausted_retry_budget:
        recommended_action = "deepen_evidence"
        strategy_summary = "企画に渡す前に、もう一段だけ根拠を厚くするべき状態です。"
        follow_up_question = "優先する顧客像か導入文脈を一つに絞ると、次の回復で精度を上げやすくなります。"
    elif stalled_signature or attempt_count >= max_attempts:
        if conditional_handoff_allowed:
            recommended_action = "conditional_handoff"
            strategy_summary = (
                "自動回復の予算を使い切ったため、品質ゲートが未達でも前提条件つきで企画に進めます。"
                if exhausted_retry_budget and not strict_handoff_allowed
                else "品質ゲートは未達ですが、前提条件つきで企画に渡せるだけの材料は揃っています。"
            )
            follow_up_question = "企画では未解決の前提を明示し、低信頼論点と重大な反証を除外条件に落とし込むべきです。"
        else:
            recommended_action = "clarify_scope"
            strategy_summary = "同じ blocker が続いているため、検索の追加より問いの切り方を変えるべき状態です。"
            follow_up_question = "対象セグメントか成功指標のどちらを先に固定するかを決めてください。"
    else:
        recommended_action = "wait_for_autonomous_recovery"
        strategy_summary = "次の自動回復では、同じ再試行ではなく回復戦略を変えて再調査します。"
        follow_up_question = ""
    planning_guardrails = [
        "未解決の論点を前提条件と除外条件に変換する",
        "信頼度下限が低い論点は主計画ではなく検証タスクとして扱う",
        "重大な反証が残る論点は企画内で検証マイルストーンか除外条件として扱う",
    ] if conditional_handoff_allowed else []
    return {
        "recommendedAction": recommended_action,
        "strategySummary": strategy_summary,
        "followUpQuestion": follow_up_question,
        "autoRecoveryMode": auto_recovery_mode,
        "autoRecoverySummary": auto_recovery_summary,
        "autoRecoveryChecklist": auto_recovery_checklist[:3],
        "conditionalHandoffAllowed": conditional_handoff_allowed,
        "planningGuardrails": planning_guardrails[:3],
        "stalledSignature": stalled_signature,
        "confidenceFloor": confidence_floor,
        "targetConfidenceFloor": 0.6,
        "winningThesisCount": winning_thesis_count,
        "externalSourceCount": external_source_count,
        "criticalDissentCount": critical_dissent_count,
        "openQuestionCount": open_question_count,
        "degradedNodeIds": list(dict.fromkeys(degraded_node_ids))[:6],
        "blockingGateIds": [
            str(gate.get("id", "")).strip()
            for gate in failed_gates
            if str(gate.get("id", "")).strip()
        ][:6],
    }


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
    operator_guidance = research_operator_guidance_context(project_record)
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
            or "追加調査の不足分を埋め、operator の追加判断なしでも企画へ進める状態を目指します。"
        ),
        "blockingGateIds": list(dict.fromkeys(str(gate.get("id", "")) for gate in failed_gates if str(gate.get("id", "")).strip()))[:6],
        "blockingNodeIds": list(dict.fromkeys(blocking_node_ids))[:6],
        "retryNodeIds": list(dict.fromkeys(retry_node_ids))[:6],
        "missingSourceClasses": list(dict.fromkeys(missing_source_classes))[:8],
        "recoveryMode": str(operator_guidance.get("autoRecoveryMode", "deepen_evidence") or "deepen_evidence"),
        "strategySummary": str(operator_guidance.get("autoRecoverySummary", "") or ""),
        "strategyChecklist": [
            str(item).strip()
            for item in _as_list(operator_guidance.get("autoRecoveryChecklist"))
            if str(item).strip()
        ][:3],
        "stalledSignature": bool(operator_guidance.get("stalledSignature")),
        "operatorGuidance": operator_guidance,
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
    research_context = _research_context_for_input(research)
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
    winning_theses = _canonical_research_winning_theses(
        research,
        limit=2 if terse else 3,
        char_limit=160 if terse else 220,
    )
    compacted = {
        "summary_mode": "compact-terse" if terse else "compact",
        "display_language": "en",
        "readiness": canonical.get("readiness"),
        "judge_summary": _englishish_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            fallback=(
                winning_theses[0]
                if winning_theses
                else "Research judgment still needs english canonicalization."
            ),
            limit=220 if terse else 320,
        ),
        "research_context": {
            "decision_stage": research_context.get("decision_stage"),
            "decision_stage_label": _englishish_text(
                research_context.get("decision_stage_label"),
                fallback=(
                    "Ready for planning"
                    if canonical.get("readiness") == "ready"
                    else "Conditional handoff"
                    if _as_dict(canonical.get("autonomous_remediation")).get("conditionalHandoffAllowed") is True
                    else "Needs research rework"
                ),
                limit=80,
            ),
            "segment": _englishish_text(
                research_context.get("segment"),
                fallback="Target segment still needs sharpening.",
                limit=100 if terse else 140,
            ),
            "core_question": _englishish_text(
                research_context.get("core_question"),
                fallback=(
                    f"Can the team defend this thesis with enough grounded evidence to plan against it: {winning_theses[0]}"
                    if winning_theses
                    else "Can the team defend this thesis with enough grounded evidence to plan against it?"
                ),
                limit=160 if terse else 240,
            ),
            "thesis_headline": _englishish_text(
                research_context.get("thesis_headline"),
                fallback=(
                    winning_theses[0]
                    if winning_theses
                    else "Establish a defendable thesis before expanding planning scope."
                ),
                limit=140 if terse else 200,
            ),
            "confidence_floor": research_context.get("confidence_floor"),
            "target_confidence_floor": research_context.get("target_confidence_floor"),
            "external_source_count": research_context.get("external_source_count"),
            "winning_thesis_count": research_context.get("winning_thesis_count"),
            "critical_dissent_count": research_context.get("critical_dissent_count"),
            "evidence_priorities": [
                _englishish_text(
                    item,
                    fallback="Strengthen the weakest evidence chain first.",
                    limit=140 if terse else 180,
                )
                for item in _as_list(research_context.get("evidence_priorities"))[: (2 if terse else 3)]
                if _englishish_text(
                    item,
                    fallback="Strengthen the weakest evidence chain first.",
                    limit=140 if terse else 180,
                )
            ],
            "blocking_summary": [
                _englishish_text(
                    item,
                    fallback="A blocking evidence gap remains.",
                    limit=140 if terse else 180,
                )
                for item in _as_list(research_context.get("blocking_summary"))[: (2 if terse else 3)]
                if _englishish_text(
                    item,
                    fallback="A blocking evidence gap remains.",
                    limit=140 if terse else 180,
                )
            ],
            "planning_guardrails": [
                _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=140 if terse else 180,
                )
                for item in _as_list(research_context.get("planning_guardrails"))[: (2 if terse else 3)]
                if _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=140 if terse else 180,
                )
            ],
        },
        "confidence_summary": _as_dict(canonical.get("confidence_summary")),
        "market_size": _englishish_text(
            canonical.get("market_size") or localized.get("market_size"),
            fallback="Market sizing still needs english canonicalization.",
            limit=180 if terse else 240,
        ),
        "trends": [
            _englishish_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("trends"))[: (2 if terse else 3)]
            if _englishish_text(item, limit=140 if terse else 180)
        ],
        "opportunities": [
            _englishish_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("opportunities"))[: (2 if terse else 3)]
            if _englishish_text(item, limit=140 if terse else 180)
        ],
        "threats": [
            _englishish_text(item, limit=140 if terse else 180)
            for item in _as_list(canonical.get("threats"))[: (2 if terse else 3)]
            if _englishish_text(item, limit=140 if terse else 180)
        ],
        "user_research": {
            "segment": _englishish_text(
                _as_dict(canonical.get("user_research")).get("segment")
                or _as_dict(localized.get("user_research")).get("segment"),
                fallback="Target segment still needs sharpening.",
                limit=100 if terse else 140,
            ),
            "signals": [
                _englishish_text(item, limit=140 if terse else 180)
                for item in _as_list(_as_dict(canonical.get("user_research")).get("signals"))[: (2 if terse else 3)]
                if _englishish_text(item, limit=140 if terse else 180)
            ],
            "pain_points": [
                _englishish_text(item, limit=140 if terse else 180)
                for item in _as_list(_as_dict(canonical.get("user_research")).get("pain_points"))[: (2 if terse else 3)]
                if _englishish_text(item, limit=140 if terse else 180)
            ],
        },
        "winning_theses": winning_theses,
        "claims": [
            {
                "id": _as_dict(item).get("id"),
                "statement": _canonical_research_claim_statement(
                    _as_dict(item),
                    limit=180 if terse else 240,
                ),
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
                "argument": _englishish_text(
                    _as_dict(item).get("argument"),
                    fallback="Counterargument still needs english canonicalization.",
                    limit=160 if terse else 220,
                ),
                "severity": _as_dict(item).get("severity"),
                "recommended_test": _englishish_text(
                    _as_dict(item).get("recommended_test"),
                    fallback="Define a concrete validation test for this counterargument.",
                    limit=140 if terse else 180,
                ),
                "resolved": _as_dict(item).get("resolved"),
            }
            for item in _as_list(canonical.get("dissent"))
            if _as_dict(item)
        ][:dissent_limit],
        "open_questions": [
            _englishish_text(item, limit=160 if terse else 220)
            for item in _as_list(canonical.get("open_questions"))[:question_limit]
            if _englishish_text(item, limit=160 if terse else 220)
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
                "title": _englishish_text(item.get("title"), fallback="Quality gate", limit=80),
                "reason": _englishish_text(
                    item.get("reason"),
                    fallback="A blocking evidence gap remains.",
                    limit=140 if terse else 180,
                ),
                "blockingNodeIds": _as_list(item.get("blockingNodeIds"))[:4],
            }
            for item in failed_gates[:4]
        ],
    }
    if canonical.get("remediation_plan"):
        compacted["remediation_plan"] = {
            "objective": _englishish_text(
                _as_dict(canonical.get("remediation_plan")).get("objective"),
                fallback="Recover the weakest research lane before the next handoff.",
                limit=160 if terse else 220,
            ),
            "retryNodeIds": _as_list(_as_dict(canonical.get("remediation_plan")).get("retryNodeIds"))[:4],
        }
    return compacted


def _minimal_research_for_input(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    localized = _research_localized_payload(research)
    research_context = _research_context_for_input(research)
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
    winning_theses = _canonical_research_winning_theses(research, limit=1, char_limit=120)
    return {
        "summary_mode": "compact-minimal",
        "display_language": "en",
        "readiness": canonical.get("readiness"),
        "judge_summary": _englishish_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            fallback=winning_theses[0] if winning_theses else "Research judgment still needs english canonicalization.",
            limit=180,
        ),
        "research_context": {
            "decision_stage": research_context.get("decision_stage"),
            "decision_stage_label": _englishish_text(
                research_context.get("decision_stage_label"),
                fallback="Needs research rework",
                limit=80,
            ),
            "core_question": _englishish_text(
                research_context.get("core_question"),
                fallback=(
                    f"Can the team defend this thesis with enough grounded evidence to plan against it: {winning_theses[0]}"
                    if winning_theses
                    else "Can the team defend this thesis with enough grounded evidence to plan against it?"
                ),
                limit=120,
            ),
            "thesis_headline": _englishish_text(
                research_context.get("thesis_headline"),
                fallback=winning_theses[0] if winning_theses else "Leading thesis still needs grounding.",
                limit=120,
            ),
            "blocking_summary": [
                _englishish_text(
                    item,
                    fallback="A blocking evidence gap remains.",
                    limit=120,
                )
                for item in _as_list(research_context.get("blocking_summary"))[:2]
                if _englishish_text(
                    item,
                    fallback="A blocking evidence gap remains.",
                    limit=120,
                )
            ],
            "planning_guardrails": [
                _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=120,
                )
                for item in _as_list(research_context.get("planning_guardrails"))[:2]
                if _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=120,
                )
            ],
        },
        "winning_theses": winning_theses,
        "claims": [
            {
                "id": item.get("id"),
                "statement": _canonical_research_claim_statement(item, limit=120),
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
            _englishish_text(item, limit=120)
            for item in _as_list(canonical.get("open_questions"))[:2]
            if _englishish_text(item, limit=120)
        ],
        "source_links": [
            _truncate_text(item, limit=120)
            for item in _as_list(canonical.get("source_links"))[:2]
        ],
    }


def _hard_cap_research_for_input(research: dict[str, Any]) -> dict[str, Any]:
    canonical = _research_canonical_payload(research)
    localized = _research_localized_payload(research)
    research_context = _research_context_for_input(research)
    winning_theses = _canonical_research_winning_theses(research, limit=1, char_limit=80)
    return {
        "summary_mode": "compact-hard-cap",
        "display_language": "en",
        "readiness": canonical.get("readiness"),
        "judge_summary": _englishish_text(
            canonical.get("judge_summary") or localized.get("judge_summary"),
            fallback=winning_theses[0] if winning_theses else "Research judgment still needs english canonicalization.",
            limit=120,
        ),
        "research_context": {
            "decision_stage": research_context.get("decision_stage"),
            "decision_stage_label": _englishish_text(
                research_context.get("decision_stage_label"),
                fallback="Needs research rework",
                limit=80,
            ),
            "core_question": _englishish_text(
                research_context.get("core_question"),
                fallback=(
                    f"Can the team defend this thesis with enough grounded evidence to plan against it: {winning_theses[0]}"
                    if winning_theses
                    else "Can the team defend this thesis with enough grounded evidence to plan against it?"
                ),
                limit=90,
            ),
            "planning_guardrails": [
                _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=90,
                )
                for item in _as_list(research_context.get("planning_guardrails"))[:1]
                if _englishish_text(
                    item,
                    fallback="Carry uncertainty into planning as an explicit assumption.",
                    limit=90,
                )
            ],
        },
        "winning_theses": winning_theses,
        "quality_gates": [
            {
                "id": _as_dict(item).get("id"),
                "reason": _englishish_text(
                    _as_dict(item).get("reason"),
                    fallback="A blocking evidence gap remains.",
                    limit=80,
                ),
            }
            for item in _as_list(canonical.get("quality_gates"))
            if _as_dict(item) and _as_dict(item).get("passed") is not True
        ][:2],
        "research_context_notice": "Research context was aggressively summarized to fit the phase input budget.",
    }


def _research_phase_payload_for_input(project_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    research = _as_dict(project_record.get("research"))
    canonical = dict(_research_canonical_payload(research))
    canonical.setdefault("research_context", _research_context_for_input(research))
    token_estimate = _estimate_tokens(canonical)
    if token_estimate <= _RESEARCH_INPUT_TOKEN_BUDGET and not _payload_has_non_ascii(canonical):
        return canonical, {
            "source": "canonical",
            "compacted": False,
            "tokenEstimate": token_estimate,
            "tokenBudget": _RESEARCH_INPUT_TOKEN_BUDGET,
            "displayLanguage": "en",
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
        "displayLanguage": "en",
    }


def _compact_planning_for_input(
    project_record: dict[str, Any],
    *,
    terse: bool,
) -> dict[str, Any]:
    analysis = _planning_canonical_payload(_as_dict(project_record.get("analysis")))
    planning_context = _as_dict(analysis.get("planning_context"))
    summary = _englishish_text(
        analysis.get("judge_summary"),
        fallback=" ".join(
            item
            for item in (
                _englishish_text(
                    _as_dict(_as_list(analysis.get("red_team_findings"))[0]).get("title"),
                    limit=120,
                ) if _as_list(analysis.get("red_team_findings")) else "",
                _englishish_text(planning_context.get("core_loop"), limit=160),
            )
            if item
        ),
        limit=220 if terse else 320,
    )
    recommendation_defaults = [
        _englishish_text(item, limit=160 if terse else 220)
        for item in _as_list(planning_context.get("delivery_principles"))
        if _englishish_text(item, limit=160 if terse else 220)
    ]
    recommendations = [
        _englishish_text(item, limit=160 if terse else 220)
        for item in _as_list(analysis.get("recommendations"))[: (3 if terse else 5)]
        if _englishish_text(item, limit=160 if terse else 220)
    ] or recommendation_defaults[: (3 if terse else 5)]
    selected_features = [
        {
            "feature": str(_as_dict(item).get("feature", "")).strip(),
            "category": _as_dict(item).get("category"),
            "priority": _as_dict(item).get("priority"),
        }
        for item in _as_list(project_record.get("features"))
        if _as_dict(item).get("selected") is True
        and str(_as_dict(item).get("feature", "")).strip()
    ][: (4 if terse else 6)]
    compacted = {
        "summary_mode": "compact-terse" if terse else "compact",
        "display_language": "en",
        "judge_summary": summary,
        "planning_context": {
            "product_kind": planning_context.get("product_kind"),
            "north_star": _englishish_text(planning_context.get("north_star"), limit=120 if terse else 180),
            "core_loop": _englishish_text(planning_context.get("core_loop"), limit=120 if terse else 180),
            "experience_principles": [
                _englishish_text(item, limit=100 if terse else 150)
                for item in _as_list(planning_context.get("experience_principles"))[:3]
                if _englishish_text(item, limit=100 if terse else 150)
            ],
            "delivery_principles": recommendation_defaults[:3],
            "selected_feature_names": [
                str(item)
                for item in _as_list(planning_context.get("selected_feature_names"))[:6]
                if str(item).strip()
            ],
            "milestone_names": [
                _englishish_text(item, limit=80)
                for item in _as_list(planning_context.get("milestone_names"))[:3]
                if _englishish_text(item, limit=80)
            ],
            "design_anchor": _as_dict(planning_context.get("design_anchor")),
        },
        "recommendations": recommendations,
        "personas": [
            {
                "name": _truncate_text(_as_dict(item).get("name"), limit=48),
                "role": _englishish_text(_as_dict(item).get("role"), limit=80 if terse else 120),
                "goals": [
                    _englishish_text(goal, limit=90 if terse else 140)
                    for goal in _as_list(_as_dict(item).get("goals"))[:2]
                    if _englishish_text(goal, limit=90 if terse else 140)
                ],
            }
            for item in _as_list(analysis.get("personas"))[:2]
            if _as_dict(item)
        ],
        "job_stories": [
            {
                "situation": _truncate_text(_as_dict(item).get("situation"), limit=120 if terse else 180),
                "motivation": _truncate_text(_as_dict(item).get("motivation"), limit=120 if terse else 180),
                "outcome": _truncate_text(_as_dict(item).get("outcome"), limit=120 if terse else 180),
                "priority": _as_dict(item).get("priority"),
            }
            for item in _as_list(analysis.get("job_stories"))[: (2 if terse else 4)]
            if _as_dict(item)
        ],
        "use_cases": [
            {
                "id": _as_dict(item).get("id"),
                "title": _truncate_text(_as_dict(item).get("title"), limit=80 if terse else 120),
                "actor": _truncate_text(_as_dict(item).get("actor"), limit=48),
                "priority": _as_dict(item).get("priority"),
                "category": _truncate_text(_as_dict(item).get("category"), limit=48),
            }
            for item in _as_list(analysis.get("use_cases"))[: (4 if terse else 6)]
            if _as_dict(item)
        ],
        "recommended_milestones": [
            {
                "id": _as_dict(item).get("id"),
                "name": _truncate_text(_as_dict(item).get("name"), limit=64),
                "phase": _as_dict(item).get("phase"),
                "criteria": _truncate_text(_as_dict(item).get("criteria"), limit=120 if terse else 180),
            }
            for item in _as_list(analysis.get("recommended_milestones"))[:3]
            if _as_dict(item)
        ],
        "design_tokens": {
            "style": {
                "name": _truncate_text(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("name"), limit=64),
                "rationale": _truncate_text(_as_dict(analysis.get("design_tokens")).get("rationale"), limit=120 if terse else 180),
                "best_for": _truncate_text(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("best_for"), limit=120 if terse else 180),
                "performance": _truncate_text(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("performance"), limit=120 if terse else 180),
                "accessibility": _truncate_text(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("accessibility"), limit=120 if terse else 180),
            },
            "colors": {
                "primary": _as_dict(_as_dict(analysis.get("design_tokens")).get("colors")).get("primary"),
                "secondary": _as_dict(_as_dict(analysis.get("design_tokens")).get("colors")).get("secondary"),
                "cta": _as_dict(_as_dict(analysis.get("design_tokens")).get("colors")).get("cta"),
                "background": _as_dict(_as_dict(analysis.get("design_tokens")).get("colors")).get("background"),
                "text": _as_dict(_as_dict(analysis.get("design_tokens")).get("colors")).get("text"),
            },
            "typography": {
                "heading": _as_dict(_as_dict(analysis.get("design_tokens")).get("typography")).get("heading"),
                "body": _as_dict(_as_dict(analysis.get("design_tokens")).get("typography")).get("body"),
            },
            "effects": [
                _englishish_text(item, limit=90 if terse else 140)
                for item in _as_list(_as_dict(analysis.get("design_tokens")).get("effects"))[:3]
                if _englishish_text(item, limit=90 if terse else 140)
            ],
        },
        "roles": [
            {
                "name": _truncate_text(_as_dict(item).get("name"), limit=48),
                "permissions": [
                    _truncate_text(permission, limit=64)
                    for permission in _as_list(_as_dict(item).get("permissions"))[:6]
                    if _truncate_text(permission, limit=64)
                ],
            }
            for item in _as_list(analysis.get("roles"))[:4]
            if _as_dict(item)
        ],
        "feature_decisions": [
            {
                "feature": _as_dict(item).get("feature"),
                "selected": _as_dict(item).get("selected"),
                "uncertainty": _as_dict(item).get("uncertainty"),
            }
            for item in _as_list(analysis.get("feature_decisions"))[: (4 if terse else 6)]
            if _as_dict(item)
        ],
        "red_team_findings": [
            {
                "title": _truncate_text(_as_dict(item).get("title"), limit=90 if terse else 140),
                "severity": _as_dict(item).get("severity"),
                "recommendation": _truncate_text(_as_dict(item).get("recommendation"), limit=120 if terse else 180),
            }
            for item in _as_list(analysis.get("red_team_findings"))[: (2 if terse else 4)]
            if _as_dict(item)
        ],
        "kill_criteria": [
            {
                "milestone_id": _as_dict(item).get("milestone_id"),
                "condition": _truncate_text(_as_dict(item).get("condition"), limit=120 if terse else 180),
            }
            for item in _as_list(analysis.get("kill_criteria"))[: (2 if terse else 3)]
            if _as_dict(item)
        ],
        "coverage_summary": _as_dict(analysis.get("coverage_summary")),
        "selected_features": selected_features,
    }
    return compacted


def _minimal_planning_for_input(project_record: dict[str, Any]) -> dict[str, Any]:
    analysis = _planning_canonical_payload(_as_dict(project_record.get("analysis")))
    return {
        "summary_mode": "compact-minimal",
        "display_language": "en",
        "judge_summary": _englishish_text(
            analysis.get("judge_summary"),
            fallback=_englishish_text(_as_dict(analysis.get("planning_context")).get("core_loop"), limit=180),
            limit=180,
        ),
        "planning_context": {
            "product_kind": _as_dict(analysis.get("planning_context")).get("product_kind"),
            "core_loop": _englishish_text(_as_dict(analysis.get("planning_context")).get("core_loop"), limit=120),
            "north_star": _englishish_text(_as_dict(analysis.get("planning_context")).get("north_star"), limit=120),
        },
        "recommendations": [
            _englishish_text(item, limit=120)
            for item in _as_list(analysis.get("recommendations"))[:2]
            if _englishish_text(item, limit=120)
        ],
        "use_cases": [
            {
                "id": _as_dict(item).get("id"),
                "title": _truncate_text(_as_dict(item).get("title"), limit=80),
                "priority": _as_dict(item).get("priority"),
            }
            for item in _as_list(analysis.get("use_cases"))[:3]
            if _as_dict(item)
        ],
        "recommended_milestones": [
            {
                "id": _as_dict(item).get("id"),
                "name": _truncate_text(_as_dict(item).get("name"), limit=60),
            }
            for item in _as_list(analysis.get("recommended_milestones"))[:2]
            if _as_dict(item)
        ],
        "red_team_findings": [
            {
                "title": _truncate_text(_as_dict(item).get("title"), limit=80),
                "severity": _as_dict(item).get("severity"),
            }
            for item in _as_list(analysis.get("red_team_findings"))[:2]
            if _as_dict(item)
        ],
        "coverage_summary": _as_dict(analysis.get("coverage_summary")),
    }


def _hard_cap_planning_for_input(project_record: dict[str, Any]) -> dict[str, Any]:
    analysis = _planning_canonical_payload(_as_dict(project_record.get("analysis")))
    planning_context = _as_dict(analysis.get("planning_context"))
    return {
        "summary_mode": "compact-hard-cap",
        "display_language": "en",
        "judge_summary": _englishish_text(
            analysis.get("judge_summary"),
            fallback=_englishish_text(planning_context.get("core_loop"), limit=120),
            limit=120,
        ),
        "planning_context": {
            "product_kind": planning_context.get("product_kind"),
            "core_loop": _englishish_text(planning_context.get("core_loop"), limit=90),
            "north_star": _englishish_text(planning_context.get("north_star"), limit=90),
        },
        "recommendations": [
            _englishish_text(item, limit=90)
            for item in _as_list(analysis.get("recommendations"))[:1]
            if _englishish_text(item, limit=90)
        ],
        "use_cases": [
            {
                "id": _as_dict(item).get("id"),
                "title": _truncate_text(_as_dict(item).get("title"), limit=64),
            }
            for item in _as_list(analysis.get("use_cases"))[:2]
            if _as_dict(item)
        ],
        "planning_context_notice": "Planning context was aggressively summarized to fit the phase input budget.",
    }


def _planning_phase_payload_for_input(project_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = _as_dict(project_record.get("analysis"))
    canonical = _planning_canonical_payload(analysis)
    token_estimate = _estimate_tokens(canonical)
    if token_estimate <= _PLANNING_INPUT_TOKEN_BUDGET and not _payload_has_non_ascii(canonical):
        return canonical, {
            "source": "canonical",
            "compacted": False,
            "tokenEstimate": token_estimate,
            "tokenBudget": _PLANNING_INPUT_TOKEN_BUDGET,
            "displayLanguage": "en",
        }
    candidates = [
        _compact_planning_for_input(project_record, terse=False),
        _compact_planning_for_input(project_record, terse=True),
        _minimal_planning_for_input(project_record),
        _hard_cap_planning_for_input(project_record),
    ]
    compacted = candidates[-1]
    compacted_estimate = _estimate_tokens(compacted)
    for candidate in candidates:
        candidate_estimate = _estimate_tokens(candidate)
        compacted = candidate
        compacted_estimate = candidate_estimate
        if candidate_estimate <= _PLANNING_INPUT_TOKEN_BUDGET:
            break
    return compacted, {
        "source": "canonical",
        "compacted": True,
        "summaryMode": str(compacted.get("summary_mode", "compact")),
        "tokenEstimate": compacted_estimate,
        "originalTokenEstimate": token_estimate,
        "tokenBudget": _PLANNING_INPUT_TOKEN_BUDGET,
        "displayLanguage": "en",
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


PROTOTYPE_SCHEMA: dict[str, Any] = {
    "required_elements": ["html", "main"],
    "required_attributes": {"data-prototype-kind": True},
    "min_screens": 1,
    "navigation_shell": {
        "required_element": "nav",
        "valid_aria_labels": [
            "primary navigation",
            "主要ナビゲーション",
        ],
        "valid_roles": ["tablist"],
    },
}


class _PrototypeHTMLInspector(HTMLParser):
    """Lightweight HTML inspector that validates against PROTOTYPE_SCHEMA."""

    def __init__(self) -> None:
        super().__init__()
        self.found_elements: set[str] = set()
        self.found_attributes: dict[str, list[str]] = {}
        self.screen_count: int = 0
        self.nav_valid: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self.found_elements.add(tag_lower)
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        for attr_name in PROTOTYPE_SCHEMA["required_attributes"]:
            if attr_name in attr_dict:
                self.found_attributes.setdefault(attr_name, []).append(attr_dict[attr_name])

        if "data-screen-id" in attr_dict:
            self.screen_count += 1

        nav_schema = PROTOTYPE_SCHEMA["navigation_shell"]
        if tag_lower == nav_schema["required_element"]:
            aria_label = attr_dict.get("aria-label", "").lower()
            role = attr_dict.get("role", "").lower()
            if any(lbl.lower() == aria_label for lbl in nav_schema["valid_aria_labels"]):
                self.nav_valid = True
            if any(r.lower() == role for r in nav_schema["valid_roles"]):
                self.nav_valid = True


def _looks_like_prototype_html(code: str) -> bool:
    text = str(code or "")
    if not text.strip():
        return False
    inspector = _PrototypeHTMLInspector()
    try:
        inspector.feed(text)
    except Exception:
        return False

    for elem in PROTOTYPE_SCHEMA["required_elements"]:
        if elem not in inspector.found_elements:
            return False
    for attr_name in PROTOTYPE_SCHEMA["required_attributes"]:
        if attr_name not in inspector.found_attributes:
            return False
    if inspector.screen_count < PROTOTYPE_SCHEMA["min_screens"]:
        return False
    return inspector.nav_valid


def lifecycle_phase_input(project_record: dict[str, Any], phase: str) -> dict[str, Any]:
    """Build normalized workflow input for the requested lifecycle phase."""
    base_project = dict(project_record)
    research_config = _as_dict(base_project.get("researchConfig"))
    target_language = str(research_config.get("outputLanguage", "ja") or "ja")
    project = (
        backfill_native_artifacts(base_project, target_language=target_language)
        if phase == "development"
        else base_project
    )
    spec = str(project.get("spec", "") or "")
    research_config = _as_dict(project.get("researchConfig"))
    analysis = _as_dict(project.get("analysis"))
    features = _as_list(project.get("features"))
    milestones = _as_list(project.get("milestones"))
    design_variants = _as_list(project.get("designVariants"))
    selected_design = _selected_design_variant(project)

    if phase == "research":
        remediation_context = research_autonomous_remediation_context(project)
        identity_profile = _as_dict(project.get("productIdentity"))
        payload = {
            "spec": spec,
            "competitor_urls": _as_list(research_config.get("competitorUrls")),
            "depth": str(research_config.get("depth", "standard") or "standard"),
            "output_language": str(research_config.get("outputLanguage", "ja") or "ja"),
            "recovery_mode": str(research_config.get("recoveryMode", "auto") or "auto"),
        }
        if any(
            [
                str(identity_profile.get("companyName", "")).strip(),
                str(identity_profile.get("productName", "")).strip(),
                str(identity_profile.get("officialWebsite", "")).strip(),
                _as_list(identity_profile.get("officialDomains")),
                _as_list(identity_profile.get("aliases")),
                _as_list(identity_profile.get("excludedEntityNames")),
            ]
        ):
            payload["identity_profile"] = {
                "companyName": str(identity_profile.get("companyName", "")).strip(),
                "productName": str(identity_profile.get("productName", "")).strip(),
                "officialWebsite": str(identity_profile.get("officialWebsite", "")).strip(),
                "officialDomains": [
                    str(item).strip()
                    for item in _as_list(identity_profile.get("officialDomains"))
                    if str(item).strip()
                ],
                "aliases": [
                    str(item).strip()
                    for item in _as_list(identity_profile.get("aliases"))
                    if str(item).strip()
                ],
                "excludedEntityNames": [
                    str(item).strip()
                    for item in _as_list(identity_profile.get("excludedEntityNames"))
                    if str(item).strip()
                ],
            }
        if remediation_context:
            payload["remediation_context"] = remediation_context
        return payload
    if phase == "planning":
        phase_research, meta = _research_phase_payload_for_input(project)
        decision_context = build_lifecycle_decision_context(project, target_language="en", compact=True)
        return {
            "spec": spec,
            "research": phase_research,
            "research_context_meta": meta,
            "decision_context": decision_context,
        }
    if phase == "design":
        phase_analysis, meta = _planning_phase_payload_for_input(project)
        decision_context = build_lifecycle_decision_context(project, target_language="en", compact=True)
        return {
            "spec": spec,
            "analysis": phase_analysis,
            "analysis_context_meta": meta,
            "features": features,
            "decision_context": decision_context,
        }
    if phase == "development":
        phase_research, meta = _research_phase_payload_for_input(project)
        phase_analysis, analysis_meta = _planning_phase_payload_for_input(project)
        decision_context = build_lifecycle_decision_context(project, target_language="en", compact=True)
        return {
            "spec": spec,
            "research": phase_research,
            "research_context_meta": meta,
            "analysis": phase_analysis,
            "analysis_context_meta": analysis_meta,
            "selected_features": features,
            "milestones": milestones,
            "planEstimates": _as_list(project.get("planEstimates")),
            "selectedPreset": str(project.get("selectedPreset", "standard") or "standard"),
            "designVariants": design_variants,
            "selectedDesignId": project.get("selectedDesignId"),
            "selected_design": selected_design,
            "design": {"selected": selected_design, "variants": design_variants},
            "decision_context": decision_context,
            "requirements": normalize_requirements_bundle(project.get("requirements")),
            "requirementsConfig": _as_dict(project.get("requirementsConfig")),
            "reverseEngineering": normalize_reverse_engineering_result(project.get("reverseEngineering")),
            "taskDecomposition": normalize_task_decomposition(project.get("taskDecomposition")),
            "dcsAnalysis": normalize_dcs_analysis(project.get("dcsAnalysis")),
            "technicalDesign": normalize_technical_design_bundle(project.get("technicalDesign")),
            "valueContract": _as_dict(project.get("valueContract")),
            "outcomeTelemetryContract": _as_dict(project.get("outcomeTelemetryContract")),
            "githubRepo": project.get("githubRepo"),
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
        # --- Tsumiki EARS requirements quality gates ---
        requirements = _as_dict(normalize_requirements_bundle(project_record.get("requirements")))
        if requirements:
            gates.append(
                _quality_gate(
                    "ears-completeness",
                    "EARS 要件が spec の主要機能をカバーしている",
                    bool(_as_list(requirements.get("requirements")))
                    and float(requirements.get("completenessScore", requirements.get("completeness_score", 0)) or 0) >= 0.7,
                    "research should produce EARS requirements that cover the spec scope",
                ),
            )
            gates.append(
                _quality_gate(
                    "requirements-traceability",
                    "要件が research claim に追跡可能である",
                    bool(requirements.get("traceabilityIndex") or requirements.get("traceability_index")),
                    "requirements should trace back to grounded research claims",
                ),
            )
        # --- Reverse engineering coverage gate ---
        reverse_eng = _as_dict(normalize_reverse_engineering_result(project_record.get("reverseEngineering")))
        has_codebase = bool(project_record.get("githubRepo"))
        if has_codebase and reverse_eng:
            gates.append(
                _quality_gate(
                    "reverse-engineering-coverage",
                    "既存コードの逆分析が API / データフロー / インターフェースをカバーしている",
                    str(reverse_eng.get("sourceType") or "unknown") == "codebase"
                    and float(reverse_eng.get("coverageScore", 0) or 0) >= 0.6,
                    "when a codebase exists, reverse engineering should cover core surfaces",
                ),
            )
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
                "requirementCount": len(_as_list(requirements.get("requirements"))),
                "reverseEngineeringCoverage": float(reverse_eng.get("coverageScore", 0) or 0) if reverse_eng else None,
            },
            quality_gates=gates,
            handoff_targets=["planning"],
        )

    if phase == "planning":
        analysis = _as_dict(project_record.get("analysis"))
        features = _as_list(project_record.get("features"))
        estimates = _as_list(project_record.get("planEstimates"))
        milestones = _as_list(project_record.get("milestones"))
        value_contract = _as_dict(project_record.get("valueContract"))
        outcome_telemetry_contract = _as_dict(project_record.get("outcomeTelemetryContract"))
        traceability = _as_list(analysis.get("traceability"))
        coverage_summary = _as_dict(analysis.get("coverage_summary"))
        assumptions = _as_list(analysis.get("assumptions"))
        negative_personas = _as_list(analysis.get("negative_personas"))
        kill_criteria = _as_list(analysis.get("kill_criteria"))
        selected_features = [
            _as_dict(item)
            for item in features
            if _as_dict(item).get("selected") is True
        ]
        traced_use_case_ids = {
            str(_as_dict(item).get("use_case_id", "")).strip()
            for item in traceability
            if str(_as_dict(item).get("use_case_id", "")).strip()
        }
        required_traceability_ids = _planning_required_traceability_use_case_ids(analysis)
        required_use_cases_without_traceability = [
            str(item).strip()
            for item in _as_list(coverage_summary.get("required_use_cases_without_traceability"))
            if str(item).strip()
        ] or [
            str(_as_dict(item).get("title", "")).strip()
            for item in _as_list(analysis.get("use_cases"))
            if str(_as_dict(item).get("id", "")).strip() in required_traceability_ids
            and str(_as_dict(item).get("id", "")).strip() not in traced_use_case_ids
            and str(_as_dict(item).get("title", "")).strip()
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
                "required-use-case-traceability",
                "主要 use case が milestone と traceability に接続されている",
                not required_use_cases_without_traceability,
                "planning should cover must/should and milestone-linked use cases with explicit traceability",
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
            _quality_gate(
                VALUE_CONTRACT_ID,
                "Journey / JTBD / KANO / IA が downstream value contract に compile されている",
                value_contract_ready(value_contract),
                "planning should compile personas, job stories, IA, and success metrics into an enforceable value contract",
            ),
            _quality_gate(
                OUTCOME_TELEMETRY_CONTRACT_ID,
                "Success metrics / kill criteria / telemetry plan が outcome telemetry contract に compile されている",
                outcome_telemetry_contract_ready(outcome_telemetry_contract),
                "planning should compile outcome telemetry and release observability before design/development continue",
            ),
        ]
        # --- Tsumiki task decomposition quality gates ---
        task_decomp = _as_dict(normalize_task_decomposition(project_record.get("taskDecomposition")))
        if task_decomp:
            task_items = _as_list(task_decomp.get("tasks"))
            effort_by_phase = _as_dict(task_decomp.get("effortByPhase"))
            gates.append(
                _quality_gate(
                    "task-dag-validity",
                    "TASK-XXXX DAG が循環なく milestone に接続されている",
                    bool(task_items) and not task_decomp.get("hasCycles", False),
                    "planning should produce a valid acyclic task dependency graph",
                ),
            )
            if effort_by_phase:
                phase_efforts = [
                    float(hours or 0.0)
                    for hours in effort_by_phase.values()
                    if float(hours or 0.0) > 0.0
                ]
                target_effort = (
                    (
                        float(task_decomp.get("totalEffortHours") or 0.0)
                        or sum(phase_efforts)
                    )
                    / max(len(phase_efforts), 1)
                ) if phase_efforts else 0.0
                effort_balanced = (
                    bool(phase_efforts)
                    and (
                        len(phase_efforts) == 1
                        or all(abs(hours - target_effort) / max(target_effort, 1.0) <= 0.3 for hours in phase_efforts)
                    )
                )
                gates.append(
                    _quality_gate(
                        "effort-budget-balance",
                        "フェーズ別工数が計画平均に対して ±30% 以内である",
                        effort_balanced,
                        "task effort should stay reasonably balanced against the project-specific per-phase plan",
                    ),
                )
        # --- DCS edge case quality gate ---
        dcs = _as_dict(normalize_dcs_analysis(project_record.get("dcsAnalysis")))
        if dcs:
            edge_cases = _as_dict(dcs.get("edgeCases"))
            gates.append(
                _quality_gate(
                    "edge-case-coverage",
                    "主要 feature に対するエッジケース分析が完了している",
                    bool(_as_list(edge_cases.get("edgeCases"))),
                    "planning should identify edge cases and risks for selected features",
                ),
            )
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
                "requiredTraceabilityUseCaseCount": len(required_traceability_ids),
                "requiredUseCasesWithoutTraceabilityCount": len(required_use_cases_without_traceability),
                "valueMetricCount": len(_as_list(value_contract.get("success_metrics"))),
                "telemetryEventCount": len(_as_list(outcome_telemetry_contract.get("telemetry_events"))),
                "taskCount": len(_as_list(task_decomp.get("tasks"))) if task_decomp else 0,
                "edgeCaseCount": len(_as_list(_as_dict(dcs.get("edgeCases")).get("edgeCases"))) if dcs else 0,
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
        artifact_completeness = _as_dict(selected.get("artifact_completeness"))
        completeness_status = str(artifact_completeness.get("status") or "unknown")
        preview_meta = _as_dict(selected.get("preview_meta"))
        freshness = _as_dict(selected.get("freshness"))
        scorecard = _as_dict(selected.get("scorecard"))
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
            _quality_gate(
                "artifact-completeness",
                "selected design が構造化 artifact contract を満たしている",
                _check_status(completeness_status, "complete"),
                "design should persist scorecard, workflows, screen specs, and runnable handoff artifacts",
            ),
            _quality_gate(
                "preview-validation",
                "selected design の preview が contract を満たしている",
                preview_meta.get("validation_ok") is True,
                "design preview should pass the self-contained product-workspace preview contract before approval",
            ),
        ]
        # --- Tsumiki behavior model quality gate ---
        dcs = _as_dict(normalize_dcs_analysis(project_record.get("dcsAnalysis")))
        if dcs:
            seq_diagrams = _as_dict(dcs.get("sequenceDiagrams"))
            state_trans = _as_dict(dcs.get("stateTransitions"))
            gates.append(
                _quality_gate(
                    "behavior-model-coverage",
                    "主要フローのシーケンス図と状態遷移が生成されている",
                    bool(_as_list(seq_diagrams.get("diagrams")))
                    and bool(_as_list(state_trans.get("states"))),
                    "design should produce behavioral models for primary workflows",
                ),
            )
        # --- Tsumiki technical design quality gate ---
        tech_design = _as_dict(normalize_technical_design_bundle(project_record.get("technicalDesign")))
        if tech_design:
            gates.append(
                _quality_gate(
                    "technical-design-completeness",
                    "architecture / API spec / schema が生成されている",
                    bool(tech_design.get("architecture"))
                    and bool(_as_list(tech_design.get("apiSpecification"))),
                    "design should produce a technical specification bundle",
                ),
            )
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
                "workflowCount": len(_as_list(selected.get("primary_workflows"))),
                "scorecardDimensionCount": len(_as_list(scorecard.get("dimensions"))),
                "artifactCompletenessScore": artifact_completeness.get("score"),
                "artifactCompletenessStatus": completeness_status,
                "previewSource": preview_meta.get("source"),
                "previewValidationOk": preview_meta.get("validation_ok"),
                "previewValidationIssueCount": len(_as_list(preview_meta.get("validation_issues"))),
                "freshnessStatus": freshness.get("status"),
                "behaviorModelDiagramCount": len(_as_list(_as_dict(dcs.get("sequenceDiagrams")).get("diagrams"))) if dcs else 0,
                "technicalDesignPresent": bool(tech_design) if tech_design else False,
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
        target_language = str(_as_dict(project_record.get("researchConfig")).get("outputLanguage") or "ja")
        current_decision_context_fingerprint = str(
            _as_dict(
                build_lifecycle_decision_context(
                    project_record,
                    target_language=target_language,
                    compact=True,
                )
            ).get("fingerprint")
            or ""
        )
        milestone_results = _as_list(project_record.get("milestoneResults"))
        build_code = str(project_record.get("buildCode") or "")
        build_cost = float(project_record.get("buildCost", 0.0) or 0.0)
        delivery_plan = _as_dict(project_record.get("deliveryPlan"))
        development_execution = _as_dict(project_record.get("developmentExecution"))
        development_handoff = _as_dict(project_record.get("developmentHandoff"))
        value_contract = _as_dict(project_record.get("valueContract"))
        outcome_telemetry_contract = _as_dict(project_record.get("outcomeTelemetryContract"))
        spec_audit = _as_dict(delivery_plan.get("spec_audit"))
        code_workspace = _as_dict(delivery_plan.get("code_workspace"))
        repo_execution = _as_dict(delivery_plan.get("repo_execution"))
        workspace_summary = _as_dict(code_workspace.get("artifact_summary"))
        workspace_paths = {
            str(_as_dict(item).get("path") or "").strip()
            for item in _as_list(code_workspace.get("files"))
            if str(_as_dict(item).get("path") or "").strip()
        }
        critical_spec_gaps = [
            _as_dict(item)
            for item in _as_list(spec_audit.get("unresolved_gaps"))
            if str(_as_dict(item).get("severity") or "") in {"critical", "high"}
        ]
        work_packages = _as_list(delivery_plan.get("work_packages"))
        critical_path = _as_list(delivery_plan.get("critical_path"))
        goal_spec = _as_dict(delivery_plan.get("goal_spec"))
        waves = _as_list(delivery_plan.get("waves"))
        work_unit_contracts = _as_list(delivery_plan.get("work_unit_contracts"))
        shift_left_plan = _as_dict(delivery_plan.get("shift_left_plan"))
        topology_fingerprint = str(delivery_plan.get("topology_fingerprint") or "").strip()
        runtime_graph_fingerprint = str(delivery_plan.get("runtime_graph_fingerprint") or "").strip()
        plan_decision_context_fingerprint = str(delivery_plan.get("decision_context_fingerprint") or "").strip()
        handoff_topology_fingerprint = str(development_handoff.get("topology_fingerprint") or "").strip()
        ready_wave_count = int(development_handoff.get("ready_wave_count", 0) or 0)
        non_final_wave_count = int(development_handoff.get("non_final_wave_count", 0) or 0)
        deploy_checklist = _as_list(development_handoff.get("deploy_checklist"))
        lowered_build_code = build_code.lower()
        screen_surface_count = lowered_build_code.count("data-screen-id=")
        has_navigation_shell = "<nav" in lowered_build_code and (
            'aria-label="primary navigation"' in lowered_build_code
            or 'aria-label="主要ナビゲーション"' in lowered_build_code
            or 'role="tablist"' in lowered_build_code
        )
        if not build_code and not milestone_results and not delivery_plan:
            return None
        satisfied = sum(
            1
            for item in milestone_results
            if _check_status(_as_dict(item).get("status"), "satisfied")
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
                has_navigation_shell and screen_surface_count >= 2,
                "development should preserve navigation and multiple screen surfaces from design",
            ),
            _quality_gate(
                "delivery-graph",
                "dependency-aware delivery graph と merge order が固定されている",
                bool(work_packages) and len(critical_path) >= 1 and bool(_as_dict(delivery_plan.get("merge_strategy")).get("integration_order")),
                "development should translate planning WBS and design lanes into an executable delivery graph before handoff",
            ),
            _quality_gate(
                "goal-spec",
                "承認済み context が goal spec と contract injection plan に分解されている",
                bool(_as_list(goal_spec.get("selected_features")))
                and set(_as_list(goal_spec.get("contract_injection"))) >= set(REQUIRED_DELIVERY_CONTRACT_IDS),
                "development should turn approved context into an explicit goal spec before autonomous delivery starts",
            ),
            _quality_gate(
                "delivery-waves",
                "依存 DAG に基づく execution wave が定義されている",
                bool(waves) and int(delivery_plan.get("wave_count", 0) or 0) == len(waves),
                "development should schedule execution by dependency waves instead of one flat FE/BE split",
            ),
            _quality_gate(
                "delivery-topology-lineage",
                "delivery topology fingerprint と runtime graph fingerprint が current decision context に一致している",
                bool(topology_fingerprint)
                and bool(runtime_graph_fingerprint)
                and bool(plan_decision_context_fingerprint)
                and bool(current_decision_context_fingerprint)
                and plan_decision_context_fingerprint == current_decision_context_fingerprint
                and (
                    not handoff_topology_fingerprint
                    or handoff_topology_fingerprint == topology_fingerprint
                ),
                "development should bind the active delivery topology to the current decision context and deploy handoff",
            ),
            _quality_gate(
                "work-unit-contracts",
                "各 WU が acceptance / QA / security / repair policy を持っている",
                bool(work_unit_contracts)
                and all(
                    bool(_as_list(_as_dict(item).get("acceptance_criteria")))
                    and bool(_as_list(_as_dict(item).get("qa_checks")))
                    and bool(_as_list(_as_dict(item).get("security_checks")))
                    and set(_as_list(_as_dict(item).get("required_contracts"))) >= set(REQUIRED_DELIVERY_CONTRACT_IDS)
                    and bool(_as_list(_as_dict(item).get("value_targets")))
                    and bool(_as_list(_as_dict(item).get("telemetry_events")))
                    and bool(_as_dict(item).get("repair_policy"))
                    for item in work_unit_contracts
                ),
                "development should keep failures local by giving every work unit explicit quality and repair contracts",
            ),
            _quality_gate(
                "shift-left-quality",
                "QA / security が work-unit boundary に埋め込まれている",
                str(shift_left_plan.get("mode") or "") == "work_unit_micro_loop",
                "development should place QA and security at the work-unit boundary before final review",
            ),
            _quality_gate(
                "development-execution-trace",
                "WU / wave execution trace が operator record に永続化されている",
                bool(_as_list(development_execution.get("waves")))
                and bool(_as_list(development_execution.get("workUnits")))
                and int(development_execution.get("waveCount", 0) or 0) == len(waves)
                and int(development_execution.get("workUnitCount", 0) or 0) == len(work_unit_contracts),
                "development should persist compact wave/work-unit execution evidence for operation and replay",
            ),
            _quality_gate(
                "conflict-guards",
                "lane ownership と conflict guardrail が明示されている",
                any(_as_list(_as_dict(item).get("conflict_guards")) for item in _as_list(delivery_plan.get("lanes"))),
                "development should define who owns shared surfaces and how merge conflicts are prevented",
            ),
            _quality_gate(
                "spec-closure",
                "requirements / task DAG / technical design の spec gap が閉じている",
                str(spec_audit.get("status") or "") == "ready_for_autonomous_build" and not critical_spec_gaps,
                "development should close critical requirements and architecture gaps before autonomous delivery continues",
            ),
            _quality_gate(
                "design-system-contract",
                "design token contract が code workspace に実装されている",
                "app/lib/design-tokens.ts" in workspace_paths
                and "docs/spec/design-system.md" in workspace_paths,
                "development should preserve approved design tokens as code and handoff artifacts",
            ),
            _quality_gate(
                "access-control-contract",
                "auth / access-control contract が code workspace に実装されている",
                "server/contracts/access-policy.ts" in workspace_paths
                and "docs/spec/access-control.md" in workspace_paths,
                "development should keep authentication and authorization boundaries explicit in the runnable workspace",
            ),
            _quality_gate(
                "operability-contract",
                "audit / operability contract が code workspace に実装されている",
                "server/contracts/audit-events.ts" in workspace_paths
                and "docs/spec/operability.md" in workspace_paths,
                "development should carry audit events and release-operability guidance into deploy handoff",
            ),
            _quality_gate(
                "development-standards",
                "標準開発ルールとコーディング規約が code workspace に実装されている",
                "app/lib/development-standards.ts" in workspace_paths
                and "docs/spec/development-standards.md" in workspace_paths,
                "development should keep implementation and coding rules explicit so prototype delivery stays consistent",
            ),
            _quality_gate(
                VALUE_CONTRACT_ID,
                "value contract が code workspace に実装されている",
                value_contract_ready(value_contract)
                and "app/lib/value-contract.ts" in workspace_paths
                and "docs/spec/value-contract.md" in workspace_paths,
                "development should carry persona, job, journey, IA, and value metrics into the runnable workspace",
            ),
            _quality_gate(
                OUTCOME_TELEMETRY_CONTRACT_ID,
                "outcome telemetry contract が code workspace に実装されている",
                outcome_telemetry_contract_ready(outcome_telemetry_contract)
                and "server/contracts/outcome-telemetry.ts" in workspace_paths
                and "docs/spec/outcome-telemetry.md" in workspace_paths,
                "development should carry success metrics, telemetry events, and kill criteria into the runnable workspace",
            ),
            _quality_gate(
                "work-unit-artifacts",
                "WU / wave artifact が code workspace に実装されている",
                "app/lib/work-unit-contracts.ts" in workspace_paths
                and "docs/spec/work-unit-contracts.md" in workspace_paths
                and "docs/spec/delivery-waves.md" in workspace_paths,
                "development should materialize wave and work-unit topology inside the runnable workspace",
            ),
            _quality_gate(
                "code-workspace",
                "package tree / file tree / route binding を持つ multi-file workspace が存在する",
                bool(_as_list(code_workspace.get("package_tree")))
                and bool(_as_list(code_workspace.get("files")))
                and bool(_as_list(code_workspace.get("route_bindings"))),
                "development should preserve a repo-native code workspace, not only a single HTML artifact",
            ),
            _quality_gate(
                "repo-execution",
                "materialized repo/worktree で install / build / test が通っている",
                bool(repo_execution)
                and repo_execution.get("ready") is True
                and _check_status(_as_dict(repo_execution.get("build")).get("status"), "passed")
                and _check_status(_as_dict(repo_execution.get("install")).get("status"), "passed"),
                "development should execute the generated code workspace inside a real repo or detached worktree before deploy",
            ),
            _quality_gate(
                "milestone-coverage",
                "all milestone checks are satisfied",
                total > 0 and satisfied == total,
                "all milestone results should be satisfied before deploy",
            ),
            _quality_gate(
                "deploy-handoff",
                "deploy phase に渡す operator checklist と evidence が揃っている",
                bool(deploy_checklist)
                and _check_status(development_handoff.get("readiness_status"), "ready_for_deploy")
                and not _as_list(development_handoff.get("blocking_issues"))
                and development_handoff.get("wave_exit_ready") is True
                and (non_final_wave_count == 0 or ready_wave_count >= non_final_wave_count),
                "development should finish with a deploy-ready handoff packet, not only a build artifact",
            ),
        ]
        return _contract(
            phase=phase,
            contract_type="AutonomousDeliveryArtifact",
            status=status,
            summary="Integrated build output, delivery graph, and deploy handoff result.",
            outputs={
                "buildBytes": len(build_code.encode("utf-8")),
                "milestonesSatisfied": satisfied,
                "milestonesTotal": total,
                "buildCostUsd": build_cost,
                "buildIteration": int(project_record.get("buildIteration", 0) or 0),
                "workPackageCount": len(work_packages),
                "criticalPathCount": len(critical_path),
                "waveCount": len(waves),
                "workUnitCount": len(work_unit_contracts),
                "topologyFingerprint": topology_fingerprint or None,
                "runtimeGraphFingerprint": runtime_graph_fingerprint or None,
                "readyWaveCount": ready_wave_count,
                "blockedWorkUnitCount": len(_as_list(development_handoff.get("blocked_work_unit_ids"))),
                "laneCount": len(_as_list(delivery_plan.get("lanes"))),
                "valueMetricCount": len(_as_list(value_contract.get("success_metrics"))),
                "telemetryEventCount": len(_as_list(outcome_telemetry_contract.get("telemetry_events"))),
                "packageCount": int(workspace_summary.get("package_count", 0) or 0),
                "workspaceFileCount": int(workspace_summary.get("file_count", 0) or 0),
                "routeBindingCount": int(workspace_summary.get("route_binding_count", 0) or 0),
                "unresolvedSpecGapCount": len(_as_list(spec_audit.get("unresolved_gaps"))),
                "repoExecutionMode": repo_execution.get("mode"),
                "repoExecutionReady": repo_execution.get("ready") is True,
                "deployChecklistCount": len(deploy_checklist),
                "handoffStatus": development_handoff.get("readiness_status"),
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
            if _check_status(_as_dict(item).get("status"), "fail")
        ]
        gates = [
            _quality_gate(
                "deploy-checks",
                "release gate checks are green",
                bool(checks) and not failing,
                "deploy requires checks and no failing blockers",
            ),
            _quality_gate(
                VALUE_CONTRACT_ID,
                "release gate が value contract readiness を通過している",
                any(
                    _as_dict(item).get("id") == VALUE_CONTRACT_ID and _check_status(_as_dict(item).get("status"), "pass")
                    for item in checks
                ),
                "deploy should confirm the release remains tied to personas, JTBD, IA, and success metrics",
            ),
            _quality_gate(
                OUTCOME_TELEMETRY_CONTRACT_ID,
                "release gate が outcome telemetry readiness を通過している",
                any(
                    _as_dict(item).get("id") == OUTCOME_TELEMETRY_CONTRACT_ID and _check_status(_as_dict(item).get("status"), "pass")
                    for item in checks
                ),
                "deploy should confirm telemetry, kill criteria, and learning hooks exist before promotion",
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
                "valueContractCheck": next(
                    (_as_dict(item).get("status") for item in checks if _as_dict(item).get("id") == VALUE_CONTRACT_ID),
                    None,
                ),
                "outcomeTelemetryCheck": next(
                    (
                        _as_dict(item).get("status")
                        for item in checks
                        if _as_dict(item).get("id") == OUTCOME_TELEMETRY_CONTRACT_ID
                    ),
                    None,
                ),
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
