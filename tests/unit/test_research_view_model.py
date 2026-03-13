from pylon.lifecycle.services.research_view_model import build_research_view_model


def test_build_research_view_model_normalizes_core_fields():
    research = {
        "market_size": "Large and growing",
        "trends": ["Workflow governance adoption is increasing."],
        "opportunities": ["Evidence-backed approvals reduce operator risk."],
        "threats": ["Legacy suites bundle adjacent features."],
        "tech_feasibility": {"score": 0.74, "notes": "Integration is feasible."},
        "claims": [
            {
                "id": "claim-1",
                "statement": "Manufacturing teams need auditability.",
                "owner": "market-researcher",
                "category": "market",
                "evidence_ids": ["ev-1"],
                "counterevidence_ids": [],
                "confidence": 0.71,
                "status": "accepted",
            }
        ],
        "quality_gates": [
            {
                "id": "confidence-floor",
                "title": "Confidence floor",
                "passed": False,
                "reason": "confidence floor=0.42, winning_theses=0",
                "blockingNodeIds": ["research-judge"],
            }
        ],
        "autonomous_remediation": {
            "status": "retrying",
            "attemptCount": 1,
            "maxAttempts": 2,
            "remainingAttempts": 1,
            "objective": "Strengthen source grounding.",
            "retryNodeIds": ["competitor-analyst"],
            "blockingGateIds": ["confidence-floor"],
        },
    }

    view_model = build_research_view_model(research)

    assert view_model["market_size"] == "Large and growing"
    assert view_model["tech_feasibility"]["score"] == 0.74
    assert view_model["claims"][0]["id"] == "claim-1"
    assert view_model["quality_gates"][0]["blockingNodeIds"] == ["research-judge"]
    assert view_model["autonomous_remediation"]["status"] == "retrying"


def test_build_research_view_model_supplies_defaults_when_fields_are_missing():
    view_model = build_research_view_model({})

    assert view_model["market_size"] == "調査結果を取得できませんでした"
    assert view_model["tech_feasibility"]["notes"] == "データが不完全なため、調査結果を再取得してください。"
    assert view_model["competitors"] == []
    assert view_model["claims"] == []
