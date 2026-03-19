from pylon.lifecycle.services.research_localization import backfill_research_localization


def test_backfill_research_localization_builds_context_and_operator_copy() -> None:
    research = {
        "judge_summary": "Claims that survived dissent are passed to planning together with unresolved questions.",
        "winning_theses": ["Governed visibility is the leading wedge."],
        "quality_gates": [
            {
                "id": "source-grounding",
                "title": "source grounding",
                "passed": False,
                "reason": "external url evidence is missing",
                "blockingNodeIds": ["market-researcher"],
            }
        ],
        "confidence_summary": {"average": 0.6, "floor": 0.52, "accepted": 1},
        "user_research": {
            "segment": "Operations leaders",
            "signals": ["Teams want artifact lineage."],
            "pain_points": ["Retrying research does not explain what changed."],
        },
        "autonomous_remediation": {
            "conditionalHandoffAllowed": True,
            "planningGuardrails": [
                "Carry unresolved questions as explicit assumptions.",
            ],
            "targetConfidenceFloor": 0.6,
        },
        "remediation_plan": {
            "objective": "Address degraded nodes, strengthen source grounding, and re-evaluate blocked claims.",
            "retryNodeIds": ["market-researcher"],
        },
    }

    localized = backfill_research_localization(research)

    assert localized["display_language"] == "ja"
    assert localized["localization_status"] == "best_effort"
    assert localized["canonical"]["research_context"]["decision_stage"] == "conditional_handoff"
    assert localized["canonical"]["operator_copy"]["council_cards"][0]["agent"] == "Thesis Council"
    assert localized["research_context"]["decision_stage_label"] == "前提つきで企画に進める状態"
    assert localized["operator_copy"]["council_cards"][0]["agent"] == "仮説評議"
    assert localized["operator_copy"]["handoff_brief"]["headline"]


def test_backfill_research_localization_resolves_winning_thesis_ids_to_claim_statements() -> None:
    research = {
        "winning_theses": ["claim-market-demand"],
        "claims": [
            {
                "id": "claim-market-demand",
                "statement": "Governed visibility is the leading wedge.",
                "status": "accepted",
            }
        ],
        "confidence_summary": {"average": 0.63, "floor": 0.58, "accepted": 1},
        "user_research": {"segment": "Operations leaders"},
    }

    localized = backfill_research_localization(research)

    assert localized["canonical"]["winning_theses"] == ["claim-market-demand"]
    assert localized["canonical"]["research_context"]["thesis_headline"] == "Governed visibility is the leading wedge."
    assert localized["canonical"]["research_context"]["thesis_snapshot"] == ["Governed visibility is the leading wedge."]
    assert localized["research_context"]["thesis_headline"] == "Governed visibility is the leading wedge."
