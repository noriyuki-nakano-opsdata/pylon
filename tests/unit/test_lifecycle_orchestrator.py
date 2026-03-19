"""Regression tests for lifecycle orchestration semantics and state propagation."""

import asyncio
import inspect
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path

import pylon.lifecycle.orchestrator as lifecycle_orchestrator
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.services.development_workspace import build_development_code_workspace
from pylon.lifecycle.services.value_contracts import (
    REQUIRED_DELIVERY_CONTRACT_IDS,
    build_outcome_telemetry_contract,
    build_value_contract,
)
from pylon.lifecycle.orchestrator import (
    _design_variant_payload,
    _build_design_prototype,
    _looks_like_prototype_html,
    _extract_html_document,
    _rank_design_variants,
    backfill_planning_artifacts,
    _development_integrator_handler,
    _infer_product_kind,
    _merge_prototype_overrides,
    _preferred_lifecycle_model,
    _prototype_overrides_from_payload,
    build_lifecycle_workflow_definition,
    build_lifecycle_workflow_handlers,
    default_lifecycle_project_record,
)
from pylon.providers.base import Chunk, Message, Response
from pylon.runtime.llm import ProviderRegistry
from pylon.skills.catalog import SkillCatalog
from pylon.skills.runtime import SkillRuntime


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


class _InstructionCapturingProvider(_ScriptedProvider):
    def __init__(self, provider_name: str, model_id: str, responses: list[str]) -> None:
        super().__init__(provider_name, model_id, responses)
        self.static_instructions: list[str] = []
        self.system_messages: list[str] = []

    async def chat(self, messages: list[Message], **kwargs: object) -> Response:
        self.static_instructions.append(str(kwargs.get("static_instruction", "")))
        self.system_messages.extend(
            str(message.content)
            for message in messages
            if message.role == "system"
        )
        return await super().chat(messages, **kwargs)


def _write_lifecycle_skill(tmp_path: Path, *, skill_id: str, instruction: str) -> None:
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            id: {skill_id}
            name: {skill_id}
            description: Lifecycle test skill.
            ---

            {instruction}
            """
        ),
        encoding="utf-8",
    )


def _research_state(spec: str) -> dict[str, object]:
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
    return state


def _planning_state(spec: str) -> dict[str, object]:
    state = _research_state(spec)
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


def test_infer_product_kind_ignores_incidental_learning_examples_in_ops_specs():
    spec = (
        "Autonomous multi-agent workflow platform with governed approvals, "
        "operator console visibility, and artifact lineage.\n"
        "Appendix example: 学習アプリのような別ドメインにも応用できる。"
    )

    assert _infer_product_kind(spec) == "operations"


def test_infer_product_kind_keeps_learning_platform_specs_as_learning():
    spec = (
        "Family learning platform for children with daily lessons, rewards, "
        "guardian progress tracking, and adaptive difficulty."
    )

    assert _infer_product_kind(spec) == "learning"


def test_looks_like_prototype_html_accepts_japanese_navigation_shell():
    html = """
    <!doctype html>
    <html lang="ja">
      <body data-prototype-kind="control-center">
        <main>
          <nav aria-label="主要ナビゲーション"></nav>
          <section data-screen-id="workspace"></section>
          <section data-screen-id="approvals"></section>
        </main>
      </body>
    </html>
    """

    assert _looks_like_prototype_html(html) is True


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
    assert patch["research"]["readiness"] == "rework"
    assert patch["research"]["quality_gates"]
    phase_lookup = {item["phase"]: item["status"] for item in patch["phaseStatuses"]}
    assert phase_lookup["research"] == "available"
    assert phase_lookup["planning"] == "locked"


def test_research_sync_phase_run_summary_includes_token_metrics():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    patch = sync_lifecycle_project_with_run(
        project,
        phase="research",
        run_record={
            "id": "run-research-metrics",
            "state": {
                "research": {
                    "claims": [{"statement": "Demand exists", "status": "accepted"}],
                    "winning_theses": ["Ops teams need governed delivery."],
                    "source_links": ["https://example.com/report"],
                    "evidence": [{"id": "ev-1", "source_type": "url", "source_ref": "https://example.com/report"}],
                    "confidence_summary": {"average": 0.76, "floor": 0.64, "accepted": 1},
                }
            },
            "execution_summary": {},
            "runtime_metrics": {
                "estimated_cost_usd": 0.0,
                "token_usage": {
                    "input_tokens": 1200,
                    "output_tokens": 450,
                    "total_tokens": 1650,
                },
            },
        },
        checkpoints=[],
    )

    phase_run = next(item for item in patch["phaseRuns"] if item["runId"] == "run-research-metrics")
    assert phase_run["costMeasured"] is False
    assert phase_run["totalTokens"] == 1650
    assert phase_run["inputTokens"] == 1200
    assert phase_run["outputTokens"] == 450


def test_research_sync_phase_run_summary_recomputes_cost_from_checkpoint_llm_events():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    patch = sync_lifecycle_project_with_run(
        project,
        phase="research",
        run_record={
            "id": "run-research-cost-replay",
            "state": {
                "research": {
                    "claims": [{"statement": "Demand exists", "status": "accepted"}],
                    "winning_theses": ["Ops teams need governed delivery."],
                    "source_links": ["https://example.com/report"],
                    "evidence": [{"id": "ev-1", "source_type": "url", "source_ref": "https://example.com/report"}],
                    "confidence_summary": {"average": 0.76, "floor": 0.64, "accepted": 1},
                }
            },
            "execution_summary": {},
            "runtime_metrics": {
                "estimated_cost_usd": 0.0,
                "token_usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            },
        },
        checkpoints=[
            {
                "id": "cp-1",
                "event_log": [
                    {
                        "node_id": "research-judge",
                        "llm_events": [
                            {
                                "provider": "anthropic",
                                "model": "claude-sonnet-4-6",
                                "estimated_cost_usd": 0.0,
                                "usage": {
                                    "input_tokens": 3000,
                                    "output_tokens": 1500,
                                    "cache_read_tokens": 0,
                                    "cache_write_tokens": 0,
                                    "reasoning_tokens": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    )

    phase_run = next(item for item in patch["phaseRuns"] if item["runId"] == "run-research-cost-replay")
    assert phase_run["costMeasured"] is True
    assert phase_run["totalTokens"] == 4500
    assert phase_run["costUsd"] > 0


def test_phase_run_summary_rehydrates_execution_summary_from_event_log_and_node_status():
    project = default_lifecycle_project_record("orbit", tenant_id="default")

    patch = sync_lifecycle_project_with_run(
        project,
        phase="design",
        run_record={
            "id": "run-design-runtime-summary",
            "status": "completed",
            "started_at": "2026-03-17T00:00:00Z",
            "completed_at": "2026-03-17T00:05:00Z",
            "state": {
                "execution": {
                    "node_status": {
                        "claude-designer": "succeeded",
                        "claude-preview-validator": "succeeded",
                        "design-evaluator": "succeeded",
                    },
                },
            },
            "event_log": [
                {"seq": 1, "node_id": "claude-designer"},
                {"seq": 2, "node_id": "claude-preview-validator"},
                {"seq": 3, "node_id": "design-evaluator"},
            ],
            "execution_summary": {},
        },
        checkpoints=[],
    )

    phase_run = next(item for item in patch["phaseRuns"] if item["runId"] == "run-design-runtime-summary")
    execution_summary = phase_run["executionSummary"]
    assert execution_summary["eventCount"] == 3
    assert execution_summary["completedNodeCount"] == 3
    assert execution_summary["lastNodeId"] == "design-evaluator"
    assert execution_summary["recentNodeIds"] == [
        "design-evaluator",
        "claude-preview-validator",
        "claude-designer",
    ]
    assert execution_summary["nodeStatus"] == {
        "claude-designer": "succeeded",
        "claude-preview-validator": "succeeded",
        "design-evaluator": "succeeded",
    }


def test_research_sync_blocks_phase_completion_without_external_sources():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    run_state = {
        "research": {
            "competitors": [{"name": "Atlas", "strengths": ["Fast setup"], "weaknesses": ["Weak governance"], "pricing": "Custom", "target": "SMB ops"}],
            "market_size": "Operators need better workflow visibility.",
            "trends": ["AI copilots"],
            "opportunities": ["Approval routing"],
            "threats": ["Generic PM tools"],
            "tech_feasibility": {"score": 0.72, "notes": "Feasible with existing APIs."},
            "claims": [
                {
                    "id": "claim-1",
                    "statement": "Teams want governed delivery.",
                    "owner": "research-synthesizer",
                    "category": "demand",
                    "evidence_ids": ["brief-1"],
                    "counterevidence_ids": [],
                    "confidence": 0.74,
                    "status": "accepted",
                }
            ],
            "evidence": [
                {
                    "id": "brief-1",
                    "source_ref": "project://brief",
                    "source_type": "project-brief",
                    "snippet": "Spec mentions governed delivery.",
                    "recency": "current",
                    "relevance": "high",
                }
            ],
            "dissent": [
                {
                    "id": "dissent-1",
                    "claim_id": "claim-1",
                    "challenger": "devils-advocate-researcher",
                    "argument": "Need external validation.",
                    "severity": "medium",
                    "resolved": True,
                }
            ],
            "open_questions": ["Which segments pay first?"],
            "winning_theses": ["Governed delivery is a strong wedge."],
            "confidence_summary": {"average": 0.74, "floor": 0.68, "accepted": 1},
            "source_links": [],
        }
    }

    patch = sync_lifecycle_project_with_run(
        project,
        phase="research",
        run_record={
            "id": "run-research-ungrounded",
            "state": run_state,
            "execution_summary": {},
            "runtime_metrics": {
                "token_usage": {"total_tokens": 0},
                "model_routes": [],
            },
        },
        checkpoints=[],
    )

    phase_lookup = {item["phase"]: item["status"] for item in patch["phaseStatuses"]}
    outcome = next(item for item in patch["decisionLog"] if item["id"] == "run-research-ungrounded:research:outcome")

    assert phase_lookup["research"] == "available"
    assert phase_lookup["planning"] == "locked"
    assert outcome["status"] == "blocked"
    assert "external url evidence" in outcome["rationale"].lower()


def test_research_flow_emits_claims_evidence_and_dissent():
    research = _research_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )["research"]

    assert research["claims"]
    assert research["evidence"]
    assert research["dissent"]
    assert research["winning_theses"]
    assert research["confidence_summary"]["floor"] >= 0.6
    assignment_values = set(research["model_assignments"].values())
    assert any(value.startswith("moonshot/") for value in assignment_values)
    assert any(value.startswith("zhipu/") for value in assignment_values)


def test_research_flow_never_emits_synthetic_sources():
    research = _research_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )["research"]

    assert all(item["source_type"] != "synthetic-reference" for item in research["evidence"])
    assert all(not str(item["source_ref"]).startswith("synthetic://") for item in research["evidence"])


def test_provider_backed_research_handler_uses_grounded_sources(monkeypatch):
    packets = [
        {
            "source_ref": "https://acme.example/platform",
            "source_type": "url",
            "url": "https://acme.example/platform",
            "host": "acme.example",
            "title": "Acme Lifecycle Platform",
            "description": "Acme positions itself as a governed workflow platform for approvals and lifecycle automation.",
            "excerpt": "Acme positions itself as a governed workflow platform for approvals and lifecycle automation.",
            "text_excerpt": "Acme positions itself as a governed workflow platform for approvals and lifecycle automation with approval routing and audit-friendly reviews.",
        },
        {
            "source_ref": "https://northstar.example/product",
            "source_type": "url",
            "url": "https://northstar.example/product",
            "host": "northstar.example",
            "title": "Northstar Ops Workspace",
            "description": "Northstar highlights operator workflows, run visibility, and release controls.",
            "excerpt": "Northstar highlights operator workflows, run visibility, and release controls.",
            "text_excerpt": "Northstar highlights operator workflows, run visibility, and release controls, but pricing is not listed on the public product page.",
        },
    ]

    monkeypatch.setattr(
        lifecycle_orchestrator,
        "_collect_research_source_packets",
        lambda *args, **kwargs: packets,
    )

    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "selected_skills": ["competitive-intelligence"],
              "quality_targets": ["Ground claims in linked evidence", "Preserve dissent and open questions"],
              "delegations": [{"peer": "research-fabric", "skill": "competitive-intelligence", "reason": "Use an external research peer to check source diversity."}],
              "execution_note": "Synthesize from the grounded source packets and keep the competitor set evidence-backed."
            }
            """,
            """
            {
              "competitors": [
                {
                  "name": "Acme Lifecycle Platform",
                  "url": "https://acme.example/platform",
                  "strengths": ["Governed workflow positioning is explicit on the public product page."],
                  "weaknesses": ["Pricing is not visible from the captured public materials."],
                  "pricing": "Not publicly listed",
                  "target": "Product"
                },
                {
                  "name": "Northstar Ops Workspace",
                  "url": "https://northstar.example/product",
                  "strengths": ["Operator workflow and release control messaging is explicit."],
                  "weaknesses": ["Public materials emphasize control surfaces more than approval traceability depth."],
                  "pricing": "Not publicly listed",
                  "target": "Product"
                }
              ],
              "claim_statement": "Grounded public sources show adjacent products competing on workflow control and approvals, so differentiation should focus on evidence lineage and decision traceability.",
              "confidence": 0.81
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("research", provider_registry=registry)

    result = _invoke_handler(
        handlers["competitor-analyst"],
        "competitor-analyst",
        {
            "spec": (
                "Autonomous multi-agent lifecycle platform for operator-led research, "
                "approvals, artifact lineage, and governed delivery."
            )
        },
    )

    competitors = result.state_patch["competitor_report"]

    assert result.metrics["research_mode"] == "provider-backed-autonomous"
    assert competitors[0]["name"] == "Acme Lifecycle Platform"
    assert all(item["url"].startswith("https://") for item in competitors)
    assert all(item["source_type"] == "url" for item in result.state_patch["competitor-analyst_evidence"])
    assert result.state_patch["competitor-analyst_skill_plan"]["delegations"][0]["peer"] == "research-fabric"
    assert result.state_patch["competitor-analyst_delegations"][0]["peer"] == "research-fabric"
    assert result.state_patch["competitor-analyst_peer_feedback"][0]["recommendations"]


def test_normalized_research_strings_extracts_text_from_structured_payloads():
    values = [
        "{'question': 'What segment pays first?'}",
        {"statement": "Operator trust is the main wedge."},
        [{"pain_point": "Approval routing is opaque."}],
    ]

    normalized = lifecycle_orchestrator._normalized_research_strings(values, limit=4, char_limit=220)

    assert normalized == [
        "What segment pays first?",
        "Operator trust is the main wedge.",
        "Approval routing is opaque.",
    ]


def test_vendor_product_filter_rejects_article_like_competitor_pages():
    article_packet = {
        "source_ref": "https://startus-insights.example/innovators-guide",
        "url": "https://startus-insights.example/innovators-guide",
        "host": "startus-insights.example",
        "title": "Top manufacturing SaaS trends",
        "description": "Industry outlook and trend report for manufacturing SaaS.",
        "excerpt": "Top manufacturing SaaS trends and market outlook.",
        "text_excerpt": "This report covers market size, industry outlook, and top trends.",
    }
    product_packet = {
        "source_ref": "https://acme.example/product",
        "url": "https://acme.example/product",
        "host": "acme.example",
        "title": "Acme Manufacturing Control Platform",
        "description": "Acme provides workflow approvals, governance, and auditability for factory operations.",
        "excerpt": "Acme provides workflow approvals, governance, and auditability for factory operations.",
        "text_excerpt": "Workflow approvals, governance, pricing, and traceability are all described on the product page.",
    }

    assert lifecycle_orchestrator._looks_like_vendor_product_packet(article_packet) is False
    assert lifecycle_orchestrator._looks_like_vendor_product_packet(product_packet) is True


def test_research_judge_applies_structured_winning_theses_and_confidence_overrides():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "winning_theses": [
                {"claim_id": "claim-market-demand", "statement": "Manufacturing teams will pay for governed workflow visibility.", "confidence": 0.55},
                {"claim_id": "claim-user-trust", "statement": "Trust and operator control remain the decisive adoption gate.", "confidence": 0.62}
              ],
              "summary": {"summary": "Demand exists, but confidence should stay conservative until direct operator evidence improves."},
              "open_questions": [
                {"question": "Which manufacturing segment has the shortest approval chain?"},
                {"question": "What proof reduces operator distrust fastest?"}
              ]
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    claims = [
        {
            "id": "claim-market-demand",
            "statement": "Manufacturing teams need better workflow visibility.",
            "owner": "market-researcher",
            "category": "market",
            "evidence_ids": ["ev-1", "ev-2"],
            "counterevidence_ids": [],
            "confidence": 0.83,
            "status": "accepted",
        },
        {
            "id": "claim-user-trust",
            "statement": "Operator trust is the main adoption gate.",
            "owner": "user-researcher",
            "category": "user",
            "evidence_ids": ["ev-3", "ev-4"],
            "counterevidence_ids": [],
            "confidence": 0.79,
            "status": "accepted",
        },
    ]
    state = {
        "research": {
            "claims": claims,
            "evidence": [
                {"id": "ev-1", "source_ref": "https://acme.example/product", "source_type": "url"},
                {"id": "ev-2", "source_ref": "https://northstar.example/platform", "source_type": "url"},
            ],
            "source_links": ["https://acme.example/product"],
        },
        lifecycle_orchestrator._node_state_key("cross-examiner", "claims"): claims,
        lifecycle_orchestrator._node_state_key("cross-examiner", "dissent"): [],
        lifecycle_orchestrator._node_state_key("cross-examiner", "open_questions"): [
            "{'question': 'Which segment pays first?'}"
        ],
        lifecycle_orchestrator._node_state_key("evidence-librarian", "evidence"): [
            {"id": "ev-1", "source_ref": "https://acme.example/product", "source_type": "url"},
            {"id": "ev-2", "source_ref": "https://northstar.example/platform", "source_type": "url"},
        ],
        lifecycle_orchestrator._node_state_key("evidence-librarian", "source_links"): [
            "https://acme.example/product",
            "https://northstar.example/platform",
        ],
    }

    result = asyncio.run(
        lifecycle_orchestrator._research_judge_handler(
            "research-judge",
            state,
            provider_registry=registry,
        )
    )

    judged = result.state_patch["research"]
    judged_claims = {item["id"]: item for item in judged["claims"]}

    assert judged["winning_theses"] == [
        "Manufacturing teams will pay for governed workflow visibility.",
        "Trust and operator control remain the decisive adoption gate.",
    ]
    assert "Which segment pays first?" in judged["open_questions"]
    assert "Which manufacturing segment has the shortest approval chain?" in judged["open_questions"]
    assert "What proof reduces operator distrust fastest?" in judged["open_questions"]
    assert judged["judge_summary"] == "Demand exists, but confidence should stay conservative until direct operator evidence improves."
    assert judged_claims["claim-market-demand"]["confidence"] == 0.55
    assert judged_claims["claim-user-trust"]["confidence"] == 0.62


def test_research_llm_json_repairs_non_json_output_once():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            "winning_theses: market wins",
            '{"winning_theses": ["Market wins"], "summary": "repaired"}',
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})

    payload, llm_events, meta = asyncio.run(
        lifecycle_orchestrator._research_llm_json(
            provider_registry=registry,
            llm_runtime=None,
            preferred_model="claude-sonnet",
            purpose="lifecycle-research-repair-test",
            static_instruction="Return JSON only.",
            user_prompt="Return JSON only.",
            schema_name="research-judge",
            required_keys=["winning_theses", "summary"],
        )
    )

    assert payload == {"winning_theses": ["Market wins"], "summary": "repaired"}
    assert meta["parse_status"] == "repaired"


def test_research_judge_resolves_claim_id_winning_theses_to_statements():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "winning_theses": ["claim-market-demand", "claim-user-trust"],
              "summary": "Demand exists, but operator trust still decides adoption.",
              "open_questions": [],
              "claim_confidence_overrides": {},
              "blocking_reasons": [],
              "retry_node_ids": []
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    claims = [
        {
            "id": "claim-market-demand",
            "statement": "Manufacturing teams will pay for governed workflow visibility.",
            "owner": "market-researcher",
            "category": "market",
            "evidence_ids": ["ev-1"],
            "counterevidence_ids": [],
            "confidence": 0.81,
            "status": "accepted",
        },
        {
            "id": "claim-user-trust",
            "statement": "Trust and operator control remain the decisive adoption gate.",
            "owner": "user-researcher",
            "category": "user",
            "evidence_ids": ["ev-2"],
            "counterevidence_ids": [],
            "confidence": 0.78,
            "status": "accepted",
        },
    ]
    state = {
        "research": {"claims": claims},
        lifecycle_orchestrator._node_state_key("cross-examiner", "claims"): claims,
        lifecycle_orchestrator._node_state_key("cross-examiner", "dissent"): [],
        lifecycle_orchestrator._node_state_key("cross-examiner", "open_questions"): [],
    }

    result = asyncio.run(
        lifecycle_orchestrator._research_judge_handler(
            "research-judge",
            state,
            provider_registry=registry,
        )
    )

    judged = result.state_patch["research"]

    assert judged["winning_theses"] == [
        "Manufacturing teams will pay for governed workflow visibility.",
        "Trust and operator control remain the decisive adoption gate.",
    ]


def test_research_remediation_queries_bias_toward_missing_source_types():
    queries = lifecycle_orchestrator._research_remediation_queries(
        {
            "spec": "Manufacturing workflow platform with governed approvals",
            "remediation_context": {
                "retryNodeIds": ["competitor-analyst"],
                "missingSourceClasses": ["vendor_page", "pricing_page"],
                "objective": "Find official competitor product pages and pricing.",
            },
        },
        node_id="competitor-analyst",
        queries=["manufacturing workflow software"],
    )

    assert "manufacturing workflow software" in queries
    assert any("official product" in item for item in queries)
    assert any("pricing page" in item for item in queries)


def test_auto_recovery_mode_deepens_first_then_reframes_after_retry():
    initial_queries = lifecycle_orchestrator._research_remediation_queries(
        {
            "spec": "Manufacturing workflow platform with governed approvals",
            "recovery_mode": "auto",
            "research": {
                "node_results": [
                    {
                        "nodeId": "competitor-analyst",
                        "status": "degraded",
                        "retryCount": 0,
                    }
                ],
            },
            "research:competitor-analyst:result": {
                "retryCount": 0,
            },
        },
        node_id="competitor-analyst",
        queries=["manufacturing workflow software"],
    )

    retried_queries = lifecycle_orchestrator._research_remediation_queries(
        {
            "spec": "Manufacturing workflow platform with governed approvals",
            "recovery_mode": "auto",
            "research": {
                "node_results": [
                    {
                        "nodeId": "competitor-analyst",
                        "status": "degraded",
                        "retryCount": 1,
                    }
                ],
            },
            "research:competitor-analyst:result": {
                "retryCount": 1,
            },
        },
        node_id="competitor-analyst",
        queries=["manufacturing workflow software"],
    )

    assert any("official product" in item for item in initial_queries)
    assert not any("governance requirement" in item for item in initial_queries)
    assert any("governance requirement" in item for item in retried_queries)


def test_research_judge_persists_autonomous_remediation_state():
    state = {
        "spec": "Governed manufacturing workflow platform",
        "remediation_context": {
            "attempt": 1,
            "maxAttempts": 2,
            "objective": "Find grounded competitor product pages.",
            "retryNodeIds": ["competitor-analyst"],
        },
        "research": {
            "claims": [
                {
                    "id": "claim-competitive-gap",
                    "statement": "Operators need governed workflow visibility.",
                    "owner": "competitor-analyst",
                    "category": "competition",
                    "evidence_ids": ["ev-1"],
                    "counterevidence_ids": [],
                    "confidence": 0.52,
                    "status": "blocked",
                }
            ],
            "evidence": [
                {"id": "ev-1", "source_ref": "https://example.com/report", "source_type": "url"}
            ],
            "source_links": ["https://example.com/report"],
        },
        lifecycle_orchestrator._node_state_key("cross-examiner", "claims"): [
            {
                "id": "claim-competitive-gap",
                "statement": "Operators need governed workflow visibility.",
                "owner": "competitor-analyst",
                "category": "competition",
                "evidence_ids": ["ev-1"],
                "counterevidence_ids": [],
                "confidence": 0.52,
                "status": "blocked",
            }
        ],
        lifecycle_orchestrator._node_state_key("cross-examiner", "dissent"): [],
        lifecycle_orchestrator._node_state_key("cross-examiner", "open_questions"): [],
        lifecycle_orchestrator._node_state_key("evidence-librarian", "evidence"): [
            {"id": "ev-1", "source_ref": "https://example.com/report", "source_type": "url"}
        ],
        lifecycle_orchestrator._node_state_key("evidence-librarian", "source_links"): [
            "https://example.com/report"
        ],
        lifecycle_orchestrator._node_state_key("competitor-analyst", "result"): {
            "nodeId": "competitor-analyst",
            "status": "degraded",
            "parseStatus": "strict",
            "degradationReasons": ["missing_source_classes:vendor_page"],
            "sourceClassesSatisfied": [],
            "missingSourceClasses": ["vendor_page"],
            "artifact": {},
            "retryCount": 1,
        },
    }

    result = asyncio.run(
        lifecycle_orchestrator._research_judge_handler(
            "research-judge",
            state,
            provider_registry=None,
        )
    )

    autonomous = result.state_patch["research"]["autonomous_remediation"]

    assert autonomous["status"] == "retrying"
    assert autonomous["attemptCount"] == 1
    assert autonomous["maxAttempts"] == 2
    assert autonomous["retryNodeIds"] == ["competitor-analyst"]
    assert "vendor_page" in autonomous["missingSourceClasses"]


def test_localize_research_output_translates_aggregated_payload_to_japanese():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-haiku",
        responses=[
            """
            {
              "market_size": "公開ソースでは市場規模の定量記述をまだ確認できませんでした。",
              "tech_feasibility": {"notes": "技術的には成立するが、統合とデータ品質の検証が必要です。"},
              "claims": [{"id": "claim-1", "statement": "運用チームは可視性と統制の両立に価値を感じます。"}],
              "open_questions": ["どの業種が最初に導入判断を下しますか。"],
              "winning_theses": ["統制された可視化が初期導入の主な勝ち筋です。"],
              "judge_summary": "根拠は一定量あるが、競合比較の厚みはまだ不足しています。"
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})

    localized, llm_events, _ = asyncio.run(
        lifecycle_orchestrator._localize_research_output(
            {
                "market_size": "Public sources do not yet provide a quantified market-size estimate.",
                "tech_feasibility": {"score": 0.64, "notes": "Technically plausible, but integration and data quality still need validation."},
                "claims": [
                    {
                        "id": "claim-1",
                        "statement": "Operations teams value visibility with governance.",
                        "owner": "market-researcher",
                        "category": "market",
                        "evidence_ids": ["ev-1"],
                        "counterevidence_ids": [],
                        "confidence": 0.66,
                        "status": "accepted",
                    }
                ],
                "open_questions": ["Which segment buys first?"],
                "winning_theses": ["Governed visibility is the leading wedge."],
                "judge_summary": "Claims that survived dissent are passed to planning together with unresolved questions.",
                "quality_gates": [
                    {
                        "id": "source-grounding",
                        "title": "採択主張が source と evidence に接地している",
                        "passed": False,
                        "reason": "external url evidence is missing",
                        "blockingNodeIds": ["market-researcher"],
                    }
                ],
            },
            target_language="ja",
            provider_registry=registry,
            llm_runtime=None,
        )
    )

    assert localized["market_size"].startswith("公開ソース")
    assert localized["tech_feasibility"]["notes"].startswith("技術的には")
    assert localized["claims"][0]["statement"].startswith("運用チーム")
    assert localized["open_questions"] == ["どの業種が最初に導入判断を下しますか。"]
    assert localized["winning_theses"] == ["統制された可視化が初期導入の主な勝ち筋です。"]
    assert localized["judge_summary"] == "根拠は一定量あるが、競合比較の厚みはまだ不足しています。"
    assert localized["quality_gates"][0]["reason"] == "外部 URL に grounded された evidence が不足しています。"
    assert localized["research_context"]["decision_stage"] == "needs_research_rework"
    assert localized["research_context"]["decision_stage_label"] == "再調査で根拠を補う状態"
    assert localized["operator_copy"]["council_cards"][0]["agent"] == "仮説評議"
    assert localized["operator_copy"]["handoff_brief"]["headline"]
    assert localized["display_language"] == "ja"
    assert localized["localization_status"] == "strict"
    assert llm_events


def test_localize_research_output_skips_provider_call_for_already_japanese_payload():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-haiku",
        responses=['{"judge_summary":"should not be used"}'],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})

    localized, llm_events, meta = asyncio.run(
        lifecycle_orchestrator._localize_research_output(
            {
                "market_size": "市場規模は十分に大きいです。",
                "tech_feasibility": {"notes": "既存APIとETLで実装可能です。"},
                "user_research": {"segment": "中堅製造業", "signals": [], "pain_points": []},
                "judge_summary": "confidence floor は 0.62 です。",
                "quality_gates": [
                    {
                        "id": "confidence-floor",
                        "title": "信頼度下限",
                        "passed": True,
                        "reason": "confidence floor は 0.62 です。",
                    }
                ],
            },
            target_language="ja",
            provider_registry=registry,
            llm_runtime=None,
        )
    )

    assert localized["display_language"] == "ja"
    assert localized["localization_status"] == "noop"
    assert llm_events == []
    assert meta["status"] == "noop"


def test_localize_planning_output_translates_analysis_and_keeps_canonical_shape():
    provider = _ScriptedProvider(
        "anthropic",
        "claude-haiku",
        responses=[
            """
            {
              "personas": [
                {
                  "role": "運用責任者",
                  "goals": ["承認待ちを減らしたい"],
                  "frustrations": ["判断の根拠が散らばっている"],
                  "context": "週次レビューで複数案件を同時に判断する。"
                }
              ],
              "recommendations": [
                {
                  "action": "デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。",
                  "rationale": "中止条件のないマイルストーンは、進捗しているように見えるだけの誤学習を生みます。"
                }
              ],
              "judge_summary": [
                {
                  "title": "マイルストーンに中止条件がありません",
                  "description": "M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。",
                  "owner": "プロダクト責任者",
                  "must_resolve_before": "デザイン着手前"
                }
              ],
              "design_tokens": {
                "style": {
                  "name": "運用の明瞭さ",
                  "best_for": "複数案件の同時レビュー"
                },
                "rationale": "重い判断を短い視線移動で済ませるためのスタイルです。"
              }
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})

    localized, llm_events, _ = asyncio.run(
        lifecycle_orchestrator._localize_planning_output(
            {
                "personas": [
                    {
                        "name": "Naoki",
                        "role": "Operations lead",
                        "goals": ["Reduce approval lag"],
                        "frustrations": ["Evidence is scattered across tools"],
                        "tech_proficiency": "high",
                        "context": "Reviews multiple launches during weekly decision meetings.",
                    }
                ],
                "user_stories": [],
                "kano_features": [],
                "recommendations": [
                    "{\"id\": \"rec-1\", \"priority\": \"critical\", \"action\": \"Add explicit failure conditions to both milestones before design begins.\", \"rationale\": \"Milestones without stop conditions create false progress.\"}"
                ],
                "judge_summary": "{\"id\": \"risk-1\", \"severity\": \"critical\", \"title\": \"Milestones lack stop conditions\", \"description\": \"Neither M1 nor M2 has a defined failure signal or halt threshold.\", \"owner\": \"product lead\", \"must_resolve_before\": \"design kickoff\"}",
                "design_tokens": {
                    "style": {
                        "name": "Operational Clarity",
                        "keywords": ["focused", "governed"],
                        "best_for": "Multi-threaded review work",
                        "performance": "High information density with low distraction",
                        "accessibility": "Strong contrast and explicit hierarchy",
                    },
                    "colors": {
                        "primary": "#112233",
                        "secondary": "#334455",
                        "cta": "#556677",
                        "background": "#0b1020",
                        "text": "#f8fafc",
                        "notes": "Use high-contrast accents only for irreversible actions.",
                    },
                    "typography": {
                        "heading": "IBM Plex Sans",
                        "body": "IBM Plex Sans",
                        "mood": ["precise", "calm"],
                    },
                    "effects": ["Soft edge glow around the active decision lane"],
                    "anti_patterns": ["Avoid decorative gradients that compete with status meaning"],
                    "rationale": "This style keeps operator judgement legible under pressure.",
                },
            },
            target_language="ja",
            provider_registry=registry,
            llm_runtime=None,
        )
    )

    assert localized["personas"][0]["role"] == "運用責任者"
    assert localized["personas"][0]["goals"] == ["承認待ちを減らしたい"]
    assert localized["recommendations"][0].startswith("{")
    assert "デザイン着手前" in localized["recommendations"][0]
    assert "マイルストーンに中止条件がありません" in localized["judge_summary"]
    assert localized["design_tokens"]["style"]["name"] == "運用の明瞭さ"
    assert localized["design_tokens"]["style"]["best_for"] == "複数案件の同時レビュー"
    assert localized["design_tokens"]["rationale"].startswith("重い判断")
    assert localized["display_language"] == "ja"
    assert localized["localization_status"] == "strict"
    assert llm_events


def test_planning_judge_persists_canonical_and_localized_analysis():
    state = _research_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
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
    ):
        state.update(_invoke_handler(handlers[node_id], node_id, state).state_patch)

    provider = _ScriptedProvider(
        "anthropic",
        "claude-haiku",
        responses=[
            """
            {
              "recommendations": [
                {
                  "id": "rec-1",
                  "priority": "critical",
                  "action": "Add explicit failure conditions to both milestones before design begins.",
                  "rationale": "Milestones without stop conditions create false progress."
                }
              ],
              "headline_risks": [
                {
                  "id": "risk-1",
                  "severity": "critical",
                  "title": "Milestones lack stop conditions",
                  "description": "Neither M1 nor M2 has a defined failure signal or halt threshold.",
                  "owner": "product lead",
                  "must_resolve_before": "design kickoff"
                }
              ]
            }
            """,
            """
            {
              "recommendations": [
                {
                  "action": "デザイン着手前に、両方のマイルストーンへ明示的な失敗条件を追加します。",
                  "rationale": "中止条件のないマイルストーンは、進捗しているように見えるだけの誤学習を生みます。"
                }
              ],
              "judge_summary": [
                {
                  "title": "マイルストーンに中止条件がありません",
                  "description": "M1 と M2 のどちらにも、失敗シグナルや中止閾値が定義されていません。",
                  "owner": "プロダクト責任者",
                  "must_resolve_before": "デザイン着手前"
                }
              ]
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})

    result = _invoke_handler(
        lambda node_id, current_state: lifecycle_orchestrator._planning_judge_handler(
            node_id,
            current_state,
            provider_registry=registry,
            llm_runtime=None,
        ),
        "planning-judge",
        state,
    )

    analysis = result.state_patch["analysis"]
    assert analysis["canonical"]["judge_summary"].startswith("{'id': 'risk-1'")
    assert analysis["canonical"]["recommendations"][0].startswith("{'id': 'rec-1'")
    assert analysis["canonical"]["operator_copy"]["council_cards"][0]["agent"] == "Product Council"
    assert analysis["localized"]["operator_copy"]["council_cards"][0]["agent"] == "プロダクト評議"
    assert analysis["localized"]["operator_copy"]["handoff_brief"]["headline"]
    assert "マイルストーンに中止条件がありません" in analysis["judge_summary"]
    assert "デザイン着手前" in analysis["recommendations"][0]
    assert analysis["localized"]["display_language"] == "ja"
    assert analysis["display_language"] == "ja"
    assert analysis["localization_status"] == "strict"


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


def test_planning_outputs_expand_use_case_and_effort_coverage():
    planning = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )["planning"]

    assert len(planning["job_stories"]) >= 4
    assert len(planning["use_cases"]) >= 6
    assert len(planning["traceability"]) >= len([item for item in planning["features"] if item["selected"]])
    assert planning["coverage_summary"]["use_case_count"] == len(planning["use_cases"])
    standard_plan = next(item for item in planning["plan_estimates"] if item["preset"] == "standard")
    assert len(standard_plan["epics"]) >= 3
    assert len(standard_plan["wbs"]) >= 10
    assert standard_plan["total_effort_hours"] >= 80


def test_planning_estimates_use_scheduled_workdays_for_duration_weeks():
    planning = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )["planning"]

    for plan in planning["plan_estimates"]:
        scheduled_workdays = max(
            (item["start_day"] + item["duration_days"] for item in plan["wbs"]),
            default=1,
        )
        expected_weeks = max(1, (scheduled_workdays + 4) // 5)
        assert plan["duration_weeks"] == expected_weeks

    standard_plan = next(item for item in planning["plan_estimates"] if item["preset"] == "standard")
    full_plan = next(item for item in planning["plan_estimates"] if item["preset"] == "full")
    assert standard_plan["duration_weeks"] >= 2
    assert full_plan["duration_weeks"] >= standard_plan["duration_weeks"]


def test_backfill_planning_artifacts_enriches_stale_generic_bundle():
    stale_project = {
        "spec": "完全なる自律型マルチエージェント基盤",
        "analysis": {
            "use_cases": [{"id": "uc-generic-001", "title": "Complete the primary workflow"}],
            "job_stories": [{"situation": "When a user first tries the product"}],
            "actors": [{"name": "Primary User"}],
            "roles": [{"name": "Admin"}],
        },
        "features": _planning_state("Generic product")["planning"]["features"],
        "planEstimates": [],
    }

    enriched = backfill_planning_artifacts(stale_project)

    assert enriched["features"][0]["feature"] == "research workspace"
    assert enriched["analysis"]["use_cases"][0]["id"] == "uc-ops-001"
    assert enriched["analysis"]["coverage_summary"]["use_case_count"] >= 6
    assert enriched["planEstimates"][0]["wbs"]


def test_backfill_planning_artifacts_rebuilds_duration_weeks_from_schedule():
    spec = (
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    planning = _planning_state(spec)["planning"]
    stale_plan_estimates = [
        {
            **plan,
            "duration_weeks": 1,
        }
        for plan in planning["plan_estimates"]
    ]
    stale_project = {
        "spec": spec,
        "analysis": planning,
        "features": planning["features"],
        "planEstimates": stale_plan_estimates,
    }

    enriched = backfill_planning_artifacts(stale_project)
    standard_plan = next(item for item in enriched["planEstimates"] if item["preset"] == "standard")
    scheduled_workdays = max(
        (item["start_day"] + item["duration_days"] for item in standard_plan["wbs"]),
        default=1,
    )

    assert standard_plan["duration_weeks"] == max(1, (scheduled_workdays + 4) // 5)
    assert standard_plan["duration_weeks"] >= 2


def test_backfill_planning_artifacts_rebuilds_stale_generic_subfields_for_operations():
    stale_project = {
        "spec": "完全なる自律型マルチエージェント基盤",
        "analysis": {
            "personas": [
                {"name": "Naoki", "role": "Product Owner"},
                {"name": "Yuna", "role": "Primary User"},
            ],
            "use_cases": [{"id": "uc-ops-001", "title": "Run discovery-to-build workflow", "priority": "must"}],
            "job_stories": [{"situation": "When a user first tries the product"}],
            "actors": [{"name": "Primary User"}],
            "roles": [{"name": "Admin"}],
            "business_model": {
                "customer_segments": ["Primary users", "Product teams"],
                "channels": ["Web", "Mobile", "Team sharing"],
            },
            "design_tokens": {"style": {"name": "Balanced Product"}},
            "kano_features": [{"feature": "guided onboarding"}],
            "negative_personas": [{"name": "Impatient Evaluator"}],
            "kill_criteria": [{"condition": "If Configuration and recovery cannot show observable completion evidence"}],
            "red_team_findings": [{"title": "Milestone Configuration and recovery needs a failure condition"}],
            "canonical": {"judge_summary": "legacy canonical should be discarded"},
            "localized": {"judge_summary": "legacy localized should be discarded"},
        },
        "features": _planning_state("Generic product")["planning"]["features"],
        "planEstimates": [],
    }

    enriched = backfill_planning_artifacts(stale_project)

    assert enriched["analysis"]["personas"][0]["role"] == "Product Platform Lead"
    assert enriched["analysis"]["design_tokens"]["style"]["name"] == "Operational Clarity"
    assert enriched["analysis"]["negative_personas"][0]["name"] == "Shadow Automator"
    assert enriched["analysis"]["planning_context"]["product_kind"] == "operations"
    assert "Configuration and recovery" not in " ".join(
        str(item.get("condition", "")) for item in enriched["analysis"]["kill_criteria"]
    )
    assert "canonical" not in enriched["analysis"]
    assert "localized" not in enriched["analysis"]


def test_planning_flow_emits_red_team_traceability_and_negative_personas():
    planning = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )["planning"]

    assert planning["feature_decisions"]
    assert planning["red_team_findings"]
    assert planning["traceability"]
    assert planning["negative_personas"]
    assert planning["kill_criteria"]
    assignment_values = set(planning["model_assignments"].values())
    assert any(value.startswith("moonshot/") for value in assignment_values)
    assert any(value.startswith("zhipu/") for value in assignment_values)


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
              "provider_note": "Critique pass improved hierarchy and contrast.",
              "implementation_brief": {
                "architecture_thesis": "承認判断、根拠確認、差し戻し履歴を一つの review shell に束ねる。",
                "system_shape": ["decision shell", "approval ledger", "lineage rail"],
                "technical_choices": [
                  {
                    "area": "状態同期",
                    "decision": "review 状態は checkpoint 付きで復元する",
                    "rationale": "途中離脱や差し戻し後でも判断文脈を失わないため。"
                  }
                ],
                "agent_lanes": [
                  {
                    "role": "設計レーン",
                    "remit": "主要判断フローを設計する",
                    "skills": ["workflow-design", "solution-architecture"]
                  }
                ],
                "delivery_slices": ["判断レビュー", "承認レジャー", "成果物リネージ"]
              }
            }
            """,
            # LLM-generated preview HTML response
            '<!doctype html><html lang="ja"><head><meta charset="utf-8"/><title>Signal Canvas</title>'
            "<style>body{margin:0;font-family:sans-serif;background:#101828;color:#f8fafc}"
            "nav{background:#0b1120;padding:16px}main{padding:24px}"
            ".card{border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:20px;margin:12px 0;background:rgba(15,23,42,0.8)}"
            ".metric{display:inline-block;padding:12px 16px;border-radius:14px;background:rgba(255,255,255,0.06);margin:4px;border:1px solid rgba(255,255,255,0.08)}"
            ".btn{padding:10px 18px;border-radius:14px;border:1px solid #fb923c40;background:#fb923c20;color:#f8fafc;cursor:pointer}"
            "</style></head><body>"
            '<nav aria-label="主要ナビゲーション"><span>Signal Canvas</span></nav>'
            "<main>"
            '<section class="card" data-screen-id="dashboard"><h2>判断デッキ</h2><p>運用状況を一覧する</p>'
            '<div class="metric">稼働率 99.2%</div><div class="metric">承認待ち 3件</div></section>'
            '<section class="card" data-screen-id="review"><h2>レビューゲート</h2><p>品質を確認する</p>'
            '<button class="btn">承認する</button></section>'
            '<section class="card" data-screen-id="lineage"><h2>リネージ探索</h2><p>成果物の系譜を追う</p></section>'
            '<section class="card" data-screen-id="settings"><h2>設定</h2><p>ワークスペースを調整する</p></section>'
            "</main>"
            "<script>document.querySelectorAll('.btn').forEach(b=>b.addEventListener('click',()=>alert('Action')))</script>"
            "</body></html>",
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("design", provider_registry=registry)

    result = _invoke_handler(handlers["claude-designer"], "claude-designer", state)
    variant = result.state_patch["claude-designer_variant"]

    assert variant["pattern_name"] == "Signal Canvas Refined"
    assert variant["scores"]["ux_quality"] == 0.97
    assert variant["provider_note"] == "Critique pass improved hierarchy and contrast."
    assert result.metrics["design_mode"] == "provider-backed-autonomous"
    assert len(result.llm_events) == 4  # plan + proposal + critique + preview HTML
    assert result.state_patch["claude-designer_skill_plan"]["selected_skills"] == ["ui-concepting", "design-critique"]
    assert result.state_patch["claude-designer_delegations"][0]["peer"] == "design-critic"
    assert result.state_patch["claude-designer_peer_feedback"][0]["recommendations"]
    assert variant["prototype"]["screens"]
    assert variant["prototype"]["flows"]
    assert variant["implementation_brief"]["architecture_thesis"] == "承認判断、根拠確認、差し戻し履歴を一つの review shell に束ねる。"
    assert variant["implementation_brief"]["technical_choices"][0]["area"] == "状態同期"
    assert variant["implementation_brief"]["delivery_slices"][0] == "判断レビュー"
    # LLM-generated preview HTML is used instead of template
    assert 'aria-label="主要ナビゲーション"' in variant["preview_html"]
    assert 'data-screen-id=' in variant["preview_html"]
    assert "Signal Canvas" in variant["preview_html"]
    assert "<script>" in variant["preview_html"]  # LLM preview includes interactivity
    assert variant["preview_meta"]["source"] == "llm"
    assert variant["preview_meta"]["validation_ok"] is False
    assert "missing_viewport" in variant["preview_meta"]["validation_issues"]
    assert variant["preview_meta"]["copy_quality_score"] >= 0.8
    assert variant["primary_workflows"][0]["name"]
    assert variant["screen_specs"][0]["title"]
    assert variant["selection_rationale"]["reasons"]
    assert variant["approval_packet"]["review_checklist"]
    assert variant["artifact_completeness"]["status"] == "complete"
    assert variant["freshness"]["status"] == "fresh"
    assert variant["freshness"]["can_handoff"] is False
    assert "design preview does not satisfy the preview contract" in variant["freshness"]["reasons"]


def test_design_preview_validator_repairs_invalid_llm_preview_for_handoff():
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
              "selected_skills": ["ui-concepting"],
              "quality_targets": ["variant-diversity", "preview-contract"],
              "delegations": [],
              "execution_note": "Produce the concept and then validate the preview contract."
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
              "scores": {"ux_quality": 0.97, "performance": 0.9, "accessibility": 0.96}
            }
            """,
            '<!doctype html><html lang="ja"><head><meta charset="utf-8"/><title>Signal Canvas</title>'
            "<style>body{margin:0;font-family:sans-serif;background:#101828;color:#f8fafc}</style></head><body>"
            '<nav aria-label="主要ナビゲーション"><span>Signal Canvas</span></nav>'
            "<main><section data-screen-id=\"dashboard\"><h2>判断デッキ</h2></section>"
            "<section data-screen-id=\"review\"><h2>レビューゲート</h2></section>"
            "<section data-screen-id=\"lineage\"><h2>リネージ探索</h2></section>"
            "<section data-screen-id=\"settings\"><h2>設定</h2></section></main></body></html>",
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("design", provider_registry=registry)

    designer = _invoke_handler(handlers["claude-designer"], "claude-designer", state)
    validator_state = dict(state)
    validator_state.update(designer.state_patch)
    validated = _invoke_handler(handlers["claude-preview-validator"], "claude-preview-validator", validator_state)
    variant = validated.state_patch["claude-designer_variant"]
    validation = validated.state_patch["claude-preview-validator_preview_validation"]

    assert validation["status"] == "repaired"
    assert validation["repaired"] is True
    assert variant["preview_meta"]["source"] == "repaired"
    assert variant["preview_meta"]["validation_ok"] is True
    assert variant["preview_meta"]["repaired_from_source"] == "llm"
    assert variant["preview_meta"]["candidate_validation_ok"] is False
    assert "missing_viewport" in variant["preview_meta"]["candidate_validation_issues"]
    assert variant["preview_candidate_html"].startswith("<!doctype html>")
    assert 'aria-label="承認フォーム"' in variant["preview_html"]
    assert "<script>" in variant["preview_html"]
    assert variant["freshness"]["can_handoff"] is True
    assert validated.metrics["repaired"] is True


def test_lifecycle_handlers_merge_control_plane_skill_assignments(tmp_path: Path):
    _write_lifecycle_skill(
        tmp_path,
        skill_id="control-plane-design-review",
        instruction="Always apply the control-plane design review checklist before responding.",
    )
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    provider = _InstructionCapturingProvider(
        "anthropic",
        "claude-sonnet",
        responses=[
            """
            {
              "selected_skills": ["control-plane-design-review", "ui-concepting"],
              "quality_targets": ["variant-diversity", "a11y-floor"],
              "delegations": [],
              "execution_note": "Use the assigned design review skill before generating the concept."
            }
            """,
            """
            {
              "pattern_name": "Assigned Skill Canvas",
              "description": "A control-plane-aware operator workspace.",
              "primary_color": "#112233",
              "accent_color": "#f59e0b",
              "rationale": "The assigned skill reinforces evidence-first design review.",
              "quality_focus": ["artifact lineage", "design review"],
              "scores": {"ux_quality": 0.92, "accessibility": 0.93}
            }
            """,
            """
            {
              "pattern_name": "Assigned Skill Canvas Refined",
              "description": "Sharper review structure with stronger operator trust.",
              "primary_color": "#101828",
              "accent_color": "#fb923c",
              "rationale": "Refined with the assigned lifecycle skill in mind.",
              "quality_focus": ["approval clarity", "responsive density"],
              "scores": {"ux_quality": 0.95, "performance": 0.9, "accessibility": 0.96}
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    runtime = SkillRuntime(
        SkillCatalog(skill_dirs=(str(tmp_path / "skills"),), refresh_ttl_seconds=0)
    )
    handlers = build_lifecycle_workflow_handlers(
        "design",
        provider_registry=registry,
        skill_runtime=runtime,
        tenant_id="tenant-alpha",
        agent_skill_lookup=lambda agent_id: ["control-plane-design-review"] if agent_id == "claude-designer" else [],
    )

    result = _invoke_handler(handlers["claude-designer"], "claude-designer", state)

    assert "control-plane-design-review" in result.state_patch["claude-designer_skill_plan"]["candidate_skills"]
    assert "control-plane-design-review" in result.state_patch["claude-designer_skill_plan"]["selected_skills"]
    assert any(
        "control-plane design review checklist" in message.lower()
        for message in provider.system_messages
    )


def test_design_handler_generates_screen_driven_prototype_html():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    handlers = build_lifecycle_workflow_handlers("design")

    result = _invoke_handler(handlers["claude-designer"], "claude-designer", state)
    variant = result.state_patch["claude-designer_variant"]

    assert len(variant["prototype"]["screens"]) >= 3
    assert len(variant["prototype"]["flows"]) >= 1
    assert len(variant["prototype"]["app_shell"]["primary_navigation"]) >= 3
    assert 'data-prototype-kind="' in variant["preview_html"]
    assert 'class="preview-style-obsidian-atelier"' in variant["preview_html"]
    assert 'aria-label="主要ナビゲーション"' in variant["preview_html"]
    assert "<script>" in variant["preview_html"]
    assert 'role="tablist"' in variant["preview_html"]
    assert 'data-tab-target=' in variant["preview_html"]
    assert 'aria-label="承認フォーム"' in variant["preview_html"]
    assert 'aria-label="判断テーブル"' in variant["preview_html"]
    assert "制御室ビュー" in variant["preview_html"]
    assert "landing page" not in variant["preview_html"].lower()
    assert "Highlighted Capabilities" not in variant["preview_html"]
    assert "A precision" not in variant["preview_html"]
    assert "Open the approval gate" not in variant["preview_html"]
    assert "and checkpoints" not in variant["preview_html"]
    assert variant["decision_context_fingerprint"]
    assert variant["decision_scope"]["primary_use_case_ids"]
    assert variant["narrative"]["experience_thesis"]
    assert variant["narrative"]["signature_moments"]
    assert variant["implementation_brief"]["architecture_thesis"]
    assert variant["implementation_brief"]["technical_choices"]
    assert variant["prototype_spec"]["framework_target"] == "nextjs-app-router"
    assert variant["prototype_spec"]["routes"][0]["path"] == "/"
    assert variant["prototype_app"]["framework"] == "nextjs"
    assert variant["prototype_app"]["artifact_summary"]["file_count"] >= 7
    assert any(file["path"] == "app/page.tsx" for file in variant["prototype_app"]["files"])
    assert variant["display_language"] == "ja"
    assert variant["localized"]["prototype"]["screens"][0]["title"]
    assert variant["scorecard"]["dimensions"][0]["label"]
    assert variant["primary_workflows"][0]["goal"]
    assert variant["screen_specs"][0]["route_path"] == "/"
    assert variant["preview_meta"]["source"] == "template"
    assert variant["preview_meta"]["template_version"] >= 1
    assert variant["preview_meta"]["validation_ok"] is True
    assert variant["artifact_completeness"]["status"] == "complete"
    assert variant["freshness"]["status"] == "fresh"


def test_design_preview_theme_enforces_readable_text_tokens():
    meal_spec = (
        "# うちメニュー\n\n"
        "共働き家庭向けに、冷蔵庫在庫と家族の好みから3日分の献立と買い物リストを作るアプリ。"
    )
    screen_labels = ["今日の献立", "在庫登録", "買い物リスト", "家族設定"]

    light_variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="Gemini 3 Pro",
        pattern_name="うちメニュー — ギャラリー型献立オペレーション",
        description="明るい判断スタジオ。",
        primary="#f5f0e8",
        accent="#d4500a",
        selected_features=["在庫登録", "3日分献立", "買い物リスト"],
        spec=meal_spec,
        analysis={"design_tokens": {"colors": {"background": "#f8fafc", "text": "#f5f0e8"}}},
        prototype_overrides={
            "visual_style": "ivory-signal",
            "navigation_style": "top-nav",
            "screen_labels": screen_labels,
        },
    )
    dark_variant = _design_variant_payload(
        node_id="claude-designer",
        model_name="Claude Sonnet 4.6",
        pattern_name="うちメニュー — Obsidian Meal Command",
        description="暗色オペレーターシェル。",
        primary="#0d1117",
        accent="#4ade80",
        selected_features=["在庫登録", "3日分献立", "買い物リスト"],
        spec=meal_spec,
        analysis={"design_tokens": {"colors": {"background": "#0b1020", "text": "#0d1117"}}},
        prototype_overrides={
            "visual_style": "obsidian-atelier",
            "navigation_style": "sidebar",
            "screen_labels": screen_labels,
        },
    )

    assert "--text: #14213d" in light_variant["preview_html"]
    assert "--text: #f8fafc" in dark_variant["preview_html"]


def test_design_preview_meta_tracks_product_workspace_quality_signals():
    rich_preview = textwrap.dedent(
        """\
        <!doctype html>
        <html lang="ja">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
              body { font-family: sans-serif; }
              .shell { display: grid; grid-template-columns: 240px 1fr; }
              .cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
              @media (max-width: 768px) { .shell { grid-template-columns: 1fr; } }
            </style>
          </head>
          <body>
            <div class="shell">
              <nav aria-label="主要ナビゲーション">
                <button data-tab="workspace">実行台</button>
                <button data-tab="approval">承認ゲート</button>
                <button data-tab="lineage">系譜トレーサー</button>
                <button data-tab="recovery">復旧レーン</button>
              </nav>
              <main>
                <section data-screen-id="workspace" role="tabpanel">
                  <div class="cards">
                    <article>指標カード</article>
                    <article>状態カード</article>
                  </div>
                  <table aria-label="判断テーブル"><tr><td>根拠</td></tr></table>
                </section>
                <section data-screen-id="approval" role="tabpanel">
                  <form aria-label="承認フォーム">
                    <label>判定<input type="text" /></label>
                  </form>
                  <div>承認 / 根拠 / 差し戻し</div>
                </section>
                <section data-screen-id="lineage" role="tabpanel">成果物リネージと根拠</section>
                <section data-screen-id="recovery" role="tabpanel">劣化レーンの復旧</section>
              </main>
            </div>
            <script>
              document.querySelectorAll('[data-tab]').forEach((button) => {
                button.addEventListener('click', () => {});
              });
            </script>
          </body>
        </html>
        """
    )
    variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="KIMI K2.5",
        pattern_name="Signal Forge",
        description="判断を素早く通すプロダクトワークスペース。",
        primary="#0f172a",
        accent="#f97316",
        selected_features=["artifact lineage", "approval gate", "operator console"],
        spec="Operator-led lifecycle workspace",
        preview_html_override=rich_preview,
    )

    assert variant["preview_meta"]["source"] == "llm"
    assert variant["preview_meta"]["validation_ok"] is True
    assert variant["preview_meta"]["quality_score"] >= 0.8
    assert "table" in variant["preview_meta"]["surface_signals"]
    assert "form" in variant["preview_meta"]["surface_signals"]
    assert "approval" in variant["preview_meta"]["workflow_signals"]
    assert "lineage" in variant["preview_meta"]["workflow_signals"]
    assert "LLMプレビューで整合を確認" in variant["scorecard"]["summary"]
    assert [item["label"] for item in variant["scorecard"]["dimensions"]] == [
        "運用明快さ",
        "根拠追跡",
        "差し戻し耐性",
        "モバイル忠実度",
        "実装安定性",
        "アクセシビリティ",
    ]


def test_extract_html_document_recovers_json_wrapped_preview_html():
    payload = textwrap.dedent(
        """\
        {
          "preview_html": "<!DOCTYPE html><html lang=\\"ja\\"><head><meta charset=\\"utf-8\\" /><meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\" /></head><body><main data-screen-id=\\"workspace\\">判断台</main></body></html>"
        }
        """
    )

    extracted = _extract_html_document(payload)

    assert extracted.startswith("<!DOCTYPE html>")
    assert "<html lang=\"ja\">" in extracted
    assert "data-screen-id=\"workspace\"" in extracted


def test_extract_html_document_wraps_partial_workspace_fragment():
    fragment = textwrap.dedent(
        """\
        <style>.shell { display: grid; }</style>
        <nav aria-label="主要ナビゲーション"><button>実行台</button></nav>
        <main data-screen-id="workspace">
          <section>承認と根拠</section>
        </main>
        <script>window.__tabs = true;</script>
        """
    )

    extracted = _extract_html_document(fragment)

    assert extracted.startswith("<!doctype html>")
    assert "<meta charset=\"utf-8\"" in extracted
    assert "width=device-width, initial-scale=1" in extracted
    assert "<body>" in extracted
    assert "data-screen-id=\"workspace\"" in extracted


def test_design_variant_ranking_prefers_high_quality_llm_preview_when_scores_are_close():
    template_variant = _design_variant_payload(
        node_id="claude-designer",
        model_name="Claude Sonnet 4.6",
        pattern_name="Obsidian Control Atelier",
        description="暗い制御室ワークスペース。",
        primary="#101828",
        accent="#f59e0b",
        selected_features=["artifact lineage", "approval gate", "operator console"],
        spec="Operator-led lifecycle workspace",
    )
    llm_variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="KIMI K2.5",
        pattern_name="Signal Forge",
        description="判断と系譜を同時に追える運用ワークスペース。",
        primary="#0f172a",
        accent="#f97316",
        selected_features=["artifact lineage", "approval gate", "operator console"],
        spec="Operator-led lifecycle workspace",
        preview_html_override=(
            "<!doctype html><html lang='ja'><head><meta name='viewport' content='width=device-width, initial-scale=1' />"
            "<style>@media (max-width:768px){body{padding:8px}} .metric{display:grid}</style></head>"
            "<body><nav aria-label='主要ナビゲーション'></nav><section data-screen-id='a' role='tabpanel'></section>"
            "<section data-screen-id='b' role='tabpanel'><table aria-label='判断テーブル'></table></section>"
            "<section data-screen-id='c' role='tabpanel'><form aria-label='承認フォーム'></form></section>"
            "<section data-screen-id='d' role='tabpanel'>承認 根拠 成果物リネージ 復旧</section>"
            "<script>document.body.addEventListener('click',()=>{});</script></body></html>"
        ),
    )
    template_variant["scores"]["ux_quality"] = 0.93
    template_variant["preview_meta"]["quality_score"] = 0.61
    llm_variant["scores"]["ux_quality"] = 0.91

    ranked = _rank_design_variants([template_variant, llm_variant])

    assert ranked[0]["id"] == "gemini-designer"
    assert ranked[0]["selection_score"] > ranked[1]["selection_score"]


def test_design_judge_enrichment_populates_selected_rationale_and_approval_packet():
    variant = _design_variant_payload(
        node_id="claude-designer",
        model_name="Claude Sonnet 4.6",
        pattern_name="Obsidian Control Atelier",
        description="濃色の制御室型 operator workspace。",
        primary="#0f172a",
        accent="#f97316",
        selected_features=["approval gate", "artifact lineage"],
        spec="Operator-led lifecycle workspace",
    )

    enriched = lifecycle_orchestrator._apply_design_judge_enrichment(
        [variant],
        selected_design_id="claude-designer",
        payload={
            "winner_summary": "承認、根拠、差し戻しを一枚の判断面で扱えるため採用する。",
            "winner_reasons": [
                "承認理由と evidence が同じビューに残る。",
                "差し戻し時の復旧導線が preview と handoff の両方に現れている。",
            ],
            "winner_tradeoffs": ["高密度なため、視線誘導の質を落とせない。"],
            "approval_guardrails": [
                "visible UI に内部用語を残さない。",
                "主要操作のコントラストを下げない。",
            ],
        },
    )[0]

    assert enriched["selection_rationale"]["verdict"] == "selected"
    assert enriched["selection_rationale"]["summary"] == "承認、根拠、差し戻しを一枚の判断面で扱えるため採用する。"
    assert "承認理由と 根拠が同じビューに残る。" in enriched["selection_rationale"]["reasons"]
    assert "高密度なため、視線誘導の質を落とせない。" in enriched["selection_rationale"]["tradeoffs"]
    assert "画面上に内部用語を残さない。" in enriched["approval_packet"]["guardrails"]
    assert enriched["approval_packet"]["review_checklist"]


def test_provider_backed_design_handler_extracts_json_wrapped_preview_html():
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
              "delegations": [],
              "execution_note": "Focus on operator trust and artifact lineage."
            }
            """,
            """
            {
              "pattern_name": "Wrapped Preview Control Room",
              "description": "判断と系譜を同時に扱う運用 UI。",
              "primary_color": "#101828",
              "accent_color": "#f97316",
              "rationale": "系譜と承認を同じ画面で接続する。",
              "quality_focus": ["approval clarity", "artifact lineage"],
              "scores": {"ux_quality": 0.94, "accessibility": 0.92}
            }
            """,
            """
            {
              "pattern_name": "Wrapped Preview Control Room Rev 2",
              "description": "判断台と成果物系譜を並列に扱う運用シェル。",
              "primary_color": "#0f172a",
              "accent_color": "#fb923c",
              "rationale": "運用判断を速くする。",
              "quality_focus": ["approval clarity", "responsive density"],
              "scores": {"ux_quality": 0.96, "performance": 0.9, "accessibility": 0.95}
            }
            """,
            """
            {
              "preview_html": "<!DOCTYPE html><html lang=\\"ja\\"><head><meta charset=\\"utf-8\\" /><meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\" /><style>body{font-family:sans-serif}.shell{display:grid;grid-template-columns:240px 1fr}@media (max-width:768px){.shell{grid-template-columns:1fr}}</style></head><body><div class=\\"shell\\"><nav aria-label=\\"主要ナビゲーション\\"><button data-tab=\\"workspace\\">実行台</button><button data-tab=\\"approval\\">承認ゲート</button></nav><main><section data-screen-id=\\"workspace\\"><table aria-label=\\"判断テーブル\\"><tr><td>根拠</td></tr></table></section><section data-screen-id=\\"approval\\"><form aria-label=\\"承認フォーム\\"><label>判定<input type=\\"text\\" /></label></form><div>承認 / 根拠 / 成果物リネージ / 復旧</div></section><section data-screen-id=\\"lineage\\">成果物リネージ</section><section data-screen-id=\\"recovery\\">復旧レーン</section></main></div><script>document.querySelectorAll(\\\"[data-tab]\\\").forEach((button)=>button.addEventListener(\\\"click\\\",()=>{}));</script></body></html>"
            }
            """,
        ],
    )
    registry = ProviderRegistry({"anthropic": lambda model_id: provider})
    handlers = build_lifecycle_workflow_handlers("design", provider_registry=registry)

    result = _invoke_handler(handlers["claude-designer"], "claude-designer", state)
    variant = result.state_patch["claude-designer_variant"]

    assert variant["preview_meta"]["source"] == "llm"
    assert variant["preview_meta"]["extraction_ok"] is True
    assert "data-screen-id=\"workspace\"" in variant["preview_html"]
    assert "承認フォーム" in variant["preview_html"]
    assert len(result.llm_events) == 4


def test_design_preview_replaces_generic_consumer_placeholders_with_screen_specific_copy():
    meal_spec = (
        "# うちメニュー\n\n"
        "共働き家庭向けに、冷蔵庫在庫と家族の好みから3日分の献立と買い物リストを作るアプリ。"
    )
    screen_labels = ["今日の献立", "在庫登録", "買い物リスト", "家族設定"]

    prototype = _build_design_prototype(
        spec=meal_spec,
        analysis={},
        selected_features=["在庫登録", "3日分献立", "買い物リスト"],
        pattern_name="うちメニュー — ギャラリー型献立オペレーション",
        description="明るい判断スタジオ。",
        prototype_overrides={
            "visual_style": "ivory-signal",
            "navigation_style": "top-nav",
            "screen_labels": screen_labels,
        },
    )
    variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="Gemini 3 Pro",
        pattern_name="うちメニュー — ギャラリー型献立オペレーション",
        description="明るい判断スタジオ。",
        primary="#14213d",
        accent="#d4500a",
        selected_features=["在庫登録", "3日分献立", "買い物リスト"],
        spec=meal_spec,
        analysis={"design_tokens": {"colors": {"background": "#f8fafc", "text": "#14213d"}}},
        prototype_overrides={
            "visual_style": "ivory-signal",
            "navigation_style": "top-nav",
            "screen_labels": screen_labels,
        },
    )

    assert prototype["screens"][0]["headline"] == "3日分の献立を素早く決める"
    assert prototype["screens"][1]["primary_actions"][0] == "写真で登録する"
    assert prototype["flows"][0]["name"] == "今日の献立の初回導線"
    assert "guided onboarding" not in variant["preview_html"].lower()
    assert "first-run success" not in variant["preview_html"].lower()
    assert "主要 workflow" not in variant["preview_html"]
    assert "['" not in variant["preview_html"]


def test_operations_ivory_variant_keeps_alternate_screen_language_and_handoff_copy():
    spec = "Operator-led lifecycle workspace for governed approvals and artifact lineage."

    variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="KIMI K2.5 / Direction B",
        pattern_name="Ivory Signal Gallery",
        description="明るい判断室。",
        primary="#14213d",
        accent="#2563eb",
        selected_features=["approval gate", "artifact lineage"],
        spec=spec,
        analysis={"design_tokens": {"colors": {"background": "#f8fafc", "text": "#14213d"}}},
        prototype_overrides={
            "visual_style": "ivory-signal",
            "navigation_style": "top-nav",
            "screen_labels": ["フェーズワークスペース", "ラン台帳", "判断レビュー", "系譜タイムライン"],
        },
    )

    assert variant["screen_specs"][0]["title"] == "フェーズワークスペース"
    assert variant["screen_specs"][1]["title"] == "ラン台帳"
    assert variant["primary_workflows"][0]["name"] == "判断前提をそろえる"
    assert variant["selection_rationale"]["summary"] == "根拠確認と合意形成を穏やかな密度で進めやすく、レビュー負荷を下げられる。"
    assert variant["approval_packet"]["must_keep"][0] == "主要フロー「判断前提をそろえる」と承認判断を同じ文脈で往復できること。"


def test_design_override_normalization_preserves_product_screen_structure():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    overrides = _merge_prototype_overrides(
        {
            "prototype_kind": "decision-studio",
            "navigation_style": "top-nav",
            "density": "medium",
            "visual_style": "ivory-signal",
            "display_font": "Avenir Next",
            "body_font": "Hiragino Sans",
            "screen_labels": ["Phase Workspace", "Run Ledger", "Decision Review", "Release Readiness"],
        },
        _prototype_overrides_from_payload(
            {
                "prototype_kind": "application shell with decision-led product surfaces",
                "navigation_style": "hub-and-spoke with persistent left rail and contextual top bar",
                "density": "medium-high — gallery spacing in chrome, dense in data surfaces",
                "visual_style": (
                    "Luminous ivory canvas, architectural column grid, editorial typographic hierarchy, "
                    "amber operator signals, cobalt system state"
                ),
                "screen_labels": [
                    {
                        "id": "shell-lifecycle-workspace",
                        "label": "Lifecycle Workspace — Primary Shell",
                        "description": "The hub for operators.",
                    },
                    "{'id': 'screen-approval-gate', 'label': 'Approval Gate — Evidence Review', 'description': 'Focused review surface'}",
                    "Artifact Lineage — Trace View",
                ],
            }
        ),
    )

    prototype = _build_design_prototype(
        spec=str(state["spec"]),
        analysis=dict(state["analysis"]),
        selected_features=["artifact lineage", "approval gate"],
        pattern_name="Ivory Signal Gallery",
        description="Bright operator workspace.",
        prototype_overrides=overrides,
    )

    assert prototype["app_shell"]["layout"] == "sidebar"
    assert prototype["app_shell"]["density"] == "high"
    assert prototype["visual_direction"]["visual_style"] == "ivory-signal"
    assert prototype["screens"][0]["title"] == "フェーズワークスペース"
    assert prototype["screens"][1]["title"] == "ラン台帳"
    assert all("description" not in str(screen["title"]).lower() for screen in prototype["screens"][:3])
    assert all(not str(screen["title"]).startswith("{") for screen in prototype["screens"][:3])
    assert all("Evidence-to-build" not in str(screen) for screen in prototype["screens"])
    assert all("Product Platform Lead" not in str(screen) for screen in prototype["screens"])


def test_secondary_design_lane_prefers_kimi_class_model():
    assert _preferred_lifecycle_model("gemini-designer") == "moonshot/kimi-k2.5"


def test_design_variant_cost_estimate_changes_with_model_pricing():
    claude_variant = _design_variant_payload(
        node_id="claude-designer",
        model_name="Claude Sonnet 4.6",
        model_ref="anthropic/claude-sonnet-4-6",
        pattern_name="Obsidian Control Atelier",
        description="Dark operator shell.",
        primary="#111827",
        accent="#f59e0b",
        selected_features=["artifact lineage", "approval gate", "run ledger"],
        spec="Operator-led lifecycle workspace",
    )
    gemini_variant = _design_variant_payload(
        node_id="gemini-designer",
        model_name="Gemini 3 Pro",
        model_ref="google/gemini-3-pro-preview",
        pattern_name="Ivory Signal Gallery",
        description="Bright operator shell.",
        primary="#14213d",
        accent="#2563eb",
        selected_features=["artifact lineage", "approval gate", "run ledger"],
        spec="Operator-led lifecycle workspace",
    )

    assert claude_variant["tokens"] == gemini_variant["tokens"]
    assert claude_variant["cost_usd"] > gemini_variant["cost_usd"]


def test_design_sync_respects_provider_selected_design_id():
    project = default_lifecycle_project_record("orbit", tenant_id="default")
    run_state = {
        "variants": [
            {"id": "claude-designer", "pattern_name": "Calm Evidence", "scores": {"ux_quality": 0.81}},
            {"id": "gemini-designer", "pattern_name": "Decision Board", "scores": {"ux_quality": 0.88}},
        ],
        "selected_design_id": "gemini-designer",
        "design": {"variants": [], "selected_design_id": "gemini-designer"},
    }

    patch = sync_lifecycle_project_with_run(
        project,
        phase="design",
        run_record={"id": "run-design-1", "state": run_state, "execution_summary": {}},
        checkpoints=[],
    )

    assert patch["selectedDesignId"] == "gemini-designer"
    assert patch["designVariants"][1]["id"] == "gemini-designer"


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
    assert development["decision_context_fingerprint"]
    assert development["decision_scope"]["milestone_ids"]


def test_development_integrator_preserves_prototype_shell_in_build():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    design_handlers = build_lifecycle_workflow_handlers("design")
    design_result = _invoke_handler(design_handlers["claude-designer"], "claude-designer", state)
    selected_design = design_result.state_patch["claude-designer_variant"]
    selected_design.setdefault("prototype", {}).setdefault("screens", []).append(
        {
            "id": "login",
            "title": "Login",
            "headline": "Operator sign in",
            "purpose": "Authenticate the operator before promotion.",
            "primary_actions": ["Sign in"],
        }
    )
    selected_design.setdefault("prototype_spec", {}).setdefault("routes", []).append(
        {
            "path": "/login",
            "screen_id": "login",
            "title": "Login",
            "headline": "Operator sign in",
            "layout": "auth",
        }
    )
    selected_design.setdefault("screen_specs", []).append(
        {
            "id": "login",
            "title": "Login",
            "purpose": "Authenticate the operator before promotion.",
            "layout": "auth",
            "primary_actions": ["Sign in"],
            "route_path": "/login",
        }
    )
    state["selected_design"] = selected_design
    state["selectedDesignId"] = selected_design["id"]
    state["frontend_bundle"] = {
        "sections": [screen["id"] for screen in selected_design["prototype"]["screens"][:3]],
        "feature_cards": ["research workspace", "approval gate", "artifact lineage"],
        "interaction_notes": ["Preserve app navigation", "Keep evidence and action in the same viewport"],
    }
    state["backend_bundle"] = {
        "entities": [
            {"name": "LifecycleRun"},
            {"name": "ApprovalPacket"},
            {"name": "ArtifactRecord"},
        ]
    }
    state["milestones"] = [
        {"id": "ms-alpha", "name": "Evidence loop", "criteria": "artifact lineage approval gate"},
        {"id": "ms-beta", "name": "Operator clarity", "criteria": "primary navigation and screen surfaces"},
    ]

    result = _development_integrator_handler("integrator", state)
    integrated = result.state_patch["integrated_build"]
    code = integrated["code"]

    assert integrated["prototype"]["screens"]
    assert 'data-prototype-kind="' in code
    assert 'aria-label="主要ナビゲーション"' in code
    assert 'data-screen-id="' in code
    assert "マイルストーン準備" in code
    assert "Highlighted Capabilities" not in code
    assert integrated["decision_context_fingerprint"]
    assert integrated["decision_scope"]["selected_design_id"] == selected_design["id"]


def test_development_integrator_refines_delivery_plan_code_workspace():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    design_handlers = build_lifecycle_workflow_handlers("design")
    design_result = _invoke_handler(design_handlers["claude-designer"], "claude-designer", state)
    selected_design = design_result.state_patch["claude-designer_variant"]
    selected_design.setdefault("prototype", {}).setdefault("screens", []).append(
        {
            "id": "login",
            "title": "Login",
            "headline": "Operator sign in",
            "purpose": "Authenticate the operator before promotion.",
            "primary_actions": ["Sign in"],
        }
    )
    selected_design.setdefault("prototype_spec", {}).setdefault("routes", []).append(
        {
            "path": "/login",
            "screen_id": "login",
            "title": "Login",
            "headline": "Operator sign in",
            "layout": "auth",
        }
    )
    selected_design.setdefault("screen_specs", []).append(
        {
            "id": "login",
            "title": "Login",
            "purpose": "Authenticate the operator before promotion.",
            "layout": "auth",
            "primary_actions": ["Sign in"],
            "route_path": "/login",
        }
    )
    state["selected_design"] = selected_design
    state["selectedDesignId"] = selected_design["id"]
    state["features"] = [
        {
            "id": "feature-approval-packet",
            "feature": "governed approval packet",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]
    state["requirements"] = {
        "requirements": [
            {
                "id": "REQ-1",
                "statement": "The system shall let authorized operators keep approval rationale tied to the governed approval packet.",
                "acceptanceCriteria": ["Authorized operators can capture rationale before promote after signing in."],
            }
        ]
    }
    state["taskDecomposition"] = {
        "tasks": [
            {
                "id": "TASK-1",
                "title": "Implement governed approval packet",
                "description": "Show lane blockers, sign-in/session state, and rationale form in the same workspace.",
            }
        ]
    }
    state["analysis"] = {
        "personas": [
            {
                "name": "Operator",
                "role": "Release owner",
                "context": "Governed lifecycle workspace",
                "goals": ["Approve safely"],
                "frustrations": ["Missing rationale"],
            }
        ],
        "job_stories": [
            {
                "title": "When release evidence is ready, I want to approve from one governed workspace.",
                "situation": "When release evidence is ready",
                "motivation": "approve from one governed workspace",
                "outcome": "so I can promote safely",
                "priority": "core",
                "related_features": ["governed approval packet"],
            }
        ],
        "user_journeys": [
            {
                "persona_name": "Operator",
                "touchpoints": [
                    {
                        "phase": "usage",
                        "action": "Review packet",
                        "touchpoint": "Approval workspace",
                        "emotion": "neutral",
                        "pain_point": "Rationale is fragmented",
                    }
                ],
            }
        ],
        "ia_analysis": {
            "navigation_model": "hierarchical",
            "site_map": [{"id": "approval", "label": "Approval", "priority": "primary"}],
            "key_paths": [{"name": "Approval review", "steps": ["Open packet", "Review rationale", "Approve"]}],
        },
        "kano_features": [{"feature": "governed approval packet", "category": "must-be"}],
        "kill_criteria": ["Approval review cannot be verified before promotion."],
        "roles": [
            {
                "name": "Operator",
                "permissions": ["approval:write", "release:promote"],
                "responsibilities": ["Review rationale", "Promote validated releases"],
            }
        ],
        "design_tokens": {
            "style": {
                "name": "Operator Studio",
                "best_for": "governed lifecycle workspaces",
                "accessibility": "high contrast with durable focus order",
            },
            "colors": {
                "primary": "#0f172a",
                "secondary": "#1e293b",
                "cta": "#10b981",
                "background": "#f8fafc",
                "text": "#0f172a",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
            },
            "effects": ["Approval and blocker states preserve explicit focus feedback."],
        },
    }
    state["technicalDesign"] = {
        "apiSpecification": [
            {
                "method": "GET",
                "path": "/api/control-plane",
                "description": "Read the delivery control plane.",
                "authRequired": True,
            }
        ],
        "interfaceDefinitions": [
            {
                "name": "ApprovalPacket",
                "properties": [{"name": "id", "type": "string"}],
            }
        ],
    }
    state["dcsAnalysis"] = {"qualityGates": []}
    state["reverseEngineering"] = {}
    state["frontend_bundle"] = {
        "sections": [screen["id"] for screen in selected_design["prototype"]["screens"][:3]],
        "feature_cards": ["research workspace", "approval gate", "artifact lineage"],
        "interaction_notes": ["Keep evidence and approval rationale in the same viewport."],
    }
    state["backend_bundle"] = {
        "entities": [
            {"name": "LifecycleRun", "fields": ["id", "status"]},
            {"name": "ApprovalPacket", "fields": ["id", "rationale", "status"]},
        ],
        "api_endpoints": [
            {"method": "GET", "path": "/api/control-plane", "description": "Read control plane", "authRequired": True}
        ],
        "automation_notes": ["Persist approval rationale before promotion."],
    }
    state["milestones"] = [
        {"id": "ms-alpha", "name": "Evidence loop", "criteria": "artifact lineage approval gate"},
        {"id": "ms-beta", "name": "Operator clarity", "criteria": "primary navigation and screen surfaces"},
    ]
    value_contract = build_value_contract(
        {
            "spec": state["spec"],
            "analysis": state["analysis"],
            "features": state["features"],
            "milestones": state["milestones"],
        }
    )
    outcome_telemetry_contract = build_outcome_telemetry_contract(
        {
            "spec": state["spec"],
            "analysis": state["analysis"],
            "features": state["features"],
            "milestones": state["milestones"],
            "valueContract": value_contract,
        },
        value_contract=value_contract,
    )
    state["valueContract"] = value_contract
    state["outcomeTelemetryContract"] = outcome_telemetry_contract
    state["delivery_plan"] = {
        "goal_spec": {
            "selected_features": ["approval gate", "artifact lineage"],
            "contract_injection": list(REQUIRED_DELIVERY_CONTRACT_IDS),
        },
        "dependency_analysis": {
            "work_packages": [{"id": "TASK-1", "lane": "backend-builder"}],
            "edges": [],
            "component_edges": [],
            "unknown_dependencies": [],
            "has_cycles": False,
            "wave_count": 1,
        },
        "work_packages": [
            {
                "id": "TASK-1",
                "title": "Implement governed approval packet",
                "lane": "backend-builder",
                "depends_on": [],
                "deliverables": ["control-plane route"],
                "acceptance_criteria": ["Rationale is persisted before promotion."],
                "status": "planned",
                "is_critical": True,
            }
        ],
        "waves": [
            {
                "wave_index": 0,
                "work_unit_ids": ["TASK-1"],
                "lane_ids": ["backend-builder"],
                "entry_criteria": ["Approved context is injected."],
                "exit_criteria": ["WU checks pass."],
            }
        ],
        "wave_count": 1,
        "work_unit_contracts": [
            {
                "id": "wu-task-1",
                "work_package_id": "TASK-1",
                "title": "Implement governed approval packet",
                "lane": "backend-builder",
                "wave_index": 0,
                "depends_on": [],
                "acceptance_criteria": ["Rationale is persisted before promotion."],
                "qa_checks": ["Rationale is persisted before promotion."],
                "security_checks": ["Protected API paths keep authRequired truth."],
                "required_contracts": list(REQUIRED_DELIVERY_CONTRACT_IDS),
                "value_targets": [
                    {"metric_id": value_contract["success_metrics"][0]["id"], "metric_name": value_contract["success_metrics"][0]["name"]}
                ],
                "telemetry_events": [
                    {
                        "id": outcome_telemetry_contract["telemetry_events"][0]["id"],
                        "name": outcome_telemetry_contract["telemetry_events"][0]["name"],
                    }
                ],
                "repair_policy": {"qa_failure": "retry_same_work_unit"},
            }
        ],
        "shift_left_plan": {
            "mode": "work_unit_micro_loop",
            "principles": ["Builder/QA/security loop locally."],
        },
        "critical_path": ["TASK-1"],
        "merge_strategy": {"conflict_prevention": ["Shared route bindings merge through integrator."]},
        "value_contract": value_contract,
        "outcome_telemetry_contract": outcome_telemetry_contract,
        "code_workspace": build_development_code_workspace(
            spec=str(state["spec"]),
            selected_features=["approval gate", "artifact lineage"],
            selected_design=selected_design,
            requirements=state["requirements"],
            task_decomposition=state["taskDecomposition"],
            technical_design=state["technicalDesign"],
            reverse_engineering=state["reverseEngineering"],
            planning_analysis=state["analysis"],
            milestones=state["milestones"],
            goal_spec={
                "selected_features": ["approval gate", "artifact lineage"],
                "contract_injection": list(REQUIRED_DELIVERY_CONTRACT_IDS),
            },
            dependency_analysis={
                "work_packages": [{"id": "TASK-1", "lane": "backend-builder"}],
                "edges": [],
                "component_edges": [],
                "unknown_dependencies": [],
                "has_cycles": False,
                "wave_count": 1,
            },
            work_unit_contracts=[
                {
                    "id": "wu-task-1",
                    "work_package_id": "TASK-1",
                    "title": "Implement governed approval packet",
                    "lane": "backend-builder",
                    "wave_index": 0,
                    "depends_on": [],
                    "acceptance_criteria": ["Rationale is persisted before promotion."],
                    "qa_checks": ["Rationale is persisted before promotion."],
                    "security_checks": ["Protected API paths keep authRequired truth."],
                    "required_contracts": list(REQUIRED_DELIVERY_CONTRACT_IDS),
                    "value_targets": [
                        {"metric_id": value_contract["success_metrics"][0]["id"], "metric_name": value_contract["success_metrics"][0]["name"]}
                    ],
                    "telemetry_events": [
                        {
                            "id": outcome_telemetry_contract["telemetry_events"][0]["id"],
                            "name": outcome_telemetry_contract["telemetry_events"][0]["name"],
                        }
                    ],
                    "repair_policy": {"qa_failure": "retry_same_work_unit"},
                }
            ],
            waves=[
                {
                    "wave_index": 0,
                    "work_unit_ids": ["TASK-1"],
                    "lane_ids": ["backend-builder"],
                    "entry_criteria": ["Approved context is injected."],
                    "exit_criteria": ["WU checks pass."],
                }
            ],
            critical_path=["TASK-1"],
            shift_left_plan={
                "mode": "work_unit_micro_loop",
                "principles": ["Builder/QA/security loop locally."],
            },
            value_contract=value_contract,
            outcome_telemetry_contract=outcome_telemetry_contract,
        ),
        "spec_audit": {"status": "ready_for_autonomous_build", "unresolved_gaps": []},
    }

    result = _development_integrator_handler("integrator", state)

    updated_plan = result.state_patch["delivery_plan"]
    files = {item["path"]: item for item in updated_plan["code_workspace"]["files"]}

    assert "app/lib/control-plane-data.ts" in files
    assert "app/lib/design-tokens.ts" in files
    assert "app/lib/development-standards.ts" in files
    assert "app/lib/work-unit-contracts.ts" in files
    assert "server/contracts/access-policy.ts" in files
    assert "server/contracts/audit-events.ts" in files
    assert "tests/acceptance/control-plane.spec.ts" in files
    assert "docs/spec/work-unit-contracts.md" in files
    assert "docs/spec/delivery-waves.md" in files
    assert "/api/control-plane" in files["server/contracts/api-contract.ts"]["content"]
    assert updated_plan["spec_audit"]["status"] == "ready_for_autonomous_build"


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
