"""Tests for reverse engineering services."""
from __future__ import annotations

import pytest

from pylon.lifecycle.services.reverse_engineering import (
    build_reverse_engineering_result,
    detect_languages,
    evaluate_reverse_engineering_quality,
    extract_api_endpoints,
    extract_database_tables,
    extract_interfaces,
    extract_requirements_from_code,
    generate_task_structure,
    generate_test_specs,
)


def test_detect_languages() -> None:
    paths = ["src/app.py", "lib/utils.ts", "main.js", "schema.sql", "README.md"]
    result = detect_languages(paths)
    assert "python" in result
    assert "typescript" in result
    assert "javascript" in result
    assert "sql" in result
    # README.md has no mapping
    assert "markdown" not in result
    # Should be sorted
    assert result == sorted(result)


def test_extract_api_endpoints_express() -> None:
    code = """
const express = require('express');
const app = express();

app.get('/users', listUsers);
app.post('/users', createUser);
app.get('/users/:id', getUser);
app.delete('/users/:id', deleteUser);
"""
    snippets = [{"content": code, "file_path": "routes/users.js", "language": "javascript"}]
    endpoints = extract_api_endpoints(snippets)

    assert len(endpoints) == 4
    methods = {ep["method"] for ep in endpoints}
    assert methods == {"GET", "POST", "DELETE"}
    paths = {ep["path"] for ep in endpoints}
    assert "/users" in paths
    assert "/users/:id" in paths


def test_extract_api_endpoints_fastapi() -> None:
    code = """
from fastapi import APIRouter

router = APIRouter()

@router.get("/items")
async def list_items():
    pass

@router.post("/items")
async def create_item():
    pass

@router.put("/items/{item_id}")
async def update_item(item_id: int):
    pass
"""
    snippets = [{"content": code, "file_path": "api/items.py", "language": "python"}]
    endpoints = extract_api_endpoints(snippets)

    assert len(endpoints) == 3
    methods = {ep["method"] for ep in endpoints}
    assert methods == {"GET", "POST", "PUT"}
    paths = {ep["path"] for ep in endpoints}
    assert "/items" in paths
    assert "/items/{item_id}" in paths


def test_extract_api_endpoints_empty() -> None:
    endpoints = extract_api_endpoints([])
    assert endpoints == []

    endpoints = extract_api_endpoints([{"content": "", "file_path": "", "language": ""}])
    assert endpoints == []


def test_extract_interfaces_typescript() -> None:
    code = """
export interface UserProfile {
    id: string;
    name: string;
}

interface Settings {
    theme: string;
}
"""
    snippets = [{"content": code, "file_path": "types/user.ts", "language": "typescript"}]
    interfaces = extract_interfaces(snippets)

    names = {i["name"] for i in interfaces}
    assert "UserProfile" in names
    assert "Settings" in names
    assert all(i["kind"] == "interface" for i in interfaces)


def test_extract_interfaces_python_dataclass() -> None:
    code = """
from dataclasses import dataclass

@dataclass(frozen=True)
class OrderItem:
    product_id: str
    quantity: int

class BaseModel:
    pass

class UserService(BaseModel):
    def get_user(self):
        pass
"""
    snippets = [{"content": code, "file_path": "models/order.py", "language": "python"}]
    interfaces = extract_interfaces(snippets)

    names = {i["name"] for i in interfaces}
    assert "OrderItem" in names
    assert "BaseModel" in names
    assert "UserService" in names


def test_extract_database_tables_sql() -> None:
    code = """
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id)
);
"""
    snippets = [{"content": code, "file_path": "migrations/001.sql", "language": "sql"}]
    tables = extract_database_tables(snippets)

    names = {t["name"] for t in tables}
    assert "users" in names
    assert "orders" in names
    assert all(t["source"] == "raw_sql" for t in tables)


def test_extract_database_tables_sqlalchemy() -> None:
    code = """
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String)

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
"""
    snippets = [{"content": code, "file_path": "models/product.py", "language": "python"}]
    tables = extract_database_tables(snippets)

    names = {t["name"] for t in tables}
    assert "Product" in names
    assert "Category" in names
    assert all(t["source"] == "orm" for t in tables)


def test_extract_requirements_from_code_test_names() -> None:
    test_code = """
def test_should_create_user_with_valid_email():
    pass

def test_when_user_not_found_returns_404():
    pass

def test_should_hash_password_before_storing():
    pass
"""
    reqs = extract_requirements_from_code(
        code_snippets=[],
        test_snippets=[{"content": test_code, "file_path": "tests/test_user.py", "language": "python"}],
    )

    assert len(reqs) >= 3
    assert all(r["id"].startswith("REQ-R-") for r in reqs)
    assert all(0.4 <= r["confidence"] <= 0.7 for r in reqs)
    assert all(r["source_file"] == "tests/test_user.py" for r in reqs)

    # Check that test_when_ produces event-driven pattern
    when_reqs = [r for r in reqs if "when" in r["statement"].lower()]
    assert any(r["pattern"] == "event-driven" for r in when_reqs)


def test_extract_requirements_from_code_empty() -> None:
    reqs = extract_requirements_from_code(code_snippets=[], test_snippets=None)
    assert reqs == []

    reqs = extract_requirements_from_code(
        code_snippets=[{"content": "", "file_path": "", "language": ""}],
        test_snippets=[],
    )
    assert reqs == []


def test_generate_task_structure() -> None:
    endpoints = [
        {"method": "GET", "path": "/users", "handler": "list", "file_path": "routes/users.js"},
        {"method": "POST", "path": "/users", "handler": "create", "file_path": "routes/users.js"},
    ]
    interfaces = [
        {"name": "UserProfile", "kind": "interface", "properties": [], "file_path": "types/user.ts"},
    ]
    tables = [
        {"name": "users", "columns": [], "source": "raw_sql"},
    ]

    tasks = generate_task_structure(endpoints, interfaces, tables)

    assert len(tasks) >= 1
    assert all(t["id"].startswith("TASK-R-") for t in tasks)
    assert all("feature_area" in t for t in tasks)
    assert all("source_files" in t for t in tasks)
    # The "users" feature area should appear
    areas = {t["feature_area"] for t in tasks}
    assert "users" in areas


def test_generate_test_specs() -> None:
    endpoints = [
        {"method": "GET", "path": "/items", "handler": "list", "file_path": "api.py"},
        {"method": "POST", "path": "/items", "handler": "create", "file_path": "api.py"},
        {"method": "GET", "path": "/items/{id}", "handler": "get", "file_path": "api.py"},
    ]
    specs = generate_test_specs(endpoints)

    assert len(specs) > 0
    assert all(s["id"].startswith("SPEC-R-") for s in specs)

    # GET /items should have success + auth cases
    items_specs = [s for s in specs if s["endpoint"] == "GET /items"]
    cases = {s["case"] for s in items_specs}
    assert "success" in cases
    assert "auth_failure" in cases

    # POST should also have validation_error
    post_specs = [s for s in specs if s["endpoint"] == "POST /items"]
    post_cases = {s["case"] for s in post_specs}
    assert "validation_error" in post_cases

    # Parameterized GET should have not_found
    param_specs = [s for s in specs if s["endpoint"] == "GET /items/{id}"]
    param_cases = {s["case"] for s in param_specs}
    assert "not_found" in param_cases


def test_build_reverse_engineering_result() -> None:
    code_snippets = [
        {
            "content": """
from fastapi import APIRouter
router = APIRouter()

@router.get("/projects")
async def list_projects():
    pass

@router.post("/projects")
async def create_project():
    pass
""",
            "file_path": "src/api/projects.py",
            "language": "python",
        },
    ]
    test_snippets = [
        {
            "content": """
def test_should_list_projects():
    pass
""",
            "file_path": "tests/test_projects.py",
            "language": "python",
        },
    ]

    result = build_reverse_engineering_result(
        code_snippets,
        test_snippets=test_snippets,
        file_paths=["src/api/projects.py", "tests/test_projects.py"],
    )

    assert "python" in result["languages_detected"]
    assert len(result["api_endpoints"]) >= 2
    assert len(result["extracted_requirements"]) >= 1
    assert result["coverage_score"] > 0
    assert isinstance(result["architecture_doc"], dict)
    assert isinstance(result["dataflow_mermaid"], str)


def test_build_reverse_engineering_result_empty() -> None:
    result = build_reverse_engineering_result(code_snippets=[], test_snippets=None, file_paths=[])

    assert result["extracted_requirements"] == []
    assert result["api_endpoints"] == []
    assert result["database_schema"] == []
    assert result["interfaces"] == []
    assert result["task_structure"] == []
    assert result["test_specs"] == []
    assert result["coverage_score"] == 0.0
    assert result["languages_detected"] == []


def test_evaluate_reverse_engineering_quality_pass() -> None:
    result = {
        "coverage_score": 0.71,
        "extracted_requirements": [{"id": "REQ-R-0001"}],
        "api_endpoints": [{"method": "GET", "path": "/test"}],
    }
    gates = evaluate_reverse_engineering_quality(result)

    coverage_gate = next(g for g in gates if g["id"] == "reverse-engineering-coverage")
    assert coverage_gate["passed"] is True
    assert ">= 0.60" in coverage_gate["reason"]

    req_gate = next(g for g in gates if g["id"] == "reverse-engineering-requirements")
    assert req_gate["passed"] is True

    api_gate = next(g for g in gates if g["id"] == "reverse-engineering-api-surface")
    assert api_gate["passed"] is True


def test_evaluate_reverse_engineering_quality_fail() -> None:
    result = {
        "coverage_score": 0.29,
        "extracted_requirements": [],
        "api_endpoints": [],
    }
    gates = evaluate_reverse_engineering_quality(result)

    coverage_gate = next(g for g in gates if g["id"] == "reverse-engineering-coverage")
    assert coverage_gate["passed"] is False
    assert "< 0.60" in coverage_gate["reason"]

    req_gate = next(g for g in gates if g["id"] == "reverse-engineering-requirements")
    assert req_gate["passed"] is False

    api_gate = next(g for g in gates if g["id"] == "reverse-engineering-api-surface")
    assert api_gate["passed"] is False
