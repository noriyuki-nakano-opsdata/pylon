"""Materialize development workspaces and execute real repo commands."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pylon.experiments.gitops import (
    create_detached_worktree,
    ensure_worktree_excludes,
    remove_worktree,
    resolve_repo_root,
)

_IGNORED_SCAN_PARTS = {
    ".git",
    ".next",
    ".pylon",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
_MISSING_MODULE_PATTERN = re.compile(r"Cannot find module '([^']+)'")


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


def _workspace_root(
    *,
    project_key: str,
    repo_root: str | None = None,
) -> tuple[str, Path, str | None]:
    base_dir = Path(tempfile.gettempdir()) / "pylon-lifecycle-development" / _slug(project_key, prefix="project")
    if repo_root:
        try:
            resolved_repo_root = resolve_repo_root(repo_root)
        except Exception:
            resolved_repo_root = None
        if resolved_repo_root is not None:
            run_id = uuid.uuid4().hex[:10]
            worktree_path = base_dir / run_id / "worktree"
            create_detached_worktree(resolved_repo_root, worktree_path=worktree_path, ref="HEAD")
            ensure_worktree_excludes(worktree_path, ["node_modules/", ".next/", ".pylon/"])
            return ("git_worktree", worktree_path, str(worktree_path))
    workspace_path = base_dir / uuid.uuid4().hex[:10]
    workspace_path.mkdir(parents=True, exist_ok=True)
    return ("temp_workspace", workspace_path, None)


def _write_workspace_files(workspace_path: Path, files: list[dict[str, Any]]) -> int:
    written = 0
    for item in files:
        record = _as_dict(item)
        relative_path = _ns(record.get("path"))
        if not relative_path:
            continue
        target = workspace_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(record.get("content") or ""), encoding="utf-8")
        written += 1
    return written


def _trim_output(text: str, *, limit: int = 1600) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[-limit:]


def _run_shell_command(
    command: str,
    *,
    cwd: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    normalized = _ns(command)
    if not normalized:
        return {
            "status": "skipped",
            "command": normalized,
            "exit_code": None,
            "duration_ms": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        }
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            normalized,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            executable="/bin/zsh",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "command": normalized,
            "exit_code": completed.returncode,
            "duration_ms": int((time.monotonic() - started_at) * 1000),
            "stdout_tail": _trim_output(completed.stdout),
            "stderr_tail": _trim_output(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "command": normalized,
            "exit_code": None,
            "duration_ms": timeout_seconds * 1000,
            "stdout_tail": _trim_output(exc.stdout or ""),
            "stderr_tail": _trim_output(exc.stderr or ""),
        }


def _is_scannable(path: Path) -> bool:
    return not any(part in _IGNORED_SCAN_PARTS for part in path.parts)


def _iter_workspace_files(workspace_path: Path, pattern: str) -> list[Path]:
    return sorted(path for path in workspace_path.rglob(pattern) if _is_scannable(path))


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _load_toml_file(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _detect_package_manager(project_root: Path, payload: dict[str, Any]) -> str:
    package_manager = _ns(payload.get("packageManager")).lower()
    if package_manager.startswith("pnpm"):
        return "pnpm"
    if package_manager.startswith("yarn"):
        return "yarn"
    if package_manager.startswith("bun"):
        return "bun"
    if (project_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_root / "yarn.lock").exists():
        return "yarn"
    if (project_root / "bun.lock").exists() or (project_root / "bun.lockb").exists():
        return "bun"
    return "npm"


def _package_manager_test_command(package_manager: str, *, append_run: bool = False) -> str:
    if package_manager == "pnpm":
        return "pnpm test -- --run" if append_run else "pnpm test"
    if package_manager == "yarn":
        return "yarn test --run" if append_run else "yarn test"
    if package_manager == "bun":
        return "bun run test -- --run" if append_run else "bun run test"
    return "npm test -- --run" if append_run else "npm test"


def _package_manager_exec_vitest(package_manager: str) -> str:
    if package_manager == "pnpm":
        return "pnpm exec vitest run"
    if package_manager == "yarn":
        return "yarn vitest run"
    if package_manager == "bun":
        return "bunx vitest run"
    return "npm exec vitest run"


def _normalize_install_command(command: str, *, workspace_path: Path) -> str:
    normalized = _ns(command) or "npm install"
    package_json = workspace_path / "package.json"
    package_manager = _detect_package_manager(workspace_path, _load_json_file(package_json)) if package_json.exists() else "npm"
    if package_manager == "npm" and normalized in {"npm install", "npm ci"} and "--include=optional" not in normalized:
        return normalized + " --include=optional"
    return normalized


def _workspace_contains_vitest_markers(project_root: Path, payload: dict[str, Any]) -> bool:
    scripts = _as_dict(payload.get("scripts"))
    dependencies = {
        **_as_dict(payload.get("dependencies")),
        **_as_dict(payload.get("devDependencies")),
    }
    if "vitest" in _ns(scripts.get("test")).lower():
        return True
    if "vitest" in {str(key) for key in dependencies}:
        return True
    for path in _iter_workspace_files(project_root, "*.ts") + _iter_workspace_files(project_root, "*.tsx"):
        if path.name.startswith("vitest.config"):
            return True
        if any(token in path.name for token in (".spec.", ".test.")):
            content = path.read_text(encoding="utf-8")
            if '"vitest"' in content or "'vitest'" in content:
                return True
    return False


def _discover_node_test_plan(workspace_path: Path) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    seen_roots: set[Path] = set()
    for package_json in _iter_workspace_files(workspace_path, "package.json"):
        project_root = package_json.parent
        if project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        payload = _load_json_file(package_json)
        if not payload:
            continue
        scripts = _as_dict(payload.get("scripts"))
        package_manager = _detect_package_manager(project_root, payload)
        script_test = _ns(scripts.get("test"))
        if script_test:
            normalized_script = script_test.lower()
            command = _package_manager_test_command(
                package_manager,
                append_run="vitest" in normalized_script and "run" not in normalized_script and "--run" not in normalized_script,
            )
            plan.append(
                {
                    "runtime": "node",
                    "project_root": str(project_root),
                    "command": command,
                    "reason": "package_json_scripts_test",
                    "timeout_seconds": 240,
                }
            )
            continue
        if _workspace_contains_vitest_markers(project_root, payload):
            plan.append(
                {
                    "runtime": "node",
                    "project_root": str(project_root),
                    "command": _package_manager_exec_vitest(package_manager),
                    "reason": "vitest_markers",
                    "timeout_seconds": 240,
                }
            )
    return plan


def _pyproject_has_pytest(pyproject_path: Path) -> bool:
    payload = _load_toml_file(pyproject_path)
    tool = _as_dict(payload.get("tool"))
    pytest_payload = _as_dict(tool.get("pytest"))
    return bool(pytest_payload.get("ini_options")) or bool(pytest_payload)


def _tox_has_pytest(tox_path: Path) -> bool:
    try:
        content = tox_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[pytest]" in content


def _python_test_command(project_root: Path) -> str:
    local_python = project_root / ".venv" / "bin" / "python"
    if local_python.exists():
        return f"{shlex.quote(str(local_python))} -m pytest"
    return f"{shlex.quote(sys.executable)} -m pytest"


def _discover_python_test_plan(workspace_path: Path) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    seen_roots: set[Path] = set()

    for pyproject in _iter_workspace_files(workspace_path, "pyproject.toml"):
        project_root = pyproject.parent
        if project_root in seen_roots or not _pyproject_has_pytest(pyproject):
            continue
        seen_roots.add(project_root)
        plan.append(
            {
                "runtime": "python",
                "project_root": str(project_root),
                "command": _python_test_command(project_root),
                "reason": "pyproject_pytest",
                "timeout_seconds": 240,
            }
        )

    for pytest_ini in _iter_workspace_files(workspace_path, "pytest.ini"):
        project_root = pytest_ini.parent
        if project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        plan.append(
            {
                "runtime": "python",
                "project_root": str(project_root),
                "command": _python_test_command(project_root),
                "reason": "pytest_ini",
                "timeout_seconds": 240,
            }
        )

    for tox_ini in _iter_workspace_files(workspace_path, "tox.ini"):
        project_root = tox_ini.parent
        if project_root in seen_roots or not _tox_has_pytest(tox_ini):
            continue
        seen_roots.add(project_root)
        plan.append(
            {
                "runtime": "python",
                "project_root": str(project_root),
                "command": _python_test_command(project_root),
                "reason": "tox_ini_pytest",
                "timeout_seconds": 240,
            }
        )

    if not seen_roots:
        python_tests = _iter_workspace_files(workspace_path, "test_*.py") + _iter_workspace_files(workspace_path, "*_test.py")
        if python_tests:
            plan.append(
                {
                    "runtime": "python",
                    "project_root": str(workspace_path),
                    "command": _python_test_command(workspace_path),
                    "reason": "python_test_files",
                    "timeout_seconds": 240,
                }
            )
    return plan


def _workspace_contains_test_surfaces(workspace_path: Path) -> bool:
    for pattern in ("*.spec.ts", "*.spec.tsx", "*.test.ts", "*.test.tsx", "test_*.py", "*_test.py", "pytest.ini"):
        if _iter_workspace_files(workspace_path, pattern):
            return True
    for pyproject in _iter_workspace_files(workspace_path, "pyproject.toml"):
        if _pyproject_has_pytest(pyproject):
            return True
    return False


def _build_test_plan(workspace_path: Path) -> list[dict[str, Any]]:
    combined = [* _discover_node_test_plan(workspace_path), * _discover_python_test_plan(workspace_path)]
    return sorted(combined, key=lambda item: (str(item.get("project_root") or ""), str(item.get("runtime") or "")))


def _run_test_plan(test_plan: list[dict[str, Any]]) -> dict[str, Any]:
    if not test_plan:
        return {
            "status": "skipped",
            "command": "",
            "exit_code": None,
            "duration_ms": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "executions": [],
        }

    executions: list[dict[str, Any]] = []
    for item in test_plan:
        project_root = Path(str(item.get("project_root") or "."))
        command = _ns(item.get("command"))
        result = _run_shell_command(
            command,
            cwd=project_root,
            timeout_seconds=int(item.get("timeout_seconds", 240) or 240),
        )
        result["runtime"] = str(item.get("runtime") or "unknown")
        result["project_root"] = str(project_root)
        result["reason"] = str(item.get("reason") or "detected")
        executions.append(result)

    failed = [item for item in executions if item.get("status") == "failed"]
    primary = failed[0] if failed else executions[-1]
    stdout_segments = [
        f"[{Path(str(item.get('project_root') or '.')).name or '.'}] {str(item.get('stdout_tail') or '').strip()}"
        for item in executions
        if _ns(item.get("stdout_tail"))
    ]
    stderr_segments = [
        f"[{Path(str(item.get('project_root') or '.')).name or '.'}] {str(item.get('stderr_tail') or '').strip()}"
        for item in executions
        if _ns(item.get("stderr_tail"))
    ]
    return {
        "status": "failed" if failed else "passed",
        "command": " && ".join(_ns(item.get("command")) for item in test_plan if _ns(item.get("command"))),
        "exit_code": primary.get("exit_code"),
        "duration_ms": sum(int(item.get("duration_ms", 0) or 0) for item in executions),
        "stdout_tail": _trim_output("\n\n".join(stdout_segments)),
        "stderr_tail": _trim_output("\n\n".join(stderr_segments)),
        "executions": executions,
    }


def _needs_node_optional_dependency_repair(test_result: dict[str, Any]) -> bool:
    error_text = " ".join(
        [
            _ns(test_result.get("stderr_tail")),
            *[_ns(_as_dict(item).get("stderr_tail")) for item in _as_list(test_result.get("executions"))],
        ]
    )
    return "Cannot find module '@rollup/rollup-" in error_text


def _missing_node_module_name(test_result: dict[str, Any]) -> str | None:
    error_text = " ".join(
        [
            _ns(test_result.get("stderr_tail")),
            *[_ns(_as_dict(item).get("stderr_tail")) for item in _as_list(test_result.get("executions"))],
        ]
    )
    match = _MISSING_MODULE_PATTERN.search(error_text)
    return match.group(1) if match else None


def _repair_node_optional_dependencies(test_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    seen_roots: set[str] = set()
    for item in test_plan:
        record = _as_dict(item)
        if _ns(record.get("runtime")) != "node":
            continue
        project_root = _ns(record.get("project_root"))
        if not project_root or project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        root_path = Path(project_root)
        package_json = root_path / "package.json"
        package_manager = _detect_package_manager(root_path, _load_json_file(package_json)) if package_json.exists() else "npm"
        if package_manager == "pnpm":
            command = "pnpm install"
        elif package_manager == "yarn":
            command = "yarn install"
        elif package_manager == "bun":
            command = "bun install"
        else:
            command = "npm install --include=optional"
        result = _run_shell_command(command, cwd=root_path, timeout_seconds=240)
        result["runtime"] = "node"
        result["project_root"] = str(root_path)
        result["reason"] = "optional_native_dependency_repair"
        repairs.append(result)
    return repairs


def _repair_missing_node_module(test_plan: list[dict[str, Any]], *, module_name: str) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    seen_roots: set[str] = set()
    normalized_module = _ns(module_name)
    if not normalized_module:
        return repairs
    for item in test_plan:
        record = _as_dict(item)
        if _ns(record.get("runtime")) != "node":
            continue
        project_root = _ns(record.get("project_root"))
        if not project_root or project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        root_path = Path(project_root)
        package_json = root_path / "package.json"
        package_manager = _detect_package_manager(root_path, _load_json_file(package_json)) if package_json.exists() else "npm"
        quoted_module = shlex.quote(normalized_module)
        if package_manager == "pnpm":
            command = f"pnpm add -D {quoted_module}"
        elif package_manager == "yarn":
            command = f"yarn add -D {quoted_module}"
        elif package_manager == "bun":
            command = f"bun add -d {quoted_module}"
        else:
            command = f"npm install --no-save {quoted_module}"
        result = _run_shell_command(command, cwd=root_path, timeout_seconds=240)
        result["runtime"] = "node"
        result["project_root"] = str(root_path)
        result["reason"] = "missing_node_module_repair"
        repairs.append(result)
    return repairs


def _local_repo_candidate(github_repo: Any) -> str | None:
    raw = _ns(github_repo)
    if not raw:
        return None
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        candidate = Path(parsed.path).expanduser()
        return str(candidate) if candidate.exists() else None
    candidate = Path(raw).expanduser()
    return str(candidate) if candidate.exists() else None


def execute_development_code_workspace(
    *,
    project_key: str,
    github_repo: Any,
    code_workspace: dict[str, Any],
) -> dict[str, Any]:
    workspace_payload = _as_dict(code_workspace)
    files = [_as_dict(item) for item in _as_list(workspace_payload.get("files")) if _as_dict(item)]
    if not files:
        return {
            "mode": "unavailable",
            "workspace_path": "",
            "worktree_path": None,
            "repo_root": None,
            "materialized_file_count": 0,
            "install": {
                "status": "skipped",
                "command": "",
                "exit_code": None,
                "duration_ms": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            },
            "build": {
                "status": "skipped",
                "command": "",
                "exit_code": None,
                "duration_ms": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            },
            "test": {
                "status": "skipped",
                "command": "",
                "exit_code": None,
                "duration_ms": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            },
            "ready": False,
            "errors": ["Code workspace has no files to materialize."],
        }
    local_repo = _local_repo_candidate(github_repo)
    mode, workspace_path, worktree_path = _workspace_root(project_key=project_key, repo_root=local_repo)
    materialized_count = _write_workspace_files(workspace_path, files)

    install_result = _run_shell_command(
        _normalize_install_command(_ns(workspace_payload.get("install_command")) or "npm install", workspace_path=workspace_path),
        cwd=workspace_path,
        timeout_seconds=240,
    )
    build_result = _run_shell_command(
        _ns(workspace_payload.get("build_command")) or "npm run build",
        cwd=workspace_path,
        timeout_seconds=240,
    ) if install_result["status"] == "passed" else {
        "status": "skipped",
        "command": _ns(workspace_payload.get("build_command")) or "npm run build",
        "exit_code": None,
        "duration_ms": 0,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    test_plan = _build_test_plan(workspace_path)
    if build_result["status"] == "passed" and test_plan:
        test_result = _run_test_plan(test_plan)
        if test_result["status"] == "failed" and _needs_node_optional_dependency_repair(test_result):
            repair_runs = _repair_node_optional_dependencies(test_plan)
            repaired_test_result = test_result
            if repair_runs and all(item.get("status") == "passed" for item in repair_runs):
                repaired_test_result = _run_test_plan(test_plan)
            missing_module = _missing_node_module_name(repaired_test_result)
            if repaired_test_result["status"] == "failed" and missing_module:
                module_repairs = _repair_missing_node_module(test_plan, module_name=missing_module)
                repair_runs.extend(module_repairs)
                if module_repairs and all(item.get("status") == "passed" for item in module_repairs):
                    repaired_test_result = _run_test_plan(test_plan)
            repaired_test_result["repair_attempts"] = repair_runs
            test_result = repaired_test_result
    elif build_result["status"] == "passed" and _workspace_contains_test_surfaces(workspace_path):
        test_result = {
            "status": "failed",
            "command": "",
            "exit_code": None,
            "duration_ms": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "executions": [],
        }
    else:
        test_result = {
            "status": "skipped",
            "command": "",
            "exit_code": None,
            "duration_ms": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "executions": [],
        }

    errors = []
    if install_result["status"] == "failed":
        errors.append("Workspace dependency install failed.")
    if build_result["status"] == "failed":
        errors.append("Workspace build command failed.")
    if build_result["status"] == "passed" and _workspace_contains_test_surfaces(workspace_path) and not test_plan:
        errors.append("Workspace exposes tests but no runnable vitest/pytest plan could be inferred.")
    if test_result["status"] == "failed":
        errors.append("Workspace test plan failed.")

    return {
        "mode": mode,
        "workspace_path": str(workspace_path),
        "worktree_path": worktree_path,
        "repo_root": local_repo,
        "materialized_file_count": materialized_count,
        "install": install_result,
        "build": build_result,
        "test": test_result,
        "test_plan": test_plan,
        "ready": not errors and build_result["status"] == "passed",
        "errors": errors,
    }


def cleanup_development_code_workspace(result: dict[str, Any]) -> None:
    worktree_path = _ns(_as_dict(result).get("worktree_path"))
    repo_root = _ns(_as_dict(result).get("repo_root"))
    workspace_path = _ns(_as_dict(result).get("workspace_path"))
    if worktree_path and repo_root:
        try:
            remove_worktree(repo_root, worktree_path)
            return
        except Exception:
            pass
    if workspace_path:
        shutil.rmtree(workspace_path, ignore_errors=True)
