from pylon.lifecycle.services.planning_localization import backfill_planning_localization


def test_backfill_planning_localization_builds_localized_view_for_existing_analysis() -> None:
    analysis = {
        "personas": [
            {
                "name": "Naoki",
                "role": "エンタープライズ向け導入責任者 Product Owner",
                "age_range": "28-42",
                "goals": ["Complete the primary workflow"],
                "frustrations": ["Impatient Evaluator"],
                "tech_proficiency": "high",
                "context": "企画と実装の橋渡しを担う。",
            }
        ],
        "user_stories": [],
        "kano_features": [
            {
                "feature": "guided onboarding",
                "category": "one-dimensional",
                "user_delight": 0.7,
                "implementation_cost": "medium",
                "rationale": "subtle entry fades",
            }
        ],
        "recommendations": [
            "{'id': 'rec-1', 'priority': 'critical', 'target': 'milestone-1 and milestone-2', 'action': 'Add explicit failure conditions to both milestones before design begins.', 'rationale': 'Milestones without stop conditions create false progress.'}"
        ],
        "judge_summary": (
            "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions', "
            "'description': 'Neither M1 nor M2 has a defined failure signal or halt threshold.', "
            "'owner': 'product lead', 'must_resolve_before': 'design kickoff'}"
        ),
        "negative_personas": [
            {
                "id": "negative-1",
                "name": "Impatient Evaluator",
                "scenario": "Judges the product after one incomplete run.",
                "risk": "Leaves before the core loop demonstrates value.",
                "mitigation": "Make the first successful workflow obvious and measurable.",
            }
        ],
        "design_tokens": {
            "style": {
                "name": "Balanced Product",
                "keywords": ["clear", "adaptive", "modern"],
                "best_for": "general-purpose digital products with mixed audiences",
                "performance": "progressive disclosure and responsive content grouping",
                "accessibility": "clear semantic hierarchy and keyboard-safe interactions",
            },
            "colors": {
                "primary": "#1d4ed8",
                "secondary": "#14b8a6",
                "cta": "#f97316",
                "background": "#f8fafc",
                "text": "#0f172a",
                "notes": "Keep the palette restrained so feature priority and content hierarchy carry the UI.",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["balanced", "practical", "modern"],
            },
            "effects": ["subtle entry fades", "hover elevation", "clear focus rings"],
            "anti_patterns": ["generic dashboard filler", "weak empty states", "low-information hero sections"],
            "rationale": "The product should stay adaptable while preserving clear task hierarchy and predictable interactions.",
        },
    }

    localized = backfill_planning_localization(analysis)

    assert localized["display_language"] == "ja"
    assert localized["localization_status"] == "best_effort"
    assert localized["localized"]["display_language"] == "ja"
    assert localized["canonical"]["judge_summary"].startswith("{'id': 'risk-1'")
    assert "プロダクトオーナー" in localized["personas"][0]["role"]
    assert "デザイン着手前" in localized["recommendations"][0]
    assert "マイルストーンに中止条件がありません" in localized["judge_summary"]
    assert localized["negative_personas"][0]["name"] == "すぐ離脱する評価者"
    assert localized["design_tokens"]["style"]["name"] == "バランス型プロダクト"
    assert localized["design_tokens"]["effects"][0] == "穏やかなフェードイン"
    assert localized["canonical"]["operator_copy"]["council_cards"][0]["agent"] == "Product Council"
    assert localized["operator_copy"]["council_cards"][0]["agent"] == "プロダクト評議"
    assert localized["operator_copy"]["handoff_brief"]["headline"]
    assert any("UI の方向性" in item for item in localized["operator_copy"]["handoff_brief"]["bullets"])


def test_backfill_planning_localization_rebuilds_operator_copy_from_canonical_when_localized_is_stale() -> None:
    analysis = {
        "recommendations": [
            "{'id': 'rec-1', 'priority': 'critical', 'action': 'Add explicit failure conditions to both milestones before design begins.', 'rationale': 'Milestones without stop conditions create false progress.'}"
        ],
        "judge_summary": (
            "{'id': 'risk-1', 'severity': 'critical', 'title': 'Milestones lack stop conditions', "
            "'description': 'Neither M1 nor M2 has a defined failure signal or halt threshold.', "
            "'owner': 'product lead', 'must_resolve_before': 'design kickoff'}"
        ),
        "localized": {
            "recommendations": [
                "{'id': 'rec-legacy', 'priority': 'critical', 'action': 'Legacy English action should not leak.', 'rationale': 'Legacy rationale.'}"
            ],
            "judge_summary": "{\"title\": \"マイルストーンに中止条件がありません\", \"description\": \"M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。\"}",
            "display_language": "ja",
            "localization_status": "strict",
        },
    }

    localized = backfill_planning_localization(analysis)

    assert localized["operator_copy"]["council_cards"][0]["title"] != "Legacy English action should not leak."
    assert "デザイン着手前" in localized["operator_copy"]["handoff_brief"]["headline"]


def test_backfill_planning_localization_translates_mixed_canonical_copy_for_display() -> None:
    analysis = {
        "personas": [
            {
                "name": "Aiko",
                "role": "Platform Lead",
                "age_range": "30-45",
            }
        ],
        "use_cases": [
            {
                "id": "uc-ops-001",
                "title": "Run discovery-to-build workflow",
                "actor": "Lifecycle Operator",
                "priority": "must",
            }
        ],
        "kano_features": [
            {
                "feature": "release readiness",
                "category": "attractive",
                "user_delight": 0.9,
                "implementation_cost": "medium",
            }
        ],
        "design_tokens": {
            "style": {
                "name": "Operational Clarity",
            }
        },
        "kill_criteria": [
            {
                "id": "kill-1",
                "condition": "If Evidence-to-build loop cannot show observable completion evidence, stop scope expansion and re-open planning.",
                "rationale": "Milestones must be falsifiable instead of narrative.",
            }
        ],
        "judge_summary": "Scope pressure around operator console. phase ごとの artifact lineage を first-class にし、承認判断の根拠を失わないようにする",
        "red_team_findings": [
            {
                "id": "scope-5",
                "severity": "high",
                "title": "Scope pressure around operator console",
                "impact": "If this remains in the first cut, the team may lose falsifiability and review speed.",
                "recommendation": "Keep this out of the first release unless a research claim explicitly requires it.",
                "related_feature": "operator console",
            }
        ],
        "localized": {
            "judge_summary": "Scope pressure around operator console. phase ごとの artifact lineage を first-class にし、承認判断の根拠を失わないようにする",
            "red_team_findings": [
                {
                    "title": "Scope pressure around operator console",
                    "impact": "If this remains in the first cut, the team may lose falsifiability and review speed.",
                    "recommendation": "Keep this out of the first release unless a research claim explicitly requires it.",
                    "related_feature": "operator console",
                }
            ],
            "operator_copy": {
                "council_cards": [
                    {
                        "id": "legacy-design",
                        "agent": "Design Council",
                        "title": "release readiness",
                        "summary": "Operational Clarity anchors the next comparison.",
                        "action_label": "Open design tokens",
                    }
                ]
            },
            "display_language": "ja",
            "localization_status": "best_effort",
        },
    }

    localized = backfill_planning_localization(analysis)

    assert "運用コンソール" in localized["judge_summary"]
    assert localized["red_team_findings"][0]["title"] == "運用コンソールまわりのスコープ圧力が高い状態です"
    assert localized["red_team_findings"][0]["related_feature"] == "運用コンソール"
    assert localized["operator_copy"]["council_cards"][0]["title"] == "リリース準備"
    assert "運用明瞭性" in localized["operator_copy"]["council_cards"][0]["summary"]
    assert any("調査からビルドまでを実行する" in item for item in localized["operator_copy"]["handoff_brief"]["bullets"])
