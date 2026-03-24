"""Self-hosted Firecracker and Docker sandbox backends.

The Firecracker backend assumes a locally managed microVM runner on the host
or inside an AWS environment controlled by the operator. It does not call any
external SaaS APIs.
"""

from __future__ import annotations

import asyncio
import enum
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any


class SandboxBackendType(enum.Enum):
    FIRECRACKER = "firecracker"
    DOCKER = "docker"
    LOCAL = "local"


@dataclass
class ExecutionResult:
    """Result of code execution in a sandbox."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    timed_out: bool = False
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None


@dataclass
class SandboxSession:
    """Active sandbox session."""

    id: str
    backend: SandboxBackendType
    template: str = ""
    created_at: float = field(default_factory=time.time)
    timeout: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)
    _active: bool = True

    @property
    def is_active(self) -> bool:
        if not self._active:
            return False
        elapsed = time.time() - self.created_at
        return elapsed < self.timeout

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.timeout - (time.time() - self.created_at))


class SandboxBackend:
    """Abstract base for sandbox backends."""

    async def create(
        self,
        template: str = "python",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        raise NotImplementedError

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        raise NotImplementedError

    async def execute_command(
        self,
        session: SandboxSession,
        command: str,
        *,
        cwd: str = "/workspace",
        timeout: int = 30,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        raise NotImplementedError

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        raise NotImplementedError

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
    ) -> str:
        raise NotImplementedError

    async def destroy(self, session: SandboxSession) -> None:
        raise NotImplementedError


class FirecrackerSandboxBackend(SandboxBackend):
    """Self-hosted Firecracker microVM backend.

    The backend expects a local runner binary or script configured via
    ``runner_command``. The runner receives a JSON request on stdin and must
    return a JSON response on stdout.
    """

    def __init__(
        self,
        *,
        runner_command: str | None = None,
        workspace_root: str | None = None,
        default_template: str = "python",
    ) -> None:
        source_root = Path(__file__).resolve().parents[2]
        default_runner_command = shlex.join(
            [
                "env",
                f"PYTHONPATH={source_root}",
                sys.executable,
                "-m",
                "pylon.sandbox.firecracker_runner",
            ]
        )
        self._runner_command = (
            runner_command or os.getenv("PYLON_FIRECRACKER_RUNNER") or default_runner_command
        ).strip()
        self._workspace_root = Path(
            workspace_root or os.getenv("PYLON_FIRECRACKER_WORKSPACE_ROOT") or tempfile.gettempdir()
        )
        self._default_template = default_template
        self._sessions: dict[str, Path] = {}

    async def create(
        self,
        template: str = "",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        import uuid

        session_id = f"fc_{uuid.uuid4().hex[:8]}"
        workspace_dir = self._workspace_root / f"pylon-firecracker-{session_id}"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        self._sessions[session_id] = workspace_dir
        return SandboxSession(
            id=session_id,
            backend=SandboxBackendType.FIRECRACKER,
            template=template or self._default_template,
            timeout=timeout,
            metadata={
                "workspace_dir": str(workspace_dir),
                "env_vars": dict(env_vars or {}),
                "runner_command": self._runner_command,
            },
        )

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        if language == "python":
            command = f"python - <<'PY'\n{code}\nPY"
        else:
            command = f"cat <<'PYLON_CODE' | {language}\n{code}\nPYLON_CODE"
        return await self.execute_command(
            session,
            command,
            cwd="/workspace",
            timeout=timeout,
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
        workspace_dir = self._sessions.get(session.id)
        if workspace_dir is None:
            return ExecutionResult(exit_code=1, error="Session not found or expired")
        if not self._runner_command:
            return ExecutionResult(
                exit_code=1,
                error="PYLON_FIRECRACKER_RUNNER is not configured",
            )

        payload = {
            "action": "execute_command",
            "session_id": session.id,
            "workspace_dir": str(workspace_dir),
            "cwd": _translate_workspace_path(cwd, workspace_dir),
            "command": command,
            "timeout": timeout,
            "env_vars": {
                **dict(session.metadata.get("env_vars", {})),
                **dict(env_vars or {}),
            },
            "template": session.template,
        }
        started = time.monotonic()
        try:
            runner_args = shlex.split(self._runner_command)
            if not runner_args:
                return ExecutionResult(
                    exit_code=1,
                    error="PYLON_FIRECRACKER_RUNNER is not configured",
                    duration_ms=(time.monotonic() - started) * 1000,
                )
            completed = await asyncio.to_thread(
                subprocess.run,
                runner_args,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout + 5,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except FileNotFoundError:
            return ExecutionResult(
                exit_code=1,
                error=f"Firecracker runner not found: {self._runner_command}",
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                error=str(exc),
                duration_ms=(time.monotonic() - started) * 1000,
            )

        if completed.returncode != 0:
            return ExecutionResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_ms=(time.monotonic() - started) * 1000,
                error=completed.stderr.strip() or "Firecracker runner failed",
            )
        try:
            response = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return ExecutionResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=1,
                duration_ms=(time.monotonic() - started) * 1000,
                error="Firecracker runner returned invalid JSON",
            )
        return ExecutionResult(
            stdout=str(response.get("stdout", "")),
            stderr=str(response.get("stderr", "")),
            exit_code=int(response.get("exit_code", 0) or 0),
            duration_ms=float(response.get("duration_ms", (time.monotonic() - started) * 1000)),
            timed_out=bool(response.get("timed_out", False)),
            error=str(response.get("error")) if response.get("error") else None,
            artifacts=list(response.get("artifacts", [])),
        )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        workspace_dir = self._sessions.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        target = workspace_dir / _workspace_relative_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
    ) -> str:
        workspace_dir = self._sessions.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        return (workspace_dir / _workspace_relative_path(path)).read_text(encoding="utf-8")

    async def destroy(self, session: SandboxSession) -> None:
        workspace_dir = self._sessions.pop(session.id, None)
        if workspace_dir is not None:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        session._active = False


class DockerSandboxBackend(SandboxBackend):
    """Docker-based sandbox fallback."""

    def __init__(self, *, image: str = "python:3.12-slim") -> None:
        self._image = image
        self._workspaces: dict[str, Path] = {}

    async def create(
        self,
        template: str = "",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        import uuid

        session_id = f"docker_{uuid.uuid4().hex[:8]}"
        workspace_dir = Path(tempfile.mkdtemp(prefix=f"{session_id}-"))
        session = SandboxSession(
            id=session_id,
            backend=SandboxBackendType.DOCKER,
            template=template or self._image,
            timeout=timeout,
            metadata={
                "workspace_dir": str(workspace_dir),
                "env_vars": dict(env_vars or {}),
            },
        )
        self._workspaces[session_id] = workspace_dir
        return session

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        if language == "python":
            command = f"python - <<'PY'\n{code}\nPY"
        else:
            command = f"cat <<'PYLON_CODE' | {language}\n{code}\nPYLON_CODE"
        return await self.execute_command(
            session,
            command,
            cwd="/workspace",
            timeout=timeout,
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
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            return ExecutionResult(exit_code=1, error="Session not found or expired")

        container_cwd = _translate_workspace_path(cwd, workspace_dir)
        started = time.monotonic()
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--memory=512m",
            "--cpus=1",
            "-v",
            f"{workspace_dir}:/workspace",
            "-w",
            container_cwd,
        ]
        for key, value in {
            **dict(session.metadata.get("env_vars", {})),
            **dict(env_vars or {}),
        }.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.extend([self._image, "/bin/sh", "-lc", command])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except TimeoutError:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                error=str(exc),
                duration_ms=(time.monotonic() - started) * 1000,
            )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        target = workspace_dir / _workspace_relative_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
    ) -> str:
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        return (workspace_dir / _workspace_relative_path(path)).read_text(encoding="utf-8")

    async def destroy(self, session: SandboxSession) -> None:
        workspace_dir = self._workspaces.pop(session.id, None)
        if workspace_dir is not None:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        session._active = False


class LocalProcessSandboxBackend(SandboxBackend):
    """Explicit host-process backend for trusted internal tools."""

    def __init__(self) -> None:
        self._workspaces: dict[str, Path] = {}

    async def create(
        self,
        template: str = "",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        import uuid

        session_id = f"local_{uuid.uuid4().hex[:8]}"
        workspace_dir = Path(tempfile.mkdtemp(prefix=f"{session_id}-"))
        session = SandboxSession(
            id=session_id,
            backend=SandboxBackendType.LOCAL,
            template=template or "local",
            timeout=timeout,
            metadata={
                "workspace_dir": str(workspace_dir),
                "env_vars": dict(env_vars or {}),
            },
        )
        self._workspaces[session_id] = workspace_dir
        return session

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        if language == "python":
            command = f"python - <<'PY'\n{code}\nPY"
        else:
            command = f"cat <<'PYLON_CODE' | {language}\n{code}\nPYLON_CODE"
        return await self.execute_command(
            session,
            command,
            cwd="/workspace",
            timeout=timeout,
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
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            return ExecutionResult(exit_code=1, error="Session not found or expired")

        target_cwd = workspace_dir / _workspace_relative_path(cwd)
        target_cwd.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(target_cwd),
                env={
                    **os.environ,
                    **dict(session.metadata.get("env_vars", {})),
                    **dict(env_vars or {}),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable="/bin/sh",
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except TimeoutError:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                error=str(exc),
                duration_ms=(time.monotonic() - started) * 1000,
            )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        target = workspace_dir / _workspace_relative_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
    ) -> str:
        workspace_dir = self._workspaces.get(session.id)
        if workspace_dir is None:
            raise RuntimeError("Session not found")
        return (workspace_dir / _workspace_relative_path(path)).read_text(encoding="utf-8")

    async def destroy(self, session: SandboxSession) -> None:
        workspace_dir = self._workspaces.pop(session.id, None)
        if workspace_dir is not None:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        session._active = False


class SandboxManager:
    """Selects sandbox backend based on backend type."""

    def __init__(
        self,
        *,
        firecracker_runner: str | None = None,
        firecracker_workspace_root: str | None = None,
        docker_image: str = "python:3.12-slim",
    ) -> None:
        self._backends: dict[SandboxBackendType, SandboxBackend] = {}
        self._firecracker_runner = firecracker_runner
        self._firecracker_workspace_root = firecracker_workspace_root
        self._docker_image = docker_image

    def get_backend(self, backend_type: SandboxBackendType) -> SandboxBackend:
        if backend_type not in self._backends:
            if backend_type == SandboxBackendType.FIRECRACKER:
                self._backends[backend_type] = FirecrackerSandboxBackend(
                    runner_command=self._firecracker_runner,
                    workspace_root=self._firecracker_workspace_root,
                )
            elif backend_type == SandboxBackendType.DOCKER:
                self._backends[backend_type] = DockerSandboxBackend(image=self._docker_image)
            elif backend_type == SandboxBackendType.LOCAL:
                self._backends[backend_type] = LocalProcessSandboxBackend()
            else:
                raise ValueError(f"No backend for {backend_type}")
        return self._backends[backend_type]


def _translate_workspace_path(path: str, workspace_dir: Path) -> str:
    pure = PurePosixPath(path)
    if not pure.is_absolute():
        return str(pure)
    if str(pure).startswith("/workspace"):
        relative = _workspace_relative_path(str(pure))
        return str(Path("/workspace") / relative)
    return str(path)


def _workspace_relative_path(path: str) -> Path:
    pure = PurePosixPath(path)
    if pure.is_absolute():
        try:
            pure = pure.relative_to("/workspace")
        except ValueError:
            pure = PurePosixPath(*pure.parts[1:])
    return Path(*pure.parts)


def _shell_command(
    command: str,
    *,
    cwd: str,
    env_vars: dict[str, str] | None = None,
) -> str:
    env_prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in (env_vars or {}).items())
    env_segment = f"env {env_prefix} " if env_prefix else ""
    return f"cd {shlex.quote(cwd)} && {env_segment}/bin/sh -lc {shlex.quote(command)}"
