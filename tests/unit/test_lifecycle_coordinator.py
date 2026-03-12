"""Tests for lifecycle contracts and autonomous coordination."""

import asyncio
import inspect

from pylon.lifecycle.contracts import (
    build_phase_contracts,
    lifecycle_phase_input,
)
from pylon.lifecycle.coordinator import (
    build_lifecycle_approval_binding,
    build_lifecycle_autonomy_projection,
    derive_lifecycle_next_action,
    lifecycle_action_execution_budget,
    resolve_lifecycle_orchestration_mode,
)
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.orchestrator import (
    _design_evaluator_handler,
    _design_variant_handler,
    build_lifecycle_workflow_handlers,
    default_lifecycle_project_record,
)


def _project() -> dict[str, object]:
    return default_lifecycle_project_record("orbit", tenant_id="default")


def _invoke_handler(handler, node_id: str, state: dict[str, object]):
    result = handler(node_id, state)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _research_patch(spec: str) -> dict[str, object]:
    state: dict[str, object] = {"spec": spec}
    handlers = build_lifecycle_workflow_handlers("research")
    for node_id in (
        "competitor-analyst",
        "market-researcher",
        "user-researcher",
        "tech-evaluator",
        "research-synthesizer",
        "evidence-librarian",
        "devils-advocate-researcher",
        "cross-examiner",
        "research-judge",
    ):
        state.update(_invoke_handler(handlers[node_id], node_id, state).state_patch)
    patch = sync_lifecycle_project_with_run(
        _project(),
        phase="research",
        run_record={"id": "run-research", "state": state, "execution_summary": {}},
        checkpoints=[],
    )
    research = dict(patch["research"])
    canonical = dict(research.get("canonical") or research)
    localized = dict(research.get("localized") or research)
    if not canonical.get("source_links"):
        canonical["source_links"] = ["https://example.com/product"]
    if not canonical.get("evidence"):
        canonical["evidence"] = [
            {
                "id": "ev-1",
                "source_ref": "https://example.com/product",
                "source_type": "url",
                "snippet": "Grounded product evidence.",
                "recency": "current",
                "relevance": "high",
            }
        ]
    canonical["claims"] = [
        {
            **dict(item),
            "status": "accepted",
            "confidence": max(float(dict(item).get("confidence", 0.72) or 0.72), 0.72),
        }
        for item in canonical.get("claims", [])
    ]
    if not canonical["claims"]:
        canonical["claims"] = [
            {
                "id": "claim-1",
                "statement": "Operations teams value governed traceability.",
                "owner": "research-synthesizer",
                "category": "market",
                "evidence_ids": ["ev-1"],
                "counterevidence_ids": [],
                "confidence": 0.72,
                "status": "accepted",
            }
        ]
    canonical["winning_theses"] = canonical.get("winning_theses") or [
        canonical["claims"][0]["statement"]
    ]
    canonical["confidence_summary"] = {
        **dict(canonical.get("confidence_summary") or {}),
        "average": max(float(dict(canonical.get("confidence_summary") or {}).get("average", 0.72) or 0.72), 0.72),
        "floor": max(float(dict(canonical.get("confidence_summary") or {}).get("floor", 0.72) or 0.72), 0.72),
        "accepted": max(int(dict(canonical.get("confidence_summary") or {}).get("accepted", 1) or 1), 1),
    }
    canonical["dissent"] = [
        {**dict(item), "resolved": True, "severity": "medium"}
        for item in canonical.get("dissent", [])
    ]
    canonical["critical_dissent_count"] = 0
    canonical["readiness"] = "ready"
    canonical["quality_gates"] = [
        {
            "id": "source-grounding",
            "title": "採択主張が source と evidence に接地している",
            "passed": True,
            "reason": "external url evidence is present",
            "blockingNodeIds": [],
        },
        {
            "id": "counterclaim-coverage",
            "title": "主要仮説に対する反証が生成されている",
            "passed": True,
            "reason": "dissent coverage present",
            "blockingNodeIds": [],
        },
        {
            "id": "critical-dissent-resolved",
            "title": "重大な dissent が未解決のまま残っていない",
            "passed": True,
            "reason": "no unresolved critical dissent",
            "blockingNodeIds": [],
        },
        {
            "id": "confidence-floor",
            "title": "採択 thesis が planning に渡せる信頼度を満たしている",
            "passed": True,
            "reason": "confidence floor satisfied",
            "blockingNodeIds": [],
        },
        {
            "id": "critical-node-health",
            "title": "critical research nodes が degraded / failed ではない",
            "passed": True,
            "reason": "all critical nodes healthy",
            "blockingNodeIds": [],
        },
    ]
    canonical["node_results"] = [
        {**dict(item), "status": "success", "missingSourceClasses": [], "degradationReasons": []}
        for item in canonical.get("node_results", [])
    ]
    localized.update(
        {
            "source_links": canonical["source_links"],
            "evidence": canonical["evidence"],
            "claims": canonical["claims"],
            "winning_theses": canonical["winning_theses"],
            "confidence_summary": canonical["confidence_summary"],
            "dissent": canonical["dissent"],
            "critical_dissent_count": 0,
            "readiness": "ready",
            "quality_gates": canonical["quality_gates"],
            "node_results": canonical["node_results"],
        }
    )
    patch["research"] = {
        **localized,
        "canonical": canonical,
        "localized": localized,
        "display_language": "ja",
        "localization_status": "strict",
    }
    for item in patch["phaseStatuses"]:
        if item["phase"] == "research":
            item["status"] = "completed"
        if item["phase"] == "planning":
            item["status"] = "available"
    return patch


def _planning_patch(spec: str) -> dict[str, object]:
    state: dict[str, object] = {"spec": spec}
    state["research"] = _research_patch(spec)["research"]
    handlers = build_lifecycle_workflow_handlers("planning")
    for node_id in (
        "persona-builder",
        "story-architect",
        "feature-analyst",
        "solution-architect",
        "planning-synthesizer",
        "scope-skeptic",
        "assumption-auditor",
        "negative-persona-challenger",
        "milestone-falsifier",
        "planning-judge",
    ):
        state.update(_invoke_handler(handlers[node_id], node_id, state).state_patch)
    project = _project()
    project["research"] = state["research"]
    return sync_lifecycle_project_with_run(
        project,
        phase="planning",
        run_record={"id": "run-planning", "state": state, "execution_summary": {}},
        checkpoints=[],
    )


def _design_patch(spec: str) -> dict[str, object]:
    planning_patch = _planning_patch(spec)
    state: dict[str, object] = {
        "spec": spec,
        "analysis": planning_patch["analysis"],
        "features": planning_patch["features"],
    }
    state.update(_design_variant_handler("Claude", "Minimal", "Calm", "#0f172a", "#f97316")("claude-designer", state).state_patch)
    state.update(_design_variant_handler("GPT", "Ops", "Dense", "#0f172a", "#1d4ed8")("openai-designer", state).state_patch)
    state.update(_design_variant_handler("Gemini", "Cards", "Modular", "#312e81", "#06b6d4")("gemini-designer", state).state_patch)
    state.update(_design_evaluator_handler("design-evaluator", state).state_patch)
    project = _project()
    project["research"] = _research_patch(spec)["research"]
    project["analysis"] = planning_patch["analysis"]
    project["features"] = planning_patch["features"]
    project["milestones"] = planning_patch["milestones"]
    return sync_lifecycle_project_with_run(
        project,
        phase="design",
        run_record={"id": "run-design", "state": state, "execution_summary": {}},
        checkpoints=[],
    )


def _development_patch(spec: str) -> dict[str, object]:
    planning_patch = _planning_patch(spec)
    design_patch = _design_patch(spec)
    selected_design = next(
        (
            variant
            for variant in design_patch["designVariants"]
            if variant["id"] == design_patch["selectedDesignId"]
        ),
        design_patch["designVariants"][0],
    )
    return {
        "buildCode": selected_design["preview_html"],
        "buildCost": 1.2,
        "buildIteration": 1,
        "milestoneResults": [
            {"id": "ms-alpha", "name": "Alpha", "status": "satisfied"},
            {"id": "ms-beta", "name": "Beta", "status": "satisfied"},
        ],
        "research": _research_patch(spec)["research"],
        "analysis": planning_patch["analysis"],
        "features": planning_patch["features"],
        "milestones": planning_patch["milestones"],
        "designVariants": design_patch["designVariants"],
        "selectedDesignId": design_patch["selectedDesignId"],
    }


def test_contracts_capture_handoff_readiness_for_completed_phases():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))

    contracts = build_phase_contracts(project)

    assert contracts["research"]["ready"] is True
    assert contracts["planning"]["ready"] is True
    assert contracts["planning"]["outputs"]["featureCount"] > 0


def test_next_action_progresses_to_approval_boundary():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."

    project = _project()
    project["spec"] = spec
    assert derive_lifecycle_next_action(project)["phase"] == "research"

    project.update(_research_patch(spec))
    assert derive_lifecycle_next_action(project)["phase"] == "planning"

    project.update(_planning_patch(spec))
    assert derive_lifecycle_next_action(project)["phase"] == "design"

    project.update(_design_patch(spec))
    next_action = derive_lifecycle_next_action(project)
    assert next_action["type"] == "request_approval"
    assert next_action["phase"] == "approval"


def test_next_action_progresses_from_approval_to_release():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["approvalStatus"] = "approved"

    assert derive_lifecycle_next_action(project)["phase"] == "development"

    project.update(_development_patch(spec))
    assert derive_lifecycle_next_action(project)["type"] == "run_deploy_checks"

    project["deployChecks"] = [
        {"id": "dq-1", "label": "Build preview", "status": "pass"},
        {"id": "dq-2", "label": "Accessibility", "status": "pass"},
    ]
    assert derive_lifecycle_next_action(project)["type"] == "create_release"

    project["releases"] = [{"id": "rel-1"}]
    assert derive_lifecycle_next_action(project)["type"] == "collect_feedback"


def test_development_phase_input_includes_selected_design_context():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    payload = lifecycle_phase_input(project, "development")

    assert payload["selected_features"]
    assert payload["selected_design"]["id"] == project["selectedDesignId"]
    assert payload["design"]["selected"]["id"] == project["selectedDesignId"]


def test_research_phase_input_preserves_competitor_urls_and_depth():
    project = _project()
    project["spec"] = "Autonomous multi-agent lifecycle platform"
    project["researchConfig"] = {
        "competitorUrls": ["https://example.com", "https://acme.dev"],
        "depth": "deep",
        "outputLanguage": "ja",
    }

    payload = lifecycle_phase_input(project, "research")

    assert payload["competitor_urls"] == ["https://example.com", "https://acme.dev"]
    assert payload["depth"] == "deep"
    assert payload["output_language"] == "ja"


def test_research_phase_input_includes_autonomous_remediation_context_for_rework():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "quality_gates": [
                {
                    "id": "source-grounding",
                    "title": "source grounding",
                    "passed": False,
                    "reason": "external evidence is missing",
                    "blockingNodeIds": ["competitor-analyst", "market-researcher"],
                }
            ],
            "remediation_plan": {
                "objective": "Find grounded competitor product pages and market reports.",
                "retryNodeIds": ["competitor-analyst", "market-researcher"],
            },
            "node_results": [
                {
                    "nodeId": "competitor-analyst",
                    "status": "degraded",
                    "missingSourceClasses": ["vendor_page"],
                }
            ],
            "source_links": ["https://example.com/product"],
            "competitors": [{"name": "Acme Ops"}],
        },
    }

    payload = lifecycle_phase_input(project, "research")

    assert payload["remediation_context"]["attempt"] == 1
    assert payload["remediation_context"]["retryNodeIds"] == ["competitor-analyst", "market-researcher"]
    assert payload["remediation_context"]["missingSourceClasses"] == ["vendor_page"]


def test_autonomous_mode_continues_research_remediation_before_requesting_review():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "autonomous"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "quality_gates": [
                {
                    "id": "source-grounding",
                    "title": "source grounding",
                    "passed": False,
                    "reason": "external evidence is missing",
                    "blockingNodeIds": ["competitor-analyst"],
                }
            ],
            "remediation_plan": {
                "objective": "Find grounded competitor product pages.",
                "retryNodeIds": ["competitor-analyst"],
            },
        },
    }
    for item in project["phaseStatuses"]:
        if item["phase"] == "research":
            item["status"] = "available"

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "run_phase"
    assert next_action["phase"] == "research"
    assert next_action["canAutorun"] is True
    assert next_action["payload"]["input"]["remediation_context"]["attempt"] == 1


def test_research_remediation_stops_after_attempt_budget_is_exhausted():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "autonomous"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "quality_gates": [
                {
                    "id": "confidence-floor",
                    "title": "confidence floor",
                    "passed": False,
                    "reason": "confidence is still too low",
                    "blockingNodeIds": ["research-judge"],
                }
            ],
            "remediation_plan": {
                "objective": "Tighten claim grounding before planning.",
                "retryNodeIds": ["research-judge"],
            },
            "autonomous_remediation": {
                "attemptCount": 2,
                "maxAttempts": 2,
            },
        },
    }
    for item in project["phaseStatuses"]:
        if item["phase"] == "research":
            item["status"] = "available"

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "review_phase"
    assert next_action["phase"] == "research"


def test_workflow_mode_allows_self_healing_research_remediation_to_autorun():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "workflow"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "quality_gates": [
                {
                    "id": "source-grounding",
                    "title": "source grounding",
                    "passed": False,
                    "reason": "external evidence is missing",
                    "blockingNodeIds": ["competitor-analyst"],
                }
            ],
            "remediation_plan": {
                "objective": "Find grounded competitor product pages.",
                "retryNodeIds": ["competitor-analyst"],
            },
        },
    }

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "run_phase"
    assert next_action["phase"] == "research"
    assert next_action["canAutorun"] is True
    assert next_action["requiresTrigger"] is False
    assert lifecycle_action_execution_budget(project, requested_steps=4) == 1


def test_planning_phase_input_prefers_canonical_research_payload():
    project = _project()
    project["spec"] = "Governed lifecycle platform"
    project["research"] = {
        "judge_summary": "日本語の表示用要約です。",
        "display_language": "ja",
        "canonical": {
            "judge_summary": "Canonical English summary.",
            "winning_theses": ["Governed visibility is the leading wedge."],
            "claims": [{"id": "claim-1", "statement": "Operations teams value traceability.", "status": "accepted"}],
        },
        "localized": {
            "judge_summary": "日本語の表示用要約です。",
            "winning_theses": ["統制された可視化が主な勝ち筋です。"],
            "claims": [{"id": "claim-1", "statement": "運用チームはトレーサビリティを重視します。", "status": "accepted"}],
        },
    }

    payload = lifecycle_phase_input(project, "planning")

    assert payload["research"]["judge_summary"] == "Canonical English summary."
    assert payload["research"]["claims"][0]["statement"] == "Operations teams value traceability."
    assert payload["research_context_meta"]["source"] == "canonical"
    assert payload["research_context_meta"]["compacted"] is False


def test_development_phase_input_compacts_research_when_token_budget_is_exceeded():
    project = _project()
    project["spec"] = "Governed lifecycle platform"
    long_statement = " ".join(["evidence"] * 4000)
    oversized_research = {
        "display_language": "ja",
        "canonical": {
            "judge_summary": long_statement,
            "market_size": long_statement,
            "trends": [long_statement, long_statement],
            "opportunities": [long_statement],
            "threats": [long_statement],
            "claims": [
                {"id": f"claim-{index}", "statement": long_statement, "owner": "market-researcher", "category": "market", "confidence": 0.6, "status": "accepted"}
                for index in range(12)
            ],
            "dissent": [
                {"id": f"dissent-{index}", "claim_id": f"claim-{index}", "argument": long_statement, "severity": "high", "recommended_test": long_statement, "resolved": False}
                for index in range(8)
            ],
            "open_questions": [long_statement for _ in range(8)],
            "winning_theses": [long_statement for _ in range(4)],
            "source_links": [f"https://example.com/{index}" for index in range(10)],
            "quality_gates": [{"id": "source-grounding", "title": "gate", "reason": long_statement, "blockingNodeIds": ["market-researcher"], "passed": False}],
            "confidence_summary": {"average": 0.6, "floor": 0.5},
        },
    }
    project.update(_planning_patch(project["spec"]))
    project.update(_design_patch(project["spec"]))
    project["research"] = oversized_research

    payload = lifecycle_phase_input(project, "development")

    assert payload["research_context_meta"]["compacted"] is True
    assert payload["research"]["summary_mode"].startswith("compact")
    assert payload["research_context_meta"]["tokenEstimate"] <= payload["research_context_meta"]["tokenBudget"]
    assert len(payload["research"]["claims"]) <= 6
    assert len(payload["research"]["source_links"]) <= 6


def test_autonomy_projection_reports_blocked_approval_boundary():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    projection = build_lifecycle_autonomy_projection(project)

    assert projection["approvalRequired"] is True
    assert projection["nextAction"]["type"] == "request_approval"
    assert projection["phaseReadiness"]["design"]["ready"] is True


def test_a4_full_autonomy_auto_approves_instead_of_blocking():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["orchestrationMode"] = "autonomous"
    project["autonomyLevel"] = "A4"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    projection = build_lifecycle_autonomy_projection(project)

    assert projection["approvalRequired"] is False
    assert projection["nextAction"]["type"] == "auto_approve"
    assert projection["nextAction"]["canAutorun"] is True


def test_workflow_mode_blocks_autonomous_progression():
    project = _project()
    project["spec"] = "Autonomous multi-agent lifecycle platform"
    project["orchestrationMode"] = "workflow"

    next_action = derive_lifecycle_next_action(project)

    assert resolve_lifecycle_orchestration_mode(project) == "workflow"
    assert next_action["type"] == "run_phase"
    assert next_action["phase"] == "research"
    assert next_action["canAutorun"] is False
    assert next_action["requiresTrigger"] is True
    assert lifecycle_action_execution_budget(project, requested_steps=4) == 0


def test_guided_mode_allows_one_explicit_step_per_advance():
    project = _project()
    project["spec"] = "Autonomous multi-agent lifecycle platform"
    project["orchestrationMode"] = "guided"

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "run_phase"
    assert next_action["canAutorun"] is False
    assert next_action["requiresTrigger"] is True
    assert lifecycle_action_execution_budget(project, requested_steps=4) == 1


def test_autonomous_mode_allows_multi_step_progression():
    project = _project()
    project["spec"] = "Autonomous multi-agent lifecycle platform"
    project["orchestrationMode"] = "autonomous"

    next_action = derive_lifecycle_next_action(project)
    projection = build_lifecycle_autonomy_projection(project)

    assert next_action["type"] == "run_phase"
    assert next_action["canAutorun"] is True
    assert next_action["requiresTrigger"] is False
    assert lifecycle_action_execution_budget(project, requested_steps=4) == 4
    assert projection["orchestrationMode"] == "autonomous"


def test_approval_binding_tracks_selected_design_and_feature_scope():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    binding = build_lifecycle_approval_binding(project)

    assert binding["action"] == "advance_to_development"
    assert binding["plan"]["selected_design_id"] == project["selectedDesignId"]
    assert binding["effect_envelope"]["phase"] == "development"
    assert binding["effect_envelope"]["input"]["selected_design"]["id"] == project["selectedDesignId"]
    assert binding["plan"]["selected_features"]


def test_approval_binding_changes_when_design_or_feature_scope_changes():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    baseline = build_lifecycle_approval_binding(project)
    project["selectedDesignId"] = "alt-design"
    design_changed = build_lifecycle_approval_binding(project)

    assert baseline["plan"] != design_changed["plan"]
    assert baseline["effect_envelope"] != design_changed["effect_envelope"]

    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["features"] = [
        {"feature": "Artifact lineage", "selected": True},
        {"feature": "Manual exports", "selected": False},
    ]
    scope_changed = build_lifecycle_approval_binding(project)

    assert scope_changed["plan"]["selected_features"] == ["Artifact lineage"]
    assert baseline["plan"] != scope_changed["plan"]


def test_rejected_approval_stops_autonomous_progression_until_rework():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["approvalStatus"] = "revision_requested"
    project["approvalRequestId"] = "apr_demo"

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "review_phase"
    assert next_action["phase"] == "approval"
    assert next_action["canAutorun"] is False
