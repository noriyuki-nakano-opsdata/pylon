"""Tests for experiment sandbox backend selection and workspace sync."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from pylon.errors import SandboxError
from pylon.experiments.sandboxing import ExperimentSandboxConfig, LocalPolicySandboxRunner
from pylon.sandbox.firecracker_backend import (
    ExecutionResult,
    SandboxBackendType,
    SandboxSession,
)


class _FakeRemoteBackend:
    def __init__(self) -> None:
        self._workspaces: dict[str, Path] = {}

    async def create(
        self,
        template: str = "python",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        session_id = f"fake_{uuid.uuid4().hex[:8]}"
        workspace = Path(tempfile.mkdtemp(prefix=f"{session_id}-"))
        self._workspaces[session_id] = workspace
        return SandboxSession(
            id=session_id,
            backend=SandboxBackendType.FIRECRACKER,
            template=template,
            timeout=timeout,
            metadata={"workspace_dir": str(workspace), "env_vars": dict(env_vars or {})},
        )

    async def execute_command(
        self,
        session: SandboxSession,
        command: str,
        *,
        cwd: str = "/workspace",
        timeout: int = 30,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        workspace = self._workspaces[session.id]
        translated_command = command.replace("/workspace", str(workspace))
        translated_cwd = (
            str(workspace) if cwd == "/workspace" else cwd.replace("/workspace", str(workspace))
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                translated_command,
                cwd=translated_cwd,
                shell=True,
                executable="/bin/sh",
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    **dict(session.metadata.get("env_vars", {})),
                    **dict(env_vars or {}),
                },
                timeout=timeout,
                check=False,
            )
            return ExecutionResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        workspace = self._workspaces[session.id]
        target = workspace / Path(path.replace("/workspace/", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    async def destroy(self, session: SandboxSession) -> None:
        workspace = self._workspaces.pop(session.id, None)
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        session._active = False


class _FakeRemoteManager:
    def __init__(self) -> None:
        self.backend = _FakeRemoteBackend()
        self.last_backend_type: SandboxBackendType | None = None

    def get_backend(self, backend_type: SandboxBackendType) -> _FakeRemoteBackend:
        self.last_backend_type = backend_type
        return self.backend


def test_firecracker_runner_syncs_planner_changes_back(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "score.txt").write_text("10\n", encoding="utf-8")
    manager = _FakeRemoteManager()
    runner = LocalPolicySandboxRunner(remote_manager=manager)

    result = runner.execute(
        sandbox_config=ExperimentSandboxConfig.from_payload({"tier": "firecracker"}),
        command="printf '9\\n' > score.txt",
        cwd=repo,
        timeout_seconds=30,
        env={},
        agent_id="test-agent",
        sync_back=True,
    )

    assert manager.last_backend_type == SandboxBackendType.FIRECRACKER
    assert result.exit_code == 0
    assert result.sandbox["provider"] == "firecracker"
    assert (repo / "score.txt").read_text(encoding="utf-8") == "9\n"


def test_firecracker_runner_can_skip_sync_back(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "score.txt").write_text("10\n", encoding="utf-8")
    manager = _FakeRemoteManager()
    runner = LocalPolicySandboxRunner(remote_manager=manager)

    result = runner.execute(
        sandbox_config=ExperimentSandboxConfig.from_payload({"tier": "firecracker"}),
        command="printf '7\\n' > score.txt",
        cwd=repo,
        timeout_seconds=30,
        env={},
        agent_id="test-agent",
        sync_back=False,
    )

    assert result.exit_code == 0
    assert (repo / "score.txt").read_text(encoding="utf-8") == "10\n"


def test_gvisor_runner_blocks_network_commands_by_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manager = _FakeRemoteManager()
    runner = LocalPolicySandboxRunner(remote_manager=manager)

    with pytest.raises(SandboxError, match="Network egress is blocked"):
        runner.execute(
            sandbox_config=ExperimentSandboxConfig.from_payload({"tier": "gvisor"}),
            command="curl https://example.com",
            cwd=repo,
            timeout_seconds=30,
            env={},
            agent_id="test-agent",
            sync_back=False,
        )


def test_legacy_e2b_provider_is_normalized_to_firecracker() -> None:
    config = ExperimentSandboxConfig.from_payload({"tier": "firecracker", "provider": "e2b"})

    assert config.provider == "firecracker"


def test_bundled_runner_executes_firecracker_flow_in_process_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "score.txt").write_text("10\n", encoding="utf-8")
    monkeypatch.setenv("PYLON_FIRECRACKER_RUNNER_MODE", "process")

    runner = LocalPolicySandboxRunner()
    result = runner.execute(
        sandbox_config=ExperimentSandboxConfig.from_payload({"tier": "firecracker"}),
        command="printf '5\\n' > score.txt",
        cwd=repo,
        timeout_seconds=30,
        env={},
        agent_id="test-agent",
        sync_back=True,
    )

    assert result.exit_code == 0
    assert result.sandbox["provider"] == "firecracker"
    assert (repo / "score.txt").read_text(encoding="utf-8") == "5\n"


def test_bundled_runner_delegate_chain_executes_via_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "score.txt").write_text("10\n", encoding="utf-8")
    source_root = Path(__file__).resolve().parents[2] / "src"
    delegate_command = shlex.join(
        [
            "env",
            f"PYTHONPATH={source_root}",
            sys.executable,
            "-m",
            "pylon.sandbox.firecracker_executor",
        ]
    )
    monkeypatch.setenv("PYLON_FIRECRACKER_RUNNER_MODE", "delegate")
    monkeypatch.setenv("PYLON_FIRECRACKER_DELEGATE_COMMAND", delegate_command)
    monkeypatch.setenv("PYLON_FIRECRACKER_EXECUTOR_MODE", "process")

    runner = LocalPolicySandboxRunner()
    result = runner.execute(
        sandbox_config=ExperimentSandboxConfig.from_payload({"tier": "firecracker"}),
        command="printf '3\\n' > score.txt",
        cwd=repo,
        timeout_seconds=30,
        env={},
        agent_id="test-agent",
        sync_back=True,
    )

    assert result.exit_code == 0
    assert result.sandbox["provider"] == "firecracker"
    assert (repo / "score.txt").read_text(encoding="utf-8") == "3\n"
