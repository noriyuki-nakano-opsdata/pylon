"""Regression tests for lifecycle orchestration semantics and state propagation."""

import asyncio
import inspect
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path

import pylon.lifecycle.orchestrator as lifecycle_orchestrator
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.orchestrator import (
    _development_integrator_handler,
    _infer_product_kind,
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
    assert meta["degradation_reasons"] == ["llm_response_repaired"]
    assert [item["stage"] for item in llm_events if "stage" in item] == ["strict", "repair"]


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
    assert provider._responses == ['{"judge_summary":"should not be used"}']


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
    assert variant["prototype"]["screens"]
    assert variant["prototype"]["flows"]
    assert 'aria-label="Primary navigation"' in variant["preview_html"]
    assert 'data-screen-id=' in variant["preview_html"]
    assert "Highlighted Capabilities" not in variant["preview_html"]


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
    assert 'aria-label="Primary navigation"' in variant["preview_html"]
    assert "landing page" not in variant["preview_html"].lower()
    assert "Highlighted Capabilities" not in variant["preview_html"]


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


def test_development_integrator_preserves_prototype_shell_in_build():
    state = _planning_state(
        "Autonomous multi-agent lifecycle platform for operator-led research, "
        "approvals, artifact lineage, and governed delivery."
    )
    design_handlers = build_lifecycle_workflow_handlers("design")
    design_result = _invoke_handler(design_handlers["claude-designer"], "claude-designer", state)
    selected_design = design_result.state_patch["claude-designer_variant"]
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
    assert 'aria-label="Primary navigation"' in code
    assert 'data-screen-id="' in code
    assert "Milestone Readiness" in code
    assert "Highlighted Capabilities" not in code


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
