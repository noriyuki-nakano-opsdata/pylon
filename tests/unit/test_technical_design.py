"""Tests for technical design document generation services."""
from __future__ import annotations

from pylon.lifecycle.services.technical_design import (
    build_technical_design_bundle,
    evaluate_technical_design_quality,
    extract_api_specification,
    extract_interface_definitions,
    generate_architecture_doc,
    generate_database_schema,
    generate_dataflow_diagram,
)


def test_generate_architecture_doc_basic():
    analysis = {"description": "A project management tool"}
    features = [{"name": "Task Board", "description": "UI component for tasks"}]
    result = generate_architecture_doc(analysis, features=features)
    assert result["system_overview"] == "A project management tool"
    assert isinstance(result["components"], list)
    assert len(result["components"]) >= 1
    assert result["components"][0]["name"] == "Task Board"


def test_generate_architecture_doc_detects_spa_pattern():
    analysis = {"description": "Web app"}
    features = [
        {"name": "Dashboard Page", "description": "Main UI screen component"},
        {"name": "Users API", "description": "REST endpoint for user management"},
    ]
    result = generate_architecture_doc(analysis, features=features)
    assert result["architectural_pattern"] == "SPA + API"


def test_generate_architecture_doc_empty():
    result = generate_architecture_doc({})
    assert result["system_overview"] == "System overview not available."
    assert result["components"] == []
    assert isinstance(result["layers"], list)


def test_generate_dataflow_diagram_produces_mermaid():
    api_spec = [{"method": "GET", "path": "/api/v1/users"}]
    result = generate_dataflow_diagram(api_spec)
    assert result.startswith("flowchart")
    assert "GET /api/v1/users" in result
    assert "APIGateway" in result


def test_generate_dataflow_diagram_empty():
    result = generate_dataflow_diagram([])
    assert result.startswith("flowchart")
    assert "User" in result
    assert "Database" in result


def test_extract_api_specification_from_features():
    features = [{"name": "user"}]
    result = extract_api_specification(features)
    methods = [ep["method"] for ep in result]
    assert "GET" in methods
    assert "POST" in methods
    assert "PUT" in methods
    assert "DELETE" in methods
    assert any("/api/v1/users" in ep["path"] for ep in result)


def test_extract_api_specification_explicit_endpoints():
    features = [
        {
            "name": "auth",
            "endpoints": [
                {"method": "POST", "path": "/api/v1/login", "description": "Login"},
            ],
        }
    ]
    result = extract_api_specification(features)
    assert len(result) == 1
    assert result[0]["method"] == "POST"
    assert result[0]["path"] == "/api/v1/login"


def test_extract_api_specification_empty():
    result = extract_api_specification([])
    assert result == []


def test_generate_database_schema_basic():
    features = [{"name": "order", "fields": [{"name": "total", "type": "decimal"}]}]
    result = generate_database_schema(features)
    assert len(result) >= 1
    table = result[0]
    assert table["name"] == "orders"
    col_names = [c["name"] for c in table["columns"]]
    assert "id" in col_names
    assert "created_at" in col_names
    assert "updated_at" in col_names
    assert "total" in col_names


def test_generate_database_schema_with_references():
    features = [
        {
            "name": "line_item",
            "fields": [
                {"name": "order_id", "type": "uuid", "references": "orders.id"},
                {"name": "quantity", "type": "integer"},
            ],
        }
    ]
    result = generate_database_schema(features)
    assert len(result) >= 1
    table = result[0]
    ref_cols = [c for c in table["columns"] if c.get("references")]
    assert len(ref_cols) == 1
    assert ref_cols[0]["references"] == "orders.id"
    assert len(table["indexes"]) >= 1


def test_extract_interface_definitions_basic():
    features = [
        {
            "name": "user profile",
            "fields": [
                {"name": "email", "type": "text"},
                {"name": "age", "type": "integer"},
            ],
        }
    ]
    result = extract_interface_definitions(features)
    assert len(result) == 1
    iface = result[0]
    assert iface["name"] == "UserProfile"
    prop_names = [p["name"] for p in iface["properties"]]
    assert "id" in prop_names
    assert "createdAt" in prop_names
    assert "email" in prop_names
    prop_types = {p["name"]: p["type"] for p in iface["properties"]}
    assert prop_types["email"] == "string"
    assert prop_types["age"] == "number"


def test_extract_interface_definitions_empty():
    result = extract_interface_definitions([])
    assert result == []


def test_build_technical_design_bundle_complete():
    analysis = {"description": "E-commerce platform"}
    features = [
        {"name": "Product Catalog", "description": "REST API endpoint for products",
         "fields": [{"name": "price", "type": "decimal"}]},
        {"name": "Shopping Cart", "description": "UI page component for cart"},
    ]
    result = build_technical_design_bundle(analysis, features)
    assert "architecture" in result
    assert "dataflow_mermaid" in result
    assert "api_specification" in result
    assert "database_schema" in result
    assert "interface_definitions" in result
    assert "component_dependency_graph" in result
    assert result["architecture"]["architectural_pattern"] == "SPA + API"
    assert len(result["api_specification"]) > 0
    assert result["dataflow_mermaid"].startswith("flowchart")


def test_evaluate_technical_design_quality_pass():
    bundle = build_technical_design_bundle(
        {"description": "Test system"},
        [{"name": "Widget API", "description": "REST endpoint",
          "fields": [{"name": "label", "type": "text"}]}],
    )
    gates = evaluate_technical_design_quality(bundle)
    completeness_gate = next(g for g in gates if g["id"] == "technical-design-completeness")
    assert completeness_gate["passed"] is True
    api_gate = next(g for g in gates if g["id"] == "api-specification-present")
    assert api_gate["passed"] is True


def test_evaluate_technical_design_quality_fail():
    gates = evaluate_technical_design_quality({})
    completeness_gate = next(g for g in gates if g["id"] == "technical-design-completeness")
    assert completeness_gate["passed"] is False
    api_gate = next(g for g in gates if g["id"] == "api-specification-present")
    assert api_gate["passed"] is False
