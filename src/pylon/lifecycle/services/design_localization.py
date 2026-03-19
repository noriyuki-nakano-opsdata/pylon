"""Structured localization helpers for lifecycle design variants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SKIP_STRING_KEYS = frozenset(
    {
        "id",
        "model",
        "pattern_name",
        "primary_color",
        "accent_color",
        "display_language",
        "localization_status",
        "fingerprint",
        "selected_design_id",
        "selected_design_name",
        "preview_html",
    }
)

_DESIGN_TEXT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bLifecycle Workspace\b", re.IGNORECASE), "ライフサイクルワークスペース"),
    (re.compile(r"\bResearch\b", re.IGNORECASE), "調査"),
    (re.compile(r"\bRuns\b", re.IGNORECASE), "ラン"),
    (re.compile(r"\bApprovals\b", re.IGNORECASE), "承認"),
    (re.compile(r"\bArtifacts\b", re.IGNORECASE), "成果物"),
    (re.compile(r"\bResearch Workspace\b", re.IGNORECASE), "調査ワークスペース"),
    (re.compile(r"\bApproval Gate\b", re.IGNORECASE), "承認ゲート"),
    (re.compile(r"\bArtifact Lineage\b", re.IGNORECASE), "成果物リネージ"),
    (re.compile(r"\bRun Ledger\b", re.IGNORECASE), "ラン台帳"),
    (re.compile(r"\bDecision Review\b", re.IGNORECASE), "判断レビュー"),
    (re.compile(r"\bRelease Readiness\b", re.IGNORECASE), "リリース準備"),
    (re.compile(r"\bPhase Workspace\b", re.IGNORECASE), "フェーズワークスペース"),
    (re.compile(r"\bCommand Deck\b", re.IGNORECASE), "コマンドデッキ"),
    (re.compile(r"\bResearch Recovery\b", re.IGNORECASE), "調査復旧"),
    (re.compile(r"\bLineage Explorer\b", re.IGNORECASE), "リネージ探索"),
    (re.compile(r"\bEvidence Review\b", re.IGNORECASE), "根拠レビュー"),
    (re.compile(r"\bActive Run View\b", re.IGNORECASE), "稼働中ランビュー"),
    (re.compile(r"\bProvenance Drawer\b", re.IGNORECASE), "系譜ドロワー"),
    (re.compile(r"\bRun discovery-to-build workflow\b", re.IGNORECASE), "調査から実装準備までを一気通貫で進める"),
    (re.compile(r"\bRecover degraded research lane\b", re.IGNORECASE), "劣化した調査レーンを立て直す"),
    (re.compile(r"\bApprove or rework a phase\b", re.IGNORECASE), "承認するか差し戻すかを判断する"),
    (re.compile(r"\bTrace artifact lineage\b", re.IGNORECASE), "成果物の系譜を追跡する"),
    (re.compile(r"\bReview runs and checkpoints\b", re.IGNORECASE), "実行中のランとチェックポイントを確認する"),
    (re.compile(r"\bPrimary work area for each phase\b", re.IGNORECASE), "各フェーズの主要作業面"),
    (re.compile(r"\bPrimary Shell\b", re.IGNORECASE), "主要シェル"),
    (re.compile(r"\bInspect evidence quality\b", re.IGNORECASE), "根拠の質を確認する"),
    (re.compile(r"\bReview the current research pass\b", re.IGNORECASE), "現在の調査結果をレビューする"),
    (re.compile(r"The hub for operator decisions\.?", re.IGNORECASE), "オペレーター判断の中心となる画面。"),
    (re.compile(r"\bSignals\b", re.IGNORECASE), "シグナル"),
    (re.compile(r"\bSources\b", re.IGNORECASE), "ソース"),
    (re.compile(r"\bPending approvals and rework history\b", re.IGNORECASE), "保留中の承認と差し戻し履歴を確認する"),
    (re.compile(r"\bPhase artifacts and lineage\b", re.IGNORECASE), "フェーズ成果物と系譜を確認する"),
    (re.compile(r"\bReview queue\b", re.IGNORECASE), "レビューキュー"),
    (re.compile(r"\bDecision checklist\b", re.IGNORECASE), "判断チェックリスト"),
    (re.compile(r"\bGovernance context\b", re.IGNORECASE), "統治コンテキスト"),
    (re.compile(r"\bDecision snapshot\b", re.IGNORECASE), "判断サマリー"),
    (re.compile(r"\bWorkflow lane\b", re.IGNORECASE), "進行レーン"),
    (re.compile(r"\bOperator context\b", re.IGNORECASE), "運用コンテキスト"),
    (re.compile(r"\bRun monitor\b", re.IGNORECASE), "ラン監視"),
    (re.compile(r"\bCheckpoint lane\b", re.IGNORECASE), "復旧レーン"),
    (re.compile(r"\bOperator notes\b", re.IGNORECASE), "運用メモ"),
    (re.compile(r"\bTrace path\b", re.IGNORECASE), "追跡経路"),
    (re.compile(r"\bPrimary tasks\b", re.IGNORECASE), "主要タスク"),
    (re.compile(r"\bTask flow\b", re.IGNORECASE), "作業フロー"),
    (re.compile(r"\bSupport context\b", re.IGNORECASE), "補助コンテキスト"),
    (re.compile(r"\bOpen primary workspace\b", re.IGNORECASE), "主要ワークスペースを開く"),
    (re.compile(r"\bStart research\b", re.IGNORECASE), "調査を開始する"),
    (re.compile(r"\bReview planning\b", re.IGNORECASE), "企画内容を確認する"),
    (re.compile(r"\bSelect a design\b", re.IGNORECASE), "デザイン案を選ぶ"),
    (re.compile(r"\bRun development\b", re.IGNORECASE), "開発準備へ進める"),
    (re.compile(r"\bcommand-center\b", re.IGNORECASE), "コマンドセンター"),
    (re.compile(r"\bdecision-studio\b", re.IGNORECASE), "判断スタジオ"),
    (re.compile(r"\bcontrol-center\b", re.IGNORECASE), "コントロールセンター"),
    (re.compile(r"\bsplit-review\b", re.IGNORECASE), "比較レビュー"),
    (re.compile(r"\bproduct-workspace\b", re.IGNORECASE), "プロダクトワークスペース"),
    (re.compile(r"\bqueue\b", re.IGNORECASE), "キュー"),
    (re.compile(r"\bchecklist\b", re.IGNORECASE), "チェックリスト"),
    (re.compile(r"\bsummary\b", re.IGNORECASE), "サマリー"),
    (re.compile(r"\btimeline\b", re.IGNORECASE), "タイムライン"),
    (re.compile(r"\bpanel\b", re.IGNORECASE), "パネル"),
    (re.compile(r"\bgraph\b", re.IGNORECASE), "グラフ"),
    (re.compile(r"\bstructure\b", re.IGNORECASE), "構成"),
    (re.compile(r"\bprimary\b", re.IGNORECASE), "主要"),
    (re.compile(r"\bsecondary\b", re.IGNORECASE), "補助"),
    (re.compile(r"\butility\b", re.IGNORECASE), "ユーティリティ"),
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _contains_japanese(text: str) -> bool:
    return any((("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")) for ch in text)


def _looks_like_machine_token(text: str) -> bool:
    normalized = text.strip()
    return bool(
        normalized
        and (
            normalized.startswith(("http://", "https://", "project://", "#"))
            or all(ch.islower() or ch.isdigit() or ch in "_.:-/#" for ch in normalized)
        )
    )


def _translate_design_text(value: Any, *, target_language: str) -> str:
    text = _normalize_space(value)
    if not text:
        return ""
    if target_language != "ja":
        return text
    if _looks_like_machine_token(text):
        return text
    result = text
    for pattern, replacement in _DESIGN_TEXT_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def _localize_value(value: Any, *, target_language: str, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(item_key): _localize_value(item_value, target_language=target_language, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_localize_value(item, target_language=target_language, key=key) for item in value]
    if isinstance(value, str):
        if key in _SKIP_STRING_KEYS:
            return _normalize_space(value)
        if _contains_japanese(value) and target_language == "ja":
            return _translate_design_text(value, target_language=target_language)
        return _translate_design_text(value, target_language=target_language)
    return value


def _strip_preview_html(variant: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in variant.items()
        if key not in {
            "preview_html",
            "prototype_spec",
            "prototype_app",
            "canonical",
            "localized",
            "display_language",
            "localization_status",
        }
    }


def design_localization_payload(variant: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_preview_html(_as_dict(variant))
    return {
        key: value
        for key, value in payload.items()
        if key in {
            "description",
            "quality_focus",
            "rationale",
            "provider_note",
            "prototype",
            "decision_scope",
            "narrative",
            "implementation_brief",
        }
    }


def merge_design_localization(
    variant: dict[str, Any],
    translated: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(_strip_preview_html(variant))
    for key, value in _as_dict(translated).items():
        merged[key] = value
    return merged


def backfill_design_localization(
    variant: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    canonical_source = _as_dict(variant.get("canonical")) or _strip_preview_html(variant)
    canonical = _strip_preview_html(canonical_source)
    localized_existing = _as_dict(variant.get("localized"))
    if target_language != "ja":
        localized = dict(localized_existing) if localized_existing else dict(canonical)
        return {
            **localized,
            "canonical": canonical,
            "localized": localized,
            "display_language": target_language,
            "localization_status": str(variant.get("localization_status") or "skipped"),
        }

    localized_seed = (
        merge_design_localization(canonical, localized_existing)
        if localized_existing
        else canonical
    )
    localized = _as_dict(_localize_value(localized_seed, target_language=target_language))
    if not localized:
        localized = _as_dict(_localize_value(canonical, target_language=target_language))
    return {
        **localized,
        "canonical": canonical,
        "localized": localized,
        "display_language": target_language,
        "localization_status": str(variant.get("localization_status") or "best_effort"),
    }
