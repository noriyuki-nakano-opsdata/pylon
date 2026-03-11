"""Regression tests for lifecycle orchestration semantics and state propagation."""

import asyncio
import inspect
from collections.abc import AsyncIterator

from pylon.providers.base import Chunk, Message, Response
from pylon.runtime.llm import ProviderRegistry
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.orchestrator import (
    _infer_product_kind,
    _planning_feature_handler,
    _planning_persona_handler,
    _planning_solution_handler,
    _planning_story_handler,
    _planning_synthesizer_handler,
    _research_synthesizer_handler,
    _research_user_handler,
    build_lifecycle_workflow_definition,
    build_lifecycle_workflow_handlers,
    default_lifecycle_project_record,
)


class _ScriptedProvider:
    def __init__(self, provider_name: str, model_id: str, responses: list[str]) -> None:
        self._provider_name = provider_name
        self._model_id = model_id
        self._responses = responses

    async def chat(self, messages: list[Message], **kwargs: object) -> Response:
        content = self._responses.pop(0) if self._responses else "{}"
        return Response(content=content, model=str(kwargs.get("model", self._model_id)))

    async def stream(self, messages: list[Message], **kwargs: object) -> AsyncIterator[Chunk]:
        if False:
            yield Chunk()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_name(self) -> str:
        return self._provider_name


def _research_state(spec: str) -> dict[str, object]:
    state: dict[str, object] = {"spec": spec}
    state.update(_research_user_handler("user-researcher", state).state_patch)
    state["competitor_report"] = [{"name": "demo", "positioning": "reference"}]
    state["market_report"] = {
        "market_size": "Growing",
        "trends": ["evidence-based delivery"],
        "opportunities": ["context continuity"],
        "threats": ["tool sprawl"],
    }
    state["technical_report"] = {"score": 0.82, "notes": "Feasible with strong control-plane primitives."}
    state.update(_research_synthesizer_handler("research-synthesizer", state).state_patch)
    return state


def _planning_state(spec: str) -> dict[str, object]:
    state = _research_state(spec)
    state.update(_planning_persona_handler("persona-builder", state).state_patch)
    state.update(_planning_story_handler("story-architect", state).state_patch)
    state.update(_planning_feature_handler("feature-analyst", state).state_patch)
    state.update(_planning_solution_handler("solution-architect", state).state_patch)
    state.update(_planning_synthesizer_handler("planning-synthesizer", state).state_patch)
    return state


def _invoke_handler(handler, node_id: str, state: dict[str, object]):
    result = handler(node_id, state)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def test_infer_product_kind_prefers_operations_for_lifecycle_specs():
    spec = (
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )

    assert _infer_product_kind(spec) == "operations"


def test_research_sync_preserves_user_research_context():
    state = _research_state(
        "Family learning app for children with daily lessons, rewards, "
        "guardian progress tracking, and adaptive difficulty."
    )
    project = default_lifecycle_project_record("orbit", tenant_id="default")

    patch = sync_lifecycle_project_with_run(
        project,
        phase="research",
        run_record={"id": "run-research-1", "state": state, "execution_summary": {}},
        checkpoints=[],
    )

    assert patch["research"]["user_research"]["signals"]
    assert patch["research"]["user_research"]["pain_points"]
    assert patch["research"]["user_research"]["segment"] == "Product"


def test_planning_outputs_change_with_product_intent():
    ops_spec = (
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    learning_spec = (
        "Family learning app for children with daily lessons, rewards, "
        "guardian progress tracking, and adaptive difficulty."
    )

    ops = _planning_state(ops_spec)["planning"]
    learning = _planning_state(learning_spec)["planning"]

    assert ops["personas"][0]["role"] == "Product Platform Lead"
    assert learning["personas"][0]["role"] == "保護者"
    assert ops["features"][0]["feature"] == "research workspace"
    assert learning["features"][0]["feature"] == "日次レッスン"
    assert ops["use_cases"][0]["id"] == "uc-ops-001"
    assert learning["use_cases"][0]["id"] == "uc-learn-001"
    assert "artifact lineage" in ops["recommendations"][0]
    assert "5分" in learning["recommendations"][0]


def test_planning_sync_persists_information_architecture_and_design_tokens():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    project = default_lifecycle_project_record("orbit", tenant_id="default")

    patch = sync_lifecycle_project_with_run(
        project,
        phase="planning",
        run_record={"id": "run-planning-1", "state": state, "execution_summary": {}},
        checkpoints=[],
    )

    assert patch["analysis"]["ia_analysis"]["navigation_model"] == "hub-and-spoke"
    assert patch["analysis"]["design_tokens"]["style"]["name"] == "Operational Clarity"
    assert patch["features"]
    assert patch["planEstimates"]


def test_lifecycle_workflow_definitions_have_handlers_for_every_node():
    for phase in ("research", "planning", "design", "development"):
        definition = build_lifecycle_workflow_definition("orbit", phase)
        handlers = build_lifecycle_workflow_handlers(phase)
        node_ids = set(definition["project"]["workflow"]["nodes"])

        assert set(handlers) == node_ids


def test_provider_backed_design_handler_uses_llm_variant_payload():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "selected_skills": ["ui-concepting", "design-critique"],
              "quality_targets": ["variant-diversity", "a11y-floor"],
              "delegations": [{"peer": "design-critic", "skill": "design-critique", "reason": "Use an external critic to strengthen contrast and operator clarity."}],
              "execution_note": "Generate a differentiated concept first, then tighten it with peer critique."
            }
            """,
            """
            {
              "pattern_name": "Signal Canvas",
              "description": "A crisp operator workspace with evidence-first hierarchy.",
              "primary_color": "#112233",
              "accent_color": "#f59e0b",
              "rationale": "Highlight evidence, approvals, and next action in one scan.",
              "quality_focus": ["artifact lineage", "mobile resilience"],
              "scores": {"ux_quality": 0.94, "accessibility": 0.92}
            }
            """,
            """
            {
              "pattern_name": "Signal Canvas Refined",
              "description": "Sharper hierarchy, calmer density, and stronger mobile contrast.",
              "primary_color": "#101828",
              "accent_color": "#fb923c",
              "rationale": "Refined for trust, differentiation, and approval clarity.",
              "quality_focus": ["approval clarity", "responsive density"],
              "scores": {"ux_quality": 0.97, "performance": 0.9, "accessibility": 0.96},
              "provider_note": "Critique pass improved hierarchy and contrast."
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("design", provider_registry=registry)

    result = _invoke_handler(handlers["claude-designer"], "claude-designer", state)
    variant = result.state_patch["claude-designer_variant"]

    assert variant["pattern_name"] == "Signal Canvas Refined"
    assert variant["tokens"]["out"] > 0
    assert variant["scores"]["ux_quality"] == 0.97
    assert variant["provider_note"] == "Critique pass improved hierarchy and contrast."
    assert result.metrics["design_mode"] == "provider-backed-autonomous"
    assert len(result.llm_events) == 3
    assert result.state_patch["claude-designer_skill_plan"]["selected_skills"] == ["ui-concepting", "design-critique"]
    assert result.state_patch["claude-designer_delegations"][0]["peer"] == "design-critic"
    assert result.state_patch["claude-designer_peer_feedback"][0]["recommendations"]


def test_design_sync_respects_provider_selected_design_id():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    run_state = {
        "variants": [
            {"id": "claude-designer", "pattern_name": "Calm Evidence", "scores": {"ux_quality": 0.81}},
            {"id": "openai-designer", "pattern_name": "Decision Board", "scores": {"ux_quality": 0.88}},
        ],
        "selected_design_id": "openai-designer",
        "design": {"variants": [], "selected_design_id": "openai-designer"},
    }

    patch = sync_lifecycle_project_with_run(
        project,
        phase="design",
        run_record={"id": "run-design-1", "state": run_state, "execution_summary": {}},
        checkpoints=[],
    )

    assert patch["selectedDesignId"] == "openai-designer"
    assert patch["designVariants"][1]["id"] == "openai-designer"


def test_provider_backed_development_reviewer_runs_revision_iteration():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    state["milestones"] = [
        {"id": "ms-alpha", "name": "Evidence Loop", "criteria": "artifact lineage approval release"},
        {"id": "ms-beta", "name": "Operator View", "criteria": "operator console responsive"},
    ]
    state["integrated_build"] = {
        "code": "<html><body><section>draft</section></body></html>",
        "build_sections": ["hero", "quality-gates"],
    }
    state["selected_features"] = [
        {"feature": "artifact lineage", "selected": True},
        {"feature": "approval gate", "selected": True},
    ]
    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "selected_skills": ["code-review", "delivery-review"],
              "quality_targets": ["feature-coverage", "milestone-readiness"],
              "delegations": [{"peer": "build-craft", "skill": "code-review", "reason": "Bring in an external build craft review before revising the artifact."}],
              "execution_note": "Get external craft review, then revise until blockers are cleared."
            }
            """,
            """
            {
              "code": "<!doctype html><html lang='en'><head><meta charset='utf-8' /><meta name='viewport' content='width=device-width, initial-scale=1' /><title>Lifecycle Control</title><style>body{font-family:sans-serif}button{padding:12px 16px}</style></head><body><main><section><h1>Artifact Lineage</h1><p>Approval workflow and release readiness are visible inside the operator console responsive workspace.</p><button aria-label='Open approval gate'>Approve release</button></section></main></body></html>",
              "revision_summary": "Added semantic structure, responsive viewport metadata, and milestone language.",
              "resolved_blockers": ["Milestone not satisfied: Evidence Loop", "Milestone not satisfied: Operator View", "Add ARIA labels to actionable controls.", "Include responsive viewport metadata for mobile quality."],
              "remaining_risks": []
            }
            """
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("development", provider_registry=registry)

    result = _invoke_handler(handlers["reviewer"], "reviewer", state)
    development = result.state_patch["development"]

    assert result.state_patch["_build_iteration"] == 2
    assert result.metrics["review_mode"] == "provider-backed-autonomous"
    assert "viewport" in development["code"].lower()
    assert "aria-label" in development["code"].lower()
    assert all(item["status"] == "satisfied" for item in development["milestone_results"])
    assert development["review_summary"]["securityStatus"] == "pass"
    assert development["critique_history"][0]["revision_summary"].startswith("Added semantic structure")
    assert result.state_patch["reviewer_skill_plan"]["delegations"][0]["peer"] == "build-craft"
    assert result.state_patch["reviewer_delegations"][0]["peer"] == "build-craft"
    assert development["peer_feedback"][0]["summary"].startswith("build-craft reviewed")


def test_sync_prefers_runtime_skill_plans_and_delegations():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    run_state = {
        "integrated_build": {
            "code": "<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1' /></head><body><main><button aria-label='Ship'>Ship</button></main></body></html>"
        },
        "development": {
            "code": "<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1' /></head><body><main><button aria-label='Ship'>Ship</button></main></body></html>",
            "milestone_results": [{"id": "ms-1", "name": "Alpha", "status": "satisfied"}],
        },
        "estimated_cost_usd": 1.2,
        "_build_iteration": 2,
        "frontend-builder_skill_plan": {
            "selected_skills": ["frontend-implementation", "responsive-ui"],
            "mode": "provider-backed-autonomous",
            "execution_note": "Use the responsive UI craft path.",
        },
        "frontend-builder_delegations": [
            {
                "peer": "build-craft",
                "skill": "responsive-ui",
                "status": "completed",
                "task": {"id": "task-1", "state": "completed"},
                "peerCard": {"name": "build-craft"},
            }
        ],
    }

    patch = sync_lifecycle_project_with_run(
        project,
        phase="development",
        run_record={"id": "run-development-1", "state": run_state, "execution_summary": {}},
        checkpoints=[],
    )

    invocation = next(item for item in patch["skillInvocations"] if item["agentId"] == "frontend-builder")
    delegation = next(item for item in patch["delegations"] if item["agentId"] == "frontend-builder")

    assert invocation["provider"] == "provider-backed-autonomous"
    assert invocation["delegatedTo"] == "build-craft"
    assert invocation["summary"] == "Use the responsive UI craft path."
    assert delegation["peer"] == "build-craft"
    assert delegation["task"]["id"] == "task-1"
