"""Localization helpers for reverse engineering artifacts."""
from __future__ import annotations

from typing import Any

_REVERSE_ENGINEERING_FIXED_JA: dict[str, str] = {
    "reverse-engineered requirement": "リバースエンジニアリング要件",
    "extracted from code": "コードから抽出",
    "coverage score": "カバレッジスコア",
    "api endpoint": "API エンドポイント",
    "database table": "データベーステーブル",
    "interface definition": "インターフェース定義",
    "test specification": "テスト仕様",
    "task structure": "タスク構造",
}


def translate_reverse_engineering_text(
    value: Any,
    *,
    target_language: str,
) -> Any:
    """Translate a fixed reverse engineering text to the target language.

    Only translates known fixed strings when target_language is 'ja'.
    Returns the original value unchanged for unknown strings or non-ja targets.
    """
    text = str(value or "").strip()
    if not text or target_language != "ja":
        return value
    translated = _REVERSE_ENGINEERING_FIXED_JA.get(text.lower())
    if translated:
        return translated
    return value


def localize_reverse_engineering_result(
    result: dict[str, Any],
    *,
    target_language: str,
) -> dict[str, Any]:
    """Localize a reverse engineering result payload for display.

    Translates known fixed labels and enriches the result with
    a display_language field. Leaves non-translatable content as-is.
    """
    localized = dict(result)
    localized["display_language"] = target_language

    if target_language != "ja":
        return localized

    # Translate quality gate titles if present
    quality_gates = localized.get("quality_gates")
    if isinstance(quality_gates, list):
        localized["quality_gates"] = [
            {
                **gate,
                "title": translate_reverse_engineering_text(
                    gate.get("title"),
                    target_language=target_language,
                ),
            }
            if isinstance(gate, dict)
            else gate
            for gate in quality_gates
        ]

    return localized
