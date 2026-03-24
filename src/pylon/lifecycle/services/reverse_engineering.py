"""Reverse engineering services for existing codebases.

Extracts requirements, architecture documentation, API surfaces, database schemas,
task structures, and test specifications from analyzed code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ExtractedEndpoint:
    method: str
    path: str
    handler: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class ExtractedInterface:
    name: str
    kind: str = "interface"
    properties: tuple[dict[str, Any], ...] = ()
    file_path: str = ""


@dataclass(frozen=True)
class ExtractedTable:
    name: str
    columns: tuple[dict[str, Any], ...] = ()
    source: str = ""


@dataclass(frozen=True)
class ReverseEngineeringResult:
    extracted_requirements: tuple[dict[str, Any], ...] = ()
    architecture_doc: dict[str, Any] = field(default_factory=dict)
    dataflow_mermaid: str = ""
    api_endpoints: tuple[ExtractedEndpoint, ...] = ()
    database_schema: tuple[ExtractedTable, ...] = ()
    interfaces: tuple[ExtractedInterface, ...] = ()
    task_structure: tuple[dict[str, Any], ...] = ()
    test_specs: tuple[dict[str, Any], ...] = ()
    coverage_score: float = 0.0
    languages_detected: tuple[str, ...] = ()


_ROUTE_PATTERNS: dict[str, re.Pattern[str]] = {
    "express": re.compile(r"(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
    "fastapi": re.compile(r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
    "flask": re.compile(r"@(?:app|blueprint)\.(route)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
}
_INTERFACE_PATTERNS: dict[str, re.Pattern[str]] = {
    "typescript": re.compile(r"(?:export\s+)?interface\s+(\w+)"),
    "python_dataclass": re.compile(r"@dataclass[^)]*\)\s*class\s+(\w+)"),
    "python_class": re.compile(r"class\s+(\w+)\s*(?:\([^)]*\))?:"),
}
_TABLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "create_table": re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)[\"']?", re.I),
    "sqlalchemy": re.compile(r"class\s+(\w+)\s*\(.*(?:Base|Model)\s*\)"),
    "django": re.compile(r"class\s+(\w+)\s*\(.*models\.Model\s*\)"),
}
_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".rb": "ruby", ".go": "go",
    ".rs": "rust", ".java": "java", ".kt": "kotlin", ".cs": "csharp",
    ".sql": "sql", ".sh": "shell", ".css": "css", ".html": "html",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json",
}
_TEST_NAME_RE = re.compile(r"(?:def|it|test|describe)\s*\(?\s*['\"]?(test_\w+|should_\w+|when_\w+)['\"]?")
_VALIDATION_RE = re.compile(r"(?:if\s+not\s+|assert\s+|validate|raise\s+(?:ValueError|TypeError|ValidationError))", re.I)
_ERROR_HANDLING_RE = re.compile(r"(?:try\s*:|except\s+|catch\s*\(|\.catch\s*\()", re.I)
_TABLE_SOURCE = {"create_table": "raw_sql", "sqlalchemy": "orm", "django": "orm"}
_VERB_MAP = {"GET": "retrieve", "POST": "create", "PUT": "update", "DELETE": "remove", "PATCH": "modify"}
_SKIP_DIRS = {"src", "app", "api", "routes", "controllers", "models", "lib", "utils"}


def _as_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, list) else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        t = str(v).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def detect_languages(file_paths: list[str]) -> list[str]:
    """Detect programming languages from file extensions. Returns sorted unique list."""
    langs: set[str] = set()
    for p in file_paths:
        low = str(p).strip().lower()
        for ext, lang in _LANGUAGE_MAP.items():
            if low.endswith(ext):
                langs.add(lang)
                break
    return sorted(langs)


def _detect_framework(content: str, language: str) -> str:
    low = content.lower()
    if language in ("typescript", "javascript"):
        return "express"
    if language == "python":
        if "fastapi" in low or "@app.get" in low or "@router.get" in low:
            return "fastapi"
        if "flask" in low or "@app.route" in low or "@blueprint.route" in low:
            return "flask"
        return "fastapi"
    return "express"


def extract_api_endpoints(code_snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract API endpoint definitions from code snippets."""
    endpoints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snip in code_snippets:
        content, fp, lang = str(snip.get("content", "")), str(snip.get("file_path", "")), str(snip.get("language", "")).lower()
        if not content.strip():
            continue
        pat = _ROUTE_PATTERNS.get(_detect_framework(content, lang))
        if not pat:
            continue
        for m in pat.finditer(content):
            method = "GET" if m.group(1).upper() == "ROUTE" else m.group(1).upper()
            path = m.group(2)
            if (method, path) in seen:
                continue
            seen.add((method, path))
            handler = ""
            rest = content[m.end():m.end() + 200]
            hm = re.search(r"[\s,]*(\w+)\s*[)\]]", rest)
            if hm:
                handler = hm.group(1)
            endpoints.append({"method": method, "path": path, "handler": handler, "file_path": fp})
    return endpoints


def extract_interfaces(code_snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract interface/class/type definitions from code snippets."""
    interfaces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snip in code_snippets:
        content, fp, lang = str(snip.get("content", "")), str(snip.get("file_path", "")), str(snip.get("language", "")).lower()
        if not content.strip():
            continue
        pats: list[tuple[str, re.Pattern[str]]] = []
        if lang in ("typescript", "javascript"):
            pats.append(("interface", _INTERFACE_PATTERNS["typescript"]))
        elif lang == "python":
            pats.append(("class", _INTERFACE_PATTERNS["python_dataclass"]))
            pats.append(("class", _INTERFACE_PATTERNS["python_class"]))
        else:
            pats = [("interface" if k == "typescript" else "class", p) for k, p in _INTERFACE_PATTERNS.items()]
        for kind, pat in pats:
            for m in pat.finditer(content):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    interfaces.append({"name": name, "kind": kind, "properties": [], "file_path": fp})
    return interfaces


def extract_database_tables(code_snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract database table definitions from code snippets."""
    tables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snip in code_snippets:
        content = str(snip.get("content", ""))
        if not content.strip():
            continue
        for pname, pat in _TABLE_PATTERNS.items():
            for m in pat.finditer(content):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    tables.append({"name": name, "columns": [], "source": _TABLE_SOURCE.get(pname, "raw_sql")})
    return tables


def _req_from_test(test_name: str, fp: str, idx: int) -> dict[str, Any]:
    stripped = test_name.removeprefix("test_")
    if stripped.startswith("when_"):
        body = stripped.removeprefix("when_").replace("_", " ").strip()
        return {"id": f"REQ-R-{idx:04d}", "pattern": "event-driven",
                "statement": f"When {body}, the system shall handle it correctly",
                "confidence": 0.5, "source_file": fp, "source_type": "test_name"}
    body = stripped.removeprefix("should_").replace("_", " ").strip()
    return {"id": f"REQ-R-{idx:04d}", "pattern": "ubiquitous",
            "statement": f"The system shall {body}",
            "confidence": 0.5, "source_file": fp, "source_type": "test_name"}


def _req_from_endpoint(ep: dict[str, Any], idx: int) -> dict[str, Any]:
    method, path = str(ep.get("method", "GET")).upper(), str(ep.get("path", "/"))
    verb = _VERB_MAP.get(method, "handle")
    resource = path.rstrip("/").rsplit("/", 1)[-1].lstrip(":").replace("{", "").replace("}", "") or "resource"
    return {"id": f"REQ-R-{idx:04d}", "pattern": "event-driven",
            "statement": f"When a {method} request is sent to {path}, the system shall {verb} the {resource}",
            "confidence": 0.6, "source_file": str(ep.get("file_path", "")), "source_type": "api_route"}


def extract_requirements_from_code(
    code_snippets: list[dict[str, Any]],
    test_snippets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract implicit requirements from code and test files."""
    reqs: list[dict[str, Any]] = []
    seen: set[str] = set()
    idx = 1

    def _add(r: dict[str, Any]) -> None:
        nonlocal idx
        norm = r["statement"].lower()
        if norm not in seen:
            seen.add(norm)
            reqs.append(r)
            idx += 1

    for snip in _as_list(test_snippets):
        content, fp = str(snip.get("content", "")), str(snip.get("file_path", ""))
        if not content.strip():
            continue
        for m in _TEST_NAME_RE.finditer(content):
            name = m.group(1)
            if name.startswith(("test_", "should_", "when_")):
                _add(_req_from_test(name, fp, idx))

    err_seen: set[str] = set()
    val_seen: set[str] = set()
    for snip in code_snippets:
        content, fp = str(snip.get("content", "")), str(snip.get("file_path", ""))
        if not content.strip():
            continue
        if fp not in err_seen and _ERROR_HANDLING_RE.search(content):
            err_seen.add(fp)
            _add({"id": f"REQ-R-{idx:04d}", "pattern": "unwanted",
                  "statement": "If an error occurs, then the system shall handle it gracefully",
                  "confidence": 0.4, "source_file": fp, "source_type": "error_handling"})
        if fp not in val_seen and _VALIDATION_RE.search(content):
            val_seen.add(fp)
            _add({"id": f"REQ-R-{idx:04d}", "pattern": "unwanted",
                  "statement": "If invalid input is provided, then the system shall reject it with an appropriate error",
                  "confidence": 0.5, "source_file": fp, "source_type": "validation"})

    for ep in extract_api_endpoints(code_snippets):
        _add(_req_from_endpoint(ep, idx))
    return reqs


def _feature_area(name: str) -> str:
    parts = [p for p in name.lower().replace("\\", "/").split("/") if p.strip()]
    meaningful = [p for p in parts if p not in _SKIP_DIRS]
    return meaningful[0].replace("_", "-").replace(".", "-") if meaningful else "general"


def generate_task_structure(
    endpoints: list[dict[str, Any]],
    interfaces: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate task structure from extracted code artifacts grouped by feature area."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for ep in endpoints:
        groups.setdefault(_feature_area(str(ep.get("path", ""))), []).append(
            {"detail": f"{ep.get('method','GET')} {ep.get('path','')}", "file_path": str(ep.get("file_path", ""))})
    for iface in interfaces:
        groups.setdefault(_feature_area(str(iface.get("file_path", iface.get("name", "")))), []).append(
            {"detail": str(iface.get("name", "")), "file_path": str(iface.get("file_path", ""))})
    for t in tables:
        groups.setdefault(_feature_area(str(t.get("name", ""))), []).append(
            {"detail": str(t.get("name", "")), "file_path": ""})

    tasks: list[dict[str, Any]] = []
    for i, (area, items) in enumerate(sorted(groups.items()), 1):
        files = _dedupe([str(it.get("file_path", "")) for it in items if str(it.get("file_path", "")).strip()])
        details = [str(it.get("detail", "")) for it in items]
        desc = f"Implement {area} feature covering: {', '.join(details[:5])}"
        if len(details) > 5:
            desc += f" and {len(details) - 5} more"
        tasks.append({"id": f"TASK-R-{i:04d}", "title": f"Implement {area} feature area",
                       "description": desc, "feature_area": area, "source_files": files})
    return tasks


def generate_test_specs(
    endpoints: list[dict[str, Any]],
    existing_tests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate test specifications for discovered endpoints."""
    existing_text = " ".join(str(t.get("content", "")).lower() for t in (existing_tests or []))
    specs: list[dict[str, Any]] = []
    idx = 1
    for ep in endpoints:
        method, path = str(ep.get("method", "GET")).upper(), str(ep.get("path", "/"))
        label, has_param = f"{method} {path}", ("{" in path or ":" in path)
        covered = path.lower() in existing_text
        for case, desc, cond in [
            ("success", f"{label} returns expected success response", True),
            ("auth_failure", f"{label} returns 401 when unauthenticated", True),
            ("validation_error", f"{label} returns 422 for invalid payload", method in ("POST", "PUT", "PATCH")),
            ("not_found", f"{label} returns 404 for non-existent resource", has_param),
        ]:
            if not cond:
                continue
            specs.append({"id": f"SPEC-R-{idx:04d}", "endpoint": label, "case": case,
                          "description": desc, "covered": covered if case == "success" else False})
            idx += 1
    return specs


def build_reverse_engineering_result(
    code_snippets: list[dict[str, Any]],
    test_snippets: list[dict[str, Any]] | None = None,
    file_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build complete reverse engineering result. Orchestrates all extractors."""
    all_paths = list(file_paths or []) or _dedupe([
        str(s.get("file_path", "")) for s in [*code_snippets, *(test_snippets or [])]
        if str(s.get("file_path", "")).strip()])
    languages = detect_languages(all_paths)
    endpoints = extract_api_endpoints(code_snippets)
    interfaces = extract_interfaces(code_snippets)
    tables = extract_database_tables(code_snippets)
    requirements = extract_requirements_from_code(code_snippets, test_snippets)
    tasks = generate_task_structure(endpoints, interfaces, tables)
    test_specs = generate_test_specs(endpoints, test_snippets)

    areas = [bool(requirements), bool(endpoints), bool(tables), bool(interfaces),
             bool(tasks), bool(test_specs), bool(languages)]
    coverage = sum(areas) / len(areas) if areas else 0.0

    arch: dict[str, Any] = {}
    if languages: arch["languages"] = languages
    if endpoints: arch["endpoint_count"] = len(endpoints)
    if interfaces: arch["interface_count"] = len(interfaces)
    if tables: arch["table_count"] = len(tables)

    dataflow = ""
    if endpoints:
        lines = ["graph LR"]
        for ep in endpoints[:10]:
            safe = ep["path"].replace("/", "_").replace("{", "").replace("}", "").replace(":", "")
            lines.append(f"    Client -->|{ep['method']}| {safe}[{ep['path']}]")
        dataflow = "\n".join(lines)

    return {"extracted_requirements": requirements, "architecture_doc": arch,
            "dataflow_mermaid": dataflow, "api_endpoints": endpoints,
            "database_schema": tables, "interfaces": interfaces,
            "task_structure": tasks, "test_specs": test_specs,
            "coverage_score": round(coverage, 2), "languages_detected": languages}


def evaluate_reverse_engineering_quality(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate quality of reverse engineering results. Passes if coverage_score >= 0.6."""
    cov = float(result.get("coverage_score", 0.0) or 0.0)
    reqs = _as_list(result.get("extracted_requirements"))
    eps = _as_list(result.get("api_endpoints"))
    return [
        {"id": "reverse-engineering-coverage",
         "title": "Reverse engineering extraction coverage is sufficient",
         "passed": cov >= 0.6,
         "reason": f"Coverage score {cov:.2f} meets threshold (>= 0.60)" if cov >= 0.6
                   else f"Coverage score {cov:.2f} is below threshold (< 0.60)"},
        {"id": "reverse-engineering-requirements",
         "title": "Requirements were successfully extracted from code",
         "passed": bool(reqs),
         "reason": f"Extracted {len(reqs)} requirements" if reqs
                   else "No requirements could be extracted from the codebase"},
        {"id": "reverse-engineering-api-surface",
         "title": "API surface was successfully mapped",
         "passed": bool(eps),
         "reason": f"Discovered {len(eps)} API endpoints" if eps
                   else "No API endpoints discovered in the codebase"},
    ]
