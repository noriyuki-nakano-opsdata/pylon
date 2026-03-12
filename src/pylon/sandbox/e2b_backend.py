"""E2B Firecracker microVM sandbox backend.

Connects Pylon's SandboxTier definitions to E2B's managed Firecracker
microVMs, providing sub-200ms cold start sandboxed code execution.

Also includes a Docker-based fallback for environments where E2B is
not available (OpenHands pattern).
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class SandboxBackendType(enum.Enum):
    E2B = "e2b"
    DOCKER = "docker"
    LOCAL = "local"  # No sandboxing (development only)


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
    """Abstract base for sandbox backends.

    Subclasses implement the actual sandbox lifecycle:
    create → execute → file operations → destroy
    """

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


class E2BSandboxBackend(SandboxBackend):
    """E2B Firecracker microVM backend.

    Requires the ``e2b`` package and a valid E2B API key.
    Provides sub-200ms cold start and full Linux environment isolation.

    Usage:
        backend = E2BSandboxBackend(api_key="e2b_...")
        session = await backend.create("python", timeout=300)
        result = await backend.execute(session, "print('hello')")
        await backend.destroy(session)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_template: str = "python",
    ) -> None:
        self._api_key = api_key
        self._default_template = default_template
        self._e2b = None
        self._sessions: dict[str, Any] = {}

    async def _ensure_e2b(self) -> Any:
        if self._e2b is None:
            try:
                import e2b  # type: ignore[import-untyped]
                self._e2b = e2b
            except ImportError:
                raise RuntimeError(
                    "e2b package not installed. Run: pip install e2b"
                )
        return self._e2b

    async def create(
        self,
        template: str = "",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        e2b = await self._ensure_e2b()
        template = template or self._default_template

        try:
            sandbox = await e2b.AsyncSandbox.create(
                template=template,
                api_key=self._api_key,
                timeout=timeout,
                env_vars=env_vars or {},
            )
            session = SandboxSession(
                id=sandbox.sandbox_id,
                backend=SandboxBackendType.E2B,
                template=template,
                timeout=timeout,
            )
            self._sessions[session.id] = sandbox
            return session
        except Exception as exc:
            raise RuntimeError(f"Failed to create E2B sandbox: {exc}") from exc

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        sandbox = self._sessions.get(session.id)
        if sandbox is None:
            return ExecutionResult(
                exit_code=1, error="Session not found or expired"
            )

        start = time.monotonic()
        try:
            if language == "python":
                result = await sandbox.run_code(code, timeout=timeout)
            else:
                result = await sandbox.process.start_and_wait(
                    f"echo '{code}' | {language}",
                    timeout=timeout,
                )
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                stdout=getattr(result, "stdout", "") or "",
                stderr=getattr(result, "stderr", "") or "",
                exit_code=getattr(result, "exit_code", 0) or 0,
                duration_ms=elapsed,
            )
        except TimeoutError:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str | bytes,
    ) -> None:
        sandbox = self._sessions.get(session.id)
        if sandbox is None:
            raise RuntimeError("Session not found")
        await sandbox.filesystem.write(path, content)

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
    ) -> str:
        sandbox = self._sessions.get(session.id)
        if sandbox is None:
            raise RuntimeError("Session not found")
        return str(await sandbox.filesystem.read(path))

    async def destroy(self, session: SandboxSession) -> None:
        sandbox = self._sessions.pop(session.id, None)
        if sandbox is not None:
            try:
                await sandbox.close()
            except Exception:
                pass
        session._active = False


class DockerSandboxBackend(SandboxBackend):
    """Docker-based sandbox fallback (OpenHands pattern).

    Uses Docker containers for code execution when E2B is not available.
    Slower cold start (~2s) but works without external services.
    """

    def __init__(self, *, image: str = "python:3.12-slim") -> None:
        self._image = image
        self._containers: dict[str, Any] = {}

    async def create(
        self,
        template: str = "",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        import uuid

        session_id = f"docker_{uuid.uuid4().hex[:8]}"
        return SandboxSession(
            id=session_id,
            backend=SandboxBackendType.DOCKER,
            template=template or self._image,
            timeout=timeout,
        )

    async def execute(
        self,
        session: SandboxSession,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
    ) -> ExecutionResult:
        import asyncio

        start = time.monotonic()
        cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--memory=512m",
            "--cpus=1",
            f"--timeout={timeout}",
            self._image,
            language, "-c", code,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                duration_ms=elapsed,
            )
        except TimeoutError:
            return ExecutionResult(
                exit_code=124,
                timed_out=True,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                exit_code=1,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def destroy(self, session: SandboxSession) -> None:
        session._active = False


class SandboxManager:
    """High-level sandbox manager that selects backend based on SandboxTier.

    Maps Pylon's SandboxTier enum values to appropriate backends:
    - GVISOR/FIRECRACKER → E2B backend
    - DOCKER → Docker backend
    - LOCAL → No sandboxing (development)
    """

    def __init__(
        self,
        *,
        e2b_api_key: str | None = None,
        docker_image: str = "python:3.12-slim",
    ) -> None:
        self._backends: dict[SandboxBackendType, SandboxBackend] = {}
        self._docker_image = docker_image
        self._e2b_api_key = e2b_api_key

    def get_backend(self, backend_type: SandboxBackendType) -> SandboxBackend:
        """Get or create a sandbox backend."""
        if backend_type not in self._backends:
            if backend_type == SandboxBackendType.E2B:
                self._backends[backend_type] = E2BSandboxBackend(
                    api_key=self._e2b_api_key
                )
            elif backend_type == SandboxBackendType.DOCKER:
                self._backends[backend_type] = DockerSandboxBackend(
                    image=self._docker_image
                )
            else:
                raise ValueError(f"No backend for {backend_type}")
        return self._backends[backend_type]
