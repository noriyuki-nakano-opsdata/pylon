"""Technical design document generation services.

Produces architecture documentation, Mermaid dataflow diagrams, API specifications,
database schema definitions, and TypeScript interface definitions from lifecycle outputs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class APIEndpoint:
    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str  # /api/v1/users
    description: str = ""
    request_body: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    auth_required: bool = True


@dataclass(frozen=True)
class DatabaseTable:
    name: str
    columns: tuple[dict[str, Any], ...] = ()
    indexes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterfaceDefinition:
    name: str
    properties: tuple[dict[str, Any], ...] = ()
    extends: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalDesignBundle:
    architecture: dict[str, Any] = field(default_factory=dict)
    dataflow_mermaid: str = ""
    api_specification: tuple[APIEndpoint, ...] = ()
    database_schema: tuple[DatabaseTable, ...] = ()
    interface_definitions: tuple[InterfaceDefinition, ...] = ()
    component_dependency_graph: dict[str, tuple[str, ...]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_dict(v: Any) -> dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _as_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


def _ns(v: Any) -> str:
    return str(v).strip() if v is not None else ""


_LAYER_UI_HINTS = re.compile(r"\b(page|screen|component|ui|frontend|view|form|dialog)\b", re.I)
_LAYER_API_HINTS = re.compile(r"\b(api|endpoint|rest|graphql|route|handler|controller)\b", re.I)
_LAYER_DATA_HINTS = re.compile(r"\b(database|schema|table|column|migration|model|entity|record)\b", re.I)

_CRUD_METHODS = ("GET", "POST", "PUT", "DELETE")


def _to_snake_case(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]", "_", name.strip())
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"_+", "_", s).strip("_").lower()


def _to_pascal_case(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name.strip())
    return "".join(part.capitalize() for part in parts if part)


def _to_plural(name: str) -> str:
    lower = name.lower()
    if lower.endswith("s"):
        return lower
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return lower[:-1] + "ies"
    return lower + "s"


def _feature_text(feature: dict[str, Any]) -> str:
    parts = [
        _ns(feature.get("name")),
        _ns(feature.get("description")),
        _ns(feature.get("summary")),
    ]
    return " ".join(p for p in parts if p)


def _detect_layers(features: list[dict[str, Any]]) -> dict[str, bool]:
    combined = " ".join(_feature_text(_as_dict(f)) for f in features)
    return {
        "ui": bool(_LAYER_UI_HINTS.search(combined)),
        "api": bool(_LAYER_API_HINTS.search(combined)),
        "data": bool(_LAYER_DATA_HINTS.search(combined)),
    }


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

def generate_architecture_doc(
    analysis: dict[str, Any],
    design_variant: dict[str, Any] | None = None,
    features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate architecture documentation from planning analysis and design variant."""
    analysis = _as_dict(analysis)
    variant = _as_dict(design_variant)
    feats = [_as_dict(f) for f in _as_list(features)]

    system_overview = (
        _ns(analysis.get("description"))
        or _ns(analysis.get("summary"))
        or _ns(variant.get("description"))
        or "System overview not available."
    )

    layers_detected = _detect_layers(feats)
    has_ui = layers_detected["ui"]
    has_api = layers_detected["api"]
    has_data = layers_detected["data"]

    if has_ui and has_api:
        pattern = "SPA + API"
    elif has_api and not has_ui:
        pattern = "API service"
    elif has_ui and not has_api:
        pattern = "Monolith"
    else:
        pattern = "Monolith"

    components: list[dict[str, Any]] = []
    layer_defs: list[dict[str, Any]] = []

    if has_ui:
        layer_defs.append({"name": "UI", "description": "User interface layer", "components": []})
    if has_api:
        layer_defs.append({"name": "API", "description": "API gateway and routing layer", "components": []})
    if has_data:
        layer_defs.append({"name": "Data", "description": "Data persistence layer", "components": []})
    if not layer_defs:
        layer_defs.append({"name": "Application", "description": "Core application layer", "components": []})

    for feat in feats:
        name = _ns(feat.get("name")) or "unnamed"
        text = _feature_text(feat)
        deps: list[str] = []
        if has_ui and _LAYER_UI_HINTS.search(text):
            layer = "UI"
            if has_api:
                deps.append("API")
        elif has_api and _LAYER_API_HINTS.search(text):
            layer = "API"
            if has_data:
                deps.append("Data")
        elif has_data and _LAYER_DATA_HINTS.search(text):
            layer = "Data"
        else:
            layer = layer_defs[0]["name"]

        comp = {
            "name": name,
            "layer": layer,
            "responsibility": _ns(feat.get("description")) or name,
            "dependencies": deps,
        }
        components.append(comp)
        for ld in layer_defs:
            if ld["name"] == layer:
                ld["components"].append(name)

    constraints = _as_list(analysis.get("constraints")) or _as_list(variant.get("constraints"))
    quality_attributes = _as_list(analysis.get("quality_attributes")) or _as_list(
        variant.get("quality_attributes")
    )

    return {
        "system_overview": system_overview,
        "architectural_pattern": pattern,
        "components": components,
        "layers": layer_defs,
        "constraints": [_ns(c) for c in constraints if _ns(c)],
        "quality_attributes": [_ns(q) for q in quality_attributes if _ns(q)],
    }


# ---------------------------------------------------------------------------
# Dataflow diagram
# ---------------------------------------------------------------------------

def generate_dataflow_diagram(
    api_spec: list[dict[str, Any]],
    architecture: dict[str, Any] | None = None,
) -> str:
    """Generate Mermaid flowchart for data flow."""
    lines = ["flowchart LR"]
    lines.append("    User([User])")
    lines.append("    Frontend[Frontend]")
    lines.append("    APIGateway[API Gateway]")
    lines.append("    Services[Services]")
    lines.append("    Database[(Database)]")

    endpoints = [_as_dict(ep) for ep in _as_list(api_spec)]
    if endpoints:
        for ep in endpoints[:10]:
            method = _ns(ep.get("method")) or "REQ"
            path = _ns(ep.get("path")) or "/"
            label = f"{method} {path}"
            lines.append(f"    User -->|request| Frontend")
            lines.append(f'    Frontend -->|"{label}"| APIGateway')
            lines.append(f"    APIGateway --> Services")
            lines.append(f"    Services --> Database")
            break  # representative flow; add one edge set per unique pattern
        if len(endpoints) > 1:
            for ep in endpoints[1:5]:
                method = _ns(ep.get("method")) or "REQ"
                path = _ns(ep.get("path")) or "/"
                lines.append(f'    Frontend -->|"{method} {path}"| APIGateway')
    else:
        lines.append("    User -->|request| Frontend")
        lines.append("    Frontend --> APIGateway")
        lines.append("    APIGateway --> Services")
        lines.append("    Services --> Database")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API specification
# ---------------------------------------------------------------------------

def extract_api_specification(
    features: list[dict[str, Any]],
    design_variant: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract API endpoint specifications from features."""
    endpoints: list[dict[str, Any]] = []
    variant = _as_dict(design_variant)

    for feat in [_as_dict(f) for f in _as_list(features)]:
        explicit = _as_list(feat.get("endpoints"))
        if explicit:
            for ep in explicit:
                ep_data = _as_dict(ep)
                endpoints.append({
                    "method": _ns(ep_data.get("method")) or "GET",
                    "path": _ns(ep_data.get("path")) or "/api/v1/unknown",
                    "description": _ns(ep_data.get("description")) or _ns(feat.get("name")),
                    "request_body": _as_dict(ep_data.get("request_body")),
                    "response_schema": _as_dict(ep_data.get("response_schema")),
                    "auth_required": ep_data.get("auth_required", True) is not False,
                })
            continue

        name = _ns(feat.get("name"))
        if not name:
            continue
        resource = _to_snake_case(name)
        plural = _to_plural(resource)
        base_path = f"/api/v1/{plural}"

        endpoints.append({
            "method": "GET",
            "path": base_path,
            "description": f"List {plural}",
            "request_body": {},
            "response_schema": {"type": "array", "items": {"type": "object"}},
            "auth_required": True,
        })
        endpoints.append({
            "method": "POST",
            "path": base_path,
            "description": f"Create {resource}",
            "request_body": {"type": "object"},
            "response_schema": {"type": "object"},
            "auth_required": True,
        })
        endpoints.append({
            "method": "GET",
            "path": f"{base_path}/:id",
            "description": f"Get {resource} by ID",
            "request_body": {},
            "response_schema": {"type": "object"},
            "auth_required": True,
        })
        endpoints.append({
            "method": "PUT",
            "path": f"{base_path}/:id",
            "description": f"Update {resource}",
            "request_body": {"type": "object"},
            "response_schema": {"type": "object"},
            "auth_required": True,
        })
        endpoints.append({
            "method": "DELETE",
            "path": f"{base_path}/:id",
            "description": f"Delete {resource}",
            "request_body": {},
            "response_schema": {},
            "auth_required": True,
        })

    return endpoints


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

_STANDARD_COLUMNS: tuple[dict[str, Any], ...] = (
    {"name": "id", "type": "uuid", "nullable": False, "primary_key": True, "references": None},
    {"name": "created_at", "type": "timestamptz", "nullable": False, "primary_key": False, "references": None},
    {"name": "updated_at", "type": "timestamptz", "nullable": False, "primary_key": False, "references": None},
)


def generate_database_schema(
    features: list[dict[str, Any]],
    api_spec: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate database schema from features."""
    tables: list[dict[str, Any]] = []
    table_names: set[str] = set()

    for feat in [_as_dict(f) for f in _as_list(features)]:
        name = _ns(feat.get("name"))
        if not name:
            continue
        text = _feature_text(feat)
        if not _LAYER_DATA_HINTS.search(text) and not _as_list(feat.get("fields")) and not _as_list(feat.get("properties")):
            # Only generate tables for features that imply data storage or have fields
            if not any(kw in text.lower() for kw in ("store", "save", "persist", "record", "crud", "list", "manage")):
                continue

        table_name = _to_snake_case(name)
        plural_name = _to_plural(table_name)
        if plural_name in table_names:
            continue
        table_names.add(plural_name)

        columns: list[dict[str, Any]] = list(_STANDARD_COLUMNS)
        indexes: list[str] = []

        for prop in _as_list(feat.get("fields")) or _as_list(feat.get("properties")):
            prop_data = _as_dict(prop)
            col_name = _to_snake_case(_ns(prop_data.get("name")))
            if not col_name or col_name in {"id", "created_at", "updated_at"}:
                continue
            col_type = _ns(prop_data.get("type")) or "text"
            ref = _ns(prop_data.get("references")) or None
            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": prop_data.get("nullable", True) is not False,
                "primary_key": False,
                "references": ref,
            })
            if ref:
                indexes.append(f"idx_{plural_name}_{col_name}")

        tables.append({
            "name": plural_name,
            "columns": columns,
            "indexes": indexes,
        })

    return tables


# ---------------------------------------------------------------------------
# Interface definitions
# ---------------------------------------------------------------------------

_TS_TYPE_MAP: dict[str, str] = {
    "uuid": "string",
    "text": "string",
    "varchar": "string",
    "int": "number",
    "integer": "number",
    "float": "number",
    "double": "number",
    "decimal": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "timestamptz": "string",
    "timestamp": "string",
    "date": "string",
    "json": "Record<string, unknown>",
    "jsonb": "Record<string, unknown>",
}


def extract_interface_definitions(
    features: list[dict[str, Any]],
    design_variant: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract TypeScript-style interface definitions from features."""
    interfaces: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for feat in [_as_dict(f) for f in _as_list(features)]:
        name = _ns(feat.get("name"))
        if not name:
            continue
        iface_name = _to_pascal_case(name)
        if iface_name in seen_names:
            continue
        seen_names.add(iface_name)

        properties: list[dict[str, Any]] = [
            {"name": "id", "type": "string", "optional": False},
            {"name": "createdAt", "type": "string", "optional": False},
            {"name": "updatedAt", "type": "string", "optional": False},
        ]

        for prop in _as_list(feat.get("fields")) or _as_list(feat.get("properties")):
            prop_data = _as_dict(prop)
            prop_name = _ns(prop_data.get("name"))
            if not prop_name or prop_name in {"id", "createdAt", "updatedAt", "created_at", "updated_at"}:
                continue
            raw_type = _ns(prop_data.get("type")).lower()
            ts_type = _TS_TYPE_MAP.get(raw_type, "string")
            properties.append({
                "name": prop_name,
                "type": ts_type,
                "optional": prop_data.get("optional", False) is True,
            })

        extends_raw = _as_list(feat.get("extends"))
        extends = tuple(_ns(e) for e in extends_raw if _ns(e))

        interfaces.append({
            "name": iface_name,
            "properties": properties,
            "extends": list(extends),
        })

    return interfaces


# ---------------------------------------------------------------------------
# Bundle orchestrator
# ---------------------------------------------------------------------------

def build_technical_design_bundle(
    analysis: dict[str, Any],
    features: list[dict[str, Any]],
    design_variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete technical design bundle."""
    architecture = generate_architecture_doc(analysis, design_variant, features)
    api_spec = extract_api_specification(features, design_variant)
    dataflow = generate_dataflow_diagram(api_spec, architecture)
    db_schema = generate_database_schema(features, api_spec)
    interfaces = extract_interface_definitions(features, design_variant)

    dep_graph: dict[str, list[str]] = {}
    for comp in _as_list(architecture.get("components")):
        comp_data = _as_dict(comp)
        comp_name = _ns(comp_data.get("name"))
        if comp_name:
            dep_graph[comp_name] = [_ns(d) for d in _as_list(comp_data.get("dependencies")) if _ns(d)]

    return {
        "architecture": architecture,
        "dataflow_mermaid": dataflow,
        "api_specification": api_spec,
        "database_schema": db_schema,
        "interface_definitions": interfaces,
        "component_dependency_graph": dep_graph,
    }


# ---------------------------------------------------------------------------
# Quality evaluation
# ---------------------------------------------------------------------------

def evaluate_technical_design_quality(
    bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate technical design completeness."""
    bundle = _as_dict(bundle)
    gates: list[dict[str, Any]] = []

    architecture = _as_dict(bundle.get("architecture"))
    has_overview = bool(_ns(architecture.get("system_overview")))
    has_components = bool(_as_list(architecture.get("components")))
    arch_passed = has_overview and has_components
    gates.append({
        "id": "technical-design-completeness",
        "title": "Technical design documentation is complete",
        "passed": arch_passed,
        "reason": (
            "architecture documentation has system overview and components"
            if arch_passed
            else "architecture documentation is missing system overview or components"
        ),
    })

    api_spec = _as_list(bundle.get("api_specification"))
    api_passed = len(api_spec) > 0
    gates.append({
        "id": "api-specification-present",
        "title": "API specification contains at least one endpoint",
        "passed": api_passed,
        "reason": (
            f"API specification contains {len(api_spec)} endpoint(s)"
            if api_passed
            else "API specification is empty"
        ),
    })

    dataflow = _ns(bundle.get("dataflow_mermaid"))
    dataflow_passed = dataflow.startswith("flowchart")
    gates.append({
        "id": "dataflow-diagram-valid",
        "title": "Dataflow diagram is a valid Mermaid flowchart",
        "passed": dataflow_passed,
        "reason": (
            "dataflow diagram starts with flowchart declaration"
            if dataflow_passed
            else "dataflow diagram is missing or invalid"
        ),
    })

    return gates
