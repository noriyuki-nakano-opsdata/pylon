"""Spec-driven workspace builders for lifecycle development."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from textwrap import dedent
from typing import Any, TypedDict

from pylon.lifecycle.services.value_contracts import (
    OUTCOME_TELEMETRY_CONTRACT_ID,
    OUTCOME_TELEMETRY_WORKSPACE_ARTIFACTS,
    REQUIRED_DELIVERY_CONTRACT_IDS,
    VALUE_CONTRACT_ID,
    VALUE_CONTRACT_WORKSPACE_ARTIFACTS,
    outcome_telemetry_contract_ready,
    value_contract_ready,
)
from pylon.prototyping import build_nextjs_prototype_app

_VITEST_VERSION = "^3.2.4"
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


class SemanticColor(TypedDict):
    """A color with semantic meaning and accessibility metadata."""

    hex: str
    role: str  # "primary", "secondary", "cta", "background", "text"
    wcag_contrast_against_bg: float | None  # Contrast ratio against background
    meets_aa: bool  # WCAG AA (4.5:1 for text, 3:1 for large text)
    meets_aaa: bool  # WCAG AAA (7:1 for text)


class TypographyScale(TypedDict):
    """Typography with scale information."""

    family: str
    role: str  # "heading", "body"
    fallback_stack: str  # CSS fallback fonts
    variable_name: str  # CSS custom property name


def _hex_to_relative_luminance(hex_color: str) -> float:
    """Calculate relative luminance per WCAG 2.1."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return 0.0
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate WCAG contrast ratio between two colors."""
    l1 = _hex_to_relative_luminance(hex1)
    l2 = _hex_to_relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _build_semantic_colors(colors: dict[str, str], bg_hex: str) -> list[SemanticColor]:
    """Build semantic color tokens with WCAG contrast info."""
    result: list[SemanticColor] = []
    for role, hex_val in colors.items():
        if not hex_val or role == "notes":
            continue
        ratio = _contrast_ratio(hex_val, bg_hex) if bg_hex else None
        result.append(
            {
                "hex": hex_val,
                "role": role,
                "wcag_contrast_against_bg": round(ratio, 2) if ratio else None,
                "meets_aa": ratio is not None and ratio >= 4.5,
                "meets_aaa": ratio is not None and ratio >= 7.0,
            }
        )
    return result


_CSS_HARDCODED_COLOR_RE = re.compile(
    r"(?:color|background|border|fill|stroke)\s*:\s*[\"']?(#[0-9a-fA-F]{6})[\"']?"
)


def _check_css_variable_usage(
    generated_code: str, expected_variables: list[str]
) -> dict[str, Any]:
    """Check if generated code properly uses CSS custom properties instead of hardcoded values.

    Uses regex-based analysis of the generated TypeScript/CSS code.
    Returns a report of usage compliance.
    """
    results: dict[str, Any] = {
        "total_expected": len(expected_variables),
        "variables_referenced": [],
        "variables_missing": [],
        "hardcoded_colors_found": [],
        "compliance_score": 0.0,
    }

    code_lower = generated_code.lower()

    # Check which CSS variables are actually referenced
    for var_name in expected_variables:
        # Check for var(--name) or --name usage
        if f"var({var_name})" in code_lower or f"{var_name}" in code_lower:
            results["variables_referenced"].append(var_name)
        else:
            results["variables_missing"].append(var_name)

    # Detect hardcoded hex colors that should be using variables
    hardcoded = _CSS_HARDCODED_COLOR_RE.findall(generated_code)
    results["hardcoded_colors_found"] = list(set(hardcoded))

    # Calculate compliance
    referenced_count = len(results["variables_referenced"])
    if results["total_expected"] > 0:
        results["compliance_score"] = round(
            referenced_count / results["total_expected"], 2
        )
    else:
        results["compliance_score"] = 1.0

    return results


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _ns(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _slug(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:48] or prefix


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = _ns(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _path_package(path: str) -> tuple[str, str, str]:
    normalized = str(path or "").strip().lstrip("./")
    lowered = normalized.lower()
    if lowered.startswith("app/api/"):
        return ("app-api", "API Routes", "app/api")
    if lowered.startswith("app/components/"):
        return ("app-components", "UI Components", "app/components")
    if lowered.startswith("app/lib/"):
        return ("app-lib", "App Libraries", "app/lib")
    if lowered.startswith("app/"):
        return ("app-routes", "App Routes", "app")
    if lowered.startswith("server/contracts/"):
        return ("server-contracts", "Server Contracts", "server/contracts")
    if lowered.startswith("server/domain/"):
        return ("server-domain", "Server Domain", "server/domain")
    if lowered.startswith("server/db/"):
        return ("server-db", "Persistence", "server/db")
    if lowered.startswith("server/"):
        return ("server-core", "Server Core", "server")
    if lowered.startswith("tests/"):
        return ("tests", "Acceptance Tests", "tests")
    if lowered.startswith("docs/"):
        return ("docs", "Specification Docs", "docs")
    return ("config", "Project Config", ".")


def _lane_for_path(path: str) -> str:
    lowered = str(path or "").lower()
    if lowered.startswith("server/"):
        return "backend-builder"
    if lowered.startswith("tests/"):
        return "qa-engineer"
    if lowered.startswith("docs/"):
        return "reviewer"
    if lowered in {"package.json", "tsconfig.json", "next-env.d.ts"}:
        return "integrator"
    return "frontend-builder"


def _text_matches_feature(text: str, feature: str) -> bool:
    lhs = _ns(text).lower()
    rhs = _ns(feature).lower()
    if not lhs or not rhs:
        return False
    if rhs in lhs:
        return True
    feature_tokens = [token for token in rhs.replace("/", " ").replace("-", " ").split() if len(token) >= 3]
    if not feature_tokens:
        return False
    return sum(1 for token in feature_tokens if token in lhs) >= max(1, min(2, len(feature_tokens)))


_AUTH_SCOPE_HINTS = (
    "auth",
    "authentication",
    "authorization",
    "login",
    "logout",
    "log in",
    "log out",
    "sign in",
    "sign out",
    "signin",
    "signout",
    "session",
    "sso",
    "oauth",
    "permission",
    "permissions",
    "role",
    "roles",
    "access control",
    "forbidden",
    "認証",
    "認可",
    "ログイン",
    "ログアウト",
    "セッション",
    "権限",
    "ロール",
    "アクセス制御",
)

_AUTH_UI_HINTS = (
    "login",
    "logout",
    "log in",
    "log out",
    "sign in",
    "sign out",
    "signin",
    "signout",
    "ログイン",
    "ログアウト",
)


def _text_contains_any(text: str, hints: tuple[str, ...]) -> bool:
    normalized = _ns(text).lower()
    return bool(normalized) and any(hint in normalized for hint in hints)


def _design_token_contract_ready(analysis: dict[str, Any] | None) -> bool:
    """Check if design tokens meet minimum requirements including accessibility."""
    design_tokens = _as_dict(_as_dict(analysis).get("design_tokens"))
    style = _as_dict(design_tokens.get("style"))
    colors = _as_dict(design_tokens.get("colors"))
    typography = _as_dict(design_tokens.get("typography"))

    # Basic presence checks
    has_basics = (
        bool(_ns(style.get("name")))
        and all(_ns(colors.get(key)) for key in ("primary", "secondary", "cta", "background", "text"))
        and bool(_ns(typography.get("heading")))
        and bool(_ns(typography.get("body")))
    )
    if not has_basics:
        return False

    # WCAG contrast check: text color must meet AA against background
    bg = str(colors.get("background") or "")
    text = str(colors.get("text") or "")
    if bg.startswith("#") and text.startswith("#") and len(bg) == 7 and len(text) == 7:
        ratio = _contrast_ratio(text, bg)
        if ratio < 4.5:
            return False

    return True


def _interaction_principles(selected_design: dict[str, Any] | None, analysis: dict[str, Any] | None) -> list[str]:
    prototype = _as_dict(_as_dict(selected_design).get("prototype"))
    design_tokens = _as_dict(_as_dict(analysis).get("design_tokens"))
    direct_principles = _as_list(prototype.get("interaction_principles") or prototype.get("interactionPrinciples"))
    token_effects = _as_list(design_tokens.get("effects"))
    return _unique_strings([*direct_principles, *token_effects])


def _role_permission_counts(analysis: dict[str, Any] | None) -> tuple[int, int]:
    roles = [_as_dict(item) for item in _as_list(_as_dict(analysis).get("roles")) if _as_dict(item)]
    named_roles = [item for item in roles if _ns(item.get("name"))]
    permission_count = sum(
        1
        for role in named_roles
        for permission in _as_list(role.get("permissions"))
        if _ns(permission)
    )
    return len(named_roles), permission_count


def _selected_design_surface_texts(selected_design: dict[str, Any] | None) -> list[str]:
    design = _as_dict(selected_design)
    prototype = _as_dict(design.get("prototype"))
    prototype_spec = _as_dict(design.get("prototype_spec") or design.get("prototypeSpec"))
    surface_texts: list[str] = []
    for item in _as_list(design.get("screen_specs") or design.get("screenSpecs")):
        record = _as_dict(item)
        surface_texts.extend(
            [
                _ns(record.get("id")),
                _ns(record.get("title")),
                _ns(record.get("purpose")),
                _ns(record.get("layout")),
                _ns(record.get("route_path") or record.get("routePath")),
                *[_ns(action) for action in _as_list(record.get("primary_actions") or record.get("primaryActions")) if _ns(action)],
            ]
        )
    for item in _as_list(prototype.get("screens")):
        record = _as_dict(item)
        surface_texts.extend(
            [
                _ns(record.get("id")),
                _ns(record.get("title")),
                _ns(record.get("purpose")),
                _ns(record.get("headline")),
                _ns(record.get("supporting_text") or record.get("supportingText")),
                *[_ns(action) for action in _as_list(record.get("primary_actions") or record.get("primaryActions")) if _ns(action)],
            ]
        )
    for item in _as_list(prototype_spec.get("routes")):
        record = _as_dict(item)
        surface_texts.extend(
            [
                _ns(record.get("id")),
                _ns(record.get("screen_id") or record.get("screenId")),
                _ns(record.get("path")),
                _ns(record.get("title")),
                _ns(record.get("headline")),
                _ns(record.get("layout")),
                *[_ns(action) for action in _as_list(record.get("primary_actions") or record.get("primaryActions")) if _ns(action)],
                *[_ns(state) for state in _as_list(record.get("states")) if _ns(state)],
            ]
        )
    return [text for text in surface_texts if text]


def _auth_scope_explicit(
    *,
    selected_features: list[str],
    requirement_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    api_specification: list[dict[str, Any]],
    planning_analysis: dict[str, Any] | None,
    selected_design: dict[str, Any] | None,
) -> bool:
    candidate_texts: list[str] = [str(feature) for feature in selected_features if _ns(feature)]
    for requirement in requirement_rows:
        candidate_texts.extend(
            [
                _ns(requirement.get("statement")),
                *[_ns(item) for item in _as_list(requirement.get("acceptanceCriteria")) if _ns(item)],
            ]
        )
    for task in task_rows:
        candidate_texts.extend([_ns(task.get("title")), _ns(task.get("description"))])
    for endpoint in api_specification:
        candidate_texts.extend([_ns(endpoint.get("path")), _ns(endpoint.get("description"))])
    candidate_texts.extend(_selected_design_surface_texts(selected_design))
    return any(_text_contains_any(text, _AUTH_SCOPE_HINTS) for text in candidate_texts)


def _auth_ui_requested(
    *,
    selected_features: list[str],
    requirement_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    planning_analysis: dict[str, Any] | None,
) -> bool:
    texts: list[str] = [str(feature) for feature in selected_features if _ns(feature)]
    for requirement in requirement_rows:
        texts.extend(
            [
                _ns(requirement.get("statement")),
                *[_ns(item) for item in _as_list(requirement.get("acceptanceCriteria")) if _ns(item)],
            ]
        )
    for task in task_rows:
        texts.extend([_ns(task.get("title")), _ns(task.get("description"))])
    return any(_text_contains_any(text, _AUTH_UI_HINTS) for text in texts)


def _auth_surface_present(selected_design: dict[str, Any] | None, api_specification: list[dict[str, Any]]) -> bool:
    surface_texts = _selected_design_surface_texts(selected_design)
    api_texts = [
        " ".join([_ns(item.get("path")), _ns(item.get("description"))])
        for item in api_specification
    ]
    return any(_text_contains_any(text, _AUTH_UI_HINTS) for text in [*surface_texts, *api_texts])


def _render_api_contract_file(
    api_specification: list[dict[str, Any]],
    interface_definitions: list[dict[str, Any]],
) -> str:
    interface_blocks = []
    for interface in interface_definitions[:12]:
        name = _ns(interface.get("name")) or "GeneratedInterface"
        parents = [_ns(item) for item in _as_list(interface.get("extends")) if _ns(item)]
        header = f"export interface {name}"
        if parents:
            header += " extends " + ", ".join(parents)
        header += " {"
        properties = []
        for prop in _as_list(interface.get("properties"))[:20]:
            record = _as_dict(prop)
            prop_name = _ns(record.get("name")) or "value"
            prop_type = _ns(record.get("type")) or "unknown"
            optional = "?" if record.get("optional") is True else ""
            properties.append(f"  {prop_name}{optional}: {prop_type};")
        interface_blocks.append("\n".join([header, *properties, "}"]))
    endpoint_payload = [
        {
            "method": _ns(item.get("method") or "GET"),
            "path": _ns(item.get("path") or "/"),
            "description": _ns(item.get("description")),
            "authRequired": bool(item.get("authRequired", True)),
        }
        for item in api_specification[:20]
    ]
    return "\n".join(
        [
            "/* Auto-generated from technical design for the autonomous delivery mesh. */",
            "",
            *interface_blocks,
            "",
            f"export const apiSpecification = {json.dumps(endpoint_payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_domain_models_file(interface_definitions: list[dict[str, Any]]) -> str:
    model_blocks = []
    for interface in interface_definitions[:12]:
        name = _ns(interface.get("name")) or "GeneratedModel"
        properties = []
        for prop in _as_list(interface.get("properties"))[:20]:
            record = _as_dict(prop)
            prop_name = _ns(record.get("name")) or "value"
            prop_type = _ns(record.get("type")) or "unknown"
            optional = "?" if record.get("optional") is True else ""
            properties.append(f"  {prop_name}{optional}: {prop_type};")
        model_blocks.append("\n".join([f"export type {name} = {{", *properties, "};"]))
    return "\n".join(
        [
            "/* Domain-facing types derived from the technical design bundle. */",
            "",
            *model_blocks,
            "",
        ]
    ).strip() + "\n"


def _render_schema_file(database_schema: list[dict[str, Any]]) -> str:
    sections: list[str] = ["-- Auto-generated schema sketch for lifecycle development."]
    for table in database_schema[:12]:
        name = _ns(table.get("name")) or "generated_table"
        columns: list[str] = []
        primary_keys: list[str] = []
        for raw_column in _as_list(table.get("columns"))[:32]:
            column = _as_dict(raw_column)
            column_name = _ns(column.get("name")) or "column_name"
            column_type = _ns(column.get("type")) or "TEXT"
            nullable = "" if column.get("nullable") is True else " NOT NULL"
            columns.append(f"  {column_name} {column_type}{nullable}")
            if column.get("primaryKey") is True:
                primary_keys.append(column_name)
        if primary_keys:
            columns.append(f"  PRIMARY KEY ({', '.join(primary_keys)})")
        sections.append(f"CREATE TABLE {name} (\n" + ",\n".join(columns) + "\n);")
        indexes = [_ns(item) for item in _as_list(table.get("indexes")) if _ns(item)]
        for index in indexes[:6]:
            sections.append(f"-- index: {index}")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def _render_acceptance_spec(requirements: list[dict[str, Any]]) -> str:
    cases = []
    for requirement in requirements[:12]:
        statement = _ns(requirement.get("statement")) or "Generated requirement"
        requirement_id = _ns(requirement.get("id")) or "REQ"
        criteria = [
            _ns(item)
            for item in _as_list(requirement.get("acceptanceCriteria") or requirement.get("acceptance_criteria"))
            if _ns(item)
        ][:3]
        comments = "\n".join(f"    // {criterion}" for criterion in criteria) if criteria else "    // Acceptance criteria to wire here."
        cases.append(
            "\n".join(
                [
                    f'describe("{requirement_id}", () => {{',
                    f'  it("{statement}", async () => {{',
                    comments,
                    "    expect(true).toBe(true);",
                    "  });",
                    "});",
                ]
            )
        )
    return "\n".join(
        [
            'import { describe, expect, it } from "vitest";',
            "",
            "/* Acceptance coverage scaffold generated from EARS requirements. */",
            "",
            *cases,
            "",
        ]
    ).strip() + "\n"


def _render_traceability_doc(
    selected_features: list[str],
    requirements: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> str:
    lines = [
        "# Development Traceability",
        "",
        "| Feature | Requirement coverage | Task coverage |",
        "| --- | --- | --- |",
    ]
    for feature in selected_features[:16]:
        requirement_hits = sum(
            1
            for requirement in requirements
            if _text_matches_feature(
                " ".join(
                    [
                        _ns(requirement.get("statement")),
                        *[_ns(item) for item in _as_list(requirement.get("acceptanceCriteria")) if _ns(item)],
                    ]
                ),
                feature,
            )
        )
        task_hits = sum(
            1
            for task in tasks
            if _text_matches_feature(
                " ".join([_ns(task.get("title")), _ns(task.get("description"))]),
                feature,
            )
        )
        lines.append(f"| {feature} | {requirement_hits} | {task_hits} |")
    return "\n".join(lines).rstrip() + "\n"


def _planning_roles(planning_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        _as_dict(item)
        for item in _as_list(_as_dict(planning_analysis).get("roles"))
        if _as_dict(item) and _ns(_as_dict(item).get("name"))
    ]


def _design_token_payload(planning_analysis: dict[str, Any] | None) -> dict[str, Any]:
    design_tokens = _as_dict(_as_dict(planning_analysis).get("design_tokens"))
    colors = _as_dict(design_tokens.get("colors"))
    bg_hex = str(colors.get("background") or "#020617")
    text_hex = str(colors.get("text") or "#F8FAFC")
    cta_hex = str(colors.get("cta") or "#22C55E")

    semantic_colors = _build_semantic_colors(
        {k: str(v) for k, v in colors.items() if k != "notes"},
        bg_hex,
    )

    return {
        "style": _as_dict(design_tokens.get("style")),
        "colors": colors,
        "typography": _as_dict(design_tokens.get("typography")),
        "effects": [_ns(item) for item in _as_list(design_tokens.get("effects")) if _ns(item)],
        "anti_patterns": [_ns(item) for item in _as_list(design_tokens.get("anti_patterns")) if _ns(item)],
        "rationale": _ns(design_tokens.get("rationale")),
        "semantic_colors": semantic_colors,
        "accessibility": {
            "text_contrast_ratio": _contrast_ratio(text_hex, bg_hex),
            "cta_contrast_ratio": _contrast_ratio(cta_hex, bg_hex),
        },
    }


def _auth_surface_inventory(selected_design: dict[str, Any] | None) -> list[str]:
    design = _as_dict(selected_design)
    prototype = _as_dict(design.get("prototype"))
    prototype_spec = _as_dict(design.get("prototype_spec") or design.get("prototypeSpec"))
    inventory: list[str] = []
    for raw in _as_list(design.get("screen_specs") or design.get("screenSpecs")):
        record = _as_dict(raw)
        label = " / ".join(
            part
            for part in (
                _ns(record.get("title")),
                _ns(record.get("route_path") or record.get("routePath")),
            )
            if part
        )
        if label and _text_contains_any(label, _AUTH_SCOPE_HINTS):
            inventory.append(label)
    for raw in _as_list(prototype.get("screens")):
        record = _as_dict(raw)
        label = " / ".join(
            part
            for part in (
                _ns(record.get("title")),
                _ns(record.get("headline")),
                _ns(record.get("purpose")),
            )
            if part
        )
        if label and _text_contains_any(label, _AUTH_SCOPE_HINTS):
            inventory.append(label)
    for raw in _as_list(prototype_spec.get("routes")):
        record = _as_dict(raw)
        label = " / ".join(
            part
            for part in (
                _ns(record.get("title")),
                _ns(record.get("path")),
                _ns(record.get("headline")),
            )
            if part
        )
        if label and _text_contains_any(label, _AUTH_SCOPE_HINTS):
            inventory.append(label)
    return _unique_strings(inventory)


def _build_audit_events(
    *,
    api_specification: list[dict[str, Any]],
    selected_features: list[str],
    milestones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    method_to_action = {
        "GET": "read",
        "POST": "mutate",
        "PUT": "replace",
        "PATCH": "update",
        "DELETE": "delete",
    }
    events: list[dict[str, Any]] = []
    for endpoint in api_specification[:24]:
        method = _ns(endpoint.get("method") or "GET").upper()
        path = _ns(endpoint.get("path") or "/")
        description = _ns(endpoint.get("description"))
        path_parts = [
            segment
            for segment in path.strip("/").split("/")
            if segment and not segment.startswith("[")
        ]
        resource = path_parts[-1] if path_parts else "root"
        events.append(
            {
                "name": f"{resource}.{method_to_action.get(method, 'execute')}",
                "trigger": f"{method} {path}",
                "signal": description or f"{resource} {method.lower()} activity",
                "sensitive": bool(endpoint.get("authRequired", True)),
            }
        )
    if any(bool(item.get("authRequired", True)) for item in api_specification):
        events.extend(
            [
                {
                    "name": "session.signed_in",
                    "trigger": "Successful authentication",
                    "signal": "Identity and session establishment",
                    "sensitive": True,
                },
                {
                    "name": "session.access_denied",
                    "trigger": "Authorization failure",
                    "signal": "Forbidden access attempt recorded with actor context",
                    "sensitive": True,
                },
            ]
        )
    for feature in selected_features[:8]:
        if not _ns(feature):
            continue
        feature_slug = _slug(feature, prefix="feature").replace("-", "_")
        events.append(
            {
                "name": f"feature.{feature_slug}.checked",
                "trigger": f"Feature readiness for {feature}",
                "signal": "Feature-level execution and readiness telemetry",
                "sensitive": False,
            }
        )
    for milestone in milestones[:8]:
        name = _ns(_as_dict(milestone).get("name"))
        if not name:
            continue
        milestone_slug = _slug(name, prefix="milestone").replace("-", "_")
        events.append(
            {
                "name": f"release.{milestone_slug}.evaluated",
                "trigger": name,
                "signal": _ns(_as_dict(milestone).get("criteria")) or "Milestone readiness check",
                "sensitive": False,
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        key = _ns(event.get("name"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _render_design_tokens_module(planning_analysis: dict[str, Any] | None) -> str:
    if not _design_token_contract_ready(planning_analysis):
        return ""
    payload = _design_token_payload(planning_analysis)
    css_variables = _render_design_token_css_variables(planning_analysis)
    return "\n".join(
        [
            "/* Approved design token contract for autonomous delivery. */",
            "",
            f"export const designTokenContract = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;",
            "",
            f"export const designTokenCssVariables = {json.dumps(css_variables, ensure_ascii=False)};",
            "",
        ]
    ).strip() + "\n"


def _render_design_system_doc(planning_analysis: dict[str, Any] | None) -> str:
    if not _design_token_contract_ready(planning_analysis):
        return ""
    payload = _design_token_payload(planning_analysis)
    style = _as_dict(payload.get("style"))
    colors = _as_dict(payload.get("colors"))
    typography = _as_dict(payload.get("typography"))
    lines = [
        "# Design System Contract",
        "",
        f"- Style: {_ns(style.get('name'))}",
        f"- Rationale: {_ns(payload.get('rationale'))}",
        f"- Best for: {_ns(style.get('best_for'))}",
        f"- Accessibility posture: {_ns(style.get('accessibility'))}",
        "",
        "## Semantic Colors",
        "",
        "| Token | Value |",
        "| --- | --- |",
        f"| primary | {_ns(colors.get('primary'))} |",
        f"| secondary | {_ns(colors.get('secondary'))} |",
        f"| cta | {_ns(colors.get('cta'))} |",
        f"| background | {_ns(colors.get('background'))} |",
        f"| text | {_ns(colors.get('text'))} |",
        "",
        "## Typography",
        "",
        f"- Heading: {_ns(typography.get('heading'))}",
        f"- Body: {_ns(typography.get('body'))}",
    ]
    mood = [_ns(item) for item in _as_list(typography.get("mood")) if _ns(item)]
    if mood:
        lines.append(f"- Mood: {', '.join(mood)}")
    effects = [_ns(item) for item in _as_list(payload.get("effects")) if _ns(item)]
    if effects:
        lines.extend(["", "## Interaction Effects", ""])
        lines.extend(f"- {item}" for item in effects)
    anti_patterns = [_ns(item) for item in _as_list(payload.get("anti_patterns")) if _ns(item)]
    if anti_patterns:
        lines.extend(["", "## Anti-patterns", ""])
        lines.extend(f"- {item}" for item in anti_patterns)
    return "\n".join(lines).rstrip() + "\n"


def _render_access_policy_file(
    planning_analysis: dict[str, Any] | None,
    api_specification: list[dict[str, Any]],
    selected_design: dict[str, Any] | None,
) -> str:
    roles = _planning_roles(planning_analysis)
    protected_endpoints = [
        {
            "method": _ns(item.get("method") or "GET"),
            "path": _ns(item.get("path") or "/"),
            "description": _ns(item.get("description")),
        }
        for item in api_specification[:24]
        if bool(item.get("authRequired", True))
    ]
    auth_surfaces = _auth_surface_inventory(selected_design)
    if not roles and not protected_endpoints and not auth_surfaces:
        return ""
    payload = {
        "roles": [
            {
                "name": _ns(role.get("name")),
                "responsibilities": [_ns(item) for item in _as_list(role.get("responsibilities")) if _ns(item)],
                "permissions": [_ns(item) for item in _as_list(role.get("permissions")) if _ns(item)],
                "relatedActors": [_ns(item) for item in _as_list(role.get("related_actors")) if _ns(item)],
            }
            for role in roles[:12]
        ],
        "protectedApi": protected_endpoints,
        "authSurfaces": auth_surfaces,
    }
    return "\n".join(
        [
            "/* Access-control contract generated from planning and technical design. */",
            "",
            f"export const accessPolicy = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_access_control_doc(
    planning_analysis: dict[str, Any] | None,
    api_specification: list[dict[str, Any]],
    selected_design: dict[str, Any] | None,
) -> str:
    roles = _planning_roles(planning_analysis)
    protected_endpoints = [
        item for item in api_specification if bool(item.get("authRequired", True))
    ]
    auth_surfaces = _auth_surface_inventory(selected_design)
    if not roles and not protected_endpoints and not auth_surfaces:
        return ""
    lines = [
        "# Access Control Contract",
        "",
        f"- Protected endpoint count: {len(protected_endpoints)}",
        f"- Auth surface count: {len(auth_surfaces)}",
        "",
        "## Roles",
        "",
    ]
    if not roles:
        lines.append("- No named roles were provided.")
    for role in roles[:12]:
        permissions = [_ns(item) for item in _as_list(role.get("permissions")) if _ns(item)]
        responsibilities = [_ns(item) for item in _as_list(role.get("responsibilities")) if _ns(item)]
        lines.append(f"- {_ns(role.get('name'))}: permissions={', '.join(permissions) or 'none'}; responsibilities={', '.join(responsibilities) or 'none'}")
    lines.extend(["", "## Protected API", ""])
    if not protected_endpoints:
        lines.append("- No protected endpoints were declared.")
    for endpoint in protected_endpoints[:24]:
        lines.append(f"- {_ns(endpoint.get('method'))} {_ns(endpoint.get('path'))}: {_ns(endpoint.get('description'))}")
    if auth_surfaces:
        lines.extend(["", "## Auth Surfaces", ""])
        lines.extend(f"- {surface}" for surface in auth_surfaces[:12])
    return "\n".join(lines).rstrip() + "\n"


def _render_audit_events_file(
    *,
    api_specification: list[dict[str, Any]],
    selected_features: list[str],
    milestones: list[dict[str, Any]],
) -> str:
    events = _build_audit_events(
        api_specification=api_specification,
        selected_features=selected_features,
        milestones=milestones,
    )
    if not events:
        return ""
    return "\n".join(
        [
            "/* Audit and telemetry events expected from the autonomous delivery workspace. */",
            "",
            f"export const auditEvents = {json.dumps(events, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_operability_doc(
    *,
    selected_features: list[str],
    milestones: list[dict[str, Any]],
    api_specification: list[dict[str, Any]],
) -> str:
    audit_events = _build_audit_events(
        api_specification=api_specification,
        selected_features=selected_features,
        milestones=milestones,
    )
    if not selected_features and not milestones and not api_specification:
        return ""
    protected_count = sum(1 for item in api_specification if bool(item.get("authRequired", True)))
    lines = [
        "# Operability Contract",
        "",
        f"- Feature count: {len([item for item in selected_features if _ns(item)])}",
        f"- API surface count: {len(api_specification)}",
        f"- Protected endpoint count: {protected_count}",
        "",
        "## Promotion Signals",
        "",
        "- repo execution must pass install/build/test",
        "- deploy handoff must be free of blocking issues",
        "- milestone checks must be fully satisfied before promotion",
    ]
    if milestones:
        lines.extend(["", "## Milestones", ""])
        lines.extend(
            f"- {_ns(_as_dict(item).get('name'))}: {_ns(_as_dict(item).get('criteria')) or 'readiness criteria pending'}"
            for item in milestones[:12]
            if _ns(_as_dict(item).get("name"))
        )
    if audit_events:
        lines.extend(["", "## Audit Events", ""])
        lines.extend(
            f"- {_ns(event.get('name'))}: {_ns(event.get('signal'))}"
            for event in audit_events[:16]
            if _ns(event.get("name"))
        )
    return "\n".join(lines).rstrip() + "\n"


def _development_standards_payload(
    *,
    planning_analysis: dict[str, Any] | None,
    selected_design: dict[str, Any] | None,
    selected_features: list[str],
    api_specification: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> dict[str, Any]:
    roles = _planning_roles(planning_analysis)
    auth_surfaces = _auth_surface_inventory(selected_design)
    audit_events = _build_audit_events(
        api_specification=api_specification,
        selected_features=selected_features,
        milestones=milestones,
    )
    protected_api = [item for item in api_specification if bool(item.get("authRequired", True))]
    return {
        "ui_rules": _unique_strings(
            [
                "Use approved design tokens from app/lib/design-tokens.ts and CSS variables from app/globals.css for color, typography, and radius decisions.",
                "Route surfaces must preserve the selected prototype shell and keep navigation, screen hierarchy, and interaction notes intact.",
                "Do not introduce hard-coded brand colors or fonts in feature files; extend the token contract instead.",
            ]
        ),
        "security_rules": _unique_strings(
            [
                "Protected endpoints must remain explicit in server/contracts/api-contract.ts with authRequired truth preserved.",
                "Identity, role, and permission boundaries must be grounded in server/contracts/access-policy.ts before promotion.",
                "Approval and release actions must not bypass sign-in, session, or forbidden states represented in the selected design.",
            ]
            + (
                [f"Auth-facing surfaces in scope: {', '.join(auth_surfaces[:4])}"]
                if auth_surfaces
                else []
            )
        ),
        "operability_rules": _unique_strings(
            [
                "Audit and release-significant flows must map to server/contracts/audit-events.ts and docs/spec/operability.md.",
                "Repo execution, milestone evidence, and deploy handoff readiness remain the source of truth for promotion.",
                *[
                    _ns(_as_dict(item).get("criteria"))
                    for item in milestones[:8]
                    if _ns(_as_dict(item).get("criteria"))
                ],
            ]
        ),
        "coding_rules": _unique_strings(
            [
                "Prefer typed contracts and named exports for generated support modules.",
                "Keep acceptance-critical flows covered in tests/acceptance before autonomous promotion.",
                "Preserve route bindings, package boundaries, and conflict-safe ownership from the delivery plan.",
                "Implementation changes should extend the standards contract instead of introducing one-off exceptions.",
            ]
        ),
        "required_artifacts": [
            "app/lib/design-tokens.ts",
            "app/lib/development-standards.ts",
            "app/lib/value-contract.ts",
            "server/contracts/access-policy.ts" if protected_api or roles or auth_surfaces else "",
            "server/contracts/audit-events.ts" if audit_events else "",
            "server/contracts/outcome-telemetry.ts",
            "docs/spec/design-system.md",
            "docs/spec/development-standards.md",
            "docs/spec/value-contract.md",
            "docs/spec/access-control.md" if protected_api or roles or auth_surfaces else "",
            "docs/spec/operability.md" if audit_events else "",
            "docs/spec/outcome-telemetry.md",
        ],
        "prototype_features": [feature for feature in selected_features if _ns(feature)][:12],
        "role_names": [_ns(role.get("name")) for role in roles[:12] if _ns(role.get("name"))],
        "protected_api_count": len(protected_api),
        "audit_event_count": len(audit_events),
    }


def _render_development_standards_module(
    *,
    planning_analysis: dict[str, Any] | None,
    selected_design: dict[str, Any] | None,
    selected_features: list[str],
    api_specification: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> str:
    payload = _development_standards_payload(
        planning_analysis=planning_analysis,
        selected_design=selected_design,
        selected_features=selected_features,
        api_specification=api_specification,
        milestones=milestones,
    )
    if not any(_as_list(payload.get(key)) for key in ("ui_rules", "security_rules", "operability_rules", "coding_rules")):
        return ""
    payload["required_artifacts"] = [
        item for item in _as_list(payload.get("required_artifacts")) if _ns(item)
    ]
    return "\n".join(
        [
            "/* Standard development rules for autonomous prototype implementation. */",
            "",
            f"export const developmentStandards = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_development_standards_doc(
    *,
    planning_analysis: dict[str, Any] | None,
    selected_design: dict[str, Any] | None,
    selected_features: list[str],
    api_specification: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> str:
    payload = _development_standards_payload(
        planning_analysis=planning_analysis,
        selected_design=selected_design,
        selected_features=selected_features,
        api_specification=api_specification,
        milestones=milestones,
    )
    if not any(_as_list(payload.get(key)) for key in ("ui_rules", "security_rules", "operability_rules", "coding_rules")):
        return ""
    lines = [
        "# Development Standards",
        "",
        "## UI Rules",
        "",
    ]
    lines.extend(f"- {item}" for item in _as_list(payload.get("ui_rules")) if _ns(item))
    lines.extend(["", "## Security Rules", ""])
    lines.extend(f"- {item}" for item in _as_list(payload.get("security_rules")) if _ns(item))
    lines.extend(["", "## Operability Rules", ""])
    lines.extend(f"- {item}" for item in _as_list(payload.get("operability_rules")) if _ns(item))
    lines.extend(["", "## Coding Rules", ""])
    lines.extend(f"- {item}" for item in _as_list(payload.get("coding_rules")) if _ns(item))
    required_artifacts = [item for item in _as_list(payload.get("required_artifacts")) if _ns(item)]
    if required_artifacts:
        lines.extend(["", "## Required Artifacts", ""])
        lines.extend(f"- {item}" for item in required_artifacts)
    return "\n".join(lines).rstrip() + "\n"


def _render_value_contract_module(value_contract: dict[str, Any] | None) -> str:
    payload = _as_dict(value_contract)
    if not value_contract_ready(payload):
        return ""
    return "\n".join(
        [
            "/* Compiled planning value contract for downstream autonomous delivery. */",
            "",
            f"export const valueContract = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_value_contract_doc(value_contract: dict[str, Any] | None) -> str:
    payload = _as_dict(value_contract)
    if not value_contract_ready(payload):
        return ""
    ia = _as_dict(payload.get("information_architecture"))
    lines = [
        "# Value Contract",
        "",
        _ns(payload.get("summary")) or "Planning analysis is compiled into a downstream value contract.",
        "",
        "## Personas",
        "",
    ]
    for item in _as_list(payload.get("primary_personas"))[:4]:
        persona = _as_dict(item)
        lines.append(
            f"- {_ns(persona.get('name')) or 'Persona'}: {_ns(persona.get('role')) or 'role unspecified'}"
        )
    lines.extend(["", "## Job Stories", ""])
    for item in _as_list(payload.get("job_stories"))[:6]:
        story = _as_dict(item)
        lines.append(
            f"- {_ns(story.get('title')) or 'Job story'}"
        )
    lines.extend(["", "## IA Key Paths", ""])
    for item in _as_list(ia.get("key_paths"))[:6]:
        path = _as_dict(item)
        lines.append(
            f"- {_ns(path.get('name')) or 'Path'}: {', '.join(_ns(step) for step in _as_list(path.get('steps')) if _ns(step)) or '—'}"
        )
    lines.extend(["", "## Success Metrics", ""])
    for item in _as_list(payload.get("success_metrics"))[:8]:
        metric = _as_dict(item)
        lines.append(
            f"- {_ns(metric.get('name'))}: {_ns(metric.get('signal')) or _ns(metric.get('target'))}"
        )
    kill_criteria = [_ns(item) for item in _as_list(payload.get("kill_criteria")) if _ns(item)]
    if kill_criteria:
        lines.extend(["", "## Kill Criteria", ""])
        lines.extend(f"- {item}" for item in kill_criteria[:8])
    return "\n".join(lines).rstrip() + "\n"


def _render_outcome_telemetry_module(outcome_telemetry_contract: dict[str, Any] | None) -> str:
    payload = _as_dict(outcome_telemetry_contract)
    if not outcome_telemetry_contract_ready(payload):
        return ""
    return "\n".join(
        [
            "/* Outcome telemetry contract for release and iteration readiness. */",
            "",
            f"export const outcomeTelemetryContract = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_outcome_telemetry_doc(outcome_telemetry_contract: dict[str, Any] | None) -> str:
    payload = _as_dict(outcome_telemetry_contract)
    if not outcome_telemetry_contract_ready(payload):
        return ""
    lines = [
        "# Outcome Telemetry Contract",
        "",
        _ns(payload.get("summary")) or "Release observability is compiled into a downstream outcome telemetry contract.",
        "",
        "## Success Metrics",
        "",
    ]
    for item in _as_list(payload.get("success_metrics"))[:8]:
        metric = _as_dict(item)
        lines.append(f"- {_ns(metric.get('name'))}: {_ns(metric.get('signal')) or _ns(metric.get('target'))}")
    lines.extend(["", "## Telemetry Events", ""])
    for item in _as_list(payload.get("telemetry_events"))[:12]:
        event = _as_dict(item)
        lines.append(
            f"- {_ns(event.get('name'))}: {_ns(event.get('purpose')) or 'release telemetry event'}"
        )
    kill_criteria = [_ns(item) for item in _as_list(payload.get("kill_criteria")) if _ns(item)]
    if kill_criteria:
        lines.extend(["", "## Kill Criteria", ""])
        lines.extend(f"- {item}" for item in kill_criteria[:8])
    release_checks = [_as_dict(item) for item in _as_list(payload.get("release_checks")) if _as_dict(item)]
    if release_checks:
        lines.extend(["", "## Release Checks", ""])
        for check in release_checks[:8]:
            lines.append(f"- {_ns(check.get('title'))}: {_ns(check.get('detail'))}")
    return "\n".join(lines).rstrip() + "\n"


def _render_work_unit_contracts_module(
    *,
    goal_spec: dict[str, Any] | None = None,
    dependency_analysis: dict[str, Any] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    waves: list[dict[str, Any]] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
) -> str:
    payload = {
        "goalSpec": _as_dict(goal_spec),
        "dependencyAnalysis": _as_dict(dependency_analysis),
        "waves": [
            {
                "waveIndex": int(_as_dict(item).get("wave_index", 0) or 0),
                "workUnitIds": [_ns(unit_id) for unit_id in _as_list(_as_dict(item).get("work_unit_ids")) if _ns(unit_id)],
                "laneIds": [_ns(lane_id) for lane_id in _as_list(_as_dict(item).get("lane_ids")) if _ns(lane_id)],
                "entryCriteria": [_ns(text) for text in _as_list(_as_dict(item).get("entry_criteria")) if _ns(text)],
                "exitCriteria": [_ns(text) for text in _as_list(_as_dict(item).get("exit_criteria")) if _ns(text)],
            }
            for item in _as_list(waves)
            if _as_dict(item)
        ],
        "workUnitContracts": [
            {
                "id": _ns(item.get("id")),
                "workPackageId": _ns(item.get("work_package_id")),
                "title": _ns(item.get("title")),
                "lane": _ns(item.get("lane")),
                "waveIndex": int(item.get("wave_index", 0) or 0),
                "dependsOn": [_ns(dep) for dep in _as_list(item.get("depends_on")) if _ns(dep)],
                "featureNames": [_ns(feature) for feature in _as_list(item.get("feature_names")) if _ns(feature)],
                "requirementIds": [_ns(requirement_id) for requirement_id in _as_list(item.get("requirement_ids")) if _ns(requirement_id)],
                "milestoneIds": [_ns(milestone_id) for milestone_id in _as_list(item.get("milestone_ids")) if _ns(milestone_id)],
                "routePaths": [_ns(path) for path in _as_list(item.get("route_paths")) if _ns(path)],
                "apiPaths": [
                    {
                        "method": _ns(_as_dict(api_item).get("method")),
                        "path": _ns(_as_dict(api_item).get("path")),
                    }
                    for api_item in _as_list(item.get("api_surface"))
                    if _as_dict(api_item)
                ],
                "deliverables": [_ns(deliverable) for deliverable in _as_list(item.get("deliverables")) if _ns(deliverable)],
                "acceptanceCriteria": [_ns(criterion) for criterion in _as_list(item.get("acceptance_criteria")) if _ns(criterion)],
                "requiredContracts": [_ns(contract_id) for contract_id in _as_list(item.get("required_contracts")) if _ns(contract_id)],
                "qaChecks": [_ns(text) for text in _as_list(item.get("qa_checks")) if _ns(text)],
                "securityChecks": [_ns(text) for text in _as_list(item.get("security_checks")) if _ns(text)],
                "integrationChecks": [_ns(text) for text in _as_list(item.get("integration_checks")) if _ns(text)],
                "valueTargets": [
                    {
                        "metricId": _ns(_as_dict(metric).get("metric_id")),
                        "metricName": _ns(_as_dict(metric).get("metric_name")),
                    }
                    for metric in _as_list(item.get("value_targets"))
                    if _as_dict(metric)
                ],
                "telemetryEvents": [
                    {
                        "id": _ns(_as_dict(event).get("id")),
                        "name": _ns(_as_dict(event).get("name")),
                    }
                    for event in _as_list(item.get("telemetry_events"))
                    if _as_dict(event)
                ],
            }
            for item in _as_list(work_unit_contracts)
            if _as_dict(item)
        ],
        "shiftLeftPlan": _as_dict(shift_left_plan),
    }
    if not payload["workUnitContracts"] and not payload["waves"] and not payload["goalSpec"]:
        return ""
    return (
        "/* Work-unit contracts and wave topology for autonomous development. */\n\n"
        f"export const deliveryExecutionPlan = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;\n"
    )


def _render_work_unit_contracts_doc(
    *,
    goal_spec: dict[str, Any] | None = None,
    dependency_analysis: dict[str, Any] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    waves: list[dict[str, Any]] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
) -> str:
    goal = _as_dict(goal_spec)
    dependency = _as_dict(dependency_analysis)
    units = [_as_dict(item) for item in _as_list(work_unit_contracts) if _as_dict(item)]
    wave_rows = [_as_dict(item) for item in _as_list(waves) if _as_dict(item)]
    shift_left = _as_dict(shift_left_plan)
    if not units and not wave_rows and not goal:
        return ""
    lines = [
        "# Work Unit Contracts",
        "",
        "## Goal Spec",
        "",
        f"- Objective: {_ns(goal.get('objective')) or 'Autonomous delivery remains bound to the approved context.'}",
        f"- Selected features: {', '.join(_ns(item) for item in _as_list(goal.get('selected_features')) if _ns(item)) or '—'}",
        f"- Requirement IDs: {', '.join(_ns(item) for item in _as_list(goal.get('requirement_ids')) if _ns(item)) or '—'}",
        f"- Milestone IDs: {', '.join(_ns(item) for item in _as_list(goal.get('milestone_ids')) if _ns(item)) or '—'}",
        "",
        "## Dependency Analysis",
        "",
        f"- Work package count: {len(_as_list(dependency.get('work_packages')))}",
        f"- Dependency edge count: {len(_as_list(dependency.get('edges')))}",
        f"- Unknown dependencies: {', '.join(_ns(item) for item in _as_list(dependency.get('unknown_dependencies')) if _ns(item)) or 'none'}",
        f"- Has cycles: {'yes' if dependency.get('has_cycles') is True else 'no'}",
    ]
    if wave_rows:
        lines.extend(["", "## Waves", "", "| Wave | Work units | Lanes | Exit criteria |", "| --- | --- | --- | --- |"])
        for wave in wave_rows[:16]:
            lines.append(
                f"| {int(wave.get('wave_index', 0) or 0)} | "
                f"{', '.join(_ns(item) for item in _as_list(wave.get('work_unit_ids')) if _ns(item)) or '—'} | "
                f"{', '.join(_ns(item) for item in _as_list(wave.get('lane_ids')) if _ns(item)) or '—'} | "
                f"{'; '.join(_ns(item) for item in _as_list(wave.get('exit_criteria')) if _ns(item)) or '—'} |"
            )
    if units:
        lines.extend(
            [
                "",
                "## Work Unit Matrix",
                "",
                "| WU | Lane | Wave | Depends on | Acceptance | QA | Security |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for unit in units[:24]:
            lines.append(
                f"| {_ns(unit.get('work_package_id') or unit.get('id'))} | {_ns(unit.get('lane'))} | "
                f"{int(unit.get('wave_index', 0) or 0)} | "
                f"{', '.join(_ns(item) for item in _as_list(unit.get('depends_on')) if _ns(item)) or '—'} | "
                f"{'; '.join(_ns(item) for item in _as_list(unit.get('acceptance_criteria')) if _ns(item)) or '—'} | "
                f"{'; '.join(_ns(item) for item in _as_list(unit.get('qa_checks')) if _ns(item)) or '—'} | "
                f"{'; '.join(_ns(item) for item in _as_list(unit.get('security_checks')) if _ns(item)) or '—'} |"
            )
        lines.extend(["", "## Value / Telemetry Mapping", "", "| WU | Value targets | Telemetry events |", "| --- | --- | --- |"])
        for unit in units[:24]:
            lines.append(
                f"| {_ns(unit.get('work_package_id') or unit.get('id'))} | "
                f"{'; '.join(_ns(_as_dict(item).get('metric_name') or _as_dict(item).get('metric_id')) for item in _as_list(unit.get('value_targets')) if _as_dict(item)) or '—'} | "
                f"{'; '.join(_ns(_as_dict(item).get('name') or _as_dict(item).get('id')) for item in _as_list(unit.get('telemetry_events')) if _as_dict(item)) or '—'} |"
            )
    if shift_left:
        lines.extend(["", "## Shift-left Quality", ""])
        lines.append(f"- Mode: {_ns(shift_left.get('mode')) or '—'}")
        lines.extend(
            f"- {item}"
            for item in _as_list(shift_left.get("principles"))
            if _ns(item)
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_delivery_waves_doc(
    *,
    waves: list[dict[str, Any]] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    critical_path: list[str] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
) -> str:
    wave_rows = [_as_dict(item) for item in _as_list(waves) if _as_dict(item)]
    units = {
        _ns(_as_dict(item).get("work_package_id") or _as_dict(item).get("id")): _as_dict(item)
        for item in _as_list(work_unit_contracts)
        if _ns(_as_dict(item).get("work_package_id") or _as_dict(item).get("id"))
    }
    if not wave_rows:
        return ""
    lines = [
        "# Delivery Waves",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    mermaid_ids: dict[str, str] = {}
    for wave in wave_rows[:16]:
        wave_index = int(wave.get("wave_index", 0) or 0)
        lines.append(f'  subgraph wave_{wave_index}["Wave {wave_index}"]')
        for unit_id in [_ns(item) for item in _as_list(wave.get("work_unit_ids")) if _ns(item)]:
            mermaid_id = _slug(unit_id, prefix=f"wave-{wave_index}")
            mermaid_ids[unit_id] = mermaid_id
            label = _ns(_as_dict(units.get(unit_id)).get("title") or unit_id).replace('"', "'")
            lines.append(f'    {mermaid_id}["{label}"]')
        lines.append("  end")
    for unit_id, unit in units.items():
        source_id = mermaid_ids.get(unit_id)
        if not source_id:
            continue
        for dependency_id in [_ns(item) for item in _as_list(unit.get("depends_on")) if _ns(item)]:
            target_id = mermaid_ids.get(dependency_id)
            if target_id:
                lines.append(f"  {target_id} --> {source_id}")
    lines.extend(["```", "", f"- Wave count: {len(wave_rows)}"])
    critical = [_ns(item) for item in _as_list(critical_path) if _ns(item)]
    lines.append(f"- Critical path: {' -> '.join(critical) if critical else '—'}")
    shift_left = _as_dict(shift_left_plan)
    if shift_left:
        lines.append(f"- Shift-left mode: {_ns(shift_left.get('mode')) or '—'}")
    return "\n".join(lines).rstrip() + "\n"


def _hardcoded_brand_color_paths(workspace_files: list[dict[str, Any]]) -> list[str]:
    allowed_paths = {
        "app/lib/design-tokens.ts",
        "app/lib/prototype-data.ts",
        "app/lib/control-plane-data.ts",
        "app/globals.css",
        "docs/spec/design-system.md",
    }
    flagged: list[str] = []
    for item in workspace_files:
        record = _as_dict(item)
        path = _ns(record.get("path"))
        if not path or path in allowed_paths:
            continue
        if not path.endswith((".ts", ".tsx", ".js", ".jsx", ".css")):
            continue
        content = str(record.get("content") or "")
        if _HEX_COLOR_RE.search(content):
            flagged.append(path)
    return flagged


def _needs_vitest_runtime(files: list[dict[str, Any]]) -> bool:
    for item in files:
        record = _as_dict(item)
        path = _ns(record.get("path")).lower()
        content = str(record.get("content") or "")
        if path.startswith("tests/") and any(token in path for token in (".spec.", ".test.")):
            return True
        if '"vitest"' in content or "'vitest'" in content:
            return True
    return False


def _render_vitest_config() -> str:
    return (
        'import { defineConfig } from "vitest/config";\n'
        "\n"
        "export default defineConfig({\n"
        "  test: {\n"
        '    include: ["tests/**/*.spec.ts", "tests/**/*.spec.tsx", "tests/**/*.test.ts", "tests/**/*.test.tsx"],\n'
        '    environment: "node",\n'
        "    passWithNoTests: false,\n"
        "  },\n"
        "});\n"
    )


def _inject_vitest_runtime(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _needs_vitest_runtime(files):
        return [dict(item) for item in files]

    updated_files = [dict(item) for item in files]
    for item in updated_files:
        if _ns(item.get("path")) != "package.json":
            continue
        try:
            payload = json.loads(str(item.get("content") or "{}"))
        except json.JSONDecodeError:
            break
        scripts = _as_dict(payload.get("scripts"))
        dependencies = _as_dict(payload.get("dependencies"))
        dev_dependencies = _as_dict(payload.get("devDependencies"))
        if not _ns(scripts.get("test")):
            scripts["test"] = "vitest run"
        if "vitest" not in dependencies and "vitest" not in dev_dependencies:
            dev_dependencies["vitest"] = _VITEST_VERSION
        payload["scripts"] = scripts
        payload["devDependencies"] = dev_dependencies
        item["content"] = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        break

    if not any(_ns(item.get("path")) == "vitest.config.ts" for item in updated_files):
        updated_files.append(
            {
                "path": "vitest.config.ts",
                "kind": "ts",
                "content": _render_vitest_config(),
                "generated_from": "generated_workspace",
            }
        )
    return updated_files


def _route_binding_files(route_path: str) -> list[str]:
    if route_path == "/":
        return [
            "app/page.tsx",
            "app/components/prototype-shell.tsx",
            "app/lib/prototype-data.ts",
            "app/lib/control-plane-data.ts",
            "app/api/control-plane/route.ts",
        ]
    segment = route_path.strip("/") or "workspace"
    return [
        f"app/{segment}/page.tsx",
        "app/components/prototype-shell.tsx",
        "app/lib/prototype-data.ts",
        "app/lib/control-plane-data.ts",
        "app/api/control-plane/route.ts",
    ]


def _workspace_file_map(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in files:
        record = dict(item)
        path = _ns(record.get("path"))
        if path:
            mapping[path] = record
    return mapping


def _upsert_workspace_file(
    files: list[dict[str, Any]],
    *,
    path: str,
    kind: str,
    content: str,
    generated_from: str,
) -> list[dict[str, Any]]:
    updated = [dict(item) for item in files if _ns(item.get("path")) != path]
    updated.append(
        {
            "path": path,
            "kind": kind,
            "content": content,
            "generated_from": generated_from,
        }
    )
    return updated


def _render_backend_contract_from_bundle(
    entities: list[dict[str, Any]],
    api_endpoints: list[dict[str, Any]],
) -> str:
    interface_blocks: list[str] = []
    for entity in entities[:12]:
        name = _ns(entity.get("name")) or "GeneratedEntity"
        fields = [_ns(item) for item in _as_list(entity.get("fields")) if _ns(item)]
        properties = [f"  {field}: string;" for field in fields[:24]] or ["  id: string;", "  createdAt: string;", "  updatedAt: string;"]
        interface_blocks.append("\n".join([f"export interface {name} {{", *properties, "}"]))
    endpoint_payload = [
        {
            "method": _ns(item.get("method") or "GET"),
            "path": _ns(item.get("path") or "/"),
            "description": _ns(item.get("description") or item.get("name")),
            "authRequired": bool(item.get("authRequired", True)),
        }
        for item in api_endpoints[:24]
    ]
    return "\n".join(
        [
            "/* Auto-generated from backend lane outputs for the autonomous delivery mesh. */",
            "",
            *interface_blocks,
            "",
            f"export const apiSpecification = {json.dumps(endpoint_payload, ensure_ascii=False, indent=2)} as const;",
            "",
        ]
    ).strip() + "\n"


def _render_backend_models_from_bundle(entities: list[dict[str, Any]]) -> str:
    blocks: list[str] = ["/* Domain-facing types assembled from backend lane outputs. */", ""]
    for entity in entities[:12]:
        name = _ns(entity.get("name")) or "GeneratedEntity"
        fields = [_ns(item) for item in _as_list(entity.get("fields")) if _ns(item)]
        properties = [f"  {field}: string;" for field in fields[:24]] or ["  id: string;", "  createdAt: string;", "  updatedAt: string;"]
        blocks.extend([f"export type {name} = {{", *properties, "};", ""])
    return "\n".join(blocks).rstrip() + "\n"


def _render_design_token_css_variables(planning_analysis: dict[str, Any] | None) -> str:
    if not _design_token_contract_ready(planning_analysis):
        return ""
    payload = _design_token_payload(planning_analysis)
    colors = _as_dict(payload.get("colors"))
    typography = _as_dict(payload.get("typography"))
    return dedent(
        f"""\
        /* Autonomous delivery design token contract */
        :root {{
          --color-brand-primary: {_ns(colors.get("primary"))};
          --color-brand-secondary: {_ns(colors.get("secondary"))};
          --color-brand-cta: {_ns(colors.get("cta"))};
          --color-app-background: {_ns(colors.get("background"))};
          --color-app-text: {_ns(colors.get("text"))};
          --font-heading: "{_ns(typography.get("heading"))}";
          --font-body: "{_ns(typography.get("body"))}";
          --radius-control: 18px;
        }}
        """
    )


def _ensure_extension_block(content: str, *, marker: str, extension: str) -> str:
    base = content.rstrip()
    if marker in base or not extension.strip():
        return base + ("\n" if base else "")
    if not base:
        return extension.rstrip() + "\n"
    return base + "\n\n" + extension.rstrip() + "\n"


def _upsert_system_contract_artifacts(
    files: list[dict[str, Any]],
    *,
    planning_analysis: dict[str, Any] | None,
    selected_design: dict[str, Any] | None,
    selected_features: list[str],
    api_specification: list[dict[str, Any]],
    milestones: list[dict[str, Any]] | None = None,
    goal_spec: dict[str, Any] | None = None,
    dependency_analysis: dict[str, Any] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    waves: list[dict[str, Any]] | None = None,
    critical_path: list[str] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
    value_contract: dict[str, Any] | None = None,
    outcome_telemetry_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    updated = [dict(item) for item in files]
    milestone_rows = [_as_dict(item) for item in _as_list(milestones) if _as_dict(item)]

    design_token_module = _render_design_tokens_module(planning_analysis)
    if design_token_module:
        updated = _upsert_workspace_file(
            updated,
            path="app/lib/design-tokens.ts",
            kind="ts",
            content=design_token_module,
            generated_from="planning_analysis",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/design-system.md",
            kind="md",
            content=_render_design_system_doc(planning_analysis),
            generated_from="planning_analysis",
        )

    development_standards_module = _render_development_standards_module(
        planning_analysis=planning_analysis,
        selected_design=selected_design,
        selected_features=selected_features,
        api_specification=api_specification,
        milestones=milestone_rows,
    )
    if development_standards_module:
        updated = _upsert_workspace_file(
            updated,
            path="app/lib/development-standards.ts",
            kind="ts",
            content=development_standards_module,
            generated_from="planning_analysis",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/development-standards.md",
            kind="md",
            content=_render_development_standards_doc(
                planning_analysis=planning_analysis,
                selected_design=selected_design,
                selected_features=selected_features,
                api_specification=api_specification,
                milestones=milestone_rows,
            ),
            generated_from="planning_analysis",
        )

    value_contract_module = _render_value_contract_module(value_contract)
    if value_contract_module:
        updated = _upsert_workspace_file(
            updated,
            path="app/lib/value-contract.ts",
            kind="ts",
            content=value_contract_module,
            generated_from="planning_analysis",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/value-contract.md",
            kind="md",
            content=_render_value_contract_doc(value_contract),
            generated_from="planning_analysis",
        )

    outcome_telemetry_module = _render_outcome_telemetry_module(outcome_telemetry_contract)
    if outcome_telemetry_module:
        updated = _upsert_workspace_file(
            updated,
            path="server/contracts/outcome-telemetry.ts",
            kind="ts",
            content=outcome_telemetry_module,
            generated_from="planning_analysis",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/outcome-telemetry.md",
            kind="md",
            content=_render_outcome_telemetry_doc(outcome_telemetry_contract),
            generated_from="planning_analysis",
        )

    access_policy = _render_access_policy_file(planning_analysis, api_specification, selected_design)
    if access_policy:
        updated = _upsert_workspace_file(
            updated,
            path="server/contracts/access-policy.ts",
            kind="ts",
            content=access_policy,
            generated_from="planning_analysis",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/access-control.md",
            kind="md",
            content=_render_access_control_doc(planning_analysis, api_specification, selected_design),
            generated_from="planning_analysis",
        )

    audit_events = _render_audit_events_file(
        api_specification=api_specification,
        selected_features=selected_features,
        milestones=milestone_rows,
    )
    if audit_events:
        updated = _upsert_workspace_file(
            updated,
            path="server/contracts/audit-events.ts",
            kind="ts",
            content=audit_events,
            generated_from="delivery_plan",
        )

    operability_doc = _render_operability_doc(
        selected_features=selected_features,
        milestones=milestone_rows,
        api_specification=api_specification,
    )
    if operability_doc:
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/operability.md",
            kind="md",
            content=operability_doc,
            generated_from="delivery_plan",
        )

    work_unit_module = _render_work_unit_contracts_module(
        goal_spec=goal_spec,
        dependency_analysis=dependency_analysis,
        work_unit_contracts=work_unit_contracts,
        waves=waves,
        shift_left_plan=shift_left_plan,
    )
    if work_unit_module:
        updated = _upsert_workspace_file(
            updated,
            path="app/lib/work-unit-contracts.ts",
            kind="ts",
            content=work_unit_module,
            generated_from="delivery_plan",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/work-unit-contracts.md",
            kind="md",
            content=_render_work_unit_contracts_doc(
                goal_spec=goal_spec,
                dependency_analysis=dependency_analysis,
                work_unit_contracts=work_unit_contracts,
                waves=waves,
                shift_left_plan=shift_left_plan,
            ),
            generated_from="delivery_plan",
        )
        updated = _upsert_workspace_file(
            updated,
            path="docs/spec/delivery-waves.md",
            kind="md",
            content=_render_delivery_waves_doc(
                waves=waves,
                work_unit_contracts=work_unit_contracts,
                critical_path=critical_path,
                shift_left_plan=shift_left_plan,
            ),
            generated_from="delivery_plan",
        )

    file_map = _workspace_file_map(updated)
    globals_css = str(_as_dict(file_map.get("app/globals.css")).get("content") or "")
    if globals_css:
        updated = _upsert_workspace_file(
            updated,
            path="app/globals.css",
            kind="css",
            content=_extend_globals_css(globals_css, planning_analysis=planning_analysis),
            generated_from="delivery_plan",
        )

    return updated


def _render_control_plane_data(
    *,
    selected_features: list[str],
    work_packages: list[dict[str, Any]],
    critical_path: list[str],
    waves: list[dict[str, Any]] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]],
    route_bindings: list[dict[str, Any]],
    api_endpoints: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    interaction_notes: list[str],
    review_focus: list[str],
    goal_spec: dict[str, Any] | None = None,
    dependency_analysis: dict[str, Any] | None = None,
    design_contract: dict[str, Any] | None = None,
    access_model: dict[str, Any] | None = None,
    operability_contract: dict[str, Any] | None = None,
    development_standards: dict[str, Any] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
    value_contract: dict[str, Any] | None = None,
    outcome_telemetry_contract: dict[str, Any] | None = None,
) -> str:
    payload = {
        "selectedFeatures": selected_features,
        "goalSpec": _as_dict(goal_spec),
        "workPackages": [
            {
                "id": _ns(item.get("id")),
                "title": _ns(item.get("title")),
                "lane": _ns(item.get("lane")),
                "dependsOn": [_ns(dep) for dep in _as_list(item.get("depends_on")) if _ns(dep)],
                "deliverables": [_ns(deliverable) for deliverable in _as_list(item.get("deliverables")) if _ns(deliverable)],
                "acceptanceCriteria": [_ns(criterion) for criterion in _as_list(item.get("acceptance_criteria")) if _ns(criterion)],
                "critical": bool(item.get("is_critical")),
                "status": _ns(item.get("status")) or "planned",
            }
            for item in work_packages[:24]
        ],
        "criticalPath": [_ns(item) for item in critical_path if _ns(item)],
        "waves": [
            {
                "waveIndex": int(_as_dict(item).get("wave_index", 0) or 0),
                "workUnitIds": [_ns(unit_id) for unit_id in _as_list(_as_dict(item).get("work_unit_ids")) if _ns(unit_id)],
                "laneIds": [_ns(lane_id) for lane_id in _as_list(_as_dict(item).get("lane_ids")) if _ns(lane_id)],
            }
            for item in _as_list(waves)
            if _as_dict(item)
        ],
        "workUnitContracts": [
            {
                "id": _ns(item.get("id")),
                "workPackageId": _ns(item.get("work_package_id")),
                "lane": _ns(item.get("lane")),
                "waveIndex": int(item.get("wave_index", 0) or 0),
                "dependsOn": [_ns(dep) for dep in _as_list(item.get("depends_on")) if _ns(dep)],
                "acceptanceCriteria": [_ns(criterion) for criterion in _as_list(item.get("acceptance_criteria")) if _ns(criterion)],
                "qaChecks": [_ns(text) for text in _as_list(item.get("qa_checks")) if _ns(text)],
                "securityChecks": [_ns(text) for text in _as_list(item.get("security_checks")) if _ns(text)],
                "requiredContracts": [_ns(contract_id) for contract_id in _as_list(item.get("required_contracts")) if _ns(contract_id)],
                "valueTargets": [
                    _ns(_as_dict(metric).get("metric_name") or _as_dict(metric).get("metric_id"))
                    for metric in _as_list(item.get("value_targets"))
                    if _as_dict(metric)
                ],
                "telemetryEvents": [
                    _ns(_as_dict(event).get("name") or _as_dict(event).get("id"))
                    for event in _as_list(item.get("telemetry_events"))
                    if _as_dict(event)
                ],
            }
            for item in _as_list(work_unit_contracts)
            if _as_dict(item)
        ],
        "milestones": [
            {
                "id": _ns(item.get("id")),
                "name": _ns(item.get("name")),
                "criteria": _ns(item.get("criteria")),
            }
            for item in milestones[:12]
        ],
        "routeBindings": [
            {
                "routePath": _ns(item.get("route_path")),
                "screenId": _ns(item.get("screen_id")),
                "filePaths": [_ns(path) for path in _as_list(item.get("file_paths")) if _ns(path)],
            }
            for item in route_bindings[:16]
        ],
        "apiSurface": [
            {
                "method": _ns(item.get("method")),
                "path": _ns(item.get("path")),
                "description": _ns(item.get("description")),
            }
            for item in api_endpoints[:24]
        ],
        "entities": [
            {
                "name": _ns(item.get("name")),
                "fields": [_ns(field) for field in _as_list(item.get("fields")) if _ns(field)],
            }
            for item in entities[:12]
        ],
        "interactionNotes": [_ns(item) for item in interaction_notes if _ns(item)],
        "reviewFocus": [_ns(item) for item in review_focus if _ns(item)],
        "dependencyAnalysis": _as_dict(dependency_analysis),
        "designContract": _as_dict(design_contract),
        "accessModel": _as_dict(access_model),
        "operabilityContract": _as_dict(operability_contract),
        "developmentStandards": _as_dict(development_standards),
        "shiftLeftPlan": _as_dict(shift_left_plan),
        "valueContract": _as_dict(value_contract),
        "outcomeTelemetryContract": _as_dict(outcome_telemetry_contract),
    }
    return (
        f"export const controlPlaneSnapshot = {json.dumps(payload, ensure_ascii=False, indent=2)} as const;\n"
    )


def _render_control_plane_route() -> str:
    return "\n".join(
        [
            'import { NextResponse } from "next/server";',
            'import { controlPlaneSnapshot } from "../../lib/control-plane-data";',
            "",
            "export async function GET() {",
            "  return NextResponse.json(controlPlaneSnapshot);",
            "}",
            "",
        ]
    )


def _render_autonomous_delivery_doc(
    *,
    work_packages: list[dict[str, Any]],
    critical_path: list[str],
    review_focus: list[str],
    waves: list[dict[str, Any]] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
) -> str:
    lines = [
        "# Autonomous Delivery Plan",
        "",
        "## Critical Path",
        "",
        " -> ".join(_ns(item) for item in critical_path if _ns(item)) or "No critical path identified.",
        "",
        "## Work Packages",
        "",
        "| ID | Lane | Title | Depends On |",
        "| --- | --- | --- | --- |",
    ]
    for item in work_packages[:24]:
        lines.append(
            f"| {_ns(item.get('id'))} | {_ns(item.get('lane'))} | {_ns(item.get('title'))} | "
            f"{', '.join(_ns(dep) for dep in _as_list(item.get('depends_on')) if _ns(dep)) or '—'} |"
        )
    wave_rows = [_as_dict(item) for item in _as_list(waves) if _as_dict(item)]
    if wave_rows:
        lines.extend(["", "## Waves", "", "| Wave | Work units | Lanes |", "| --- | --- | --- |"])
        for item in wave_rows[:16]:
            lines.append(
                f"| {int(item.get('wave_index', 0) or 0)} | "
                f"{', '.join(_ns(unit_id) for unit_id in _as_list(item.get('work_unit_ids')) if _ns(unit_id)) or '—'} | "
                f"{', '.join(_ns(lane_id) for lane_id in _as_list(item.get('lane_ids')) if _ns(lane_id)) or '—'} |"
            )
    unit_rows = [_as_dict(item) for item in _as_list(work_unit_contracts) if _as_dict(item)]
    if unit_rows:
        lines.extend(["", "## Work Unit Contracts", "", "| Work unit | Wave | QA checks | Security checks |", "| --- | --- | --- | --- |"])
        for item in unit_rows[:24]:
            lines.append(
                f"| {_ns(item.get('work_package_id') or item.get('id'))} | {int(item.get('wave_index', 0) or 0)} | "
                f"{'; '.join(_ns(text) for text in _as_list(item.get('qa_checks')) if _ns(text)) or '—'} | "
                f"{'; '.join(_ns(text) for text in _as_list(item.get('security_checks')) if _ns(text)) or '—'} |"
            )
    shift_left = _as_dict(shift_left_plan)
    if shift_left:
        lines.extend(["", "## Shift-left Quality", ""])
        lines.append(f"- Mode: {_ns(shift_left.get('mode')) or '—'}")
        lines.extend(f"- {item}" for item in _as_list(shift_left.get("principles")) if _ns(item))
    if review_focus:
        lines.extend(["", "## Review Focus", ""])
        lines.extend(f"- {item}" for item in review_focus if _ns(item))
    return "\n".join(lines).rstrip() + "\n"


def _render_control_plane_test() -> str:
    return "\n".join(
        [
            'import { describe, expect, it } from "vitest";',
            'import { controlPlaneSnapshot } from "../../app/lib/control-plane-data";',
            'import { prototypeSpec } from "../../app/lib/prototype-data";',
            "",
            'describe("control-plane snapshot", () => {',
            '  it("keeps the dependency graph internally consistent", () => {',
            "    const ids = new Set(controlPlaneSnapshot.workPackages.map((item) => item.id));",
            "    expect(ids.size).toBeGreaterThan(0);",
            "    for (const item of controlPlaneSnapshot.workPackages) {",
            "      for (const dep of item.dependsOn) {",
            "        expect(ids.has(dep)).toBe(true);",
            "      }",
            "    }",
            "    for (const critical of controlPlaneSnapshot.criticalPath) {",
            "      expect(ids.has(critical)).toBe(true);",
            "    }",
            "  });",
            "",
            '  it("covers routes, API surface, and milestone evidence", () => {',
            "    expect(prototypeSpec.routes.length).toBeGreaterThanOrEqual(3);",
            "    expect(controlPlaneSnapshot.routeBindings.length).toBeGreaterThanOrEqual(prototypeSpec.routes.length);",
            "    expect(controlPlaneSnapshot.apiSurface.length).toBeGreaterThan(0);",
            "    expect(controlPlaneSnapshot.milestones.length).toBeGreaterThan(0);",
            "  });",
            "});",
            "",
        ]
    )


def _render_control_plane_css() -> str:
    return dedent(
        """\
        /* Autonomous delivery workspace extensions */
        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 12px;
          min-width: min(100%, 420px);
        }

        .metric-card {
          border-radius: 18px;
          border: 1px solid var(--border);
          background: color-mix(in srgb, var(--surface) 92%, transparent);
          padding: 14px 16px;
          display: grid;
          gap: 6px;
        }

        .metric-card span {
          color: var(--muted);
          font-size: 0.8rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
        }

        .metric-card strong {
          font-size: 1.4rem;
        }

        .table-shell {
          overflow-x: auto;
          border-radius: 20px;
          border: 1px solid var(--border);
          background: color-mix(in srgb, var(--surface) 80%, transparent);
        }

        .data-table {
          width: 100%;
          border-collapse: collapse;
          min-width: 620px;
        }

        .data-table th,
        .data-table td {
          padding: 14px 16px;
          border-bottom: 1px solid var(--border);
          text-align: left;
          vertical-align: top;
        }

        .data-table th {
          color: var(--muted);
          font-size: 0.78rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
        }

        .data-table tbody tr:last-child td {
          border-bottom: none;
        }

        .inline-meta {
          margin-top: 6px;
          color: var(--muted);
          font-size: 0.82rem;
        }

        .approval-form,
        .form-field,
        .checklist-stack {
          display: grid;
          gap: 14px;
        }

        .form-field span {
          font-size: 0.82rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          color: var(--muted);
        }

        .form-field textarea {
          min-height: 140px;
          resize: vertical;
          border-radius: 18px;
          border: 1px solid var(--border);
          background: color-mix(in srgb, var(--surface) 90%, transparent);
          color: var(--text);
          padding: 14px 16px;
          font: inherit;
        }

        .check-item {
          display: flex;
          gap: 10px;
          align-items: flex-start;
          padding: 12px 14px;
          border-radius: 18px;
          border: 1px solid var(--border);
          background: color-mix(in srgb, var(--surface) 86%, transparent);
        }

        .check-item input {
          margin-top: 3px;
        }

        @media (max-width: 1080px) {
          .metrics-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            min-width: 0;
          }
        }

        @media (max-width: 720px) {
          .metrics-grid {
            grid-template-columns: 1fr;
          }

          .data-table {
            min-width: 520px;
          }
        }
        """
    )


def _extend_globals_css(content: str, *, planning_analysis: dict[str, Any] | None = None) -> str:
    updated = _ensure_extension_block(
        content,
        marker="/* Autonomous delivery design token contract */",
        extension=_render_design_token_css_variables(planning_analysis),
    )
    return _ensure_extension_block(
        updated,
        marker="/* Autonomous delivery workspace extensions */",
        extension=_render_control_plane_css(),
    )


def _render_autonomous_prototype_shell(
    *,
    title: str,
    review_focus: list[str],
) -> str:
    escaped_title = json.dumps(title, ensure_ascii=False)
    escaped_review_focus = json.dumps([_ns(item) for item in review_focus if _ns(item)], ensure_ascii=False)
    return f'''"use client";

import Link from "next/link";
import {{ useMemo, useState }} from "react";
import {{ controlPlaneSnapshot }} from "../lib/control-plane-data";
import {{ prototypeSpec }} from "../lib/prototype-data";

type RouteRecord = {{
  readonly id: string;
  readonly screen_id: string;
  readonly path: string;
  readonly layout: string;
  readonly title: string;
}};

type ScreenRecord = {{
  readonly id: string;
  readonly title: string;
  readonly headline: string;
  readonly purpose: string;
  readonly supporting_text?: string;
  readonly primary_actions: readonly string[];
}};

type WorkPackage = {{
  readonly id: string;
  readonly title: string;
  readonly lane: string;
  readonly dependsOn: readonly string[];
  readonly acceptanceCriteria: readonly string[];
  readonly critical: boolean;
  readonly status: string;
}};

type AccessRole = {{
  readonly name: string;
  readonly permissions?: readonly string[];
  readonly responsibilities?: readonly string[];
}};

type ProtectedEndpoint = {{
  readonly method: string;
  readonly path: string;
  readonly description: string;
}};

type AuditEvent = {{
  readonly name: string;
  readonly trigger: string;
  readonly signal: string;
}};

type DevelopmentStandards = {{
  readonly ui_rules?: readonly string[];
  readonly security_rules?: readonly string[];
  readonly operability_rules?: readonly string[];
  readonly coding_rules?: readonly string[];
}};

export function PrototypeShell({{ screenId }}: {{ screenId: string }}) {{
  const screens = prototypeSpec.screens as unknown as readonly ScreenRecord[];
  const routes = prototypeSpec.routes as unknown as readonly RouteRecord[];
  const screen = useMemo(() => screens.find((item) => item.id === screenId) ?? screens[0], [screenId, screens]);
  const [approvalNote, setApprovalNote] = useState("");
  const [selectedLane, setSelectedLane] = useState<string>("all");
  const workPackages = controlPlaneSnapshot.workPackages as readonly WorkPackage[];
  const laneOptions = useMemo(
    () => ["all", ...Array.from(new Set(workPackages.map((item) => item.lane)))],
    [workPackages],
  );
  const visiblePackages = useMemo(
    () => (selectedLane === "all" ? workPackages : workPackages.filter((item) => item.lane === selectedLane)),
    [selectedLane, workPackages],
  );
  const summaryCards = [
    {{ label: "Features", value: controlPlaneSnapshot.selectedFeatures.length }},
    {{ label: "Work packages", value: controlPlaneSnapshot.workPackages.length }},
    {{ label: "Critical path", value: controlPlaneSnapshot.criticalPath.length }},
    {{ label: "API surface", value: controlPlaneSnapshot.apiSurface.length }},
  ];
  const reviewFocus = {escaped_review_focus};
  const designContract = (controlPlaneSnapshot.designContract ?? {{}}) as {{
    style?: {{ name?: string }};
    colors?: Record<string, string>;
    typography?: {{ heading?: string; body?: string }};
    effects?: readonly string[];
  }};
  const accessModel = (controlPlaneSnapshot.accessModel ?? {{}}) as {{
    roles?: readonly AccessRole[];
    protectedApi?: readonly ProtectedEndpoint[];
    authSurfaces?: readonly string[];
  }};
  const operabilityContract = (controlPlaneSnapshot.operabilityContract ?? {{}}) as {{
    auditEvents?: readonly AuditEvent[];
    releaseSignals?: readonly string[];
    promotionChecks?: readonly string[];
  }};
  const protectedApi = accessModel.protectedApi ?? [];
  const roles = accessModel.roles ?? [];
  const authSurfaces = accessModel.authSurfaces ?? [];
  const auditEvents = operabilityContract.auditEvents ?? [];
  const releaseSignals = operabilityContract.releaseSignals ?? [];
  const promotionChecks = operabilityContract.promotionChecks ?? [];
  const standards = (controlPlaneSnapshot.developmentStandards ?? {{}}) as DevelopmentStandards;
  const codingRules = standards.coding_rules ?? [];
  const uiRules = standards.ui_rules ?? [];
  const securityRules = standards.security_rules ?? [];

  return (
    <main className="prototype-shell">
      <aside className="shell-rail">
        <div className="brand-mark">
          <span className="brand-dot" aria-hidden="true" />
          <div>
            <p className="eyebrow">Autonomous delivery workspace</p>
            <h1>{escaped_title}</h1>
          </div>
        </div>
        <p className="shell-note">{{prototypeSpec.subtitle}}</p>
        <div className="feature-pills">
          {{controlPlaneSnapshot.selectedFeatures.map((feature) => (
            <span key={{feature}} className="pill">
              {{feature}}
            </span>
          ))}}
        </div>
        <nav aria-label="Prototype routes">
          <ul className="nav-list">
            {{routes.map((route) => (
              <li key={{route.id}}>
                <Link href={{route.path}} className={{route.screen_id === screen.id ? "nav-link active" : "nav-link"}}>
                  <span>{{route.title}}</span>
                  <small>{{route.layout}}</small>
                </Link>
              </li>
            ))}}
          </ul>
        </nav>
      </aside>

      <section className="canvas">
        <header className="panel hero-panel">
          <div>
            <p className="eyebrow">Active screen</p>
            <h2>{{screen.headline || screen.title}}</h2>
            <p className="lede">{{screen.purpose}}</p>
          </div>
          <div className="metrics-grid">
            {{summaryCards.map((card) => (
              <article key={{card.label}} className="metric-card">
                <span>{{card.label}}</span>
                <strong>{{card.value}}</strong>
              </article>
            ))}}
          </div>
        </header>

        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Dependency-aware execution</p>
              <h3>Work packages and lane ownership</h3>
            </div>
            <div className="action-row">
              {{laneOptions.map((lane) => (
                <button
                  key={{lane}}
                  type="button"
                  className={{lane === selectedLane ? "state-pill active" : "state-pill"}}
                  onClick={{() => setSelectedLane(lane)}}
                >
                  <span>{{lane === "all" ? "all lanes" : lane}}</span>
                  <small>
                    {{
                      lane === "all"
                        ? `${{workPackages.length}} packages`
                        : `${{workPackages.filter((item) => item.lane === lane).length}} packages`
                    }}
                  </small>
                </button>
              ))}}
            </div>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Package</th>
                  <th>Lane</th>
                  <th>Depends on</th>
                  <th>Acceptance</th>
                </tr>
              </thead>
              <tbody>
                {{visiblePackages.map((item) => (
                  <tr key={{item.id}}>
                    <td>
                      <strong>{{item.title}}</strong>
                      <div className="inline-meta">{{item.id}}{{item.critical ? " · critical" : ""}}</div>
                    </td>
                    <td>{{item.lane}}</td>
                    <td>{{item.dependsOn.join(", ") || "—"}}</td>
                    <td>{{item.acceptanceCriteria[0] || "No acceptance criteria"}}</td>
                  </tr>
                ))}}
              </tbody>
            </table>
          </div>
        </section>

        <div className="content-grid">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Standards</p>
                <h3>Implementation and coding rules</h3>
              </div>
              <p className="caption">Prototype implementation stays bound to one shared engineering contract.</p>
            </div>
            <div className="stack">
              {{uiRules.map((item) => (
                <div key={{item}} className="data-card">{{item}}</div>
              ))}}
              {{securityRules.map((item) => (
                <div key={{item}} className="data-card">{{item}}</div>
              ))}}
              {{codingRules.map((item) => (
                <article key={{item}} className="data-group">
                  <strong>Coding rule</strong>
                  <p>{{item}}</p>
                </article>
              ))}}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Approval packet</p>
                <h3>Operator rationale form</h3>
              </div>
              <p className="caption">Review focus stays attached to the selected build and its dependency graph.</p>
            </div>
            <form className="approval-form">
              <label className="form-field">
                <span>Approval rationale</span>
                <textarea
                  value={{approvalNote}}
                  onChange={{(event) => setApprovalNote(event.target.value)}}
                  placeholder="Explain why this build is safe to promote, or what must be reworked."
                />
              </label>
              <div className="checklist-stack">
                {{reviewFocus.map((item) => (
                  <label key={{item}} className="check-item">
                    <input type="checkbox" />
                    <span>{{item}}</span>
                  </label>
                ))}}
              </div>
              <div className="caption">Character count: {{approvalNote.length}}</div>
            </form>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">API surface</p>
                <h3>Backend contract</h3>
              </div>
              <p className="caption">Generated from the backend lane, aligned with route bindings and milestones.</p>
            </div>
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Method</th>
                    <th>Path</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {{controlPlaneSnapshot.apiSurface.map((item) => (
                    <tr key={{`${{item.method}}-${{item.path}}`}}>
                      <td>{{item.method}}</td>
                      <td>{{item.path}}</td>
                      <td>{{item.description}}</td>
                    </tr>
                  ))}}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="content-grid">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Design system</p>
                <h3>Approved token contract</h3>
              </div>
              <p className="caption">Implementation inherits approved palette, typography, and motion rules instead of inventing them at build time.</p>
            </div>
            <div className="stack">
              <article className="data-group">
                <strong>{{designContract.style?.name || "Style contract pending"}}</strong>
                <p>Heading: {{designContract.typography?.heading || "n/a"}} · Body: {{designContract.typography?.body || "n/a"}}</p>
              </article>
              <article className="data-group">
                <strong>Semantic colors</strong>
                <div className="data-tags">
                  {{Object.entries(designContract.colors ?? {{}}).map(([token, value]) => (
                    <span key={{token}} className="tag">{{token}}: {{value}}</span>
                  ))}}
                </div>
              </article>
              {{(designContract.effects ?? []).map((effect) => (
                <div key={{effect}} className="data-card">{{effect}}</div>
              ))}}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Identity and access</p>
                <h3>Authentication and authorization boundaries</h3>
              </div>
              <p className="caption">Protected endpoints, operator roles, and auth-facing surfaces stay explicit through delivery.</p>
            </div>
            <div className="stack">
              <article className="data-group">
                <strong>{{roles.length}} roles / {{protectedApi.length}} protected endpoints</strong>
                <p>{{authSurfaces.length}} auth-facing surfaces captured in the selected design.</p>
              </article>
              {{roles.map((role) => (
                <article key={{role.name}} className="data-group">
                  <strong>{{role.name}}</strong>
                  <p>{{(role.permissions ?? []).join(", ") || "No permissions recorded"}}</p>
                </article>
              ))}}
              {{protectedApi.map((endpoint) => (
                <div key={{`${{endpoint.method}}-${{endpoint.path}}`}} className="data-card">
                  {{endpoint.method}} {{endpoint.path}} · {{endpoint.description}}
                </div>
              ))}}
            </div>
          </section>
        </div>

        <div className="content-grid">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Operability</p>
                <h3>Audit and release signals</h3>
              </div>
              <p className="caption">Autonomous delivery keeps promotion checks and audit events reviewable before deploy.</p>
            </div>
            <div className="stack">
              {{releaseSignals.map((item) => (
                <div key={{item}} className="data-card">{{item}}</div>
              ))}}
              {{promotionChecks.map((item) => (
                <div key={{item}} className="data-card">{{item}}</div>
              ))}}
              {{auditEvents.map((event) => (
                <article key={{event.name}} className="data-group">
                  <strong>{{event.name}}</strong>
                  <p>{{event.signal || event.trigger}}</p>
                </article>
              ))}}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Route bindings</p>
                <h3>Preview-to-code map</h3>
              </div>
            </div>
            <div className="stack">
              {{controlPlaneSnapshot.routeBindings.map((item) => (
                <article key={{item.routePath}} className="data-group">
                  <strong>{{item.routePath}}</strong>
                  <div className="data-tags">
                    {{item.filePaths.map((filePath) => (
                      <span key={{filePath}} className="tag">{{filePath}}</span>
                    ))}}
                  </div>
                </article>
              ))}}
            </div>
          </section>
        </div>

        <div className="content-grid">
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="eyebrow">Lineage</p>
                <h3>Critical path and milestones</h3>
              </div>
            </div>
            <div className="stack">
              {{controlPlaneSnapshot.criticalPath.map((item) => (
                <div key={{item}} className="data-card">{{item}}</div>
              ))}}
              {{controlPlaneSnapshot.milestones.map((item) => (
                <article key={{item.id}} className="data-group">
                  <strong>{{item.name}}</strong>
                  <p>{{item.criteria}}</p>
                </article>
              ))}}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}}
'''


def _assemble_code_workspace(
    *,
    prototype_app: dict[str, Any],
    prototype_spec: dict[str, Any],
    technical_design_payload: dict[str, Any],
    workspace_files: list[dict[str, Any]],
    base_existing_paths: set[str],
) -> dict[str, Any]:
    enriched_files: list[dict[str, Any]] = []
    for raw_file in workspace_files:
        record = dict(raw_file)
        path = _ns(record.get("path"))
        if not path:
            continue
        package_id, package_label, package_path = _path_package(path)
        route_paths = []
        for route in _as_list(prototype_spec.get("routes")):
            route_record = _as_dict(route)
            route_path = _ns(route_record.get("path"))
            if path in _route_binding_files(route_path):
                route_paths.append(route_path)
        content = str(record.get("content") or "")
        enriched_files.append(
            {
                "path": path,
                "kind": _ns(record.get("kind")) or "txt",
                "package_id": package_id,
                "package_label": package_label,
                "package_path": package_path,
                "lane": _lane_for_path(path),
                "route_paths": route_paths,
                "entrypoint": path in {"app/page.tsx", "app/layout.tsx"} or path.endswith("/page.tsx"),
                "generated_from": _ns(record.get("generated_from")) or ("prototype_app" if path in base_existing_paths else "generated_workspace"),
                "line_count": len(content.splitlines()),
                "content_preview": "\n".join(content.splitlines()[:12]),
                "content": content,
            }
        )

    package_map: dict[str, dict[str, Any]] = {}
    for file_record in enriched_files:
        package_id = str(file_record["package_id"])
        package_entry = package_map.setdefault(
            package_id,
            {
                "id": package_id,
                "label": str(file_record["package_label"]),
                "path": str(file_record["package_path"]),
                "lane": str(file_record["lane"]),
                "kind": "generated",
                "file_count": 0,
            },
        )
        package_entry["file_count"] += 1

    route_bindings = []
    for route in _as_list(prototype_spec.get("routes")):
        route_record = _as_dict(route)
        route_path = _ns(route_record.get("path"))
        if not route_path:
            continue
        file_paths = [
            str(item["path"])
            for item in enriched_files
            if route_path in _as_list(item.get("route_paths"))
        ]
        route_bindings.append(
            {
                "route_path": route_path,
                "screen_id": _ns(route_record.get("screen_id")) or None,
                "file_paths": file_paths,
            }
        )

    package_graph = []
    component_graph = _as_dict(technical_design_payload.get("componentDependencyGraph"))
    for source, targets in component_graph.items():
        source_id = _slug(str(source), prefix="component")
        for target in _as_list(targets):
            target_id = _slug(str(target), prefix="component")
            if not target_id:
                continue
            package_graph.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "reason": "technical_design_dependency",
                }
            )

    artifact_summary = {
        "package_count": len(package_map),
        "file_count": len(enriched_files),
        "route_binding_count": len(route_bindings),
        "entrypoint_count": sum(1 for item in enriched_files if item.get("entrypoint") is True),
    }

    return {
        "framework": _ns(prototype_app.get("framework")) or "nextjs",
        "router": _ns(prototype_app.get("router")) or "app",
        "preview_entry": _as_list(prototype_app.get("entry_routes"))[:1][0] if _as_list(prototype_app.get("entry_routes")) else "/",
        "entrypoints": [str(item.get("path")) for item in enriched_files if item.get("entrypoint") is True],
        "install_command": _ns(prototype_app.get("install_command")) or "npm install",
        "dev_command": _ns(prototype_app.get("dev_command")) or "npm run dev",
        "build_command": _ns(prototype_app.get("build_command")) or "npm run build",
        "package_tree": sorted(package_map.values(), key=lambda item: (int(item.get("lane") == "integrator"), str(item.get("path")))),
        "files": enriched_files,
        "package_graph": package_graph,
        "route_bindings": route_bindings,
        "artifact_summary": artifact_summary,
    }


def build_development_code_workspace(
    *,
    spec: str,
    selected_features: list[str],
    selected_design: dict[str, Any],
    requirements: dict[str, Any] | None = None,
    task_decomposition: dict[str, Any] | None = None,
    technical_design: dict[str, Any] | None = None,
    reverse_engineering: dict[str, Any] | None = None,
    planning_analysis: dict[str, Any] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    goal_spec: dict[str, Any] | None = None,
    dependency_analysis: dict[str, Any] | None = None,
    work_unit_contracts: list[dict[str, Any]] | None = None,
    waves: list[dict[str, Any]] | None = None,
    critical_path: list[str] | None = None,
    shift_left_plan: dict[str, Any] | None = None,
    value_contract: dict[str, Any] | None = None,
    outcome_telemetry_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    design = _as_dict(selected_design)
    prototype_spec = _as_dict(design.get("prototype_spec"))
    prototype_app = _as_dict(design.get("prototype_app"))
    if not prototype_app and prototype_spec:
        prototype_app = build_nextjs_prototype_app(
            title=_ns(prototype_spec.get("title")) or "Generated App",
            subtitle=_ns(prototype_spec.get("subtitle")) or _ns(spec),
            primary=_ns(_as_dict(prototype_spec.get("theme")).get("primary")) or "#2563eb",
            accent=_ns(_as_dict(prototype_spec.get("theme")).get("accent")) or "#f59e0b",
            prototype_spec=prototype_spec,
        )

    requirement_rows = [_as_dict(item) for item in _as_list(_as_dict(requirements).get("requirements")) if _as_dict(item)]
    task_rows = [_as_dict(item) for item in _as_list(_as_dict(task_decomposition).get("tasks")) if _as_dict(item)]
    technical_design_payload = _as_dict(technical_design)
    reverse_engineering_payload = _as_dict(reverse_engineering)

    files = [dict(item) for item in _as_list(prototype_app.get("files")) if isinstance(item, dict)]
    existing_paths = {str(item.get("path") or "").strip() for item in files}

    generated_files: list[dict[str, Any]] = []
    api_specification = [_as_dict(item) for item in _as_list(technical_design_payload.get("apiSpecification")) if _as_dict(item)]
    interface_definitions = [_as_dict(item) for item in _as_list(technical_design_payload.get("interfaceDefinitions")) if _as_dict(item)]
    database_schema = [_as_dict(item) for item in _as_list(technical_design_payload.get("databaseSchema")) if _as_dict(item)]

    supplemental_candidates = [
        {
            "path": "server/contracts/api-contract.ts",
            "kind": "ts",
            "content": _render_api_contract_file(api_specification, interface_definitions),
            "generated_from": "technical_design",
        },
        {
            "path": "server/domain/models.ts",
            "kind": "ts",
            "content": _render_domain_models_file(interface_definitions),
            "generated_from": "technical_design",
        },
        {
            "path": "server/db/schema.sql",
            "kind": "sql",
            "content": _render_schema_file(database_schema or _as_list(reverse_engineering_payload.get("databaseSchema"))),
            "generated_from": "technical_design",
        },
        {
            "path": "tests/acceptance/requirements.spec.ts",
            "kind": "ts",
            "content": _render_acceptance_spec(requirement_rows),
            "generated_from": "requirements",
        },
        {
            "path": "docs/spec/traceability.md",
            "kind": "md",
            "content": _render_traceability_doc(selected_features, requirement_rows, task_rows),
            "generated_from": "requirements",
        },
    ]
    for item in supplemental_candidates:
        if item["path"] in existing_paths:
            continue
        if not _ns(item["content"]):
            continue
        generated_files.append(item)

    workspace_files = _inject_vitest_runtime([*files, *generated_files])
    workspace_files = _upsert_system_contract_artifacts(
        workspace_files,
        planning_analysis=planning_analysis,
        selected_design=design,
        selected_features=selected_features,
        api_specification=api_specification,
        milestones=milestones,
        goal_spec=goal_spec,
        dependency_analysis=dependency_analysis,
        work_unit_contracts=work_unit_contracts,
        waves=waves,
        critical_path=critical_path,
        shift_left_plan=shift_left_plan,
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    return _assemble_code_workspace(
        prototype_app=prototype_app,
        prototype_spec=prototype_spec,
        technical_design_payload=technical_design_payload,
        workspace_files=workspace_files,
        base_existing_paths=existing_paths,
    )


def refine_development_code_workspace(
    *,
    code_workspace: dict[str, Any],
    spec: str,
    selected_features: list[str],
    selected_design: dict[str, Any],
    frontend_bundle: dict[str, Any] | None = None,
    backend_bundle: dict[str, Any] | None = None,
    delivery_plan: dict[str, Any] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    technical_design: dict[str, Any] | None = None,
    planning_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_workspace = _as_dict(code_workspace)
    workspace_files = [
        {
            "path": _ns(_as_dict(item).get("path")),
            "kind": _ns(_as_dict(item).get("kind")) or "txt",
            "content": str(_as_dict(item).get("content") or ""),
            "generated_from": _ns(_as_dict(item).get("generated_from")) or "generated_workspace",
        }
        for item in _as_list(existing_workspace.get("files"))
        if _ns(_as_dict(item).get("path"))
    ]
    if not workspace_files:
        return dict(existing_workspace)

    design = _as_dict(selected_design)
    prototype_spec = _as_dict(design.get("prototype_spec"))
    prototype_app = _as_dict(design.get("prototype_app"))
    prototype_app = {
        **prototype_app,
        "framework": _ns(prototype_app.get("framework")) or _ns(existing_workspace.get("framework")) or "nextjs",
        "router": _ns(prototype_app.get("router")) or _ns(existing_workspace.get("router")) or "app",
        "install_command": _ns(prototype_app.get("install_command")) or _ns(existing_workspace.get("install_command")) or "npm install",
        "dev_command": _ns(prototype_app.get("dev_command")) or _ns(existing_workspace.get("dev_command")) or "npm run dev",
        "build_command": _ns(prototype_app.get("build_command")) or _ns(existing_workspace.get("build_command")) or "npm run build",
        "entry_routes": _as_list(prototype_app.get("entry_routes")) or [_ns(existing_workspace.get("preview_entry")) or "/"],
    }
    technical_design_payload = _as_dict(technical_design)
    planning_analysis_payload = _as_dict(planning_analysis)
    frontend_payload = _as_dict(frontend_bundle)
    backend_payload = _as_dict(backend_bundle)
    delivery_payload = _as_dict(delivery_plan)
    technical_api_spec = [
        _as_dict(item)
        for item in _as_list(
            technical_design_payload.get("apiSpecification") or technical_design_payload.get("api_specification")
        )
        if _as_dict(item)
    ]
    interface_definitions = [
        _as_dict(item)
        for item in _as_list(
            technical_design_payload.get("interfaceDefinitions") or technical_design_payload.get("interface_definitions")
        )
        if _as_dict(item)
    ]
    entities = [
        _as_dict(item)
        for item in _as_list(backend_payload.get("entities"))
        if _as_dict(item)
    ] or [
        {
            "name": _ns(item.get("name")),
            "fields": [
                _ns(_as_dict(prop).get("name"))
                for prop in _as_list(item.get("properties"))
                if _ns(_as_dict(prop).get("name"))
            ],
        }
        for item in interface_definitions
        if _ns(item.get("name"))
    ]
    api_endpoints = [
        _as_dict(item)
        for item in _as_list(backend_payload.get("api_endpoints"))
        if _as_dict(item)
    ] or technical_api_spec
    work_packages = [_as_dict(item) for item in _as_list(delivery_payload.get("work_packages")) if _as_dict(item)]
    critical_path = [_ns(item) for item in _as_list(delivery_payload.get("critical_path")) if _ns(item)]
    wave_rows = [_as_dict(item) for item in _as_list(delivery_payload.get("waves")) if _as_dict(item)]
    work_unit_rows = [_as_dict(item) for item in _as_list(delivery_payload.get("work_unit_contracts")) if _as_dict(item)]
    milestone_rows = [_as_dict(item) for item in _as_list(milestones) if _as_dict(item)]
    interaction_notes = _unique_strings(_as_list(frontend_payload.get("interaction_notes")))
    review_focus = _unique_strings(
        _as_list(frontend_payload.get("interaction_notes"))
        + _as_list(backend_payload.get("automation_notes"))
        + _as_list(_as_dict(delivery_payload.get("merge_strategy")).get("conflict_prevention"))
    )[:8]
    design_contract_payload = _design_token_payload(planning_analysis_payload)
    development_standards_payload = _development_standards_payload(
        planning_analysis=planning_analysis_payload,
        selected_design=selected_design,
        selected_features=selected_features,
        api_specification=api_endpoints,
        milestones=milestone_rows,
    )
    access_model_payload = {
        "roles": [
            {
                "name": _ns(role.get("name")),
                "permissions": [_ns(item) for item in _as_list(role.get("permissions")) if _ns(item)],
                "responsibilities": [_ns(item) for item in _as_list(role.get("responsibilities")) if _ns(item)],
            }
            for role in _planning_roles(planning_analysis_payload)[:12]
        ],
        "protectedApi": [
            {
                "method": _ns(item.get("method") or "GET"),
                "path": _ns(item.get("path") or "/"),
                "description": _ns(item.get("description")),
            }
            for item in api_endpoints[:24]
            if bool(item.get("authRequired", True))
        ],
        "authSurfaces": _auth_surface_inventory(selected_design),
    }
    audit_events_payload = _build_audit_events(
        api_specification=api_endpoints,
        selected_features=selected_features,
        milestones=milestone_rows,
    )
    operability_contract_payload = {
        "auditEvents": audit_events_payload,
        "releaseSignals": _unique_strings(
            [
                "repo execution must pass install / build / test",
                "deploy handoff must be blocker-free before promotion",
                *[
                    _ns(item.get("criteria"))
                    for item in milestone_rows
                    if _ns(item.get("criteria"))
                ],
            ]
        )[:10],
        "promotionChecks": _unique_strings(
            [
                "spec audit closed with no critical or high gaps",
                "protected APIs keep explicit auth and permission boundaries",
                "design token and interaction contracts remain attached to the build",
                "audit events are defined for protected and release-critical flows",
            ]
        ),
    }
    canonical_title = _ns(prototype_spec.get("title")) or _ns(spec) or "Autonomous delivery workspace"
    value_contract_payload = _as_dict(delivery_payload.get("value_contract"))
    outcome_telemetry_payload = _as_dict(delivery_payload.get("outcome_telemetry_contract"))
    existing_paths = {
        _ns(_as_dict(item).get("path"))
        for item in workspace_files
        if _ns(_as_dict(item).get("path"))
    }

    workspace_files = _upsert_workspace_file(
        workspace_files,
        path="app/lib/control-plane-data.ts",
        kind="ts",
        content=_render_control_plane_data(
            selected_features=selected_features,
            work_packages=work_packages,
            critical_path=critical_path,
            waves=wave_rows,
            work_unit_contracts=work_unit_rows,
            milestones=milestone_rows,
            route_bindings=_as_list(existing_workspace.get("route_bindings")),
            api_endpoints=api_endpoints,
            entities=entities,
            interaction_notes=interaction_notes,
            review_focus=review_focus,
            goal_spec=_as_dict(delivery_payload.get("goal_spec")),
            dependency_analysis=_as_dict(delivery_payload.get("dependency_analysis")),
            design_contract=design_contract_payload,
            access_model=access_model_payload,
            operability_contract=operability_contract_payload,
            development_standards=development_standards_payload,
            shift_left_plan=_as_dict(delivery_payload.get("shift_left_plan")),
            value_contract=value_contract_payload,
            outcome_telemetry_contract=outcome_telemetry_payload,
        ),
        generated_from="delivery_plan",
    )
    workspace_files = _upsert_workspace_file(
        workspace_files,
        path="app/api/control-plane/route.ts",
        kind="ts",
        content=_render_control_plane_route(),
        generated_from="delivery_plan",
    )
    workspace_files = _upsert_workspace_file(
        workspace_files,
        path="app/components/prototype-shell.tsx",
        kind="tsx",
        content=_render_autonomous_prototype_shell(title=canonical_title, review_focus=review_focus),
        generated_from="delivery_plan",
    )
    workspace_files = _upsert_workspace_file(
        workspace_files,
        path="tests/acceptance/control-plane.spec.ts",
        kind="ts",
        content=_render_control_plane_test(),
        generated_from="delivery_plan",
    )
    workspace_files = _upsert_workspace_file(
        workspace_files,
        path="docs/spec/autonomous-delivery.md",
        kind="md",
        content=_render_autonomous_delivery_doc(
            work_packages=work_packages,
            critical_path=critical_path,
            review_focus=review_focus,
            waves=wave_rows,
            work_unit_contracts=work_unit_rows,
            shift_left_plan=_as_dict(delivery_payload.get("shift_left_plan")),
        ),
        generated_from="delivery_plan",
    )
    if entities or api_endpoints:
        workspace_files = _upsert_workspace_file(
            workspace_files,
            path="server/contracts/api-contract.ts",
            kind="ts",
            content=_render_backend_contract_from_bundle(entities, api_endpoints),
            generated_from="backend_bundle",
        )
    if entities:
        workspace_files = _upsert_workspace_file(
            workspace_files,
            path="server/domain/models.ts",
            kind="ts",
            content=_render_backend_models_from_bundle(entities),
            generated_from="backend_bundle",
        )

    workspace_files = _upsert_system_contract_artifacts(
        workspace_files,
        planning_analysis=planning_analysis_payload,
        selected_design=selected_design,
        selected_features=selected_features,
        api_specification=api_endpoints,
        milestones=milestone_rows,
        goal_spec=_as_dict(delivery_payload.get("goal_spec")),
        dependency_analysis=_as_dict(delivery_payload.get("dependency_analysis")),
        work_unit_contracts=work_unit_rows,
        waves=wave_rows,
        critical_path=critical_path,
        shift_left_plan=_as_dict(delivery_payload.get("shift_left_plan")),
        value_contract=value_contract_payload,
        outcome_telemetry_contract=outcome_telemetry_payload,
    )
    workspace_files = _inject_vitest_runtime(workspace_files)
    return _assemble_code_workspace(
        prototype_app=prototype_app,
        prototype_spec=prototype_spec,
        technical_design_payload=technical_design_payload,
        workspace_files=workspace_files,
        base_existing_paths=existing_paths,
    )


def build_development_spec_audit(
    *,
    selected_features: list[str],
    requirements: dict[str, Any] | None = None,
    task_decomposition: dict[str, Any] | None = None,
    dcs_analysis: dict[str, Any] | None = None,
    technical_design: dict[str, Any] | None = None,
    reverse_engineering: dict[str, Any] | None = None,
    code_workspace: dict[str, Any] | None = None,
    selected_design: dict[str, Any] | None = None,
    planning_analysis: dict[str, Any] | None = None,
    delivery_plan_context: dict[str, Any] | None = None,
    value_contract: dict[str, Any] | None = None,
    outcome_telemetry_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirement_rows = [_as_dict(item) for item in _as_list(_as_dict(requirements).get("requirements")) if _as_dict(item)]
    task_rows = [_as_dict(item) for item in _as_list(_as_dict(task_decomposition).get("tasks")) if _as_dict(item)]
    api_specification = [_as_dict(item) for item in _as_list(_as_dict(technical_design).get("apiSpecification")) if _as_dict(item)]
    database_schema = [_as_dict(item) for item in _as_list(_as_dict(technical_design).get("databaseSchema")) if _as_dict(item)]
    interface_definitions = [_as_dict(item) for item in _as_list(_as_dict(technical_design).get("interfaceDefinitions")) if _as_dict(item)]
    route_bindings = [_as_dict(item) for item in _as_list(_as_dict(code_workspace).get("route_bindings")) if _as_dict(item)]
    workspace_summary = _as_dict(_as_dict(code_workspace).get("artifact_summary"))
    workspace_paths = {
        _ns(_as_dict(item).get("path"))
        for item in _as_list(_as_dict(code_workspace).get("files"))
        if _ns(_as_dict(item).get("path"))
    }
    workspace_files = [
        _as_dict(item)
        for item in _as_list(_as_dict(code_workspace).get("files"))
        if _as_dict(item)
    ]
    workspace_file_map = {
        _ns(item.get("path")): item
        for item in workspace_files
        if _ns(item.get("path"))
    }
    quality_gates = [_as_dict(item) for item in _as_list(_as_dict(dcs_analysis).get("qualityGates")) if _as_dict(item)]
    reverse_engineering_payload = _as_dict(reverse_engineering)
    planning_analysis_payload = _as_dict(planning_analysis)
    selected_design_payload = _as_dict(selected_design)
    delivery_plan_payload = _as_dict(delivery_plan_context)
    goal_spec = _as_dict(delivery_plan_payload.get("goal_spec"))
    dependency_analysis = _as_dict(delivery_plan_payload.get("dependency_analysis"))
    work_unit_contracts = [
        _as_dict(item)
        for item in _as_list(delivery_plan_payload.get("work_unit_contracts"))
        if _as_dict(item)
    ]
    waves = [
        _as_dict(item)
        for item in _as_list(delivery_plan_payload.get("waves"))
        if _as_dict(item)
    ]
    shift_left_plan = _as_dict(delivery_plan_payload.get("shift_left_plan"))
    value_contract_payload = _as_dict(value_contract or delivery_plan_payload.get("value_contract"))
    outcome_telemetry_payload = _as_dict(
        outcome_telemetry_contract or delivery_plan_payload.get("outcome_telemetry_contract")
    )
    interaction_principles = _interaction_principles(selected_design_payload, planning_analysis_payload)
    design_token_contract_ready = _design_token_contract_ready(planning_analysis_payload)
    role_count, permission_count = _role_permission_counts(planning_analysis_payload)
    protected_api_specification = [
        item
        for item in api_specification
        if bool(item.get("authRequired", True))
    ]
    auth_scope_explicit = _auth_scope_explicit(
        selected_features=selected_features,
        requirement_rows=requirement_rows,
        task_rows=task_rows,
        api_specification=api_specification,
        planning_analysis=planning_analysis_payload,
        selected_design=selected_design_payload,
    )
    auth_ui_requested = _auth_ui_requested(
        selected_features=selected_features,
        requirement_rows=requirement_rows,
        task_rows=task_rows,
        planning_analysis=planning_analysis_payload,
    )
    auth_surface_present = _auth_surface_present(selected_design_payload, api_specification)
    value_contract_is_ready = value_contract_ready(value_contract_payload)
    outcome_telemetry_is_ready = outcome_telemetry_contract_ready(outcome_telemetry_payload)

    feature_coverage = []
    unresolved_gaps: list[dict[str, Any]] = []

    if not requirement_rows:
        unresolved_gaps.append(
            {
                "id": "requirements-missing",
                "title": "EARS requirements are missing",
                "severity": "critical",
                "detail": "Development cannot stay spec-driven without a normalized requirements bundle.",
                "closing_action": "Generate or backfill requirements before starting autonomous build execution.",
            }
        )
    if not task_rows:
        unresolved_gaps.append(
            {
                "id": "task-dag-missing",
                "title": "Task DAG is missing",
                "severity": "critical",
                "detail": "A dependency-aware delivery mesh needs normalized task decomposition.",
                "closing_action": "Generate task decomposition so lanes and merge order are grounded in a DAG.",
            }
        )
    if not api_specification:
        unresolved_gaps.append(
            {
                "id": "api-spec-missing",
                "title": "API specification is missing",
                "severity": "high",
                "detail": "Production delivery should expose typed API contracts, not only UI structure.",
                "closing_action": "Generate technical design API specification before starting the implementation lanes.",
            }
        )
    if not _as_dict(code_workspace).get("files"):
        unresolved_gaps.append(
            {
                "id": "workspace-missing",
                "title": "Code workspace is missing",
                "severity": "critical",
                "detail": "The delivery mesh has no multi-file workspace to execute against.",
                "closing_action": "Build a runnable multi-file workspace before launching lane execution.",
            }
        )
    if not design_token_contract_ready:
        unresolved_gaps.append(
            {
                "id": "design-token-contract-missing",
                "title": "Design token contract is missing",
                "severity": "high",
                "detail": "Autonomous implementation should not invent color, type, and surface primitives during build execution.",
                "closing_action": "Define approved design tokens for style, palette, and typography before autonomous build starts.",
            }
        )
    if not interaction_principles:
        unresolved_gaps.append(
            {
                "id": "interaction-contract-missing",
                "title": "Interaction contract is missing",
                "severity": "high",
                "detail": "The selected design does not specify motion, state, or micro-interaction principles tightly enough for autonomous implementation.",
                "closing_action": "Add interaction principles or motion notes to the selected design handoff before build lanes start.",
            }
        )
    if protected_api_specification and role_count > 0 and permission_count == 0:
        unresolved_gaps.append(
            {
                "id": "access-control-model-missing",
                "title": "Declared access roles lack permissions",
                "severity": "critical",
                "detail": "Roles are present in planning, but their permission boundaries are not explicit enough for protected endpoint implementation.",
                "closing_action": "Define the missing permissions for declared roles before autonomous build continues.",
            }
        )
    if protected_api_specification and not auth_scope_explicit:
        unresolved_gaps.append(
            {
                "id": "auth-boundary-missing",
                "title": "Protected API surface lacks an auth/session specification",
                "severity": "critical",
                "detail": "Protected endpoints exist, but the requirements, tasks, and selected design do not explain sign-in, session, access-denied, or external SSO boundaries.",
                "closing_action": "Specify login/session/forbidden/logout behavior or document external SSO ownership before autonomous build.",
            }
        )
    if auth_ui_requested and not auth_surface_present:
        unresolved_gaps.append(
            {
                "id": "auth-journey-missing",
                "title": "Requested auth journey is not represented in the selected design",
                "severity": "high",
                "detail": "The scope requests login/logout or session-facing behavior, but the design handoff does not contain matching surfaces or routes.",
                "closing_action": "Add the required auth screens, routes, and state transitions to the selected design before autonomous build.",
            }
        )
    if design_token_contract_ready and (
        "app/lib/design-tokens.ts" not in workspace_paths
        or "docs/spec/design-system.md" not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "design-token-implementation-missing",
                "title": "Design token implementation artifacts are missing",
                "severity": "high",
                "detail": "Approved design tokens exist in planning, but the runnable workspace does not carry a token module and design-system handoff document.",
                "closing_action": "Generate design token code and design-system documentation inside the development workspace before autonomous build continues.",
            }
        )
    if design_token_contract_ready:
        globals_css_content = str(_as_dict(workspace_file_map.get("app/globals.css")).get("content") or "")
        if "--color-brand-primary" not in globals_css_content or "--font-heading" not in globals_css_content:
            unresolved_gaps.append(
                {
                    "id": "design-token-usage-missing",
                    "title": "Runtime surfaces are not wired to approved design tokens",
                    "severity": "high",
                    "detail": "The workspace has design tokens, but app/globals.css does not expose the approved token variables needed by the prototype surfaces.",
                    "closing_action": "Wire app/globals.css to the approved design token variables before autonomous build continues.",
                }
            )
        hardcoded_brand_paths = _hardcoded_brand_color_paths(workspace_files)
        if hardcoded_brand_paths:
            unresolved_gaps.append(
                {
                    "id": "hardcoded-brand-values-detected",
                    "title": "Hard-coded brand values were detected outside the token contract",
                    "severity": "high",
                    "detail": f"Files with raw color literals: {', '.join(hardcoded_brand_paths[:6])}.",
                    "closing_action": "Move brand-specific colors and fonts into the design token contract so implementation remains consistent.",
                }
            )
        # Semantic token compliance check via CSS variable usage analysis
        expected_css_vars = [
            "--color-brand-primary",
            "--color-brand-secondary",
            "--color-brand-cta",
            "--color-app-background",
            "--color-app-text",
            "--font-heading",
            "--font-body",
        ]
        globals_css_for_check = str(_as_dict(workspace_file_map.get("app/globals.css")).get("content") or "")
        if globals_css_for_check:
            usage_report = _check_css_variable_usage(globals_css_for_check, expected_css_vars)
            if usage_report["compliance_score"] < 1.0:
                missing_vars = ", ".join(usage_report["variables_missing"][:5])
                unresolved_gaps.append(
                    {
                        "id": "semantic-token-compliance-gap",
                        "title": "CSS variable coverage is incomplete for semantic design tokens",
                        "severity": "high",
                        "detail": f"Missing CSS variables: {missing_vars}. Compliance: {usage_report['compliance_score']}.",
                        "closing_action": "Define all semantic token CSS custom properties in app/globals.css before autonomous build.",
                    }
                )
    if (
        "app/lib/development-standards.ts" not in workspace_paths
        or "docs/spec/development-standards.md" not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "development-standards-artifact-missing",
                "title": "Development standards artifacts are missing",
                "severity": "high",
                "detail": "The workspace should carry explicit implementation and coding rules so autonomous development stays consistent.",
                "closing_action": "Generate development-standards code and documentation before autonomous build continues.",
            }
        )
    if task_rows and not value_contract_is_ready:
        unresolved_gaps.append(
            {
                "id": "value-contract-missing",
                "title": "Value contract is missing",
                "severity": "critical",
                "detail": "Development is not grounded in a compiled persona / JTBD / IA / value-metric contract.",
                "closing_action": "Compile planning analysis into a value contract before autonomous build continues.",
            }
        )
    if task_rows and not outcome_telemetry_is_ready:
        unresolved_gaps.append(
            {
                "id": "outcome-telemetry-contract-missing",
                "title": "Outcome telemetry contract is missing",
                "severity": "critical",
                "detail": "Development cannot preserve release observability without explicit success metrics, telemetry events, and kill criteria.",
                "closing_action": "Compile outcome telemetry and release observability before autonomous build continues.",
            }
        )
    if value_contract_is_ready and (
        VALUE_CONTRACT_WORKSPACE_ARTIFACTS[0] not in workspace_paths
        or VALUE_CONTRACT_WORKSPACE_ARTIFACTS[1] not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "value-contract-artifact-missing",
                "title": "Value contract artifacts are missing",
                "severity": "high",
                "detail": "The workspace should materialize the compiled value contract as code and documentation.",
                "closing_action": "Generate value-contract code and documentation inside the development workspace before autonomous build continues.",
            }
        )
    if outcome_telemetry_is_ready and (
        OUTCOME_TELEMETRY_WORKSPACE_ARTIFACTS[0] not in workspace_paths
        or OUTCOME_TELEMETRY_WORKSPACE_ARTIFACTS[1] not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "outcome-telemetry-artifact-missing",
                "title": "Outcome telemetry artifacts are missing",
                "severity": "high",
                "detail": "The workspace should materialize the compiled telemetry contract as code and documentation.",
                "closing_action": "Generate outcome-telemetry code and documentation inside the development workspace before autonomous build continues.",
            }
        )
    if task_rows and (
        "app/lib/work-unit-contracts.ts" not in workspace_paths
        or "docs/spec/work-unit-contracts.md" not in workspace_paths
        or "docs/spec/delivery-waves.md" not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "work-unit-contract-artifact-missing",
                "title": "Work-unit contract artifacts are missing",
                "severity": "critical",
                "detail": "A governed delivery mesh should materialize work-unit contracts and wave topology as runnable artifacts inside the workspace.",
                "closing_action": "Generate work-unit contract and delivery-wave artifacts before autonomous build continues.",
            }
        )
    if task_rows and not goal_spec:
        unresolved_gaps.append(
            {
                "id": "goal-spec-missing",
                "title": "Goal spec decomposition is missing",
                "severity": "critical",
                "detail": "Development should decompose the approved context into an explicit goal spec before execution starts.",
                "closing_action": "Build a goal spec that binds selected features, requirements, milestones, and mandatory contracts.",
            }
        )
    if task_rows and not work_unit_contracts:
        unresolved_gaps.append(
            {
                "id": "work-unit-contracts-missing",
                "title": "Work-unit contracts are missing",
                "severity": "critical",
                "detail": "Feature delivery is still phase-wide instead of work-unit scoped, so local retries and traceability are not enforceable.",
                "closing_action": "Generate work-unit contracts with per-unit acceptance, QA, security, and repair policy metadata.",
            }
        )
    if task_rows and not waves:
        unresolved_gaps.append(
            {
                "id": "delivery-waves-missing",
                "title": "Execution wave plan is missing",
                "severity": "critical",
                "detail": "Parallel execution needs dependency-based waves rather than one flat frontend/backend split.",
                "closing_action": "Build a topologically ordered wave plan from the task DAG before autonomous build starts.",
            }
        )
    if dependency_analysis.get("has_cycles") is True or _as_list(dependency_analysis.get("unknown_dependencies")):
        unresolved_gaps.append(
            {
                "id": "dependency-analysis-invalid",
                "title": "Dependency analysis is invalid",
                "severity": "critical",
                "detail": "The delivery topology contains cycles or unknown dependencies, so wave execution cannot be trusted.",
                "closing_action": "Repair the dependency DAG and regenerate the wave plan before autonomous build continues.",
            }
        )
    if task_rows and _ns(shift_left_plan.get("mode")) != "work_unit_micro_loop":
        unresolved_gaps.append(
            {
                "id": "shift-left-quality-plan-missing",
                "title": "Shift-left quality plan is missing",
                "severity": "high",
                "detail": "QA and security are not embedded at the work-unit boundary, so failures would still bounce back too late.",
                "closing_action": "Define a work-unit micro-loop for builder, QA, security, and wave-exit review before autonomous build continues.",
            }
        )
    incomplete_contracts = [
        unit
        for unit in work_unit_contracts
        if not _as_list(unit.get("acceptance_criteria"))
        or not _as_list(unit.get("qa_checks"))
        or not _as_list(unit.get("security_checks"))
        or not set(_as_list(unit.get("required_contracts"))) >= set(REQUIRED_DELIVERY_CONTRACT_IDS)
        or not _as_list(unit.get("value_targets"))
        or not _as_list(unit.get("telemetry_events"))
    ]
    if incomplete_contracts:
        unresolved_gaps.append(
            {
                "id": "work-unit-contracts-incomplete",
                "title": "Some work-unit contracts are incomplete",
                "severity": "high",
                "detail": f"Incomplete WU count: {len(incomplete_contracts)}.",
                "closing_action": "Fill acceptance, QA, security, and required-contract sections for every work unit before autonomous build continues.",
            }
        )
    if (protected_api_specification or role_count > 0 or auth_ui_requested) and (
        "server/contracts/access-policy.ts" not in workspace_paths
        or "docs/spec/access-control.md" not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "access-control-artifact-missing",
                "title": "Access-control contract artifacts are missing",
                "severity": "critical" if protected_api_specification else "high",
                "detail": "Autonomous delivery needs an explicit access-policy contract and access-control handoff document when auth or roles are in scope.",
                "closing_action": "Generate access-policy and access-control artifacts so role, permission, and protected endpoint boundaries stay explicit.",
            }
        )
    if protected_api_specification:
        api_contract_content = str(_as_dict(workspace_file_map.get("server/contracts/api-contract.ts")).get("content") or "")
        if '"authRequired": true' not in api_contract_content:
            unresolved_gaps.append(
                {
                    "id": "protected-api-auth-flag-missing",
                    "title": "Protected API contract does not preserve authRequired metadata",
                    "severity": "critical",
                    "detail": "Protected API surfaces exist, but the generated API contract is missing explicit authRequired markers.",
                    "closing_action": "Propagate authRequired truth into the runnable API contract before autonomous build continues.",
                }
            )
    if api_specification and (
        "server/contracts/audit-events.ts" not in workspace_paths
        or "docs/spec/operability.md" not in workspace_paths
    ):
        unresolved_gaps.append(
            {
                "id": "operability-contract-missing",
                "title": "Operability contract artifacts are missing",
                "severity": "high",
                "detail": "A production-grade autonomous build should carry audit events, release signals, and operability guidance alongside the API surface.",
                "closing_action": "Generate audit-event and operability artifacts before autonomous build execution continues.",
            }
        )

    for feature in selected_features:
        requirement_covered = any(
            _text_matches_feature(
                " ".join(
                    [
                        _ns(item.get("statement")),
                        *[_ns(criterion) for criterion in _as_list(item.get("acceptanceCriteria")) if _ns(criterion)],
                    ]
                ),
                feature,
            )
            for item in requirement_rows
        )
        task_covered = any(
            _text_matches_feature(" ".join([_ns(item.get("title")), _ns(item.get("description"))]), feature)
            for item in task_rows
        )
        api_covered = any(
            _text_matches_feature(" ".join([_ns(item.get("path")), _ns(item.get("description"))]), feature)
            for item in api_specification
        )
        route_covered = any(
            _text_matches_feature(" ".join([_ns(item.get("route_path")), _ns(item.get("screen_id"))]), feature)
            for item in route_bindings
        )
        feature_coverage.append(
            {
                "feature": feature,
                "requirement_covered": requirement_covered,
                "task_covered": task_covered,
                "api_covered": api_covered,
                "route_covered": route_covered,
            }
        )
        if not requirement_covered:
            unresolved_gaps.append(
                {
                    "id": f"feature-{_slug(feature, prefix='feature')}-requirements",
                    "title": f"{feature} is not covered by requirements",
                    "severity": "high",
                    "detail": "The selected feature does not trace to a normalized EARS requirement.",
                    "closing_action": "Add or refine requirements so this feature has explicit acceptance criteria.",
                }
            )
        if not task_covered:
            unresolved_gaps.append(
                {
                    "id": f"feature-{_slug(feature, prefix='feature')}-tasks",
                    "title": f"{feature} is not decomposed into executable tasks",
                    "severity": "high",
                    "detail": "The selected feature is not grounded in the task DAG used by the delivery mesh.",
                    "closing_action": "Decompose this feature into explicit tasks with dependencies and effort.",
                }
            )

    critical_or_high = [
        item
        for item in unresolved_gaps
        if _ns(_as_dict(item).get("severity")) in {"critical", "high"}
    ]
    total_checks = max(
        1,
        4
        + 2
        + (1 if design_token_contract_ready else 0)
        + 1
        + 7
        + (1 if protected_api_specification or role_count > 0 or auth_ui_requested else 0)
        + (1 if api_specification else 0)
        + (2 if protected_api_specification else 0)
        + (1 if auth_ui_requested else 0)
        + len(selected_features),
    )
    passed_checks = total_checks - len(critical_or_high)
    completeness_score = round(max(0.0, min(1.0, passed_checks / total_checks)), 2)

    return {
        "status": "ready_for_autonomous_build" if not critical_or_high else "needs_spec_closure",
        "completeness_score": completeness_score,
        "requirements_count": len(requirement_rows),
        "task_count": len(task_rows),
        "api_surface_count": len(api_specification),
        "database_table_count": len(database_schema) or len(_as_list(reverse_engineering_payload.get("databaseSchema"))),
        "interface_count": len(interface_definitions) or len(_as_list(reverse_engineering_payload.get("interfaces"))),
        "route_binding_count": len(route_bindings),
        "workspace_file_count": int(workspace_summary.get("file_count", 0) or 0),
        "behavior_gate_count": len(quality_gates),
        "value_metric_count": len(_as_list(value_contract_payload.get("success_metrics"))),
        "telemetry_event_count": len(_as_list(outcome_telemetry_payload.get("telemetry_events"))),
        "feature_coverage": feature_coverage,
        "unresolved_gaps": unresolved_gaps,
        "closing_actions": list(
            dict.fromkeys(
                [
                    _ns(_as_dict(item).get("closing_action"))
                    for item in unresolved_gaps
                    if _ns(_as_dict(item).get("closing_action"))
                ]
            )
        ),
    }
