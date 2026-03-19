"""Tests for DCS (Development Context Support) analysis services."""
from __future__ import annotations

import pytest

from pylon.lifecycle.services.dcs_analysis import (
    analyze_edge_cases,
    analyze_impact,
    analyze_state_transitions,
    evaluate_dcs_quality,
    generate_rubber_duck_prd,
    generate_sequence_diagrams,
)


# ---------------------------------------------------------------------------
# Edge-case analysis
# ---------------------------------------------------------------------------


def test_analyze_edge_cases_generates_cases() -> None:
    features = [
        {"id": "f1", "name": "User Authentication", "description": "Login with OAuth token"},
        {"id": "f2", "name": "Data Export", "description": "Export API service integration"},
    ]
    result = analyze_edge_cases(features)
    assert len(result["edge_cases"]) > 0
    ids = [c["id"] for c in result["edge_cases"]]
    assert any("f1" in eid for eid in ids)
    assert any("f2" in eid for eid in ids)


def test_analyze_edge_cases_empty_features() -> None:
    result = analyze_edge_cases([])
    assert result["edge_cases"] == []
    assert result["risk_matrix"] == {}
    assert result["coverage_score"] == 0.0


def test_analyze_edge_cases_risk_matrix() -> None:
    features = [
        {"id": "f1", "name": "Auth Login", "description": "Authentication with password credential"},
        {"id": "f2", "name": "Display Widget", "description": "Show a simple widget"},
    ]
    result = analyze_edge_cases(features)
    matrix = result["risk_matrix"]
    total = sum(matrix.values())
    assert total == len(result["edge_cases"])
    # Auth-related feature should produce at least one critical severity
    assert matrix.get("critical", 0) >= 1


def test_analyze_edge_cases_coverage_score() -> None:
    features = [
        {"id": "f1", "name": "Feature A", "description": "Simple feature"},
        {"id": "f2", "name": "Feature B", "description": "Another feature"},
    ]
    result = analyze_edge_cases(features)
    # Both features should have edge cases generated
    assert result["coverage_score"] == 1.0


# ---------------------------------------------------------------------------
# Rubber-duck PRD
# ---------------------------------------------------------------------------


def test_generate_rubber_duck_prd_from_spec() -> None:
    spec = "Enable real-time collaboration for distributed teams. The product must support concurrent editing."
    result = generate_rubber_duck_prd(spec)
    assert result["problem_statement"] == "Enable real-time collaboration for distributed teams."
    assert isinstance(result["target_users"], list)
    assert isinstance(result["scope_boundaries"], dict)


def test_generate_rubber_duck_prd_with_research() -> None:
    spec = "Build a notification service."
    research = {
        "user_research": {
            "segment": "Enterprise SaaS teams",
            "signals": ["Need push notifications", "Email overload"],
        },
        "claims": [
            {"id": "c1", "statement": "Push notifications increase engagement by 40%", "confidence": 0.85},
            {"id": "c2", "statement": "SMS fallback is unnecessary for enterprise", "confidence": 0.4},
        ],
    }
    features = [
        {"id": "f1", "name": "Push Notifications", "acceptance_criteria": ["Delivered within 2 seconds"]},
    ]
    result = generate_rubber_duck_prd(spec, research=research, features=features)
    assert "Enterprise SaaS teams" in result["target_users"]
    assert len(result["success_metrics"]) >= 1
    # Only high-confidence claim should appear as key decision
    assert len(result["key_decisions"]) == 1
    assert result["key_decisions"][0]["confidence"] >= 0.7


def test_generate_rubber_duck_prd_empty() -> None:
    result = generate_rubber_duck_prd("")
    assert result["problem_statement"] == ""
    assert result["target_users"] == []
    assert result["success_metrics"] == []
    assert result["key_decisions"] == []


# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------


def test_analyze_impact_layers() -> None:
    features = [
        {"id": "f1", "name": "API Gateway", "description": "REST api endpoint routing"},
        {"id": "f2", "name": "User Database", "description": "Database schema for user storage"},
    ]
    result = analyze_impact("API routing change", features=features)
    layer_names = [layer["layer"] for layer in result["layers"]]
    assert "api" in layer_names
    assert result["blast_radius"] > 0


def test_analyze_impact_blast_radius() -> None:
    features = [
        {"id": "f1", "name": "Auth Service", "description": "Core authentication service handler"},
        {"id": "f2", "name": "Auth Config", "description": "Configuration for auth settings"},
        {"id": "f3", "name": "Auth UI", "description": "Frontend UI login component"},
    ]
    result = analyze_impact("auth", features=features)
    # All three features should be affected since they all contain "auth"
    assert result["blast_radius"] >= 3


def test_analyze_impact_empty() -> None:
    result = analyze_impact("some change")
    assert result["layers"] == []
    assert result["blast_radius"] == 0
    assert result["critical_paths_affected"] == []


# ---------------------------------------------------------------------------
# Sequence diagrams
# ---------------------------------------------------------------------------


def test_generate_sequence_diagrams_basic() -> None:
    features = [
        {"id": "f1", "name": "User Login", "description": "Authenticate user via API"},
    ]
    result = generate_sequence_diagrams(features)
    assert len(result["diagrams"]) >= 1
    diagram = result["diagrams"][0]
    assert diagram["flow_type"] == "success"
    assert "sequenceDiagram" in diagram["mermaid_code"]
    assert "participant User" in diagram["mermaid_code"]
    assert "participant API" in diagram["mermaid_code"]


def test_generate_sequence_diagrams_multiple_features() -> None:
    features = [
        {"id": "f1", "name": "Create Order", "description": "Submit new order via API"},
        {"id": "f2", "name": "Cancel Order", "description": "Cancel existing order with error handling"},
    ]
    result = generate_sequence_diagrams(features)
    feature_ids_in_diagrams = {d["id"].split("-")[1] for d in result["diagrams"]}
    assert "f1" in feature_ids_in_diagrams
    assert "f2" in feature_ids_in_diagrams
    # Cancel Order has "error" keyword, so it should produce an error flow too
    flow_types = [d["flow_type"] for d in result["diagrams"]]
    assert "error" in flow_types


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def test_analyze_state_transitions_basic() -> None:
    features = [
        {
            "id": "f1",
            "name": "Order Processing",
            "states": [
                {"id": "pending", "name": "Pending"},
                {"id": "confirmed", "name": "Confirmed"},
                {"id": "shipped", "name": "Shipped"},
            ],
            "transitions": [
                {"from": "pending", "to": "confirmed", "trigger": "confirm_payment"},
                {"from": "confirmed", "to": "shipped", "trigger": "ship_order"},
            ],
        }
    ]
    result = analyze_state_transitions(features)
    assert len(result["states"]) >= 3
    assert len(result["transitions"]) >= 2
    state_ids = [s["id"] for s in result["states"]]
    assert "pending" in state_ids
    assert "confirmed" in state_ids
    assert "shipped" in state_ids


def test_analyze_state_transitions_risk_states() -> None:
    features = [
        {
            "id": "f1",
            "name": "Payment",
            "states": [
                {"id": "initiated", "name": "Initiated"},
                {"id": "processing", "name": "Processing"},
                {"id": "failed_error", "name": "Failed"},
                {"id": "completed", "name": "Completed"},
            ],
            "transitions": [
                {"from": "initiated", "to": "processing", "trigger": "submit"},
                {"from": "processing", "to": "completed", "trigger": "success"},
                {"from": "processing", "to": "failed_error", "trigger": "failure"},
            ],
        }
    ]
    result = analyze_state_transitions(features)
    risk_ids = [r["id"] for r in result["risk_states"]]
    # completed is terminal (no outgoing), failed_error is terminal + error keyword
    assert "failed_error" in risk_ids
    assert "completed" in risk_ids


def test_analyze_state_transitions_mermaid() -> None:
    features = [
        {
            "id": "f1",
            "name": "Simple Flow",
            "states": [
                {"id": "start", "name": "Start"},
                {"id": "end", "name": "End"},
            ],
            "transitions": [
                {"from": "start", "to": "end", "trigger": "go"},
            ],
        }
    ]
    result = analyze_state_transitions(features)
    mermaid = result["mermaid_code"]
    assert mermaid.startswith("stateDiagram-v2")
    assert "start --> end: go" in mermaid


# ---------------------------------------------------------------------------
# Quality evaluation
# ---------------------------------------------------------------------------


def test_evaluate_dcs_quality_all_present() -> None:
    analysis = {
        "edge_case_analysis": {
            "edge_cases": [{"id": "ec1", "scenario": "test", "severity": "low"}],
            "coverage_score": 1.0,
        },
        "sequence_diagrams": {
            "diagrams": [{"id": "sd1", "title": "test", "mermaid_code": "sequenceDiagram"}],
        },
        "state_transitions": {
            "transitions": [{"from_state": "a", "to_state": "b", "trigger": "go"}],
        },
    }
    gates = evaluate_dcs_quality(analysis)
    assert len(gates) == 2
    assert all(g["passed"] is True for g in gates)
    gate_ids = [g["id"] for g in gates]
    assert "edge-case-coverage" in gate_ids
    assert "behavior-model-coverage" in gate_ids


def test_evaluate_dcs_quality_missing_edge_cases() -> None:
    analysis = {
        "edge_case_analysis": {
            "edge_cases": [],
            "coverage_score": 0.0,
        },
        "sequence_diagrams": {
            "diagrams": [{"id": "sd1", "title": "test", "mermaid_code": "sequenceDiagram"}],
        },
        "state_transitions": {
            "transitions": [],
        },
    }
    gates = evaluate_dcs_quality(analysis)
    edge_gate = next(g for g in gates if g["id"] == "edge-case-coverage")
    assert edge_gate["passed"] is False
    # behavior gate should still pass because diagrams exist
    behavior_gate = next(g for g in gates if g["id"] == "behavior-model-coverage")
    assert behavior_gate["passed"] is True
