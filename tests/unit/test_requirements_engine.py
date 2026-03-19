from pylon.lifecycle.services.requirements_engine import (
    classify_ears_pattern,
    confidence_to_level,
    build_requirements_bundle,
    evaluate_requirements_quality,
    merge_requirements_with_reverse_engineering,
)


def test_classify_ears_pattern_ubiquitous():
    """Plain SHALL statement -> ubiquitous."""
    assert classify_ears_pattern("The system SHALL display a dashboard.") == "ubiquitous"


def test_classify_ears_pattern_event_driven():
    """WHEN ... SHALL -> event-driven."""
    assert classify_ears_pattern("WHEN the user clicks submit, the system SHALL save the form.") == "event-driven"


def test_classify_ears_pattern_unwanted():
    """IF ... THEN ... SHALL -> unwanted."""
    assert classify_ears_pattern("IF the network is unavailable, THEN the system SHALL queue requests.") == "unwanted"


def test_classify_ears_pattern_state_driven():
    """WHILE ... SHALL -> state-driven."""
    assert classify_ears_pattern("WHILE the system is in maintenance mode, the system SHALL reject new requests.") == "state-driven"


def test_classify_ears_pattern_optional():
    """WHERE ... SHALL -> optional."""
    assert classify_ears_pattern("WHERE the premium tier is active, the system SHALL enable advanced analytics.") == "optional"


def test_classify_ears_pattern_complex():
    """Multiple keywords -> complex."""
    assert classify_ears_pattern("WHEN the user logs in, IF 2FA is enabled, THEN the system SHALL prompt for a code.") == "complex"


def test_classify_ears_pattern_empty_returns_ubiquitous():
    assert classify_ears_pattern("") == "ubiquitous"


def test_confidence_to_level_high():
    assert confidence_to_level(0.85) == "high"
    assert confidence_to_level(0.8) == "high"


def test_confidence_to_level_medium():
    assert confidence_to_level(0.65) == "medium"
    assert confidence_to_level(0.5) == "medium"


def test_confidence_to_level_low():
    assert confidence_to_level(0.3) == "low"
    assert confidence_to_level(0.0) == "low"


def test_confidence_to_level_boundary():
    assert confidence_to_level(0.79) == "medium"
    assert confidence_to_level(0.49) == "low"


def test_build_requirements_bundle_from_claims():
    claims = [
        {"id": "claim-1", "statement": "Users need dashboard visibility.", "status": "accepted", "confidence": 0.85},
        {"id": "claim-2", "statement": "API latency must stay under 200ms.", "status": "accepted", "confidence": 0.7},
        {"id": "claim-3", "statement": "Rejected claim.", "status": "rejected", "confidence": 0.4},
    ]
    bundle = build_requirements_bundle(claims, None, "Build a monitoring tool")
    reqs = bundle["requirements"]
    assert len(reqs) == 2  # Only accepted claims
    assert reqs[0]["id"] == "REQ-0001"
    assert reqs[1]["id"] == "REQ-0002"
    assert all(r["source_claim_ids"] for r in reqs)


def test_build_requirements_bundle_empty_claims():
    bundle = build_requirements_bundle([], None, "Empty spec")
    assert bundle["requirements"] == []
    assert bundle["completeness_score"] == 0.0


def test_build_requirements_bundle_confidence_distribution():
    claims = [
        {"id": "c1", "statement": "High conf.", "status": "accepted", "confidence": 0.9},
        {"id": "c2", "statement": "Med conf.", "status": "accepted", "confidence": 0.6},
        {"id": "c3", "statement": "Low conf.", "status": "accepted", "confidence": 0.3},
    ]
    bundle = build_requirements_bundle(claims, None, "spec")
    dist = bundle["confidence_distribution"]
    assert dist["high"] == 1
    assert dist["medium"] == 1
    assert dist["low"] == 1


def test_build_requirements_bundle_traceability_index():
    claims = [
        {"id": "claim-a", "statement": "Feature A needed.", "status": "accepted", "confidence": 0.8},
    ]
    bundle = build_requirements_bundle(claims, None, "spec")
    index = bundle["traceability_index"]
    assert "claim-a" in index
    assert "REQ-0001" in index["claim-a"]


def test_evaluate_requirements_quality_valid_bundle():
    bundle = {
        "requirements": [
            {"id": "REQ-0001", "confidence": 0.85, "source_claim_ids": ["c1"]},
            {"id": "REQ-0002", "confidence": 0.9, "source_claim_ids": ["c2"]},
        ],
        "acceptance_criteria": [
            {"requirement_id": "REQ-0001", "criterion": "Given X, When Y, Then Z"},
            {"requirement_id": "REQ-0002", "criterion": "Given A, When B, Then C"},
        ],
        "confidence_distribution": {"high": 2, "medium": 0, "low": 0},
        "completeness_score": 0.9,
    }
    issues, score = evaluate_requirements_quality(bundle)
    assert issues == []
    assert score >= 0.8


def test_evaluate_requirements_quality_missing_traceability():
    bundle = {
        "requirements": [
            {"id": "REQ-0001", "confidence": 0.85, "source_claim_ids": [], "acceptance_criteria": ["test"]},
        ],
        "confidence_distribution": {"high": 1, "medium": 0, "low": 0},
    }
    issues, score = evaluate_requirements_quality(bundle)
    assert any("traceability" in i["message"].lower() or "trace" in i["message"].lower() for i in issues)


def test_evaluate_requirements_quality_invalid_id():
    bundle = {
        "requirements": [
            {"id": "BAD-ID", "confidence": 0.85, "source_claim_ids": ["c1"], "acceptance_criteria": ["test"]},
        ],
        "confidence_distribution": {"high": 1, "medium": 0, "low": 0},
    }
    issues, _ = evaluate_requirements_quality(bundle)
    assert any("id" in i["message"].lower() for i in issues)


def test_evaluate_requirements_quality_low_confidence_ratio():
    bundle = {
        "requirements": [
            {"id": "REQ-0001", "confidence": 0.3, "source_claim_ids": ["c1"], "acceptance_criteria": ["t"]},
            {"id": "REQ-0002", "confidence": 0.2, "source_claim_ids": ["c2"], "acceptance_criteria": ["t"]},
        ],
        "confidence_distribution": {"high": 0, "medium": 0, "low": 2},
    }
    issues, score = evaluate_requirements_quality(bundle)
    assert score < 0.5


def test_merge_requirements_with_reverse_engineering():
    forward = {
        "requirements": [
            {"id": "REQ-0001", "statement": "The system shall display a dashboard.", "confidence": 0.8, "source_claim_ids": ["c1"]},
        ],
        "completeness_score": 0.7,
    }
    reverse = [
        {"statement": "The system shall display a dashboard.", "confidence": 0.6},  # duplicate
        {"statement": "The system shall export CSV reports.", "confidence": 0.5},  # new
    ]
    merged = merge_requirements_with_reverse_engineering(forward, reverse)
    assert len(merged["requirements"]) == 2  # deduped
    # The duplicate should have boosted confidence
    dashboard_req = next(r for r in merged["requirements"] if "dashboard" in r["statement"].lower())
    assert dashboard_req["confidence"] >= 0.8


def test_merge_requirements_empty_reverse():
    forward = {"requirements": [{"id": "REQ-0001", "statement": "Test.", "confidence": 0.8}], "completeness_score": 0.7}
    merged = merge_requirements_with_reverse_engineering(forward, [])
    assert len(merged["requirements"]) == 1
