"""Tests for spec-driven development workspace generation."""

from __future__ import annotations

import json

from pylon.lifecycle.services.development_workspace import (
    _build_semantic_colors,
    _check_css_variable_usage,
    _contrast_ratio,
    _design_token_contract_ready,
    _hex_to_relative_luminance,
    build_development_code_workspace,
    build_development_spec_audit,
    refine_development_code_workspace,
)
from pylon.lifecycle.services.value_contracts import (
    REQUIRED_DELIVERY_CONTRACT_IDS,
    build_outcome_telemetry_contract,
    build_value_contract,
)


def test_build_development_code_workspace_injects_vitest_runtime_for_acceptance_specs() -> None:
    selected_design = {
        "prototype_spec": {
            "routes": [{"path": "/", "screen_id": "workspace"}],
        },
        "prototype_app": {
            "framework": "nextjs",
            "router": "app",
            "files": [
                {
                    "path": "package.json",
                    "kind": "json",
                    "content": json.dumps(
                        {
                            "name": "demo-workspace",
                            "private": True,
                            "scripts": {"dev": "next dev", "build": "next build"},
                            "dependencies": {"next": "16.1.6", "react": "19.2.4", "react-dom": "19.2.4"},
                            "devDependencies": {"typescript": "5.9.3"},
                        }
                    ),
                },
                {
                    "path": "app/page.tsx",
                    "kind": "tsx",
                    "content": "export default function Page() { return <main>ok</main>; }\n",
                },
            ],
        },
    }
    requirements = {
        "requirements": [
            {
                "id": "REQ-1",
                "statement": "The system shall surface operator approvals with clear acceptance coverage.",
                "acceptanceCriteria": ["Approvals can be reviewed before autonomous delivery starts."],
            }
        ]
    }

    workspace = build_development_code_workspace(
        spec="Operator-led lifecycle workspace",
        selected_features=["Approval review"],
        selected_design=selected_design,
        requirements=requirements,
        task_decomposition={"tasks": []},
        technical_design={},
        reverse_engineering={},
    )

    files = {str(item["path"]): item for item in workspace["files"]}
    package_payload = json.loads(files["package.json"]["content"])

    assert package_payload["scripts"]["test"] == "vitest run"
    assert package_payload["devDependencies"]["vitest"]
    assert "vitest.config.ts" in files
    assert "tests/acceptance/requirements.spec.ts" in files


def test_refine_development_code_workspace_merges_lane_outputs_into_real_files() -> None:
    selected_design = {
        "prototype_spec": {
            "title": "Autonomous delivery workspace",
            "subtitle": "Operator-led release control",
            "theme": {"primary": "#0f172a", "accent": "#10b981"},
            "routes": [
                {"path": "/", "screen_id": "workspace", "title": "Workspace", "layout": "control"},
                {"path": "/approval", "screen_id": "approval", "title": "Approval", "layout": "control"},
            ],
            "screens": [
                {
                    "id": "workspace",
                    "title": "Workspace",
                    "headline": "Control tower",
                    "purpose": "Coordinate delivery lanes and approvals.",
                    "primary_actions": ["Review readiness"],
                },
                {
                    "id": "approval",
                    "title": "Approval",
                    "headline": "Approval packet",
                    "purpose": "Approve or reject promotion.",
                    "primary_actions": ["Approve"],
                },
            ],
        },
        "prototype_app": {
            "framework": "nextjs",
            "router": "app",
            "files": [
                {
                    "path": "package.json",
                    "kind": "json",
                    "content": json.dumps(
                        {
                            "name": "autonomous-workspace",
                            "private": True,
                            "scripts": {"dev": "next dev", "build": "next build"},
                            "dependencies": {"next": "16.1.6", "react": "19.2.4", "react-dom": "19.2.4"},
                            "devDependencies": {"typescript": "5.9.3"},
                        }
                    )
                    + "\n",
                },
                {
                    "path": "app/layout.tsx",
                    "kind": "tsx",
                    "content": 'import "./globals.css";\nexport default function RootLayout({ children }: { children: React.ReactNode }) { return <html lang="ja"><body>{children}</body></html>; }\n',
                },
                {
                    "path": "app/globals.css",
                    "kind": "css",
                    "content": ":root { --border: rgba(255,255,255,0.2); --surface: rgba(255,255,255,0.1); --muted: #94a3b8; --text: #f8fafc; }\n",
                },
                {
                    "path": "app/components/prototype-shell.tsx",
                    "kind": "tsx",
                    "content": 'export function PrototypeShell() { return <main>prototype</main>; }\n',
                },
                {
                    "path": "app/page.tsx",
                    "kind": "tsx",
                    "content": 'import { PrototypeShell } from "./components/prototype-shell";\nexport default function Page() { return <PrototypeShell screenId="workspace" />; }\n',
                },
            ],
        },
    }
    planning_analysis = {
        "roles": [
            {
                "name": "Operator",
                "permissions": ["approval:write", "release:promote"],
                "responsibilities": ["Review rationale", "Approve promotion"],
            }
        ],
        "personas": [
            {
                "name": "Operator",
                "role": "Release owner",
                "context": "Governed delivery workspace",
                "goals": ["Approve safely"],
                "frustrations": ["Missing rationale"],
            }
        ],
        "job_stories": [
            {
                "title": "When delivery is ready, I need to approve with full context.",
                "situation": "When delivery is ready",
                "motivation": "approve with full context",
                "outcome": "so I can promote safely",
                "priority": "core",
                "related_features": ["Approval workspace"],
            }
        ],
        "user_journeys": [
            {
                "persona_name": "Operator",
                "touchpoints": [
                    {
                        "phase": "usage",
                        "action": "Review approval packet",
                        "touchpoint": "Approval workspace",
                        "emotion": "neutral",
                        "pain_point": "Missing rationale",
                    }
                ],
            }
        ],
        "ia_analysis": {
            "navigation_model": "hierarchical",
            "site_map": [{"id": "approval", "label": "Approval", "priority": "primary"}],
            "key_paths": [{"name": "Approval review", "steps": ["Open workspace", "Review rationale", "Approve"]}],
        },
        "kano_features": [{"feature": "Approval workspace", "category": "must-be"}],
        "design_tokens": {
            "style": {
                "name": "Operator Studio",
                "best_for": "approval-heavy control planes",
                "accessibility": "strong contrast and governed focus order",
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
            "effects": ["Focus rings remain visible during lane transitions."],
            "anti_patterns": ["Do not invent ad-hoc accent colors."],
            "rationale": "Keep autonomous delivery outputs visually governed.",
        },
        "kill_criteria": ["Approval review cannot be observed before release promotion."],
    }
    milestone_rows = [{"id": "ms-alpha", "name": "Approval ready", "criteria": "Rationale and blockers are visible."}]
    value_contract = build_value_contract(
        {
            "spec": "Autonomous delivery workspace",
            "analysis": planning_analysis,
            "features": [{"id": "feature-approval", "name": "Approval workspace", "feature": "Approval workspace", "selected": True}],
            "milestones": milestone_rows,
        }
    )
    outcome_telemetry_contract = build_outcome_telemetry_contract(
        {
            "spec": "Autonomous delivery workspace",
            "analysis": planning_analysis,
            "features": [{"id": "feature-approval", "name": "Approval workspace", "feature": "Approval workspace", "selected": True}],
            "milestones": milestone_rows,
            "valueContract": value_contract,
        },
        value_contract=value_contract,
    )
    base_workspace = build_development_code_workspace(
        spec="Autonomous delivery workspace",
        selected_features=["Approval workspace", "Artifact lineage"],
        selected_design=selected_design,
        requirements={
            "requirements": [
                {
                    "id": "REQ-1",
                    "statement": "The system shall keep approval rationale attached to the current delivery packet.",
                    "acceptanceCriteria": ["Operators can record rationale before promotion."],
                }
            ]
        },
        task_decomposition={
            "tasks": [
                {
                    "id": "TASK-1",
                    "title": "Implement approval packet",
                    "description": "Persist the rationale and show delivery readiness.",
                }
            ]
        },
        technical_design={
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
                    "name": "LifecycleProject",
                    "properties": [{"name": "id", "type": "string"}],
                }
            ],
        },
        reverse_engineering={},
    )

    refined = refine_development_code_workspace(
        code_workspace=base_workspace,
        spec="Autonomous delivery workspace",
        selected_features=["Approval workspace", "Artifact lineage"],
        selected_design=selected_design,
        frontend_bundle={
            "interaction_notes": ["Keep approvals and lane blockers in the same viewport."],
        },
        backend_bundle={
            "entities": [{"name": "ApprovalPacket", "fields": ["id", "rationale", "status"]}],
            "api_endpoints": [
                {"method": "GET", "path": "/api/control-plane", "description": "Read control plane", "authRequired": True}
            ],
            "automation_notes": ["Persist approval rationale before promotion."],
        },
        delivery_plan={
            "goal_spec": {
                "selected_features": ["Approval workspace", "Artifact lineage"],
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
                    "title": "Implement approval packet",
                    "lane": "backend-builder",
                    "depends_on": [],
                    "deliverables": ["control-plane route"],
                    "acceptance_criteria": ["Rationale is persisted before promote."],
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
                    "title": "Implement approval packet",
                    "lane": "backend-builder",
                    "wave_index": 0,
                    "depends_on": [],
                    "acceptance_criteria": ["Rationale is persisted before promotion."],
                    "qa_checks": ["Rationale is persisted before promotion."],
                    "security_checks": ["Protected API paths keep authRequired truth."],
                    "required_contracts": list(REQUIRED_DELIVERY_CONTRACT_IDS),
                    "value_targets": [{"metric_id": value_contract["success_metrics"][0]["id"], "metric_name": value_contract["success_metrics"][0]["name"]}],
                    "telemetry_events": [{"id": outcome_telemetry_contract["telemetry_events"][0]["id"], "name": outcome_telemetry_contract["telemetry_events"][0]["name"]}],
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
        },
        milestones=milestone_rows,
        technical_design={
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
                    "name": "LifecycleProject",
                    "properties": [{"name": "id", "type": "string"}],
                }
            ],
        },
        planning_analysis=planning_analysis,
    )

    files = {str(item["path"]): item for item in refined["files"]}

    assert "app/lib/control-plane-data.ts" in files
    assert "app/lib/design-tokens.ts" in files
    assert "app/lib/development-standards.ts" in files
    assert "app/lib/value-contract.ts" in files
    assert "app/lib/work-unit-contracts.ts" in files
    assert "app/api/control-plane/route.ts" in files
    assert "tests/acceptance/control-plane.spec.ts" in files
    assert "docs/spec/autonomous-delivery.md" in files
    assert "docs/spec/design-system.md" in files
    assert "docs/spec/development-standards.md" in files
    assert "docs/spec/value-contract.md" in files
    assert "docs/spec/work-unit-contracts.md" in files
    assert "docs/spec/delivery-waves.md" in files
    assert "docs/spec/access-control.md" in files
    assert "docs/spec/operability.md" in files
    assert "docs/spec/outcome-telemetry.md" in files
    assert "server/contracts/access-policy.ts" in files
    assert "server/contracts/audit-events.ts" in files
    assert "server/contracts/outcome-telemetry.ts" in files
    assert "Character count" in files["app/components/prototype-shell.tsx"]["content"]
    assert "Identity and access" in files["app/components/prototype-shell.tsx"]["content"]
    assert "Approved token contract" in files["app/components/prototype-shell.tsx"]["content"]
    assert "Audit and release signals" in files["app/components/prototype-shell.tsx"]["content"]
    assert "Implementation and coding rules" in files["app/components/prototype-shell.tsx"]["content"]
    assert "developmentStandards" in files["app/lib/control-plane-data.ts"]["content"]
    assert "workUnitContracts" in files["app/lib/control-plane-data.ts"]["content"]
    assert "valueContract" in files["app/lib/control-plane-data.ts"]["content"]
    assert "outcomeTelemetryContract" in files["app/lib/control-plane-data.ts"]["content"]
    assert "/api/control-plane" in files["server/contracts/api-contract.ts"]["content"]
    assert "Autonomous delivery workspace extensions" in files["app/globals.css"]["content"]
    assert "--color-brand-primary" in files["app/globals.css"]["content"]
    assert "deliveryExecutionPlan" in files["app/lib/work-unit-contracts.ts"]["content"]
    assert "## Waves" in files["docs/spec/autonomous-delivery.md"]["content"]


def test_build_development_spec_audit_blocks_missing_system_contract_artifacts() -> None:
    audit = build_development_spec_audit(
        selected_features=["Approval workspace"],
        requirements={
            "requirements": [
                {
                    "id": "REQ-1",
                    "statement": "The system shall let authorized operators approve delivery.",
                    "acceptanceCriteria": ["Operators can sign in and approve release promotion."],
                }
            ]
        },
        task_decomposition={
            "tasks": [
                {
                    "id": "TASK-1",
                    "title": "Implement auth-aware approval flow",
                    "description": "Support login, approval, and promotion.",
                }
            ]
        },
        dcs_analysis={},
        technical_design={
            "apiSpecification": [
                {
                    "method": "POST",
                    "path": "/api/releases/promote",
                    "description": "Promote validated release",
                    "authRequired": True,
                }
            ],
            "databaseSchema": [],
            "interfaceDefinitions": [],
        },
        reverse_engineering={},
        code_workspace={
            "files": [
                {"path": "app/page.tsx"},
                {"path": "server/contracts/api-contract.ts"},
            ],
            "route_bindings": [{"route_path": "/", "screen_id": "approval"}],
            "artifact_summary": {"file_count": 2},
        },
        selected_design={
            "prototype_spec": {
                "routes": [{"path": "/login", "screen_id": "login", "title": "Login"}],
            }
        },
        planning_analysis={
            "roles": [
                {
                    "name": "Operator",
                    "permissions": ["release:promote"],
                    "responsibilities": ["Approve release"],
                }
            ],
            "design_tokens": {
                "style": {"name": "Operator Studio"},
                "colors": {
                    "primary": "#0f172a",
                    "secondary": "#1e293b",
                    "cta": "#10b981",
                    "background": "#f8fafc",
                    "text": "#0f172a",
                },
                "typography": {"heading": "IBM Plex Sans", "body": "Noto Sans JP"},
            },
        },
    )

    gap_ids = {item["id"] for item in audit["unresolved_gaps"]}

    assert "design-token-implementation-missing" in gap_ids
    assert "development-standards-artifact-missing" in gap_ids
    assert "value-contract-missing" in gap_ids
    assert "outcome-telemetry-contract-missing" in gap_ids
    assert "work-unit-contract-artifact-missing" in gap_ids
    assert "goal-spec-missing" in gap_ids
    assert "work-unit-contracts-missing" in gap_ids
    assert "delivery-waves-missing" in gap_ids
    assert "shift-left-quality-plan-missing" in gap_ids
    assert "access-control-artifact-missing" in gap_ids
    assert "operability-contract-missing" in gap_ids


# ---------------------------------------------------------------------------
# Semantic token helpers
# ---------------------------------------------------------------------------


def test_hex_to_relative_luminance_white() -> None:
    assert abs(_hex_to_relative_luminance("#FFFFFF") - 1.0) < 0.001


def test_hex_to_relative_luminance_black() -> None:
    assert abs(_hex_to_relative_luminance("#000000") - 0.0) < 0.001


def test_hex_to_relative_luminance_invalid_returns_zero() -> None:
    assert _hex_to_relative_luminance("#FFF") == 0.0
    assert _hex_to_relative_luminance("") == 0.0


def test_contrast_ratio_black_on_white() -> None:
    ratio = _contrast_ratio("#000000", "#FFFFFF")
    assert abs(ratio - 21.0) < 0.1


def test_contrast_ratio_same_color_is_one() -> None:
    ratio = _contrast_ratio("#336699", "#336699")
    assert abs(ratio - 1.0) < 0.01


def test_build_semantic_colors_produces_wcag_ratings() -> None:
    colors = {"primary": "#0f172a", "text": "#0f172a", "background": "#f8fafc"}
    result = _build_semantic_colors(colors, "#f8fafc")

    by_role = {item["role"]: item for item in result}
    assert "text" in by_role
    text_entry = by_role["text"]
    # Dark text on light bg should meet AA
    assert text_entry["meets_aa"] is True
    assert text_entry["wcag_contrast_against_bg"] is not None
    assert text_entry["wcag_contrast_against_bg"] >= 4.5

    # Background against itself should have ratio ~1:1
    bg_entry = by_role["background"]
    assert bg_entry["meets_aa"] is False


def test_build_semantic_colors_skips_notes_key() -> None:
    colors = {"primary": "#0f172a", "notes": "some note"}
    result = _build_semantic_colors(colors, "#ffffff")
    roles = [item["role"] for item in result]
    assert "notes" not in roles


def test_check_css_variable_usage_full_compliance() -> None:
    css = """:root {
        --color-brand-primary: #0f172a;
        --color-brand-secondary: #1e293b;
        --font-heading: "IBM Plex Sans";
    }"""
    expected = ["--color-brand-primary", "--color-brand-secondary", "--font-heading"]
    report = _check_css_variable_usage(css, expected)
    assert report["compliance_score"] == 1.0
    assert report["variables_missing"] == []
    assert len(report["variables_referenced"]) == 3


def test_check_css_variable_usage_partial_compliance() -> None:
    css = ":root { --color-brand-primary: #0f172a; }"
    expected = ["--color-brand-primary", "--color-brand-secondary", "--font-heading"]
    report = _check_css_variable_usage(css, expected)
    assert report["compliance_score"] < 1.0
    assert "--color-brand-secondary" in report["variables_missing"]
    assert "--font-heading" in report["variables_missing"]


def test_check_css_variable_usage_detects_hardcoded_colors() -> None:
    css = "body { color: #ff0000; background: var(--color-app-background); }"
    report = _check_css_variable_usage(css, ["--color-app-background"])
    assert "#ff0000" in report["hardcoded_colors_found"]


def test_check_css_variable_usage_empty_expected() -> None:
    report = _check_css_variable_usage("some code", [])
    assert report["compliance_score"] == 1.0


def test_design_token_contract_ready_rejects_low_contrast() -> None:
    """Text on background with insufficient contrast should fail."""
    analysis = {
        "design_tokens": {
            "style": {"name": "Low Contrast Theme"},
            "colors": {
                "primary": "#888888",
                "secondary": "#999999",
                "cta": "#aaaaaa",
                "background": "#cccccc",
                "text": "#bbbbbb",  # very low contrast against #cccccc
            },
            "typography": {"heading": "Arial", "body": "Helvetica"},
        }
    }
    assert _design_token_contract_ready(analysis) is False


def test_design_token_contract_ready_accepts_good_contrast() -> None:
    """Dark text on light background should pass."""
    analysis = {
        "design_tokens": {
            "style": {"name": "Operator Studio"},
            "colors": {
                "primary": "#0f172a",
                "secondary": "#1e293b",
                "cta": "#10b981",
                "background": "#f8fafc",
                "text": "#0f172a",
            },
            "typography": {"heading": "IBM Plex Sans", "body": "Noto Sans JP"},
        }
    }
    assert _design_token_contract_ready(analysis) is True


def test_design_token_contract_ready_returns_false_for_missing_fields() -> None:
    assert _design_token_contract_ready(None) is False
    assert _design_token_contract_ready({}) is False
    assert _design_token_contract_ready({"design_tokens": {"style": {"name": "X"}}}) is False
