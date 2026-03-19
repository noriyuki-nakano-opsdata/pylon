"""Localization helpers for EARS requirements artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_REQUIREMENTS_FIXED_JA: dict[str, str] = {
    "EARS requirement completeness satisfied": "EARS 要件の網羅性が満たされています。",
    "traceability coverage present": "要件とクレームの追跡可能性が確認されています。",
    "confidence floor met": "信頼度の下限値を満たしています。",
    "requirements not yet generated": "要件がまだ生成されていません。",
    "no requirements produced": "要件が生成されませんでした。",
    "high confidence": "高信頼度",
    "medium confidence": "中信頼度",
    "low confidence": "低信頼度",
    "ubiquitous": "普遍的要件",
    "event-driven": "イベント駆動要件",
    "unwanted": "例外処理要件",
    "state-driven": "状態駆動要件",
    "optional": "オプション要件",
    "complex": "複合要件",
}

_SECTION_TITLES_JA: dict[str, str] = {
    "requirements": "要件一覧",
    "user_stories": "ユーザーストーリー",
    "acceptance_criteria": "受け入れ基準",
    "confidence_distribution": "信頼度分布",
    "traceability_index": "追跡可能性インデックス",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def translate_requirements_text(key: str, *, target_language: str = "ja") -> str:
    """Translate a fixed requirements text key."""
    text = str(key or "").strip()
    if not text or target_language != "ja":
        return text
    translated = _REQUIREMENTS_FIXED_JA.get(text)
    return translated if translated else text


def _confidence_label(confidence: float, *, target_language: str) -> str:
    if confidence >= 0.8:
        key = "high confidence"
    elif confidence >= 0.5:
        key = "medium confidence"
    else:
        key = "low confidence"
    if target_language == "ja":
        return _REQUIREMENTS_FIXED_JA.get(key, key)
    return key


def localize_requirements_bundle(
    bundle: dict[str, Any],
    *,
    target_language: str = "ja",
) -> dict[str, Any]:
    """Add localized labels to a requirements bundle for UI display.

    Adds pattern_label, confidence_label, and section_titles for UI rendering.
    """
    localized = dict(bundle)
    localized_reqs = []
    for req in _as_list(bundle.get("requirements")):
        req_data = dict(_as_dict(req))
        pattern = str(req_data.get("pattern", "")).strip()
        confidence = float(req_data.get("confidence", 0.0) or 0.0)
        if target_language == "ja":
            req_data["pattern_label"] = _REQUIREMENTS_FIXED_JA.get(pattern, pattern)
        else:
            req_data["pattern_label"] = pattern
        req_data["confidence_label"] = _confidence_label(confidence, target_language=target_language)
        localized_reqs.append(req_data)
    localized["requirements"] = localized_reqs

    if target_language == "ja":
        localized["section_titles"] = dict(_SECTION_TITLES_JA)
    else:
        localized["section_titles"] = {
            "requirements": "Requirements",
            "user_stories": "User Stories",
            "acceptance_criteria": "Acceptance Criteria",
            "confidence_distribution": "Confidence Distribution",
            "traceability_index": "Traceability Index",
        }
    return localized


def requirements_localization_payload(
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Extract translatable content for external translation service."""
    payload: dict[str, Any] = {}
    statements = []
    for req in _as_list(bundle.get("requirements")):
        req_data = _as_dict(req)
        statement = str(req_data.get("statement", "")).strip()
        if statement:
            statements.append({
                "id": str(req_data.get("id", "")),
                "statement": statement,
                "pattern": str(req_data.get("pattern", "")),
            })
    if statements:
        payload["requirements"] = statements

    stories = []
    for story in _as_list(bundle.get("user_stories")):
        story_data = _as_dict(story)
        text = str(story_data.get("text", "")).strip()
        if text:
            stories.append({"id": str(story_data.get("id", "")), "text": text})
    if stories:
        payload["user_stories"] = stories

    criteria = []
    for ac in _as_list(bundle.get("acceptance_criteria")):
        ac_data = _as_dict(ac)
        text = str(ac_data.get("text", "")).strip()
        if text:
            criteria.append({"id": str(ac_data.get("id", "")), "text": text})
    if criteria:
        payload["acceptance_criteria"] = criteria

    return payload
