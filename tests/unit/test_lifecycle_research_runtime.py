from pylon.lifecycle.services.research_runtime import (
    claim_confidence_overrides,
    normalized_research_strings,
    research_autonomous_remediation_state,
    research_judgement_artifact,
    research_runtime_output,
)


def test_claim_confidence_overrides_accepts_stringified_payloads() -> None:
    payload = '[{"claim_id": "claim-a", "confidence": 0.72}]'

    assert claim_confidence_overrides(payload) == {"claim-a": 0.72}


def test_research_runtime_output_shapes_human_readable_summary() -> None:
    research = {
        "readiness": "rework",
        "display_language": "ja",
        "judge_summary": "Need more evidence.",
        "winning_theses": ["Factory operators need fewer manual approvals."],
        "claims": [{"id": "c1", "statement": "Manual approvals are slow.", "status": "accepted", "confidence": 0.74}],
        "quality_gates": [{"id": "source-grounding", "passed": False, "reason": "Missing vendor sources."}],
        "source_links": ["https://example.com/vendor"],
        "remediation_plan": {"objective": "Collect vendor evidence", "retryNodeIds": ["competitor-analyst"]},
        "autonomous_remediation": {
            "status": "retrying",
            "attemptCount": 1,
            "maxAttempts": 2,
            "remainingAttempts": 1,
            "recoveryMode": "reframe_research",
            "recommendedOperatorAction": "conditional_handoff",
            "conditionalHandoffAllowed": True,
            "strategySummary": "Reframe the research angle before retrying.",
        },
    }

    summary = research_runtime_output(research)

    assert summary["kind"] == "research-runtime-output"
    assert summary["claims"][0]["id"] == "c1"
    assert summary["quality_gates"][0]["id"] == "source-grounding"
    assert summary["remediation_plan"]["retryNodeIds"] == ["competitor-analyst"]
    assert summary["autonomous_remediation"]["recoveryMode"] == "reframe_research"


def test_research_autonomous_remediation_state_reports_blocking_signature() -> None:
    state = research_autonomous_remediation_state(
        {
            "node_results": [{"missingSourceClasses": ["vendor_page"]}],
            "winning_theses": ["One strong thesis"],
            "source_links": ["https://example.com/vendor"],
            "confidence_summary": {"floor": 0.52},
        },
        quality_gates=[{"id": "source-grounding", "passed": False, "reason": "Missing vendor pages.", "blockingNodeIds": ["competitor-analyst"]}],
        remediation_plan={"objective": "Recover sources", "retryNodeIds": ["competitor-analyst"]},
        remediation_context={
            "attempt": 1,
            "maxAttempts": 2,
            "lastBlockingSignature": "source-grounding",
            "recoveryMode": "reframe_research",
            "strategySummary": "Switch the angle of research.",
        },
        readiness="rework",
    )

    assert state["status"] == "retrying"
    assert state["blockingGateIds"] == ["source-grounding"]
    assert state["blockingNodeIds"] == ["competitor-analyst"]
    assert state["missingSourceClasses"] == ["vendor_page"]
    assert state["recoveryMode"] == "reframe_research"
    assert state["stalledSignature"] is True


def test_research_autonomous_remediation_allows_guarded_handoff_after_budget_exhaustion() -> None:
    state = research_autonomous_remediation_state(
        {
            "node_results": [{"missingSourceClasses": ["vendor_page"]}],
            "winning_theses": ["One strong thesis"],
            "source_links": ["https://example.com/vendor"],
            "confidence_summary": {"floor": 0.32},
            "critical_dissent_count": 1,
        },
        quality_gates=[
            {"id": "confidence-floor", "passed": False, "reason": "Confidence floor is still low.", "blockingNodeIds": ["research-judge"]},
            {"id": "critical-dissent-resolved", "passed": False, "reason": "Critical dissent remains unresolved.", "blockingNodeIds": ["devils-advocate-researcher"]},
        ],
        remediation_plan={"objective": "Recover sources", "retryNodeIds": ["competitor-analyst"]},
        remediation_context={
            "attempt": 2,
            "maxAttempts": 2,
            "lastBlockingSignature": "confidence-floor|critical-dissent-resolved",
            "recoveryMode": "reframe_research",
            "strategySummary": "Switch the angle of research.",
        },
        readiness="rework",
    )

    assert state["status"] == "blocked"
    assert state["remainingAttempts"] == 0
    assert state["conditionalHandoffAllowed"] is True
    assert state["recommendedOperatorAction"] == "conditional_handoff"
    assert any("重大な反証" in item for item in state["planningGuardrails"])


def test_research_judgement_artifact_embeds_runtime_output() -> None:
    artifact = research_judgement_artifact(
        {
            "readiness": "ready",
            "winning_theses": ["One"],
            "node_results": [
                {
                    "nodeId": "research-judge",
                    "status": "success",
                    "parseStatus": "strict",
                    "retryCount": 0,
                    "degradationReasons": [],
                    "missingSourceClasses": [],
                }
            ],
        }
    )

    assert artifact["name"] == "research-judgement"
    assert artifact["node_results"][0]["nodeId"] == "research-judge"
    assert normalized_research_strings(artifact["winning_theses"]) == ["One"]
