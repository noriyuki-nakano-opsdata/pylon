"""Localization helpers for DCS analysis artifacts."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_DCS_FIXED_JA: dict[str, str] = {
    "critical": "致命的",
    "high": "高",
    "medium": "中",
    "low": "低",
    "edge case analysis": "エッジケース分析",
    "impact analysis": "影響範囲分析",
    "sequence diagram": "シーケンス図",
    "state transition": "状態遷移",
    "rubber duck PRD": "ラバーダック PRD",
    "core": "コア",
    "api": "API",
    "service": "サービス",
    "data": "データ",
    "ui": "UI",
    "test": "テスト",
    "config": "設定",
    "success": "正常系",
    "error": "異常系",
    "exception": "例外系",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def translate_dcs_text(key: str, *, target_language: str = "ja") -> str:
    """Translate a DCS fixed-vocabulary key to the target language.

    Returns the original key unchanged for unsupported languages or unknown keys.
    """
    if target_language != "ja":
        return key
    return _DCS_FIXED_JA.get(key.lower().strip(), key)


def localize_dcs_analysis(
    analysis: dict[str, Any],
    *,
    target_language: str = "ja",
) -> dict[str, Any]:
    """Localize DCS analysis artifacts to the target language.

    Translates severity labels, layer names, flow types, and section titles
    found in edge case analysis, impact analysis, sequence diagrams, and
    state transition results.
    """
    if target_language != "ja":
        return dict(analysis)

    localized = dict(analysis)

    # Localize edge case analysis
    ec_analysis = _as_dict(localized.get("edge_case_analysis"))
    if ec_analysis:
        localized_cases = []
        for case in _as_list(ec_analysis.get("edge_cases")):
            case_data = dict(_as_dict(case))
            severity = str(case_data.get("severity", "")).strip().lower()
            if severity in _DCS_FIXED_JA:
                case_data["severity_label"] = _DCS_FIXED_JA[severity]
            localized_cases.append(case_data)
        localized_matrix: dict[str, Any] = {}
        for sev, count in _as_dict(ec_analysis.get("risk_matrix")).items():
            label = _DCS_FIXED_JA.get(sev.lower().strip(), sev)
            localized_matrix[label] = count
        localized["edge_case_analysis"] = {
            **ec_analysis,
            "edge_cases": localized_cases,
            "risk_matrix_localized": localized_matrix,
        }

    # Localize impact analysis
    impact = _as_dict(localized.get("impact_analysis"))
    if impact:
        localized_layers = []
        for layer in _as_list(impact.get("layers")):
            layer_data = dict(_as_dict(layer))
            layer_name = str(layer_data.get("layer", "")).strip().lower()
            if layer_name in _DCS_FIXED_JA:
                layer_data["layer_label"] = _DCS_FIXED_JA[layer_name]
            localized_layers.append(layer_data)
        localized["impact_analysis"] = {
            **impact,
            "layers": localized_layers,
        }

    # Localize sequence diagrams
    seq = _as_dict(localized.get("sequence_diagrams"))
    if seq:
        localized_diagrams = []
        for diagram in _as_list(seq.get("diagrams")):
            d = dict(_as_dict(diagram))
            flow_type = str(d.get("flow_type", "")).strip().lower()
            if flow_type in _DCS_FIXED_JA:
                d["flow_type_label"] = _DCS_FIXED_JA[flow_type]
            localized_diagrams.append(d)
        localized["sequence_diagrams"] = {
            **seq,
            "diagrams": localized_diagrams,
        }

    return localized
