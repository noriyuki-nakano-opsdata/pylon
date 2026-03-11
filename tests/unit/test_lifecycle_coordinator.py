"""Tests for lifecycle contracts and autonomous coordination."""

import asyncio
import inspect

from pylon.lifecycle.contracts import (
    build_phase_contracts,
    lifecycle_phase_input,
)
from pylon.lifecycle.coordinator import (
    build_lifecycle_autonomy_projection,
    build_lifecycle_approval_binding,
    derive_lifecycle_next_action,
    lifecycle_action_execution_budget,
    resolve_lifecycle_orchestration_mode,
)
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.orchestrator import (
    build_lifecycle_workflow_handlers,
    _design_evaluator_handler,
    _design_variant_handler,
    _planning_feature_handler,
    _planning_persona_handler,
    _planning_solution_handler,
    _planning_story_handler,
    _planning_synthesizer_handler,
    _research_synthesizer_handler,
    _research_user_handler,
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
    return sync_lifecycle_project_with_run(
        _project(),
        phase="research",
        run_record={"id": "run-research", "state": state, "execution_summary": {}},
        checkpoints=[],
    )


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
    }

    payload = lifecycle_phase_input(project, "research")

    assert payload["competitor_urls"] == ["https://example.com", "https://acme.dev"]
    assert payload["depth"] == "deep"


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
