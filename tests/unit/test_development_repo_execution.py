"""Tests for repo-native development workspace execution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pylon.lifecycle.services.development_repo_execution import (
    cleanup_development_code_workspace,
    execute_development_code_workspace,
)


def test_execute_development_code_workspace_materializes_and_runs_commands() -> None:
    code_workspace = {
        "install_command": "true",
        "build_command": "true",
        "files": [
            {
                "path": "package.json",
                "content": json.dumps(
                    {
                        "name": "demo-workspace",
                        "private": True,
                        "scripts": {"test": "true"},
                    }
                ),
            },
            {
                "path": "app/page.tsx",
                "content": "export default function Page() { return <main>ok</main>; }\n",
            },
        ],
    }

    result = execute_development_code_workspace(
        project_key="demo-project",
        github_repo=None,
        code_workspace=code_workspace,
    )

    workspace_path = Path(result["workspace_path"])
    assert result["mode"] == "temp_workspace"
    assert result["ready"] is True
    assert result["materialized_file_count"] == 2
    assert result["install"]["status"] == "passed"
    assert result["build"]["status"] == "passed"
    assert result["test"]["status"] == "passed"
    assert len(result["test_plan"]) == 1
    assert (workspace_path / "package.json").exists()
    assert (workspace_path / "app/page.tsx").exists()

    cleanup_development_code_workspace(result)
    assert not workspace_path.exists()


def test_execute_development_code_workspace_returns_error_for_empty_workspace() -> None:
    result = execute_development_code_workspace(
        project_key="empty-project",
        github_repo=None,
        code_workspace={"files": []},
    )

    assert result["ready"] is False
    assert "no files" in result["errors"][0].lower()
    assert result["build"]["status"] == "skipped"


def test_execute_development_code_workspace_runs_pytest_when_pyproject_present() -> None:
    code_workspace = {
        "install_command": "true",
        "build_command": "true",
        "files": [
            {
                "path": "pyproject.toml",
                "content": '\n'.join(
                    [
                        '[project]',
                        'name = "demo-workspace"',
                        'version = "0.1.0"',
                        '',
                        '[tool.pytest.ini_options]',
                        'addopts = "-q"',
                    ]
                ),
            },
            {
                "path": "tests/test_smoke.py",
                "content": "def test_smoke() -> None:\n    assert 2 + 2 == 4\n",
            },
        ],
    }

    result = execute_development_code_workspace(
        project_key="python-project",
        github_repo=None,
        code_workspace=code_workspace,
    )

    workspace_path = Path(result["workspace_path"])
    assert result["ready"] is True
    assert result["test"]["status"] == "passed"
    assert any(item["runtime"] == "python" for item in result["test_plan"])
    assert "pytest" in result["test"]["command"]

    cleanup_development_code_workspace(result)
    assert not workspace_path.exists()


def test_execute_development_code_workspace_fails_when_tests_exist_without_runnable_plan() -> None:
    code_workspace = {
        "install_command": "true",
        "build_command": "true",
        "files": [
            {
                "path": "tests/acceptance/requirements.spec.ts",
                "content": 'import { describe, expect, it } from "vitest";\n\ndescribe("req", () => { it("works", () => { expect(true).toBe(true); }); });\n',
            }
        ],
    }

    result = execute_development_code_workspace(
        project_key="broken-tests-project",
        github_repo=None,
        code_workspace=code_workspace,
    )

    workspace_path = Path(result["workspace_path"])
    assert result["ready"] is False
    assert result["test"]["status"] == "failed"
    assert any("no runnable vitest/pytest plan" in error.lower() for error in result["errors"])

    cleanup_development_code_workspace(result)
    assert not workspace_path.exists()


def test_execute_development_code_workspace_repairs_missing_rollup_optional_dependency() -> None:
    code_workspace = {
        "files": [
            {
                "path": "package.json",
                "content": json.dumps(
                    {
                        "name": "demo-workspace",
                        "private": True,
                        "scripts": {"test": "vitest run"},
                    }
                ),
            },
            {
                "path": "tests/acceptance/control-plane.spec.ts",
                "content": 'import { describe, expect, it } from "vitest";\n\ndescribe("control-plane", () => { it("works", () => { expect(true).toBe(true); }); });\n',
            },
        ],
    }

    shell_results = iter(
        [
            {"status": "passed", "command": "npm install --include=optional", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            {"status": "passed", "command": "npm run build", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            {
                "status": "failed",
                "command": "npm test",
                "exit_code": 1,
                "duration_ms": 10,
                "stdout_tail": "",
                "stderr_tail": "Error: Cannot find module '@rollup/rollup-darwin-arm64'",
            },
            {"status": "passed", "command": "npm install --include=optional", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            {
                "status": "failed",
                "command": "npm test",
                "exit_code": 1,
                "duration_ms": 10,
                "stdout_tail": "",
                "stderr_tail": "Error: Cannot find module '@rollup/rollup-darwin-arm64'",
            },
            {"status": "passed", "command": "npm install --no-save @rollup/rollup-darwin-arm64", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
            {"status": "passed", "command": "npm test", "exit_code": 0, "duration_ms": 10, "stdout_tail": "", "stderr_tail": ""},
        ]
    )

    with patch(
        "pylon.lifecycle.services.development_repo_execution._run_shell_command",
        side_effect=lambda command, *, cwd, timeout_seconds: next(shell_results),
    ):
        result = execute_development_code_workspace(
            project_key="repair-project",
            github_repo=None,
            code_workspace=code_workspace,
        )

    workspace_path = Path(result["workspace_path"])
    assert result["ready"] is True
    assert result["install"]["command"] == "npm install --include=optional"
    assert result["test"]["status"] == "passed"
    assert result["test"]["repair_attempts"][0]["reason"] == "optional_native_dependency_repair"
    assert result["test"]["repair_attempts"][1]["reason"] == "missing_node_module_repair"

    cleanup_development_code_workspace(result)
    assert not workspace_path.exists()
