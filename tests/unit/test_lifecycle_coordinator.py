"""Tests for lifecycle contracts and autonomous coordination."""

import asyncio
import inspect
from unittest.mock import patch

from pylon.approval.types import compute_approval_binding_hash
from pylon.lifecycle.contracts import (
    build_phase_contracts,
    lifecycle_phase_input,
)
from pylon.lifecycle.coordinator import (
    build_lifecycle_approval_binding,
    build_lifecycle_autonomy_projection,
    derive_lifecycle_next_action,
    lifecycle_action_execution_budget,
    resolve_lifecycle_governance_mode,
    resolve_lifecycle_orchestration_mode,
)
from pylon.lifecycle.operator_console import sync_lifecycle_project_with_run
from pylon.lifecycle.runtime_projection import lifecycle_phase_runtime_summary
from pylon.lifecycle.services.decision_context import build_lifecycle_decision_context
from pylon.lifecycle.services.value_contracts import (
    REQUIRED_DELIVERY_CONTRACT_IDS,
    build_outcome_telemetry_contract,
    build_value_contract,
)
from pylon.lifecycle.orchestrator import (
    _build_development_handoff,
    _development_planner_handler,
    _development_repo_executor_handler,
    _development_reviewer_handler,
    _design_evaluator_handler,
    _design_variant_handler,
    build_lifecycle_workflow_definition,
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


def _with_development_contracts(analysis: dict[str, object] | None) -> dict[str, object]:
    payload = dict(analysis or {})
    payload.setdefault(
        "roles",
        [
            {
                "name": "Operator",
                "responsibilities": ["review approval packets", "approve delivery"],
                "permissions": ["approve_delivery", "view_lineage"],
                "related_actors": ["Lifecycle Operator"],
            }
        ],
    )
    payload.setdefault(
        "design_tokens",
        {
            "style": {
                "name": "Operator Studio",
                "keywords": ["structured", "high-contrast"],
                "best_for": "operator workspaces",
                "performance": "lightweight transitions",
                "accessibility": "strong contrast and focus rings",
            },
            "colors": {
                "primary": "#2563eb",
                "secondary": "#0f172a",
                "cta": "#f97316",
                "background": "#f8fafc",
                "text": "#0f172a",
                "notes": "approval actions stay warm and visible",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["governed", "precise"],
            },
            "effects": [
                "approval actions use restrained hover elevation",
                "state changes fade with explicit focus retention",
            ],
            "anti_patterns": ["avoid decorative motion"],
            "rationale": "Keep approval work visible and calm.",
        },
    )
    return payload


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
    patch = sync_lifecycle_project_with_run(
        project,
        phase="planning",
        run_record={"id": "run-planning", "state": state, "execution_summary": {}},
        checkpoints=[],
    )
    patch["analysis"] = _with_development_contracts(dict(patch.get("analysis") or {}))
    contract_project = _project()
    contract_project["spec"] = spec
    contract_project["research"] = state["research"]
    contract_project["analysis"] = patch["analysis"]
    contract_project["features"] = patch["features"]
    contract_project["milestones"] = patch["milestones"]
    value_contract = build_value_contract(contract_project)
    patch["valueContract"] = value_contract
    patch["outcomeTelemetryContract"] = build_outcome_telemetry_contract(
        contract_project,
        value_contract=value_contract,
    )
    return patch


def _design_patch(spec: str) -> dict[str, object]:
    planning_patch = _planning_patch(spec)
    state: dict[str, object] = {
        "spec": spec,
        "analysis": planning_patch["analysis"],
        "features": planning_patch["features"],
    }
    state.update(_design_variant_handler("Claude", "Minimal", "Calm", "#0f172a", "#f97316")("claude-designer", state).state_patch)
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


def _native_development_artifacts() -> dict[str, object]:
    return {
        "requirements": {
            "requirements": [
                {
                    "id": "REQ-1",
                    "pattern": "ubiquitous",
                    "statement": "The system shall let authorized operators review approval packets and trigger autonomous delivery safely.",
                    "confidence": 0.9,
                    "sourceClaimIds": ["claim-1"],
                    "userStoryIds": ["story-1"],
                    "acceptanceCriteria": [
                        "Authorized operators can inspect the approval packet before approving delivery.",
                    ],
                }
            ],
            "userStories": [{"id": "story-1", "title": "Operator approval", "description": "Approve delivery safely within an explicit authorization boundary."}],
            "acceptanceCriteria": [{"id": "ac-1", "requirementId": "REQ-1", "criterion": "Approval packet is visible before delivery starts and authorization boundaries are enforced."}],
            "confidenceDistribution": {"high": 1, "medium": 0, "low": 0},
            "completenessScore": 0.92,
            "traceabilityIndex": {"REQ-1": ["claim-1"]},
        },
        "requirementsConfig": {"earsEnabled": True, "interactiveClarification": True, "confidenceFloor": 0.6},
        "taskDecomposition": {
            "tasks": [
                {
                    "id": "TASK-1",
                    "title": "Implement approval delivery workspace",
                    "description": "Build the access-controlled approval delivery workspace and operator shell.",
                    "phase": "development",
                    "milestoneId": "ms-alpha",
                    "dependsOn": [],
                    "effortHours": 16,
                    "priority": "must",
                    "featureId": "feature-1",
                    "requirementId": "REQ-1",
                }
            ],
            "dagEdges": [],
            "phaseMilestones": [{"phase": "development", "milestoneIds": ["ms-alpha"], "taskCount": 1, "totalHours": 16, "durationDays": 3}],
            "totalEffortHours": 16,
            "criticalPath": ["TASK-1"],
            "effortByPhase": {"development": 16},
            "hasCycles": False,
        },
        "dcsAnalysis": {
            "rubberDuckPrd": None,
            "edgeCases": {"edgeCases": [], "riskMatrix": {}, "coverageScore": 0.8},
            "impactAnalysis": {"layers": [], "blastRadius": 1, "criticalPathsAffected": ["approval"]},
            "sequenceDiagrams": {"diagrams": [{"id": "seq-1", "title": "Approval flow", "mermaidCode": "sequenceDiagram\nA->>B: ok", "flowType": "core"}]},
            "stateTransitions": {"states": [{"id": "s1", "name": "Ready", "description": "ready"}], "transitions": [], "riskStates": [], "mermaidCode": "stateDiagram-v2\n[*] --> Ready"},
        },
        "technicalDesign": {
            "architecture": {"style": "nextjs + typed contracts"},
            "dataflowMermaid": "flowchart LR\nUI-->API",
            "apiSpecification": [{"method": "POST", "path": "/api/approval/decision", "description": "Approve delivery", "authRequired": True}],
            "databaseSchema": [{"name": "approval_decisions", "columns": [{"name": "id", "type": "uuid", "primaryKey": True}], "indexes": ["approval_decisions_pkey"]}],
            "interfaceDefinitions": [{"name": "ApprovalDecision", "properties": [{"name": "id", "type": "string"}], "extends": []}],
            "componentDependencyGraph": {"shell": ["approval-panel"]},
        },
        "reverseEngineering": {
            "extractedRequirements": [],
            "architectureDoc": {},
            "dataflowMermaid": "flowchart LR\nUI-->API",
            "apiEndpoints": [{"method": "POST", "path": "/api/approval/decision", "handler": "approveDecision", "filePath": "server/api/approval.ts"}],
            "databaseSchema": [{"name": "approval_decisions", "columns": [], "source": "schema.sql"}],
            "interfaces": [{"name": "ApprovalDecision", "kind": "interface", "properties": [], "filePath": "server/contracts/api-contract.ts"}],
            "taskStructure": [],
            "testSpecs": [],
            "coverageScore": 0.82,
            "languagesDetected": ["typescript"],
            "sourceType": "prototype_app",
        },
    }


def _development_patch(spec: str) -> dict[str, object]:
    planning_patch = _planning_patch(spec)
    design_patch = _design_patch(spec)
    fingerprint_project = _project()
    fingerprint_project["spec"] = spec
    fingerprint_project.update(_research_patch(spec))
    fingerprint_project.update(planning_patch)
    fingerprint_project.update(design_patch)
    fingerprint_project.update(_native_development_artifacts())
    value_contract = build_value_contract(fingerprint_project)
    outcome_telemetry_contract = build_outcome_telemetry_contract(
        fingerprint_project,
        value_contract=value_contract,
    )
    decision_context_fingerprint = str(
        build_lifecycle_decision_context(
            fingerprint_project,
            target_language="ja",
            compact=True,
        ).get("fingerprint")
        or ""
    )
    topology_fingerprint = f"topology-{decision_context_fingerprint[:12]}"
    runtime_graph_fingerprint = f"runtime-{decision_context_fingerprint[:12]}"
    selected_design = next(
        (
            variant
            for variant in design_patch["designVariants"]
            if variant["id"] == design_patch["selectedDesignId"]
        ),
        design_patch["designVariants"][0],
    )
    return {
        "buildCode": (
            "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /></head>"
            "<body data-prototype-kind=\"build\"><nav aria-label=\"主要ナビゲーション\"></nav>"
            "<main><section data-screen-id=\"workspace\"></section><section data-screen-id=\"approval\"></section></main></body></html>"
        ),
        "buildCost": 1.2,
        "buildIteration": 1,
        "milestoneResults": [
            {"id": "ms-alpha", "name": "Alpha", "status": "satisfied"},
            {"id": "ms-beta", "name": "Beta", "status": "satisfied"},
        ],
        "deliveryPlan": {
            "execution_mode": "autonomous_repo_delivery",
            "topology_mode": "work_unit_wave_mesh",
            "summary": "Dependency-aware delivery graph",
            "selected_preset": "standard",
            "source_plan_preset": "standard",
            "success_definition": "Selected design is implemented and ready for deploy handoff.",
            "decision_context_fingerprint": decision_context_fingerprint,
            "topology_fingerprint": topology_fingerprint,
            "runtime_graph_fingerprint": runtime_graph_fingerprint,
            "goal_spec": {
                "selected_features": ["approval delivery workspace"],
                "contract_injection": list(REQUIRED_DELIVERY_CONTRACT_IDS),
            },
            "work_packages": [
                {
                    "id": "wp-1",
                    "title": "UI shell",
                    "lane": "frontend-builder",
                    "summary": "Build the operator workspace shell",
                    "depends_on": [],
                    "start_day": 0,
                    "duration_days": 2,
                    "deliverables": ["UI shell"],
                    "acceptance_criteria": ["primary navigation and screen surfaces"],
                    "owned_surfaces": ["workspace shell"],
                    "status": "completed",
                    "is_critical": True,
                }
            ],
            "dependency_analysis": {
                "work_packages": [{"id": "wp-1", "lane": "frontend-builder"}],
                "edges": [],
                "component_edges": [],
                "unknown_dependencies": [],
                "has_cycles": False,
                "wave_count": 1,
            },
            "waves": [
                {
                    "wave_index": 0,
                    "work_unit_ids": ["wp-1"],
                    "lane_ids": ["frontend-builder"],
                    "entry_criteria": ["Approved context is injected before coding begins."],
                    "exit_criteria": ["Each work unit clears embedded QA and security checks."],
                }
            ],
            "wave_count": 1,
            "work_unit_contracts": [
                {
                    "id": "wu-wp-1",
                    "work_package_id": "wp-1",
                    "title": "UI shell",
                    "lane": "frontend-builder",
                    "wave_index": 0,
                    "depends_on": [],
                    "acceptance_criteria": ["primary navigation and screen surfaces"],
                    "qa_checks": ["primary navigation and screen surfaces"],
                    "security_checks": ["Avoid unsafe DOM and permission regressions in this work unit."],
                    "required_contracts": list(REQUIRED_DELIVERY_CONTRACT_IDS),
                    "value_targets": [
                        {
                            "metric_id": value_contract["success_metrics"][0]["id"],
                            "metric_name": value_contract["success_metrics"][0]["name"],
                        }
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
            "lanes": [
                {
                    "agent": "frontend-builder",
                    "label": "Frontend Builder",
                    "remit": "UI shell",
                    "skills": ["responsive-ui"],
                    "owned_surfaces": ["workspace shell"],
                    "conflict_guards": ["UI shell is owned by frontend-builder"],
                    "merge_order": 1,
                }
            ],
            "critical_path": ["wp-1"],
            "gantt": [
                {
                    "work_package_id": "wp-1",
                    "lane": "frontend-builder",
                    "start_day": 0,
                    "duration_days": 2,
                    "depends_on": [],
                    "is_critical": True,
                }
            ],
            "merge_strategy": {
                "integration_order": ["wp-1"],
                "conflict_prevention": ["Shared shell changes route through integrator"],
                "shared_touchpoints": ["approval gate"],
            },
            "value_contract": value_contract,
            "outcome_telemetry_contract": outcome_telemetry_contract,
            "spec_audit": {
                "status": "ready_for_autonomous_build",
                "completeness_score": 0.95,
                "requirements_count": 1,
                "task_count": 1,
                "api_surface_count": 1,
                "database_table_count": 1,
                "interface_count": 1,
                "route_binding_count": 1,
                "workspace_file_count": 3,
                "behavior_gate_count": 1,
                "feature_coverage": [],
                "unresolved_gaps": [],
                "closing_actions": [],
            },
            "code_workspace": {
                "framework": "nextjs",
                "router": "app",
                "preview_entry": "/",
                "entrypoints": ["app/page.tsx"],
                "install_command": "npm install",
                "dev_command": "npm run dev",
                "build_command": "npm run build",
                "package_tree": [
                    {"id": "app-routes", "label": "App Routes", "path": "app", "lane": "frontend-builder", "kind": "generated", "file_count": 4},
                    {"id": "app-lib", "label": "App Libraries", "path": "app/lib", "lane": "frontend-builder", "kind": "generated", "file_count": 2},
                    {"id": "server-contracts", "label": "Server Contracts", "path": "server/contracts", "lane": "backend-builder", "kind": "generated", "file_count": 3},
                    {"id": "docs", "label": "Specification Docs", "path": "docs", "lane": "reviewer", "kind": "generated", "file_count": 4},
                ],
                "files": [
                    {
                        "path": "app/page.tsx",
                        "kind": "tsx",
                        "package_id": "app-routes",
                        "package_label": "App Routes",
                        "package_path": "app",
                        "lane": "frontend-builder",
                        "route_paths": ["/"],
                        "entrypoint": True,
                        "generated_from": "prototype_app",
                        "line_count": 12,
                        "content_preview": "export default function Page() {}",
                        "content": "export default function Page() {}",
                    }
                    ,
                    {
                        "path": "app/globals.css",
                        "kind": "css",
                        "package_id": "app-routes",
                        "package_label": "App Routes",
                        "package_path": "app",
                        "lane": "frontend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 8,
                        "content_preview": ":root { --color-brand-primary: #0f172a; }",
                        "content": "/* Autonomous delivery design token contract */\n:root { --color-brand-primary: #0f172a; --font-heading: \"IBM Plex Sans\"; }\n",
                    },
                    {
                        "path": "app/lib/design-tokens.ts",
                        "kind": "ts",
                        "package_id": "app-lib",
                        "package_label": "App Libraries",
                        "package_path": "app/lib",
                        "lane": "frontend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 6,
                        "content_preview": "export const designTokenContract",
                        "content": "export const designTokenContract = { colors: { primary: \"#0f172a\" } } as const;\n",
                    },
                    {
                        "path": "app/lib/development-standards.ts",
                        "kind": "ts",
                        "package_id": "app-lib",
                        "package_label": "App Libraries",
                        "package_path": "app/lib",
                        "lane": "frontend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 8,
                        "content_preview": "export const developmentStandards",
                        "content": "export const developmentStandards = { coding_rules: [\"Use shared standards\"] } as const;\n",
                    },
                    {
                        "path": "app/lib/value-contract.ts",
                        "kind": "ts",
                        "package_id": "app-lib",
                        "package_label": "App Libraries",
                        "package_path": "app/lib",
                        "lane": "frontend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 8,
                        "content_preview": "export const valueContract",
                        "content": "export const valueContract = { summary: \"value contract\" } as const;\n",
                    },
                    {
                        "path": "app/lib/work-unit-contracts.ts",
                        "kind": "ts",
                        "package_id": "app-lib",
                        "package_label": "App Libraries",
                        "package_path": "app/lib",
                        "lane": "frontend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 12,
                        "content_preview": "export const deliveryExecutionPlan",
                        "content": "export const deliveryExecutionPlan = { waves: [{ waveIndex: 0 }], workUnitContracts: [{ id: \"wu-wp-1\" }] } as const;\n",
                    },
                    {
                        "path": "server/contracts/access-policy.ts",
                        "kind": "ts",
                        "package_id": "server-contracts",
                        "package_label": "Server Contracts",
                        "package_path": "server/contracts",
                        "lane": "backend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 6,
                        "content_preview": "export const accessPolicy",
                        "content": "export const accessPolicy = { roles: [{ name: \"Operator\", permissions: [\"release:promote\"] }] } as const;\n",
                    },
                    {
                        "path": "server/contracts/audit-events.ts",
                        "kind": "ts",
                        "package_id": "server-contracts",
                        "package_label": "Server Contracts",
                        "package_path": "server/contracts",
                        "lane": "backend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 6,
                        "content_preview": "export const auditEvents",
                        "content": "export const auditEvents = [{ name: \"release.promote\", signal: \"promotion\" }] as const;\n",
                    },
                    {
                        "path": "server/contracts/outcome-telemetry.ts",
                        "kind": "ts",
                        "package_id": "server-contracts",
                        "package_label": "Server Contracts",
                        "package_path": "server/contracts",
                        "lane": "backend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 6,
                        "content_preview": "export const outcomeTelemetryContract",
                        "content": "export const outcomeTelemetryContract = { summary: \"telemetry contract\" } as const;\n",
                    },
                    {
                        "path": "server/contracts/api-contract.ts",
                        "kind": "ts",
                        "package_id": "server-contracts",
                        "package_label": "Server Contracts",
                        "package_path": "server/contracts",
                        "lane": "backend-builder",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "technical_design",
                        "line_count": 6,
                        "content_preview": "export const apiSpecification",
                        "content": "export const apiSpecification = [{ method: \"POST\", path: \"/api/approval/decision\", authRequired: true }] as const;\n",
                    },
                    {
                        "path": "docs/spec/design-system.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 4,
                        "content_preview": "# Design System Contract",
                        "content": "# Design System Contract\n",
                    },
                    {
                        "path": "docs/spec/development-standards.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 4,
                        "content_preview": "# Development Standards",
                        "content": "# Development Standards\n",
                    },
                    {
                        "path": "docs/spec/value-contract.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 4,
                        "content_preview": "# Value Contract",
                        "content": "# Value Contract\n",
                    },
                    {
                        "path": "docs/spec/work-unit-contracts.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 6,
                        "content_preview": "# Work Unit Contracts",
                        "content": "# Work Unit Contracts\n",
                    },
                    {
                        "path": "docs/spec/delivery-waves.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 8,
                        "content_preview": "# Delivery Waves",
                        "content": "# Delivery Waves\n",
                    },
                    {
                        "path": "docs/spec/access-control.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 4,
                        "content_preview": "# Access Control Contract",
                        "content": "# Access Control Contract\n",
                    },
                    {
                        "path": "docs/spec/operability.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "delivery_plan",
                        "line_count": 4,
                        "content_preview": "# Operability Contract",
                        "content": "# Operability Contract\n",
                    },
                    {
                        "path": "docs/spec/outcome-telemetry.md",
                        "kind": "md",
                        "package_id": "docs",
                        "package_label": "Specification Docs",
                        "package_path": "docs",
                        "lane": "reviewer",
                        "route_paths": [],
                        "entrypoint": False,
                        "generated_from": "planning_analysis",
                        "line_count": 4,
                        "content_preview": "# Outcome Telemetry Contract",
                        "content": "# Outcome Telemetry Contract\n",
                    },
                ],
                "package_graph": [],
                "route_bindings": [{"route_path": "/", "screen_id": "workspace", "file_paths": ["app/page.tsx"]}],
                "artifact_summary": {"package_count": 4, "file_count": 17, "route_binding_count": 1, "entrypoint_count": 1},
            },
            "repo_execution": {
                "mode": "temp_workspace",
                "workspace_path": "/tmp/pylon-lifecycle-development/demo",
                "worktree_path": None,
                "repo_root": None,
                "materialized_file_count": 1,
                "install": {"status": "passed", "command": "npm install", "exit_code": 0, "duration_ms": 1200, "stdout_tail": "", "stderr_tail": ""},
                "build": {"status": "passed", "command": "npm run build", "exit_code": 0, "duration_ms": 2100, "stdout_tail": "", "stderr_tail": ""},
                "test": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
                "ready": True,
                "errors": [],
            },
        },
        "developmentExecution": {
            "decisionContextFingerprint": decision_context_fingerprint,
            "topologyFingerprint": topology_fingerprint,
            "runtimeGraphFingerprint": runtime_graph_fingerprint,
            "topologyFresh": True,
            "topologyIssues": [],
            "waveCount": 1,
            "workUnitCount": 1,
            "currentWaveIndex": 0,
            "retryNodeIds": [],
            "focusWorkUnitIds": ["wp-1"],
            "blockedWorkUnitIds": [],
            "waves": [
                {
                    "waveIndex": 0,
                    "workUnitIds": ["wp-1"],
                    "laneIds": ["frontend-builder"],
                    "status": "completed",
                    "ready": True,
                    "blockedWorkUnitIds": [],
                    "activeNodeIds": [],
                    "completedWorkUnitCount": 1,
                    "workUnitCount": 1,
                }
            ],
            "workUnits": [
                {
                    "id": "wp-1",
                    "title": "UI shell",
                    "lane": "frontend-builder",
                    "waveIndex": 0,
                    "status": "completed",
                    "builderStatus": "completed",
                    "qaStatus": "satisfied",
                    "securityStatus": "pass",
                    "blockedBy": [],
                    "nodeId": "wave-0-wu-wp-1",
                }
            ],
        },
        "developmentHandoff": {
            "readiness_status": "ready_for_deploy",
            "release_candidate": "release-reviewable build candidate",
            "operator_summary": "Deploy phase can execute release gates immediately.",
            "deploy_checklist": ["critical path integrated", "milestones satisfied"],
            "evidence": ["Alpha satisfied", "Beta satisfied"],
            "blocking_issues": [],
            "review_focus": ["approval gate"],
            "topology_fingerprint": topology_fingerprint,
            "runtime_graph_fingerprint": runtime_graph_fingerprint,
            "wave_exit_ready": True,
            "ready_wave_count": 0,
            "non_final_wave_count": 0,
            "blocked_work_unit_ids": [],
        },
        "research": _research_patch(spec)["research"],
        "analysis": planning_patch["analysis"],
        "features": planning_patch["features"],
        "milestones": planning_patch["milestones"],
        "designVariants": design_patch["designVariants"],
        "selectedDesignId": design_patch["selectedDesignId"],
        "valueContract": value_contract,
        "outcomeTelemetryContract": outcome_telemetry_contract,
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


def test_development_contract_requires_delivery_graph_and_deploy_handoff():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["approvalStatus"] = "approved"
    project.update(_development_patch(spec))

    contract = build_phase_contracts(project)["development"]

    assert contract["ready"] is True
    assert contract["outputs"]["workPackageCount"] == 1
    assert contract["outputs"]["repoExecutionReady"] is True
    assert contract["outputs"]["deployChecklistCount"] == 2
    assert contract["outputs"]["handoffStatus"] == "ready_for_deploy"


def test_development_runtime_summary_exposes_wave_and_work_unit_mesh() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["approvalStatus"] = "approved"
    project.update(_development_patch(spec))

    summary = lifecycle_phase_runtime_summary(project, "development")

    assert summary["waveCount"] == 1
    assert summary["workUnitCount"] == 1
    assert summary["executionWaves"][0]["status"] == "completed"
    assert summary["workUnits"][0]["status"] == "completed"
    assert summary["topologyFresh"] is True


def test_planning_sync_backfills_missing_spec_from_run_payload() -> None:
    spec = "Operator-led lifecycle workspace for research, planning, approval, and release."
    patch = sync_lifecycle_project_with_run(
        _project(),
        phase="planning",
        run_record={
            "id": "run-planning-backfill",
            "input_data": {"spec": spec},
            "state": {
                "spec": spec,
                "analysis": {"summary": "Planning synthesis"},
                "features": [{"id": "artifact-lineage", "name": "Artifact lineage", "selected": True}],
                "planEstimates": [],
            },
            "execution_summary": {},
        },
        checkpoints=[],
    )

    assert patch["spec"] == spec


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


def test_next_action_does_not_regress_to_research_when_downstream_design_is_ready():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."

    project = _project()
    project["spec"] = spec
    project.update(_planning_patch(spec))
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
    assert derive_lifecycle_next_action(project)["type"] == "request_release_decision"

    project["releases"] = [{"id": "rel-1"}]
    assert derive_lifecycle_next_action(project)["type"] == "request_iteration_triage"


def test_next_action_retries_blocked_development_wave_with_precise_payload() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["orchestrationMode"] = "autonomous"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project["approvalStatus"] = "approved"
    project.update(_development_patch(spec))
    project["developmentExecution"] = {
        **project["developmentExecution"],
        "currentWaveIndex": 0,
        "retryNodeIds": ["wave-0-wu-wp-1", "wave-0-qa-engineer"],
        "focusWorkUnitIds": ["wp-1"],
        "blockedWorkUnitIds": ["wp-1"],
        "waves": [
            {
                "waveIndex": 0,
                "workUnitIds": ["wp-1"],
                "laneIds": ["frontend-builder"],
                "status": "blocked",
                "ready": False,
                "blockedWorkUnitIds": ["wp-1"],
                "activeNodeIds": ["wave-0-wu-wp-1"],
                "completedWorkUnitCount": 0,
                "workUnitCount": 1,
            }
        ],
        "workUnits": [
            {
                "id": "wp-1",
                "title": "UI shell",
                "lane": "frontend-builder",
                "waveIndex": 0,
                "status": "blocked",
                "builderStatus": "failed",
                "qaStatus": "not_satisfied",
                "securityStatus": "pass",
                "blockedBy": ["build", "qa"],
                "nodeId": "wave-0-wu-wp-1",
            }
        ],
    }
    project["developmentHandoff"]["readiness_status"] = "needs_rework"
    project["developmentHandoff"]["blocking_issues"] = ["Wave 1 remains blocked."]

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "run_phase"
    assert next_action["phase"] == "development"
    assert next_action["payload"]["waveIndex"] == 0
    assert next_action["payload"]["workUnitIds"] == ["wp-1"]
    assert next_action["payload"]["retryNodeIds"] == ["wave-0-wu-wp-1", "wave-0-qa-engineer"]
    assert next_action["payload"]["executionMode"] == "resume_current_wave"


def test_development_phase_input_includes_selected_design_context():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())

    payload = lifecycle_phase_input(project, "development")

    assert payload["selected_features"]
    assert payload["selected_design"]["id"] == project["selectedDesignId"]
    assert payload["design"]["selected"]["id"] == project["selectedDesignId"]
    assert payload["planEstimates"]
    assert payload["selectedPreset"] == project["selectedPreset"]
    assert payload["decision_context"]["fingerprint"]
    assert payload["decision_context"]["project_frame"]["primary_use_cases"]
    assert payload["decision_context"]["decision_graph"]["nodes"]
    assert payload["requirements"]["requirements"][0]["id"] == "REQ-1"
    assert payload["taskDecomposition"]["tasks"][0]["id"] == "TASK-1"
    assert payload["technicalDesign"]["apiSpecification"][0]["path"] == "/api/approval/decision"
    assert payload["reverseEngineering"]["apiEndpoints"][0]["path"] == "/api/approval/decision"


def test_research_phase_input_preserves_competitor_urls_and_depth():
    project = _project()
    project["spec"] = "Autonomous multi-agent lifecycle platform"
    project["productIdentity"] = {
        "companyName": "Pylon Labs",
        "productName": "Pylon",
        "officialWebsite": "https://pylon.example.com",
        "officialDomains": ["pylon.example.com"],
        "aliases": ["Pylon Platform"],
        "excludedEntityNames": ["Basler pylon"],
    }
    project["researchConfig"] = {
        "competitorUrls": ["https://example.com", "https://acme.dev"],
        "depth": "deep",
        "outputLanguage": "ja",
        "recoveryMode": "reframe_research",
    }

    payload = lifecycle_phase_input(project, "research")

    assert payload["competitor_urls"] == ["https://example.com", "https://acme.dev"]
    assert payload["depth"] == "deep"
    assert payload["output_language"] == "ja"
    assert payload["recovery_mode"] == "reframe_research"
    assert payload["identity_profile"]["companyName"] == "Pylon Labs"
    assert payload["identity_profile"]["productName"] == "Pylon"
    assert payload["identity_profile"]["officialDomains"] == ["pylon.example.com"]


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
    assert payload["remediation_context"]["recoveryMode"] == "deepen_evidence"


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


def test_research_remediation_switches_to_reframing_when_blocking_signature_stalls():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "autonomous"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "winning_theses": ["Traceability is a differentiator."],
            "source_links": ["https://example.com/product"],
            "confidence_summary": {"floor": 0.52, "average": 0.6, "accepted": 1},
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
                "attemptCount": 1,
                "maxAttempts": 2,
                "lastBlockingSignature": "confidence-floor",
            },
        },
    }

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "run_phase"
    assert next_action["payload"]["remediation"]["recoveryMode"] == "reframe_research"
    assert "観点を切り替える" in next_action["reason"]


def test_operator_can_unlock_guarded_planning_handoff_after_retry_budget_exhausts():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "workflow"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "winning_theses": ["Traceability is a differentiator."],
            "source_links": ["https://example.com/product"],
            "confidence_summary": {"floor": 0.52, "average": 0.6, "accepted": 1},
            "quality_gates": [
                {
                    "id": "confidence-floor",
                    "title": "confidence floor",
                    "passed": False,
                    "reason": "confidence is still too low",
                    "blockingNodeIds": ["research-judge"],
                }
            ],
            "autonomous_remediation": {
                "attemptCount": 2,
                "maxAttempts": 2,
                "lastBlockingSignature": "confidence-floor",
            },
        },
    }

    blocked_action = derive_lifecycle_next_action(project)

    assert blocked_action["type"] == "review_phase"
    assert blocked_action["phase"] == "research"
    assert blocked_action["payload"]["operatorGuidance"]["conditionalHandoffAllowed"] is True

    project["researchOperatorDecision"] = {
        "mode": "conditional_handoff",
        "selectedAt": "2026-03-13T00:00:00Z",
    }
    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "review_phase"
    assert next_action["phase"] == "planning"


def test_retry_budget_exhaustion_allows_guarded_handoff_even_when_quality_gates_stay_failed():
    project = _project()
    project["spec"] = "Governed manufacturing workflow platform"
    project["orchestrationMode"] = "workflow"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "readiness": "rework",
            "winning_theses": ["Traceability is a differentiator."],
            "source_links": ["https://example.com/product"],
            "confidence_summary": {"floor": 0.31, "average": 0.48, "accepted": 1},
            "critical_dissent_count": 1,
            "quality_gates": [
                {
                    "id": "confidence-floor",
                    "title": "confidence floor",
                    "passed": False,
                    "reason": "confidence is still too low",
                    "blockingNodeIds": ["research-judge"],
                },
                {
                    "id": "critical-dissent-resolved",
                    "title": "critical dissent resolved",
                    "passed": False,
                    "reason": "critical dissent remains unresolved",
                    "blockingNodeIds": ["devils-advocate-researcher"],
                },
            ],
            "autonomous_remediation": {
                "attemptCount": 2,
                "maxAttempts": 2,
                "lastBlockingSignature": "confidence-floor|critical-dissent-resolved",
            },
        },
    }

    blocked_action = derive_lifecycle_next_action(project)

    assert blocked_action["type"] == "review_phase"
    assert blocked_action["phase"] == "research"
    assert blocked_action["payload"]["operatorGuidance"]["conditionalHandoffAllowed"] is True
    assert blocked_action["payload"]["operatorGuidance"]["recommendedAction"] == "conditional_handoff"

    project["researchOperatorDecision"] = {
        "mode": "conditional_handoff",
        "selectedAt": "2026-03-13T00:00:00Z",
    }
    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "review_phase"
    assert next_action["phase"] == "planning"


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
    assert payload["research"]["research_context"]["decision_stage"] == "needs_research_rework"
    assert payload["research"]["research_context"]["core_question"].startswith("Can the team defend this thesis")
    assert payload["decision_context"]["project_frame"]["lead_thesis"] == "Governed visibility is the leading wedge."
    assert payload["decision_context"]["decision_graph"]["stats"]["node_count"] >= 1
    assert payload["research_context_meta"]["source"] == "canonical"
    assert payload["research_context_meta"]["compacted"] is False
    assert payload["research_context_meta"]["displayLanguage"] == "en"


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
    assert payload["research"]["display_language"] == "en"
    assert payload["research"]["research_context"]["decision_stage"]
    assert payload["research"]["research_context"]["planning_guardrails"]
    assert payload["research_context_meta"]["tokenEstimate"] <= payload["research_context_meta"]["tokenBudget"]
    assert len(payload["research"]["claims"]) <= 6
    assert len(payload["research"]["source_links"]) <= 6


def test_planning_phase_input_compacts_non_ascii_research_into_english_context():
    project = _project()
    project["spec"] = "Governed lifecycle platform"
    project["research"] = {
        "display_language": "ja",
        "canonical": {
            "judge_summary": "日本語の要約です。",
            "winning_theses": ["claim-market-demand"],
            "claims": [
                {
                    "id": "claim-market-demand",
                    "statement": "公開ソースでは導入拡大と運用上の制約が併存しており、需要自体はある一方で差別化には具体的な運用品質の説明が必要です。",
                    "status": "accepted",
                    "confidence": 0.81,
                }
            ],
            "quality_gates": [
                {
                    "id": "confidence-floor",
                    "title": "信頼度下限",
                    "passed": False,
                    "reason": "confidence floor は 0.52 です。",
                    "blockingNodeIds": ["research-judge"],
                }
            ],
            "confidence_summary": {"average": 0.58, "floor": 0.52, "accepted": 1},
            "autonomous_remediation": {
                "conditionalHandoffAllowed": True,
                "planningGuardrails": [
                    "未解決の論点を前提条件として扱う",
                ],
                "targetConfidenceFloor": 0.6,
            },
        },
    }

    payload = lifecycle_phase_input(project, "planning")

    assert payload["research_context_meta"]["compacted"] is True
    assert payload["research_context_meta"]["displayLanguage"] == "en"
    assert payload["research"]["research_context"]["decision_stage"] == "conditional_handoff"
    assert payload["research"]["research_context"]["core_question"].startswith("Can the team defend")
    assert payload["research"]["research_context"]["thesis_headline"] == "Demand exists, but differentiation depends on proving operational quality."
    assert payload["research"]["winning_theses"] == [
        "Demand exists, but differentiation depends on proving operational quality."
    ]
    assert payload["research"]["claims"][0]["statement"] == "Demand exists, but differentiation depends on proving operational quality."
    assert payload["decision_context"]["project_frame"]["lead_thesis"] == "Demand exists, but differentiation depends on proving operational quality."


def test_design_phase_input_prefers_canonical_planning_payload():
    project = _project()
    project["spec"] = "Governed lifecycle platform"
    project["analysis"] = {
        "judge_summary": "日本語の表示用企画要約です。",
        "canonical": {
            "judge_summary": "Canonical English planning summary.",
            "planning_context": {
                "product_kind": "operations",
                "core_loop": "Carry evidence into governed delivery.",
            },
            "use_cases": [{"id": "uc-1", "title": "Trace artifact lineage", "priority": "must"}],
            "recommended_milestones": [{"id": "ms-alpha", "name": "Evidence-to-build loop"}],
        },
        "localized": {
            "judge_summary": "日本語の表示用企画要約です。",
            "planning_context": {
                "product_kind": "operations",
                "core_loop": "根拠を保ったまま delivery に渡す",
            },
        },
    }

    payload = lifecycle_phase_input(project, "design")

    assert payload["analysis"]["judge_summary"] == "Canonical English planning summary."
    assert payload["analysis"]["planning_context"]["core_loop"] == "Carry evidence into governed delivery."
    assert payload["decision_context"]["project_frame"]["core_loop"] == "Carry evidence into governed delivery."
    assert payload["decision_context"]["decision_graph"]["stats"]["node_count"] >= 1
    assert payload["analysis_context_meta"]["source"] == "canonical"
    assert payload["analysis_context_meta"]["compacted"] is False


def test_design_phase_input_compacts_planning_when_token_budget_is_exceeded():
    project = _project()
    project["spec"] = "Governed lifecycle platform"
    long_text = " ".join(["planning"] * 5000)
    project["analysis"] = {
        "canonical": {
            "judge_summary": long_text,
            "planning_context": {
                "product_kind": "operations",
                "core_loop": long_text,
                "north_star": long_text,
            },
            "recommendations": [long_text for _ in range(6)],
            "personas": [{"name": "Aiko", "role": long_text, "goals": [long_text, long_text]} for _ in range(3)],
            "job_stories": [{"situation": long_text, "motivation": long_text, "outcome": long_text} for _ in range(6)],
            "use_cases": [{"id": f"uc-{index}", "title": long_text, "actor": long_text, "priority": "must"} for index in range(8)],
            "recommended_milestones": [{"id": f"ms-{index}", "name": long_text, "criteria": long_text} for index in range(4)],
            "design_tokens": {"style": {"name": "Operational Clarity"}, "rationale": long_text, "colors": {"primary": "#0f172a", "cta": "#f97316"}},
            "feature_decisions": [{"feature": f"feature-{index}", "selected": True, "uncertainty": 0.2} for index in range(8)],
            "red_team_findings": [{"title": long_text, "severity": "medium", "recommendation": long_text} for _ in range(4)],
            "kill_criteria": [{"milestone_id": f"ms-{index}", "condition": long_text} for index in range(3)],
            "coverage_summary": {"use_case_count": 8},
        }
    }
    project["features"] = [{"feature": f"feature-{index}", "selected": True, "category": "must-be", "priority": "must"} for index in range(8)]

    payload = lifecycle_phase_input(project, "design")

    assert payload["analysis_context_meta"]["compacted"] is True
    assert payload["analysis"]["summary_mode"].startswith("compact")
    assert payload["analysis_context_meta"]["tokenEstimate"] <= payload["analysis_context_meta"]["tokenBudget"]
    assert len(payload["analysis"]["use_cases"]) <= 6


def test_planning_contract_requires_required_use_case_traceability():
    spec = "Autonomous multi-agent lifecycle platform for operator-led research, approvals, artifact lineage, and governed delivery."
    project = _planning_patch(spec)
    analysis = dict(project["analysis"])
    traceability = [
        dict(item)
        for item in analysis["traceability"]
        if item.get("use_case_id") != "uc-ops-006"
    ]
    analysis["traceability"] = traceability
    project["analysis"] = analysis

    contracts = build_phase_contracts(project)
    planning = contracts["planning"]
    failed_gates = {
        item["id"]: item["passed"]
        for item in planning["qualityGates"]
    }

    assert planning["ready"] is False
    assert failed_gates["required-use-case-traceability"] is False


def test_autonomy_projection_reports_blocked_approval_boundary():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    projection = build_lifecycle_autonomy_projection(project)

    assert projection["governanceMode"] == "governed"
    assert projection["approvalRequired"] is True
    assert projection["humanDecisionRequired"] is True
    assert projection["nextAction"]["type"] == "request_approval"
    assert projection["phaseReadiness"]["design"]["ready"] is True
    assert projection["requiredHumanDecisions"][0]["decisionId"] == "approval_gate"


def test_governed_mode_keeps_human_approval_even_at_a4():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["orchestrationMode"] = "autonomous"
    project["autonomyLevel"] = "A4"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    projection = build_lifecycle_autonomy_projection(project)

    assert resolve_lifecycle_governance_mode(project) == "governed"
    assert projection["approvalRequired"] is True
    assert projection["nextAction"]["type"] == "request_approval"
    assert projection["nextAction"]["canAutorun"] is False


def test_complete_autonomy_mode_auto_approves_at_a4():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["orchestrationMode"] = "autonomous"
    project["autonomyLevel"] = "A4"
    project["governanceMode"] = "complete_autonomy"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    projection = build_lifecycle_autonomy_projection(project)

    assert projection["approvalRequired"] is False
    assert projection["governanceMode"] == "complete_autonomy"
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
    project.update(_native_development_artifacts())

    binding = build_lifecycle_approval_binding(project)

    assert binding["action"] == "advance_to_development"
    assert binding["plan"]["selected_design_id"] == project["selectedDesignId"]
    assert binding["effect_envelope"]["phase"] == "development"
    assert binding["effect_envelope"]["input"]["selected_design"]["id"] == project["selectedDesignId"]
    assert binding["effect_envelope"]["input"]["decision_context"]["fingerprint"]
    assert binding["effect_envelope"]["input"]["requirements"]["requirements"][0]["id"] == "REQ-1"
    assert binding["effect_envelope"]["input"]["technicalDesign"]["apiSpecification"][0]["path"] == "/api/approval/decision"
    assert binding["plan"]["selected_features"]


def test_governed_mode_requests_release_decision_after_checks_pass():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["approvalStatus"] = "approved"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_development_patch(spec))
    project["deployChecks"] = [
        {"id": "deploy-smoke", "label": "Smoke", "status": "pass", "detail": "ready"}
    ]

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "request_release_decision"
    assert next_action["phase"] == "deploy"
    assert next_action["requiresHumanDecision"] is True


def test_complete_autonomy_auto_creates_release_after_checks_pass():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["approvalStatus"] = "approved"
    project["governanceMode"] = "complete_autonomy"
    project["orchestrationMode"] = "autonomous"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_development_patch(spec))
    project["deployChecks"] = [
        {"id": "deploy-smoke", "label": "Smoke", "status": "pass", "detail": "ready"}
    ]

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "create_release"
    assert next_action["phase"] == "deploy"
    assert next_action["canAutorun"] is True


def test_governed_mode_requests_iteration_triage_after_release():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["approvalStatus"] = "approved"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_development_patch(spec))
    project["deployChecks"] = [
        {"id": "deploy-smoke", "label": "Smoke", "status": "pass", "detail": "ready"}
    ]
    project["releases"] = [
        {
            "id": "rel-1",
            "createdAt": "2026-03-19T00:00:00Z",
            "version": "v0.1.0",
            "note": "demo",
            "artifactBytes": 128,
            "qualitySummary": {
                "overallScore": 0.94,
                "releaseReady": True,
                "passed": 1,
                "warnings": 0,
                "failed": 0,
            },
        }
    ]

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "request_iteration_triage"
    assert next_action["phase"] == "iterate"
    assert next_action["requiresHumanDecision"] is True


def test_complete_autonomy_keeps_iteration_loop_open_without_hard_human_gate():
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project["approvalStatus"] = "approved"
    project["governanceMode"] = "complete_autonomy"
    project["orchestrationMode"] = "autonomous"
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_development_patch(spec))
    project["deployChecks"] = [
        {"id": "deploy-smoke", "label": "Smoke", "status": "pass", "detail": "ready"}
    ]
    project["releases"] = [
        {
            "id": "rel-1",
            "createdAt": "2026-03-19T00:00:00Z",
            "version": "v0.1.0",
            "note": "demo",
            "artifactBytes": 128,
            "qualitySummary": {
                "overallScore": 0.94,
                "releaseReady": True,
                "passed": 1,
                "warnings": 0,
                "failed": 0,
            },
        }
    ]

    next_action = derive_lifecycle_next_action(project)

    assert next_action["type"] == "done"
    assert next_action["phase"] == "iterate"
    assert next_action["requiresHumanDecision"] is False


def test_development_planner_builds_spec_audit_and_code_workspace() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]

    payload = lifecycle_phase_input(project, "development")
    result = _invoke_handler(_development_planner_handler, "planner", payload)
    delivery_plan = dict(result.state_patch["delivery_plan"])
    definition = build_lifecycle_workflow_definition(
        "orbit",
        "development",
        project_record=payload,
    )
    project_definition = build_lifecycle_workflow_definition(
        "orbit",
        "development",
        project_record=project,
    )
    workflow_nodes = dict(definition["project"]["workflow"]["nodes"])
    project_workflow_nodes = dict(project_definition["project"]["workflow"]["nodes"])

    assert delivery_plan["spec_audit"]["status"] == "ready_for_autonomous_build"
    assert delivery_plan["topology_mode"] == "work_unit_wave_mesh"
    assert delivery_plan["goal_spec"]["selected_features"]
    assert delivery_plan["wave_count"] >= 1
    assert delivery_plan["work_unit_contracts"]
    assert delivery_plan["runtime_graph"]["node_count"] == len(workflow_nodes)
    assert delivery_plan["runtime_graph"]["work_unit_node_count"] >= 1
    assert any(str(node_id).startswith("wave-0-wu-") for node_id in workflow_nodes)
    assert any(str(node_id).startswith("wave-0-wu-") for node_id in project_workflow_nodes)
    assert any(
        isinstance(item, dict) and str(item.get("stage") or "") == "work_unit"
        for item in delivery_plan["runtime_graph"]["runtime_assignments"]
    )
    assert delivery_plan["code_workspace"]["artifact_summary"]["package_count"] >= 1
    assert delivery_plan["code_workspace"]["artifact_summary"]["file_count"] >= 5
    assert delivery_plan["code_workspace"]["route_bindings"]
    workspace_paths = {str(item["path"]) for item in delivery_plan["code_workspace"]["files"]}
    assert "app/lib/work-unit-contracts.ts" in workspace_paths
    assert "docs/spec/work-unit-contracts.md" in workspace_paths
    assert "docs/spec/delivery-waves.md" in workspace_paths


def test_development_dynamic_work_unit_handler_scopes_runtime_node() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]

    payload = lifecycle_phase_input(project, "development")
    planner_result = _invoke_handler(_development_planner_handler, "planner", payload)
    state = {**payload, **planner_result.state_patch}
    runtime_graph = dict(state["delivery_plan"]["runtime_graph"])
    work_unit_assignment = next(
        dict(item)
        for item in runtime_graph["runtime_assignments"]
        if isinstance(item, dict)
        and str(item.get("stage") or "") == "work_unit"
    )
    handlers = build_lifecycle_workflow_handlers("development")
    handler = handlers[str(work_unit_assignment["agent"])]

    result = _invoke_handler(
        handler,
        str(work_unit_assignment["node_id"]),
        state,
    )
    if str(work_unit_assignment["agent"]) == "frontend-builder":
        assigned_units = dict(result.state_patch["frontend_bundle"])["assigned_work_units"]
        bucket_name = "frontend_bundles"
        assert len(assigned_units) == 1
        assert assigned_units[0]["work_package_id"] == work_unit_assignment["focus_work_unit_ids"][0]
    elif str(work_unit_assignment["agent"]) == "backend-builder":
        assigned_units = dict(result.state_patch["backend_bundle"])["assigned_work_units"]
        bucket_name = "backend_bundles"
        assert len(assigned_units) == 1
        assert assigned_units[0]["work_package_id"] == work_unit_assignment["focus_work_unit_ids"][0]
    else:
        bucket_name = "integrated_builds"
        assert dict(result.state_patch["integrated_build"])["runtime_node"]["focus_work_unit_ids"] == work_unit_assignment["focus_work_unit_ids"]
    assert result.state_patch["development_execution"][bucket_name][work_unit_assignment["node_id"]]["runtime_node"]["stage"] == "work_unit"


def test_development_workflow_definition_rebuilds_stale_topology_from_project_state() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project.update(_development_patch(spec))

    definition = build_lifecycle_workflow_definition("orbit", "development", project_record=project)
    workflow_nodes = definition["project"]["workflow"]["nodes"]

    assert "wave-0-wu-task-1" in workflow_nodes
    assert "wave-0-wu-wp-1" not in workflow_nodes


def test_development_planner_blocks_when_design_and_auth_contracts_are_missing() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]
    project["analysis"] = {
        **dict(project["analysis"]),
        "roles": [],
        "design_tokens": None,
        "canonical": {
            **dict(dict(project["analysis"]).get("canonical") or {}),
            "roles": [],
            "design_tokens": None,
        },
    }
    project["requirements"] = {
        **dict(project["requirements"]),
        "requirements": [
            {
                "id": "REQ-1",
                "pattern": "ubiquitous",
                "statement": "The system shall let operators review approval packets before delivery.",
                "confidence": 0.9,
                "sourceClaimIds": ["claim-1"],
                "userStoryIds": ["story-1"],
                "acceptanceCriteria": ["Operators can inspect approval packet details before approving delivery."],
            }
        ],
        "acceptanceCriteria": [{"id": "ac-1", "requirementId": "REQ-1", "criterion": "Approval packet details are visible before delivery."}],
    }
    project["taskDecomposition"] = {
        **dict(project["taskDecomposition"]),
        "tasks": [
            {
                "id": "TASK-1",
                "title": "Implement approval delivery workspace",
                "description": "Build the approval delivery workspace and operator shell.",
                "phase": "development",
                "milestoneId": "ms-alpha",
                "dependsOn": [],
                "effortHours": 16,
                "priority": "must",
                "featureId": "feature-1",
                "requirementId": "REQ-1",
            }
        ],
    }

    payload = lifecycle_phase_input(project, "development")
    result = _invoke_handler(_development_planner_handler, "planner", payload)
    spec_audit = dict(result.state_patch["delivery_plan"]["spec_audit"])
    gap_ids = {str(item.get("id")) for item in spec_audit["unresolved_gaps"]}

    assert spec_audit["status"] == "needs_spec_closure"
    assert "design-token-contract-missing" in gap_ids
    assert "auth-boundary-missing" in gap_ids


def test_development_phase_input_backfills_requirements_from_selected_features_without_claims() -> None:
    spec = "Operator console that drives governed approval delivery, artifact lineage, and autonomous handoff."
    project = _project()
    project["spec"] = spec
    project.update(_design_patch(spec))
    project["research"] = {
        "user_research": {
            "segment": "delivery operator",
            "pain_points": ["manual approval coordination"],
        },
        "claims": [],
    }
    project["features"] = [
        {
            "id": "feature-console",
            "feature": "operator console",
            "selected": True,
            "priority": "must",
            "implementation_cost": "medium",
            "rationale": "Operators need one governed console for approvals and lineage.",
            "acceptance_criteria": ["operator console shows approval packets and lineage status"],
        }
    ]
    project["requirements"] = None

    payload = lifecycle_phase_input(project, "development")

    requirements = dict(payload["requirements"])
    assert requirements["requirements"]
    assert requirements["requirements"][0]["sourceClaimIds"][0].startswith("synthetic-")
    assert "operator console" in requirements["requirements"][0]["statement"].lower()
    assert payload["taskDecomposition"]["tasks"]


def test_planning_effort_budget_balance_scales_with_project_size() -> None:
    spec = "Operator-led lifecycle workspace with a focused first milestone."
    project = _project()
    project["spec"] = spec
    project.update(_planning_patch(spec))
    project["taskDecomposition"] = {
        "tasks": [
            {
                "id": "TASK-1",
                "title": "Implement operator console milestone",
                "description": "Focused delivery slice for the first milestone.",
                "phase": "Phase 1",
                "milestoneId": "ms-alpha",
                "dependsOn": [],
                "effortHours": 88,
                "priority": "must",
                "featureId": "feature-console",
            }
        ],
        "dagEdges": [],
        "phaseMilestones": [{"phase": "Phase 1", "milestoneIds": ["ms-alpha"], "taskCount": 1, "totalHours": 88, "durationDays": 10}],
        "totalEffortHours": 88,
        "criticalPath": ["TASK-1"],
        "effortByPhase": {"Phase 1": 88},
        "hasCycles": False,
    }

    planning_contract = build_phase_contracts(project)["planning"]
    effort_gate = next(
        gate for gate in planning_contract["qualityGates"] if gate["id"] == "effort-budget-balance"
    )

    assert effort_gate["passed"] is True
    assert planning_contract["ready"] is True


def test_development_repo_executor_persists_repo_execution_result() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project["githubRepo"] = "/tmp/local-repo"
    project["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]
    payload = lifecycle_phase_input(project, "development")
    planner_result = _invoke_handler(_development_planner_handler, "planner", payload)
    state = {**payload, **planner_result.state_patch}

    with patch(
        "pylon.lifecycle.orchestrator.execute_development_code_workspace",
        return_value={
            "mode": "git_worktree",
            "workspace_path": "/tmp/pylon/worktree",
            "worktree_path": "/tmp/pylon/worktree",
            "repo_root": "/tmp/local-repo",
            "materialized_file_count": 9,
            "install": {"status": "passed", "command": "npm install", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            "build": {"status": "passed", "command": "npm run build", "exit_code": 0, "duration_ms": 12, "stdout_tail": "", "stderr_tail": ""},
            "test": {"status": "passed", "command": "npm test", "exit_code": 0, "duration_ms": 9, "stdout_tail": "", "stderr_tail": ""},
            "ready": True,
            "errors": [],
        },
    ):
        result = _invoke_handler(_development_repo_executor_handler, "repo-executor", state)

    repo_execution = dict(result.state_patch["delivery_plan"]["repo_execution"])
    assert repo_execution["mode"] == "git_worktree"
    assert repo_execution["ready"] is True
    assert repo_execution["materialized_file_count"] == 9


def test_sync_lifecycle_project_with_run_replays_checkpoint_outputs_for_development() -> None:
    project = _project()
    patch = sync_lifecycle_project_with_run(
        project,
        phase="development",
        run_record={
            "id": "run-dev",
            "workflow_id": "lifecycle-development-orbit",
            "status": "completed",
            "state": {
                "spec": "Operator-led lifecycle workspace",
                "decision_context": {"fingerprint": "fp-dev-context"},
            },
            "started_at": "2026-03-17T10:00:00Z",
            "completed_at": "2026-03-17T10:00:02Z",
            "execution_summary": {},
            "runtime_metrics": {},
        },
        checkpoints=[
            {
                "id": "cp-1",
                "created_at": "2026-03-17T10:00:02Z",
                "event_log": [
                    {
                        "node_id": "reviewer",
                        "state_version": 1,
                        "state_hash": "",
                        "state_patch_scrubbed": False,
                        "state_patch": {
                            "_build_iteration": 1,
                            "estimated_cost_usd": 1.23,
                            "development": {
                                "code": "<!doctype html><html><body><main data-screen-id='workspace'></main></body></html>",
                                "milestone_results": [{"id": "ms-1", "name": "Alpha", "status": "satisfied"}],
                                "delivery_plan": {
                                    "spec_audit": {"status": "ready_for_autonomous_build", "unresolved_gaps": []},
                                    "decision_context_fingerprint": "fp-dev-context",
                                    "topology_fingerprint": "topology-fp-dev",
                                    "runtime_graph_fingerprint": "runtime-fp-dev",
                                    "waves": [{"wave_index": 0, "work_unit_ids": ["wp-1"], "lane_ids": ["frontend-builder"]}],
                                    "work_unit_contracts": [{"id": "wu-wp-1", "work_package_id": "wp-1", "title": "UI shell", "lane": "frontend-builder", "wave_index": 0}],
                                },
                                "handoff": {
                                    "readiness_status": "ready_for_deploy",
                                    "blocking_issues": [],
                                    "deploy_checklist": ["repo execution passed"],
                                    "topology_fingerprint": "topology-fp-dev",
                                    "wave_exit_ready": True,
                                    "ready_wave_count": 0,
                                    "non_final_wave_count": 0,
                                },
                            },
                            "qa_report": {
                                "wave_results": [{"wave_index": 0, "status": "satisfied", "satisfied": 1, "total": 1}],
                                "work_unit_results": [{"id": "wp-1", "wave_index": 0, "status": "satisfied"}],
                            },
                            "security_report": {
                                "status": "pass",
                                "work_unit_results": [{"id": "wp-1", "wave_index": 0, "status": "pass"}],
                            },
                            "development_execution": {
                                "reviews": {
                                    "wave-0-reviewer": {
                                        "wave_index": 0,
                                        "ready": True,
                                    }
                                }
                            },
                            "integrated_build": {"decision_context_fingerprint": "fp-dev"},
                        },
                    }
                ],
            }
        ],
    )

    assert patch["buildCode"].startswith("<!doctype html>")
    assert patch["buildIteration"] == 1
    assert patch["buildCost"] == 1.23
    assert patch["buildDecisionFingerprint"] == "fp-dev"
    assert patch["deliveryPlan"]["spec_audit"]["status"] == "ready_for_autonomous_build"
    assert patch["developmentHandoff"]["readiness_status"] == "ready_for_deploy"
    assert patch["developmentExecution"]["waveCount"] == 1
    assert patch["developmentExecution"]["workUnitCount"] == 1
    phase_run = next(item for item in patch["phaseRuns"] if item["runId"] == "run-dev")
    assert phase_run["executionSummary"]["waveCount"] == 1
    assert phase_run["executionSummary"]["topologyFresh"] is True


def test_development_reviewer_requires_repo_execution_for_deploy_ready_handoff() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))
    project.update(_native_development_artifacts())
    project["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]
    payload = lifecycle_phase_input(project, "development")
    planner_result = _invoke_handler(_development_planner_handler, "planner", payload)
    html = (
        "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /></head>"
        "<body data-prototype-kind=\"build\"><nav aria-label=\"primary navigation\"></nav>"
        "<main><section data-screen-id=\"workspace\"></section><button aria-label=\"Approve\"></button></main></body></html>"
    )
    state = {
        **payload,
        **planner_result.state_patch,
        "milestones": [],
        "integrated_build": {"code": html, "build_sections": ["workspace"]},
        "qa_report": {
            "milestone_results": [{"id": "ms-1", "name": "Alpha", "status": "satisfied"}],
            "work_unit_results": [
                {"id": "TASK-1", "wave_index": 0, "lane": "frontend-builder", "status": "satisfied", "reason": "ok"}
            ],
            "wave_results": [{"wave_index": 0, "status": "satisfied", "satisfied": 1, "total": 1}],
        },
        "security_report": {
            "status": "pass",
            "findings": ["No obvious unsafe DOM execution pattern was detected."],
            "blockers": [],
            "recommendations": [
                "Prefer semantic landmarks and explicit ARIA labels for operator controls.",
                "Keep release actions distinct from navigation actions.",
            ],
        },
        "repo_execution": {
            "mode": "temp_workspace",
            "workspace_path": "/tmp/pylon/workspace",
            "worktree_path": None,
            "repo_root": None,
            "materialized_file_count": 9,
            "install": {"status": "passed", "command": "npm install", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            "build": {"status": "passed", "command": "npm run build", "exit_code": 0, "duration_ms": 12, "stdout_tail": "", "stderr_tail": ""},
            "test": {"status": "passed", "command": "npm test", "exit_code": 0, "duration_ms": 9, "stdout_tail": "", "stderr_tail": ""},
            "ready": True,
            "errors": [],
        },
    }
    state["delivery_plan"] = {
        **dict(state["delivery_plan"]),
        "repo_execution": dict(state["repo_execution"]),
    }

    result = _invoke_handler(_development_reviewer_handler, "reviewer", state)
    handoff = dict(result.state_patch["development_handoff"])

    assert handoff["readiness_status"] == "ready_for_deploy"
    assert any("repo execution" in item.get("label", "") for item in handoff["evidence"])
    assert any("install / build / test" in item.get("label", "") for item in handoff["deploy_checklist"])
    assert not handoff["blocking_issues"]


def test_development_handoff_ignores_positive_security_findings_in_blockers():
    state = _project()
    state["spec"] = "Operator-led lifecycle workspace"
    state.update(_research_patch(state["spec"]))
    state.update(_planning_patch(state["spec"]))
    state.update(_design_patch(state["spec"]))
    state.update(_native_development_artifacts())
    state["features"] = [
        {
            "id": "feature-1",
            "feature": "approval delivery workspace",
            "selected": True,
            "priority": "must",
            "category": "must-be",
        }
    ]
    planner_payload = lifecycle_phase_input(state, "development")
    planner_result = _invoke_handler(_development_planner_handler, "planner", planner_payload)
    state = {
        **planner_payload,
        **planner_result.state_patch,
    }
    state["delivery_plan"] = {
        **dict(state["delivery_plan"]),
        "repo_execution": {
            "mode": "temp_workspace",
            "workspace_path": "/tmp/pylon/workspace",
            "worktree_path": None,
            "repo_root": None,
            "materialized_file_count": 9,
            "install": {"status": "passed", "command": "npm install", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            "build": {"status": "passed", "command": "npm run build", "exit_code": 0, "duration_ms": 12, "stdout_tail": "", "stderr_tail": ""},
            "test": {"status": "passed", "command": "npm test", "exit_code": 0, "duration_ms": 9, "stdout_tail": "", "stderr_tail": ""},
            "ready": True,
            "errors": [],
        },
    }

    handoff = _build_development_handoff(
        state=state,
        delivery_plan=state["delivery_plan"],
        snapshot={
            "milestone_results": [
                {"id": "ms-1", "name": "Alpha", "status": "satisfied", "reason": "ok"},
            ],
            "security_report": {
                "status": "pass",
                "findings": ["No obvious unsafe DOM execution pattern was detected."],
                "blockers": [],
                "recommendations": [],
            },
            "repo_execution_report": dict(state["delivery_plan"]["repo_execution"]),
            "blockers": ["No obvious unsafe DOM execution pattern was detected."],
        },
    )

    assert handoff["readiness_status"] == "ready_for_deploy"
    assert handoff["blocking_issues"] == []


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


def test_approval_binding_is_stable_across_approval_and_development_phase_progress() -> None:
    spec = "Autonomous multi-agent lifecycle platform for operator-led approvals and artifact lineage."
    project = _project()
    project["spec"] = spec
    project.update(_research_patch(spec))
    project.update(_planning_patch(spec))
    project.update(_design_patch(spec))

    baseline = build_lifecycle_approval_binding(project)

    progressed = {
        **project,
        "approvalStatus": "approved",
        "approvalRequestId": "apr_demo",
        "phaseStatuses": [
            {"phase": "research", "status": "completed", "version": 1},
            {"phase": "planning", "status": "completed", "version": 1},
            {"phase": "design", "status": "completed", "version": 1},
            {"phase": "approval", "status": "completed", "version": 1},
            {"phase": "development", "status": "in_progress", "version": 1},
            {"phase": "deploy", "status": "locked", "version": 1},
            {"phase": "iterate", "status": "locked", "version": 1},
        ],
    }
    progressed_binding = build_lifecycle_approval_binding(progressed)

    assert compute_approval_binding_hash(baseline["plan"]) == compute_approval_binding_hash(progressed_binding["plan"])
    assert compute_approval_binding_hash(baseline["effect_envelope"]) == compute_approval_binding_hash(
        progressed_binding["effect_envelope"]
    )


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
