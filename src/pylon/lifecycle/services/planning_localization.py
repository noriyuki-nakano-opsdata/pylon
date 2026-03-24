"""Pure planning localization helpers for lifecycle orchestration."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from typing import Any

_STRUCTURED_SKIP_KEYS = frozenset(
    {
        "id",
        "severity",
        "priority",
        "phase",
        "selected",
        "implementation_cost",
        "category",
        "type",
        "emotion",
        "navigation_model",
        "confidence",
        "uncertainty",
        "user_delight",
        "milestone_id",
        "claim_id",
        "use_case_id",
    }
)

_BEST_EFFORT_EXACT_TRANSLATIONS: dict[str, str] = {
    "clear": "明快",
    "adaptive": "適応的",
    "modern": "モダン",
    "balanced": "均衡",
    "practical": "実務的",
    "high": "高い",
    "medium": "中程度",
    "low": "低い",
    "must": "必須",
    "should": "推奨",
    "could": "任意",
    "must-be": "当たり前品質",
    "one-dimensional": "一元的品質",
    "attractive": "魅力品質",
    "indifferent": "無関心",
    "reverse": "逆転",
}

_BEST_EFFORT_REGEX_TRANSLATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bMilestones lack stop conditions\b", re.IGNORECASE), "マイルストーンに中止条件がありません"),
    (re.compile(r"\bSpeed-vs-governance assumption is unvalidated\b", re.IGNORECASE), "速度重視か統制重視かの前提が未検証です"),
    (re.compile(r"\bImpatient Evaluator has no hard gate\b", re.IGNORECASE), "早期離脱ユーザーへのハードゲートがありません"),
    (re.compile(r"\bHistory and recovery scope is unbounded\b", re.IGNORECASE), "履歴と復旧のスコープが膨らみやすい状態です"),
    (re.compile(r"\bMulti-agent architectural assumption may foreclose future options\b", re.IGNORECASE), "マルチエージェント前提の扱い次第で将来の選択肢を狭める恐れがあります"),
    (re.compile(r"\bScope pressure around operator console\b", re.IGNORECASE), "運用コンソールまわりのスコープ圧力が高い状態です"),
    (re.compile(r"Neither M1 nor M2 has a defined failure signal or halt threshold\.", re.IGNORECASE), "M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。"),
    (re.compile(r"The team will ship on schedule rather than on evidence\.", re.IGNORECASE), "このままでは、根拠ではなく予定に合わせて出荷してしまいます。"),
    (re.compile(r"This is the single highest-probability path to a product that appears to progress while the core assumption goes untested\.", re.IGNORECASE), "中核仮説を検証しないまま、進んでいるように見える製品を作ってしまう最も起こりやすい経路です。"),
    (re.compile(r"Both milestone-falsifier findings confirm that milestones without stop conditions produce shipping momentum rather than evidence\.", re.IGNORECASE), "milestone-falsifier の両指摘が、中止条件のないマイルストーンは根拠ではなく勢いで進んでしまうことを示しています。"),
    (re.compile(r"This is a structural gap that will corrupt all downstream learning\.", re.IGNORECASE), "これは以降の学習判断を歪める構造的な欠陥です。"),
    (re.compile(r"scope-skeptic and assumption-2 both flag that scope blur is the primary risk to learning\.", re.IGNORECASE), "scope-skeptic と assumption-2 の両方が、スコープの曖昧化を学習上の最大リスクと指摘しています。"),
    (re.compile(r"Locking the loop definition in design prevents feature creep from obscuring whether the core workflow works\.", re.IGNORECASE), "デザイン段階でループ定義を固定すると、機能肥大でコアワークフローの有効性が見えなくなるのを防げます。"),
    (re.compile(r"If this remains in the first cut, the team may lose falsifiability and review speed\.", re.IGNORECASE), "これを初期スコープに残すと、仮説の反証可能性とレビュー速度を失う恐れがあります。"),
    (re.compile(r"Keep this out of the first release unless a research claim explicitly requires it\.", re.IGNORECASE), "調査上の必須要件として明示されない限り、初回リリースには含めません。"),
    (re.compile(r"The entire selected feature set assumes users \(represented by Naoki\) will accept onboarding friction in exchange for control and traceability\.", re.IGNORECASE), "現在の機能選定は、Naoki のような利用者が導入時の摩擦を受け入れてでも統制と追跡可能性を重視する、という前提に立っています。"),
    (re.compile(r"If users actually optimize for speed, the scope is wrong and no current instrumentation will surface this before rollout\.", re.IGNORECASE), "実際には速度が優先されるなら、スコープは誤っており、現状の計測ではリリース前にそのズレを検知できません。"),
    (re.compile(r"The negative persona is documented but not wired into acceptance criteria or instrumentation\.", re.IGNORECASE), "ネガティブペルソナは定義されていますが、受け入れ条件や計測設計にはまだ組み込まれていません。"),
    (re.compile(r"Early evaluators who abandon after one incomplete run will not generate actionable signal unless session-completion metrics are captured from day one\.", re.IGNORECASE), "初回の不完全な実行で離脱する評価者は、初日からセッション完了率を計測しない限り、有効な学習シグナルを残しません。"),
    (re.compile(r"Selected without a size constraint, history and recovery can silently consume M1 capacity\.", re.IGNORECASE), "履歴と復旧は規模の上限を決めないまま選ぶと、M1 の工数を静かに食い潰します。"),
    (re.compile(r"If it expands beyond single-run restoration, it delays the falsifiable core loop\.", re.IGNORECASE), "単一 run の復元を超えて広がると、反証可能なコアループの検証を遅らせます。"),
    (re.compile(r"assumption-3 identifies a structural shift in the LLM landscape\.", re.IGNORECASE), "assumption-3 は LLM 活用の構造変化を指摘しています。"),
    (re.compile(r"If M1 architecture assumes single-agent execution, adding multi-agent coordination later may require rework that is disproportionate to the original build cost\.", re.IGNORECASE), "M1 の設計が単一エージェント前提だと、後からマルチエージェント協調を足す際の手戻りが初期実装コストに見合わないほど大きくなる恐れがあります。"),
    (re.compile(r"Add explicit failure conditions to both milestones before design begins\.", re.IGNORECASE), "デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。"),
    (re.compile(r"Each milestone spec must include: \(a\) the observable failure signal, \(b\) a numeric stop threshold, and \(c\) a named decision owner who can call a halt\.", re.IGNORECASE), "各マイルストーン仕様には、(a) 観測可能な失敗シグナル、(b) 数値の中止閾値、(c) 停止判断を下せる責任者名を必ず含めます。"),
    (re.compile(r"Milestones without stop conditions create false progress\.", re.IGNORECASE), "中止条件のないマイルストーンは、進捗しているように見えるだけの誤学習を生みます。"),
    (re.compile(r"\bmilestone-1 and milestone-2\b", re.IGNORECASE), "マイルストーン 1 と 2"),
    (re.compile(r"\bProduct Owner\b", re.IGNORECASE), "プロダクトオーナー"),
    (re.compile(r"\bPrimary User\b", re.IGNORECASE), "主要ユーザー"),
    (re.compile(r"\bComplete the primary workflow\b", re.IGNORECASE), "主要ワークフローを完了する"),
    (re.compile(r"\bAdjust settings\b", re.IGNORECASE), "設定を調整する"),
    (re.compile(r"\bProtect first-release scope\b", re.IGNORECASE), "初回リリースのスコープを守る"),
    (re.compile(r"Adding convenience features early would blur whether the core workflow is actually working\.", re.IGNORECASE), "便利機能を早期に足すと、コアワークフローが本当に機能しているか判別しにくくなります。"),
    (re.compile(r"Keep the first milestone focused on a single evidence-to-decision loop\.", re.IGNORECASE), "最初のマイルストーンは、根拠から意思決定までの単一ループに絞ります。"),
    (re.compile(r"Naoki will trade setup breadth for stronger control and traceability\.", re.IGNORECASE), "Naoki は導入範囲の広さよりも、強い統制と追跡可能性を優先します。"),
    (re.compile(r"\bImpatient Evaluator\b", re.IGNORECASE), "すぐ離脱する評価者"),
    (re.compile(r"Leaves before the core loop demonstrates value\.", re.IGNORECASE), "コアループの価値が見える前に離脱します。"),
    (re.compile(r"Judges the product after one incomplete run\.", re.IGNORECASE), "1 回の不完全な実行だけで製品を判断します。"),
    (re.compile(r"Make the first successful workflow obvious and measurable\.", re.IGNORECASE), "最初の成功フローがひと目で分かり、計測できる状態にします。"),
    (re.compile(r"If Core workflow ready cannot show observable completion evidence, stop scope expansion and re-open planning\.", re.IGNORECASE), "コアワークフローの完了で観測可能な証跡を示せない場合は、スコープ拡張を止めて planning を再開します。"),
    (re.compile(r"If Evidence-to-build loop cannot show observable completion evidence, stop scope expansion and re-open planning\.", re.IGNORECASE), "根拠からビルドまでのループで観測可能な完了証跡を示せない場合は、スコープ拡張を止めて企画を再開します。"),
    (re.compile(r"Milestones must be falsifiable instead of narrative\.", re.IGNORECASE), "マイルストーンは物語ではなく、反証可能でなければなりません。"),
    (re.compile(r"Treat phase-by-phase (?:artifact lineage|成果物の系譜) as a first-class surface so approval evidence never gets lost\.", re.IGNORECASE), "フェーズごとの成果物の系譜を主軸として扱い、承認判断の根拠を失わないようにします。"),
    (re.compile(r"Stabilize handoff and rework control before widening multi-agent parallelism\.", re.IGNORECASE), "マルチエージェントの並列実行を広げる前に、handoff と差し戻しの制御面を固めます。"),
    (re.compile(r"\bBalanced Product\b", re.IGNORECASE), "バランス型プロダクト"),
    (re.compile(r"\bOperational Clarity\b", re.IGNORECASE), "運用明瞭性"),
    (re.compile(r"\brelease readiness\b", re.IGNORECASE), "リリース準備"),
    (re.compile(r"\boperator console\b", re.IGNORECASE), "運用コンソール"),
    (re.compile(r"\bartifact lineage\b", re.IGNORECASE), "成果物の系譜"),
    (re.compile(r"\bRun discovery-to-build workflow\b", re.IGNORECASE), "調査からビルドまでを実行する"),
    (re.compile(r"\bRecover degraded research lane\b", re.IGNORECASE), "劣化した調査レーンを回復する"),
    (re.compile(r"\bApprove or rework a phase\b", re.IGNORECASE), "フェーズを承認または差し戻す"),
    (re.compile(r"\bTrace artifact lineage\b", re.IGNORECASE), "成果物の系譜を追跡する"),
    (re.compile(r"\bConfigure policies and team routing\b", re.IGNORECASE), "ポリシーとチームルーティングを設定する"),
    (re.compile(r"\bMonitor active runs and intervene\b", re.IGNORECASE), "実行中の run を監視して介入する"),
    (re.compile(r"general-purpose digital products with mixed audiences", re.IGNORECASE), "幅広い利用者が混在する汎用デジタルプロダクト"),
    (re.compile(r"progressive disclosure and responsive content grouping", re.IGNORECASE), "段階的な情報開示とレスポンシブな情報グルーピング"),
    (re.compile(r"clear semantic hierarchy and keyboard-safe interactions", re.IGNORECASE), "明確な意味階層とキーボードでも迷わないインタラクション"),
    (re.compile(r"subtle entry fades", re.IGNORECASE), "穏やかなフェードイン"),
    (re.compile(r"hover elevation", re.IGNORECASE), "hover 時の浮き上がり"),
    (re.compile(r"clear focus rings", re.IGNORECASE), "明確なフォーカスリング"),
    (re.compile(r"generic dashboard filler", re.IGNORECASE), "情報密度の低いダッシュボード装飾"),
    (re.compile(r"weak empty states", re.IGNORECASE), "弱い空状態"),
    (re.compile(r"low-information hero sections", re.IGNORECASE), "情報量の少ないヒーロー領域"),
    (re.compile(r"The product should stay adaptable while preserving clear task hierarchy and predictable interactions\.", re.IGNORECASE), "プロダクトは適応性を保ちつつ、タスク階層の明快さと予測可能な操作感を維持します。"),
    (re.compile(r"phase ごとの artifact lineage を first-class にし、承認判断の根拠を失わないようにする", re.IGNORECASE), "フェーズごとの成果物の系譜を主軸として扱い、承認判断の根拠を失わないようにします。"),
    (re.compile(r"\bThe design handoff packet is ready\.", re.IGNORECASE), "デザインへ渡す判断パケットを整理しました。"),
    (re.compile(r"\bStart design with the primary path, decision criteria, and stop conditions visible up front\.", re.IGNORECASE), "デザインでは主導線、判断基準、停止条件が先に分かる状態で比較を始めます。"),
    (re.compile(r"\bproduct lead\b", re.IGNORECASE), "プロダクト責任者"),
    (re.compile(r"\bresearch lead\b", re.IGNORECASE), "リサーチ責任者"),
    (re.compile(r"\bengineering lead\b", re.IGNORECASE), "開発責任者"),
    (re.compile(r"\barchitecture lead\b", re.IGNORECASE), "アーキテクト責任者"),
    (re.compile(r"\bdesign kickoff\b", re.IGNORECASE), "デザイン着手前"),
    (re.compile(r"\bend of M1 user testing\b", re.IGNORECASE), "M1 ユーザーテスト終了前"),
    (re.compile(r"\bM1 instrumentation spec\b", re.IGNORECASE), "M1 計測仕様確定前"),
    (re.compile(r"\bM1 design spec\b", re.IGNORECASE), "M1 デザイン仕様確定前"),
    (re.compile(r"\bM1 technical design review\b", re.IGNORECASE), "M1 技術設計レビュー前"),
)

_PLANNING_RISK_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_PLANNING_RECOMMENDATION_PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_PLANNING_DEADLINE_ORDER_EN: tuple[str, ...] = (
    "design kickoff",
    "m1 instrumentation spec",
    "m1 design spec",
    "m1 technical design review",
    "end of m1 user testing",
)

_PLANNING_DEADLINE_ORDER_JA: tuple[str, ...] = (
    "デザイン着手前",
    "M1 計測仕様確定前",
    "M1 デザイン仕様確定前",
    "M1 技術設計レビュー前",
    "M1 ユーザーテスト終了前",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _contains_japanese(text: str) -> bool:
    return any((("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")) for ch in text)


def _contains_latin_word(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", text))


def _looks_like_machine_token(text: str) -> bool:
    normalized = text.strip()
    return bool(
        normalized
        and (
            normalized.startswith(("http://", "https://", "project://"))
            or all(ch.islower() or ch.isdigit() or ch in "_.:-/#" for ch in normalized)
        )
    )


def _translatable_text(value: Any) -> str:
    text = _normalize_space(value)
    if not text or _looks_like_machine_token(text):
        return ""
    if _contains_japanese(text) and not _contains_latin_word(text):
        return ""
    return text


def _assign_text(target: dict[str, Any], key: str, value: Any) -> None:
    text = _translatable_text(value)
    if text:
        target[key] = text


def _assign_text_list(target: dict[str, Any], key: str, value: Any) -> None:
    translated = [_translatable_text(item) for item in _as_list(value)]
    if any(item for item in translated):
        target[key] = translated


def _record_list_payload(value: Any, builder: Any) -> list[dict[str, Any]]:
    localized = [builder(_as_dict(item)) for item in _as_list(value)]
    return localized if any(item for item in localized) else []


def _structured_translation_payload(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, Mapping):
        translated: dict[str, Any] = {}
        for key, item in value.items():
            if key in _STRUCTURED_SKIP_KEYS:
                continue
            localized = _structured_translation_payload(item, parent_key=key)
            if localized not in ("", None, [], {}):
                translated[str(key)] = localized
        return translated
    if isinstance(value, list):
        translated_items = [
            _structured_translation_payload(item, parent_key=parent_key)
            for item in value
        ]
        return translated_items if any(item not in ("", None, [], {}) for item in translated_items) else []
    if isinstance(value, str):
        if parent_key in _STRUCTURED_SKIP_KEYS:
            return ""
        return _translatable_text(value)
    return None


def _try_parse_loose_structured_value(raw: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    candidate = text
    if candidate.startswith("{") and candidate.endswith("}") and "}, {" in candidate:
        candidate = f"[{candidate}]"
    try:
        return ast.literal_eval(candidate)
    except Exception:
        return None


def _structured_text_payload(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _try_parse_loose_structured_value(value)
        if parsed is None:
            return _translatable_text(value)
        return _structured_translation_payload(parsed)
    if isinstance(value, (list, Mapping)):
        return _structured_translation_payload(value)
    return None


def _is_empty_translation(value: Any) -> bool:
    return value in ("", None, [], {})


def _merge_localized_value(original: Any, translated: Any) -> Any:
    if _is_empty_translation(translated):
        return original
    if isinstance(original, Mapping) and isinstance(translated, Mapping):
        merged = dict(original)
        for key, value in translated.items():
            merged[key] = _merge_localized_value(merged.get(key), value)
        return merged
    if isinstance(original, list) and isinstance(translated, list):
        merged = list(original)
        for index, value in enumerate(translated):
            if index >= len(merged):
                if not _is_empty_translation(value):
                    merged.append(value)
                continue
            merged[index] = _merge_localized_value(merged[index], value)
        return merged
    if isinstance(translated, str):
        normalized = translated.strip()
        return normalized or original
    return translated


def _merge_structured_text(original: Any, translated: Any) -> Any:
    if _is_empty_translation(translated):
        return original
    if isinstance(original, str):
        parsed = _try_parse_loose_structured_value(original)
        if parsed is not None and isinstance(translated, (list, Mapping)):
            merged = _merge_localized_value(parsed, translated)
            return json.dumps(merged, ensure_ascii=False)
        if isinstance(translated, str):
            return translated.strip() or original
        return original
    return _merge_localized_value(original, translated)


def _best_effort_translate_text(value: Any) -> str:
    text = _normalize_space(value)
    if not text or _looks_like_machine_token(text):
        return text
    translated = text
    for pattern, replacement in _BEST_EFFORT_REGEX_TRANSLATIONS:
        translated = pattern.sub(replacement, translated)
    if translated == text:
        translated = _BEST_EFFORT_EXACT_TRANSLATIONS.get(text.casefold(), text)
    return _normalize_space(translated)


def _best_effort_translate_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _best_effort_translate_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_best_effort_translate_value(item) for item in value]
    if isinstance(value, str):
        return _best_effort_translate_text(value)
    return value


def _persona_payload(persona: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("name", "role", "tech_proficiency", "context"):
        _assign_text(translated, key, persona.get(key))
    for key in ("goals", "frustrations"):
        _assign_text_list(translated, key, persona.get(key))
    return translated


def _story_payload(story: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("role", "action", "benefit"):
        _assign_text(translated, key, story.get(key))
    _assign_text_list(translated, "acceptance_criteria", story.get("acceptance_criteria"))
    return translated


def _kano_payload(feature: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("feature", "rationale"):
        _assign_text(translated, key, feature.get(key))
    return translated


def _journey_touchpoint_payload(touchpoint: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("persona", "action", "touchpoint", "pain_point", "opportunity"):
        _assign_text(translated, key, touchpoint.get(key))
    return translated


def _journey_payload(journey: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    _assign_text(translated, "persona_name", journey.get("persona_name"))
    touchpoints = _record_list_payload(
        journey.get("touchpoints"),
        _journey_touchpoint_payload,
    )
    if touchpoints:
        translated["touchpoints"] = touchpoints
    return translated


def _job_story_payload(story: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("situation", "motivation", "outcome"):
        _assign_text(translated, key, story.get(key))
    _assign_text_list(translated, "related_features", story.get("related_features"))
    return translated


def _ia_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("label", "description"):
        _assign_text(translated, key, node.get(key))
    children = _record_list_payload(node.get("children"), _ia_node_payload)
    if children:
        translated["children"] = children
    return translated


def _ia_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    ia = _as_dict(analysis.get("ia_analysis"))
    if not ia:
        return {}
    translated: dict[str, Any] = {}
    site_map = _record_list_payload(ia.get("site_map"), _ia_node_payload)
    if site_map:
        translated["site_map"] = site_map
    key_paths = []
    for item in _as_list(ia.get("key_paths")):
        path = _as_dict(item)
        translated_path: dict[str, Any] = {}
        _assign_text(translated_path, "name", path.get("name"))
        _assign_text_list(translated_path, "steps", path.get("steps"))
        key_paths.append(translated_path)
    if any(item for item in key_paths):
        translated["key_paths"] = key_paths
    return translated


def _actor_payload(actor: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("name", "description"):
        _assign_text(translated, key, actor.get(key))
    for key in ("goals", "interactions"):
        _assign_text_list(translated, key, actor.get(key))
    return translated


def _role_payload(role: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    _assign_text(translated, "name", role.get("name"))
    for key in ("responsibilities", "permissions", "related_actors"):
        _assign_text_list(translated, key, role.get(key))
    return translated


def _alternative_flow_payload(flow: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    _assign_text(translated, "condition", flow.get("condition"))
    _assign_text_list(translated, "steps", flow.get("steps"))
    return translated


def _use_case_payload(use_case: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("title", "actor", "category", "sub_category"):
        _assign_text(translated, key, use_case.get(key))
    for key in ("preconditions", "main_flow", "postconditions", "related_stories"):
        _assign_text_list(translated, key, use_case.get(key))
    alternative_flows = _record_list_payload(
        use_case.get("alternative_flows"),
        _alternative_flow_payload,
    )
    if alternative_flows:
        translated["alternative_flows"] = alternative_flows
    return translated


def _milestone_payload(milestone: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("name", "criteria", "rationale"):
        _assign_text(translated, key, milestone.get(key))
    return translated


def _design_tokens_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    tokens = _as_dict(analysis.get("design_tokens"))
    if not tokens:
        return {}
    translated: dict[str, Any] = {}
    style = _as_dict(tokens.get("style"))
    translated_style: dict[str, Any] = {}
    for key in ("name", "best_for", "performance", "accessibility"):
        _assign_text(translated_style, key, style.get(key))
    _assign_text_list(translated_style, "keywords", style.get("keywords"))
    if translated_style:
        translated["style"] = translated_style
    colors = _as_dict(tokens.get("colors"))
    translated_colors: dict[str, Any] = {}
    _assign_text(translated_colors, "notes", colors.get("notes"))
    if translated_colors:
        translated["colors"] = translated_colors
    typography = _as_dict(tokens.get("typography"))
    translated_typography: dict[str, Any] = {}
    _assign_text_list(translated_typography, "mood", typography.get("mood"))
    if translated_typography:
        translated["typography"] = translated_typography
    _assign_text_list(translated, "effects", tokens.get("effects"))
    _assign_text_list(translated, "anti_patterns", tokens.get("anti_patterns"))
    _assign_text(translated, "rationale", tokens.get("rationale"))
    return translated


def _feature_decision_payload(decision: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("feature", "rejection_reason"):
        _assign_text(translated, key, decision.get(key))
    _assign_text_list(translated, "counterarguments", decision.get("counterarguments"))
    return translated


def _rejected_feature_payload(feature: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("feature", "reason"):
        _assign_text(translated, key, feature.get(key))
    _assign_text_list(translated, "counterarguments", feature.get("counterarguments"))
    return translated


def _assumption_payload(assumption: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    _assign_text(translated, "statement", assumption.get("statement"))
    return translated


def _red_team_payload(finding: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("title", "impact", "recommendation", "related_feature"):
        _assign_text(translated, key, finding.get(key))
    return translated


def _negative_persona_payload(persona: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("name", "scenario", "risk", "mitigation"):
        _assign_text(translated, key, persona.get(key))
    return translated


def _traceability_payload(item: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("claim", "use_case", "feature", "milestone"):
        _assign_text(translated, key, item.get(key))
    return translated


def _kill_criterion_payload(item: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in ("condition", "rationale"):
        _assign_text(translated, key, item.get(key))
    return translated


def _coverage_summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for key in (
        "uncovered_features",
        "use_cases_without_milestone",
        "use_cases_without_traceability",
        "required_use_cases_without_traceability",
    ):
        _assign_text_list(translated, key, summary.get(key))
    preset_breakdown: list[dict[str, Any]] = []
    for entry in _as_list(summary.get("preset_breakdown")):
        item = _as_dict(entry)
        if not item:
            continue
        preset_breakdown.append(
            {
                "preset": str(item.get("preset", "")),
                "epic_count": item.get("epic_count"),
                "wbs_count": item.get("wbs_count"),
                "total_effort_hours": item.get("total_effort_hours"),
            }
        )
    if preset_breakdown:
        translated["preset_breakdown"] = preset_breakdown
    for key in (
        "selected_feature_count",
        "job_story_count",
        "use_case_count",
        "actor_count",
        "role_count",
        "traceability_count",
        "required_traceability_use_case_count",
        "milestone_count",
    ):
        value = summary.get(key)
        if value not in (None, ""):
            translated[key] = value
    return translated


def _structured_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, str):
        parsed = _try_parse_loose_structured_value(value)
        if isinstance(parsed, Mapping):
            return [dict(parsed)]
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, Mapping)]
    return []


def _planning_deadline_rank(value: Any, *, target_language: str) -> int:
    normalized = _normalize_space(value).casefold()
    if not normalized:
        return 99
    ordered_labels = _PLANNING_DEADLINE_ORDER_JA if target_language == "ja" else _PLANNING_DEADLINE_ORDER_EN
    try:
        return ordered_labels.index(normalized)
    except ValueError:
        return len(ordered_labels)


def _planning_risks(analysis: dict[str, Any], *, target_language: str) -> list[dict[str, Any]]:
    risks = [
        {
            "id": str(item.get("id", f"risk-{index + 1}")),
            "severity": _normalize_space(item.get("severity") or "medium").lower(),
            "title": _normalize_space(item.get("title")),
            "description": _normalize_space(item.get("description")),
            "owner": _normalize_space(item.get("owner")) or None,
            "must_resolve_before": _normalize_space(
                item.get("must_resolve_before") or item.get("mustResolveBefore")
            )
            or None,
        }
        for index, item in enumerate(_structured_records(analysis.get("judge_summary")))
    ]
    filtered = [item for item in risks if item["title"] and item["description"]]
    return sorted(
        filtered,
        key=lambda item: (
            _PLANNING_RISK_SEVERITY_ORDER.get(str(item.get("severity")), 99),
            _planning_deadline_rank(item.get("must_resolve_before"), target_language=target_language),
            str(item.get("title", "")).casefold(),
        ),
    )


def _planning_recommendation_cards(
    analysis: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    cards_with_order: list[tuple[int, dict[str, Any]]] = []
    notes: list[str] = []
    for index, entry in enumerate(_as_list(analysis.get("recommendations"))):
        parsed = _structured_records(entry)
        first = parsed[0] if parsed else {}
        if first and any(_normalize_space(first.get(key)) for key in ("action", "rationale", "target")):
            cards_with_order.append(
                (
                    index,
                    {
                    "id": str(first.get("id", f"rec-{index + 1}")),
                    "priority": _normalize_space(first.get("priority") or "medium").lower(),
                    "target": _normalize_space(first.get("target")) or None,
                    "action": _normalize_space(first.get("action")),
                    "rationale": _normalize_space(first.get("rationale")) or None,
                    },
                )
            )
            continue
        note = _normalize_space(entry)
        if note:
            notes.append(note)
    sorted_cards = sorted(
        [item for item in cards_with_order if item[1]["action"]],
        key=lambda item: (
            _PLANNING_RECOMMENDATION_PRIORITY_ORDER.get(str(item[1].get("priority")), 99),
            item[0],
        ),
    )
    return [item for _, item in sorted_cards], notes


def _pick_planning_kano_focus(analysis: dict[str, Any]) -> dict[str, Any] | None:
    category_rank = {
        "attractive": 0,
        "one-dimensional": 1,
        "must-be": 2,
        "indifferent": 3,
        "reverse": 4,
    }
    features = [_as_dict(item) for item in _as_list(analysis.get("kano_features")) if _as_dict(item)]
    ordered = sorted(
        features,
        key=lambda item: (
            category_rank.get(str(item.get("category", "")).lower(), 99),
            -float(item.get("user_delight", 0) or 0),
        ),
    )
    return ordered[0] if ordered else None


def _planning_operator_copy(
    analysis: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    is_japanese = target_language == "ja"
    risks = _planning_risks(analysis, target_language=target_language)
    recommendation_cards, recommendation_notes = _planning_recommendation_cards(analysis)
    top_risk = risks[0] if risks else None
    top_recommendation = recommendation_cards[0] if recommendation_cards else None
    top_persona = _as_dict(_as_list(analysis.get("personas"))[0]) if _as_list(analysis.get("personas")) else {}
    top_use_case = _as_dict(_as_list(analysis.get("use_cases"))[0]) if _as_list(analysis.get("use_cases")) else {}
    top_kano = _pick_planning_kano_focus(analysis)
    top_kill_criterion = _as_dict(_as_list(analysis.get("kill_criteria"))[0]) if _as_list(analysis.get("kill_criteria")) else {}
    top_milestone = _as_dict(_as_list(analysis.get("recommended_milestones"))[0]) if _as_list(analysis.get("recommended_milestones")) else {}
    design_style = _normalize_space(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("name"))
    feature_name = _normalize_space(top_kano.get("feature")) if top_kano else ""
    delight_score = float(top_kano.get("user_delight", 0) or 0) if top_kano else 0.0
    persona_name = _normalize_space(top_persona.get("name")) or ("主要ユーザー" if is_japanese else "Primary user")
    use_case_title = _normalize_space(top_use_case.get("title")) or (
        "主要ユースケースを設計基準にする"
        if is_japanese
        else "Use the leading use case as the design benchmark"
    )
    kill_condition = _normalize_space(top_kill_criterion.get("condition"))
    risk_due = _normalize_space(top_risk.get("must_resolve_before")) if top_risk else ""
    risk_due_suffix = f"（{risk_due}まで）" if is_japanese and risk_due else (f" (before {risk_due})" if risk_due else "")
    if not any(
        (
            top_risk,
            top_recommendation,
            top_persona,
            top_use_case,
            top_kano,
            top_kill_criterion,
            top_milestone,
            design_style,
            recommendation_notes,
        )
    ):
        return {}

    council_cards: list[dict[str, Any]] = []

    if top_recommendation:
        council_cards.append(
            {
                "id": "product-council",
                "agent": "プロダクト評議" if is_japanese else "Product Council",
                "lens": "価値判断" if is_japanese else "Value decision",
                "title": top_recommendation["action"],
                "summary": top_recommendation.get("rationale")
                or (
                    "価値仮説を崩さずに次フェーズへ渡すための最優先判断です。"
                    if is_japanese
                    else "This is the highest-leverage decision before handing off to design."
                ),
                "action_label": "推奨アクションへ" if is_japanese else "Open recommendations",
                "target_section": "recommendation",
                "tone": top_recommendation.get("priority") or "medium",
            }
        )

    if top_risk:
        council_cards.append(
            {
                "id": "research-council",
                "agent": "リサーチ評議" if is_japanese else "Research Council",
                "lens": "リスク信号" if is_japanese else "Risk signal",
                "title": top_risk["title"],
                "summary": top_risk["description"],
                "action_label": "リスクを見る" if is_japanese else "Review risks",
                "target_section": "risk",
                "tone": top_risk.get("severity") or "medium",
            }
        )

    if top_kano:
        design_summary = (
            f"{design_style} を基調に、「{feature_name}」を主体験として強調します。"
            if is_japanese and design_style
            else (
                f"{design_style} anchors the next comparison, with “{feature_name}” treated as the primary experience."
                if design_style
                else (
                    f"{feature_name} は {delight_score:.1f} の満足度仮説を持つため、design の主導線として扱います。"
                    if is_japanese
                    else f"{feature_name} leads the next design comparison with a {delight_score:.1f} delight hypothesis."
                )
            )
        )
        council_cards.append(
            {
                "id": "design-council",
                "agent": "デザイン評議" if is_japanese else "Design Council",
                "lens": "体験設計" if is_japanese else "Experience direction",
                "title": feature_name,
                "summary": design_summary,
                "action_label": (
                    "デザイントークンへ"
                    if design_style and is_japanese
                    else (
                        "Open design tokens"
                        if design_style
                        else ("KANO へ" if is_japanese else "Open KANO")
                    )
                ),
                "target_tab": "design-tokens" if design_style else "kano",
                "tone": "high",
            }
        )

    if top_kill_criterion or top_milestone or top_persona:
        milestone_name = _normalize_space(top_milestone.get("name"))
        council_cards.append(
            {
                "id": "delivery-council",
                "agent": "デリバリー評議" if is_japanese else "Delivery Council",
                "lens": "実行条件" if is_japanese else "Execution condition",
                "title": _normalize_space(top_kill_criterion.get("condition"))
                or milestone_name
                or (
                    f"{persona_name}の体験を先に固める" if is_japanese else f"Stabilize the {persona_name} journey first"
                ),
                "summary": _normalize_space(top_kill_criterion.get("rationale"))
                or _normalize_space(top_milestone.get("criteria"))
                or (
                    f"{persona_name}の文脈と主要ユースケースを先に固定すると、delivery の手戻りが減ります。"
                    if is_japanese
                    else f"Locking {persona_name}'s context and primary use case first reduces delivery churn."
                ),
                "action_label": (
                    "中止基準へ"
                    if top_kill_criterion
                    else ("ユースケースへ" if top_milestone and is_japanese else ("Open use cases" if top_milestone else ("ペルソナへ" if is_japanese else "Open persona")))
                ),
                "target_tab": "overview" if top_kill_criterion else ("usecases" if top_milestone else "persona"),
                "tone": "high" if top_kill_criterion else "medium",
            }
        )

    bullets = [
        (
            f"最初に固める判断: {top_recommendation['action']}"
            if is_japanese
            else f"Lock first: {top_recommendation['action']}"
        )
        if top_recommendation
        else None,
        (
            f"未解決リスク: {top_risk['title']}{risk_due_suffix}"
            if is_japanese
            else f"Open risk: {top_risk['title']}{risk_due_suffix}"
        )
        if top_risk
        else None,
        (
            f"中心体験: {persona_name} / {use_case_title}"
            if is_japanese
            else f"Primary journey: {persona_name} / {use_case_title}"
        )
        if top_persona or top_use_case
        else None,
        (
            f"価値の主導線: {feature_name} を {delight_score:.1f} の満足度仮説で優先する"
            if is_japanese
            else f"Value lead: {feature_name} at {delight_score:.1f} delight hypothesis"
        )
        if top_kano
        else None,
        (
            f"UI の方向性: {design_style}"
            if is_japanese
            else f"UI direction: {design_style}"
        )
        if design_style
        else None,
        (
            f"停止条件: {kill_condition}"
            if is_japanese
            else f"Stop condition: {kill_condition}"
        )
        if top_kill_criterion
        else None,
        (
            f"持ち込む前提: {recommendation_notes[0]}"
            if is_japanese
            else f"Carryover assumption: {recommendation_notes[0]}"
        )
        if recommendation_notes
        else None,
    ]

    handoff_brief = {
        "headline": (
            top_recommendation["action"]
            if top_recommendation
            else (
                top_risk["title"]
                if top_risk
                else (
                    "デザインへ渡す判断パケットを整理しました。"
                    if is_japanese
                    else "The design handoff packet is ready."
                )
            )
        ),
        "summary": (
            f"{top_risk['title']} を未解決の前提として管理しつつ、デザインでは中心体験と判断基準を先に比較できるようにします。"
            if is_japanese and top_risk
            else (
                f"Treat {top_risk['title']} as an explicit constraint, and start design by comparing the primary journey and decision criteria."
                if top_risk
                else (
                    "デザインでは主導線、判断基準、停止条件が先に分かる状態で比較を始めます。"
                    if is_japanese
                    else "Start design with the primary path, decision criteria, and stop conditions visible up front."
                )
            )
        ),
        "bullets": [item for item in bullets if item][:5],
    }

    payload: dict[str, Any] = {}
    if council_cards:
        payload["council_cards"] = council_cards
    if handoff_brief["headline"] or handoff_brief["summary"] or handoff_brief["bullets"]:
        payload["handoff_brief"] = handoff_brief
    return payload


def with_planning_operator_copy(
    analysis: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    enriched = dict(analysis)
    operator_copy = _planning_operator_copy(enriched, target_language=target_language)
    if operator_copy:
        enriched["operator_copy"] = operator_copy
    return enriched


def planning_localization_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    def assign(key: str, value: Any) -> None:
        if value not in ("", None, [], {}):
            payload[key] = value

    assign("personas", _record_list_payload(analysis.get("personas"), _persona_payload))
    assign("user_stories", _record_list_payload(analysis.get("user_stories"), _story_payload))
    assign("kano_features", _record_list_payload(analysis.get("kano_features"), _kano_payload))
    recommendations = [_structured_text_payload(item) for item in _as_list(analysis.get("recommendations"))]
    if any(item not in ("", None, [], {}) for item in recommendations):
        payload["recommendations"] = recommendations
    business_model = _as_dict(analysis.get("business_model"))
    translated_business_model: dict[str, Any] = {}
    for key in ("value_propositions", "customer_segments", "channels", "revenue_streams"):
        _assign_text_list(translated_business_model, key, business_model.get(key))
    assign("business_model", translated_business_model)
    assign("user_journeys", _record_list_payload(analysis.get("user_journeys"), _journey_payload))
    assign("job_stories", _record_list_payload(analysis.get("job_stories"), _job_story_payload))
    assign("ia_analysis", _ia_payload(analysis))
    assign("actors", _record_list_payload(analysis.get("actors"), _actor_payload))
    assign("roles", _record_list_payload(analysis.get("roles"), _role_payload))
    assign("use_cases", _record_list_payload(analysis.get("use_cases"), _use_case_payload))
    assign(
        "recommended_milestones",
        _record_list_payload(analysis.get("recommended_milestones"), _milestone_payload),
    )
    assign("design_tokens", _design_tokens_payload(analysis))
    assign(
        "feature_decisions",
        _record_list_payload(analysis.get("feature_decisions"), _feature_decision_payload),
    )
    planning_context = _structured_translation_payload(analysis.get("planning_context"), parent_key="planning_context")
    assign("planning_context", planning_context)
    assign(
        "rejected_features",
        _record_list_payload(analysis.get("rejected_features"), _rejected_feature_payload),
    )
    assign("assumptions", _record_list_payload(analysis.get("assumptions"), _assumption_payload))
    assign(
        "red_team_findings",
        _record_list_payload(analysis.get("red_team_findings"), _red_team_payload),
    )
    assign(
        "negative_personas",
        _record_list_payload(analysis.get("negative_personas"), _negative_persona_payload),
    )
    assign("traceability", _record_list_payload(analysis.get("traceability"), _traceability_payload))
    assign("kill_criteria", _record_list_payload(analysis.get("kill_criteria"), _kill_criterion_payload))
    assign("coverage_summary", _coverage_summary_payload(_as_dict(analysis.get("coverage_summary"))))
    judge_summary = _structured_text_payload(analysis.get("judge_summary"))
    assign("judge_summary", judge_summary)
    return payload


def merge_planning_localization(
    analysis: dict[str, Any],
    translated: dict[str, Any],
) -> dict[str, Any]:
    localized = dict(analysis)
    if "recommendations" in translated:
        original_recommendations = _as_list(localized.get("recommendations"))
        translated_recommendations = _as_list(translated.get("recommendations"))
        localized["recommendations"] = [
            _merge_structured_text(
                original_recommendations[index],
                translated_recommendations[index] if index < len(translated_recommendations) else None,
            )
            for index in range(len(original_recommendations))
        ]
    if "judge_summary" in translated:
        localized["judge_summary"] = _merge_structured_text(
            localized.get("judge_summary"),
            translated.get("judge_summary"),
        )
    for key, value in translated.items():
        if key in {"recommendations", "judge_summary"}:
            continue
        localized[key] = _merge_localized_value(localized.get(key), value)
    return localized


def _rebuild_localized_planning_view(
    canonical: dict[str, Any],
    *,
    target_language: str,
) -> tuple[dict[str, Any], bool]:
    payload = planning_localization_payload(canonical)
    translated_payload = _best_effort_translate_value(payload) if payload else {}
    localized = (
        merge_planning_localization(dict(canonical), translated_payload)
        if translated_payload
        else dict(canonical)
    )
    localized = _best_effort_translate_value(localized)
    localized = with_planning_operator_copy(dict(localized), target_language=target_language)
    return localized, bool(translated_payload)


def backfill_planning_localization(
    analysis: dict[str, Any],
    *,
    target_language: str = "ja",
) -> dict[str, Any]:
    canonical_source = _as_dict(analysis.get("canonical")) or dict(analysis)
    canonical = with_planning_operator_copy(dict(canonical_source), target_language="en")
    localized_existing = _as_dict(analysis.get("localized"))
    if target_language != "ja":
        return {
            **dict(analysis),
            "canonical": canonical,
            "localized": with_planning_operator_copy(localized_existing, target_language=target_language),
            "display_language": target_language,
            "localization_status": str(analysis.get("localization_status") or "skipped"),
        }

    if localized_existing:
        localized, had_translated_payload = _rebuild_localized_planning_view(
            canonical,
            target_language=target_language,
        )
        display_language = str(
            analysis.get("display_language")
            or localized.get("display_language")
            or target_language
        )
        localization_status = str(
            analysis.get("localization_status")
            or localized.get("localization_status")
            or ("best_effort" if had_translated_payload else "noop")
        )
        localized["display_language"] = display_language
        localized["localization_status"] = localization_status
        return {
            **dict(analysis),
            **localized,
            "canonical": canonical,
            "localized": localized,
            "display_language": display_language,
            "localization_status": localization_status,
        }

    localized, had_translated_payload = _rebuild_localized_planning_view(
        canonical,
        target_language=target_language,
    )
    localization_status = "best_effort" if had_translated_payload else "noop"
    localized["display_language"] = target_language
    localized["localization_status"] = localization_status
    return {
        **localized,
        "canonical": canonical,
        "localized": dict(localized),
        "display_language": target_language,
        "localization_status": localization_status,
    }
