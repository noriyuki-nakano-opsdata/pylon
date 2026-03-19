from pylon.lifecycle.services.research_quality import evaluate_research_quality


def _healthy_research() -> dict[str, object]:
    return {
        "winning_theses": ["Operations teams need clearer decision traceability."],
        "source_links": ["https://example.com/product"],
        "evidence": [
            {
                "id": "ev-1",
                "source_ref": "https://example.com/product",
                "source_type": "url",
                "snippet": "Grounded product evidence.",
                "recency": "current",
                "relevance": "high",
            }
        ],
        "dissent": [
            {
                "id": "d1",
                "claim_id": "c1",
                "challenger": "judge",
                "argument": "Adoption may stall without governance controls.",
                "severity": "medium",
                "resolved": True,
            }
        ],
        "critical_dissent_count": 0,
        "confidence_summary": {
            "average": 0.74,
            "floor": 0.71,
            "accepted": 1,
        },
        "competitors": [],
    }


def test_research_quality_allows_healthy_research_without_identity_profile() -> None:
    gates, readiness, remediation = evaluate_research_quality(
        _healthy_research(),
        node_results=[],
        remaining_iterations=0,
        proposal_node_ids=["research-judge"],
        review_node_ids=["cross-examiner"],
        identity_profile=None,
    )

    assert readiness == "ready"
    assert remediation is None
    assert {gate["id"] for gate in gates}.isdisjoint({"target-identity-locked", "homonym-risk-cleared"})


def test_research_quality_does_not_fail_on_partial_identity_hints() -> None:
    gates, readiness, remediation = evaluate_research_quality(
        _healthy_research(),
        node_results=[],
        remaining_iterations=0,
        proposal_node_ids=["research-judge"],
        review_node_ids=["cross-examiner"],
        identity_profile={
            "companyName": "",
            "productName": "Orbit",
            "officialDomains": [],
            "aliases": [],
            "excludedEntityNames": [],
        },
    )

    assert readiness == "ready"
    assert remediation is None
    assert {gate["id"] for gate in gates}.isdisjoint({"target-identity-locked", "homonym-risk-cleared"})
