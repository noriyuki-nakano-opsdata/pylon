from pylon.lifecycle.services.decision_context import build_lifecycle_decision_context


def _project() -> dict[str, object]:
    return {
        "spec": "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage.",
        "research": {
            "canonical": {
                "winning_theses": ["Governed visibility is the leading wedge."],
                "claims": [
                    {
                        "id": "claim-1",
                        "statement": "Governed visibility is the leading wedge.",
                        "status": "accepted",
                    }
                ],
                "research_context": {
                    "decision_stage": "conditional_handoff",
                    "segment": "Platform teams",
                    "thesis_headline": "Governed visibility is the leading wedge.",
                    "thesis_snapshot": ["Governed visibility is the leading wedge."],
                },
                "judge_summary": "Research can move forward with explicit assumptions.",
            },
            "localized": {
                "research_context": {
                    "decision_stage": "conditional_handoff",
                    "segment": "プラットフォームチーム",
                    "thesis_headline": "統制された可視化が主な勝ち筋です。",
                    "thesis_snapshot": ["統制された可視化が主な勝ち筋です。"],
                }
            },
        },
        "analysis": {
            "canonical": {
                "judge_summary": "Carry traceable decisions into design and build.",
                "planning_context": {
                    "product_kind": "operations",
                    "segment": "Platform teams",
                    "north_star": "Operator trust",
                    "core_loop": "Carry evidence into governed delivery.",
                },
                "personas": [{"name": "Aiko", "role": "Platform Lead"}],
                "use_cases": [
                    {"id": "uc-1", "title": "Trace artifact lineage", "priority": "must"},
                    {"id": "uc-2", "title": "Approve governed release", "priority": "should"},
                ],
                "traceability": [
                    {
                        "claim_id": "claim-1",
                        "claim": "Governed visibility is the leading wedge.",
                        "use_case_id": "uc-1",
                        "use_case": "Trace artifact lineage",
                        "feature": "artifact lineage",
                        "milestone_id": "ms-1",
                        "milestone": "Evidence loop",
                    }
                ],
                "red_team_findings": [
                    {"id": "risk-1", "title": "Milestones lack stop conditions", "severity": "critical", "recommendation": "Define explicit failure signals."}
                ],
                "assumptions": [
                    {"id": "assumption-1", "assumption": "Operators will trade speed for traceability."}
                ],
                "kill_criteria": [
                    {"id": "stop-1", "milestone_id": "ms-1", "condition": "Stop if lineage cannot be reconstructed."}
                ],
                "coverage_summary": {
                    "required_use_cases_without_traceability": ["uc-2"],
                },
            },
            "localized": {
                "planning_context": {
                    "product_kind": "operations",
                    "segment": "プラットフォームチーム",
                    "north_star": "オペレーター信頼",
                    "core_loop": "根拠を保ったまま delivery に渡す",
                },
                "use_cases": [
                    {"id": "uc-1", "title": "artifact lineage を追跡する", "priority": "must"},
                    {"id": "uc-2", "title": "統制された release を承認する", "priority": "should"},
                ],
            },
        },
        "features": [
            {"feature": "artifact lineage", "selected": True, "priority": "must", "category": "must-be"},
            {"feature": "approval gate", "selected": True, "priority": "should", "category": "one-dimensional"},
        ],
        "milestones": [
            {"id": "ms-1", "name": "Evidence loop", "phase": "alpha", "depends_on_use_cases": ["uc-1", "uc-2"]},
        ],
        "designVariants": [
            {
                "id": "design-1",
                "pattern_name": "Control Center",
                "description": "Dense operator workspace",
                "decision_context_fingerprint": "legacyfingerprint",
                "prototype": {"screens": [{"id": "screen-1"}]},
            }
        ],
        "selectedDesignId": "design-1",
    }


def test_build_lifecycle_decision_context_links_scope_and_detects_stale_design() -> None:
    context = build_lifecycle_decision_context(_project(), target_language="en", compact=True)

    assert context["fingerprint"]
    assert context["project_frame"]["lead_thesis"] == "Governed visibility is the leading wedge."
    assert context["decision_graph"]["nodes"]
    assert context["decision_graph"]["edges"]
    assert any(issue["id"] == "stale-selected-design" for issue in context["consistency_snapshot"]["issues"])
    assert context["consistency_snapshot"]["status"] == "attention"


def test_build_lifecycle_decision_context_uses_localized_copy_for_japanese() -> None:
    context = build_lifecycle_decision_context(_project(), target_language="ja", compact=True)

    assert context["project_frame"]["segment"] == "プラットフォームチーム"
    assert context["project_frame"]["lead_thesis"] == "統制された可視化が主な勝ち筋です。"


def test_build_lifecycle_decision_context_resolves_machine_thesis_ids() -> None:
    project = _project()
    project["research"] = {
        "canonical": {
            "winning_theses": ["claim-1"],
            "claims": [
                {
                    "id": "claim-1",
                    "statement": "Governed visibility is the leading wedge.",
                    "status": "accepted",
                }
            ],
            "research_context": {
                "decision_stage": "conditional_handoff",
                "segment": "Platform teams",
                "thesis_headline": "claim-1",
                "thesis_snapshot": ["claim-1"],
            },
        }
    }

    context = build_lifecycle_decision_context(project, target_language="en", compact=True)

    assert context["project_frame"]["lead_thesis"] == "Governed visibility is the leading wedge."
    assert context["project_frame"]["thesis_snapshot"] == ["Governed visibility is the leading wedge."]


def test_build_lifecycle_decision_context_uses_english_fallback_for_known_claim_ids() -> None:
    project = _project()
    project["research"] = {
        "canonical": {
            "winning_theses": ["claim-market-demand"],
            "claims": [
                {
                    "id": "claim-market-demand",
                    "statement": "公開ソースでは導入拡大と運用上の制約が併存しており、需要自体はある一方で差別化には具体的な運用品質の説明が必要です。",
                    "status": "accepted",
                }
            ],
            "research_context": {
                "decision_stage": "conditional_handoff",
                "segment": "Platform teams",
                "thesis_headline": "公開ソースでは導入拡大と運用上の制約が併存しており、需要自体はある一方で差別化には具体的な運用品質の説明が必要です。",
                "thesis_snapshot": [
                    "公開ソースでは導入拡大と運用上の制約が併存しており、需要自体はある一方で差別化には具体的な運用品質の説明が必要です。"
                ],
            },
        }
    }

    context = build_lifecycle_decision_context(project, target_language="en", compact=True)

    assert context["project_frame"]["lead_thesis"] == "Demand exists, but differentiation depends on proving operational quality."
    assert context["project_frame"]["thesis_snapshot"] == [
        "Demand exists, but differentiation depends on proving operational quality."
    ]


def test_build_lifecycle_decision_context_fingerprint_stays_stable_when_selected_design_matches_upstream() -> None:
    project = _project()
    project["designVariants"] = []
    project["selectedDesignId"] = None

    baseline = build_lifecycle_decision_context(project, target_language="en", compact=True)
    project["designVariants"] = [
        {
            "id": "design-1",
            "pattern_name": "Control Center",
            "description": "Dense operator workspace",
            "decision_context_fingerprint": baseline["fingerprint"],
            "prototype": {"screens": [{"id": "screen-1"}]},
        }
    ]
    project["selectedDesignId"] = "design-1"

    with_selected_design = build_lifecycle_decision_context(project, target_language="en", compact=True)

    assert with_selected_design["fingerprint"] == baseline["fingerprint"]
    assert not any(
        issue["id"] == "stale-selected-design"
        for issue in with_selected_design["consistency_snapshot"]["issues"]
    )


def test_build_lifecycle_decision_context_fingerprint_is_independent_of_compact_mode() -> None:
    project = _project()
    baseline = build_lifecycle_decision_context(project, target_language="en", compact=True)
    expanded = build_lifecycle_decision_context(project, target_language="en", compact=False)

    assert baseline["fingerprint"] == expanded["fingerprint"]
