"""Hybrid sandbox execution for experiment campaigns.

Uses local policy-enforced execution for host/docker tiers and routes
Firecracker/gVisor tiers through self-hosted sandbox backends.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import resource
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pylon.errors import SandboxError
from pylon.sandbox.firecracker_backend import (
    SandboxBackend,
    SandboxBackendType,
    SandboxSession,
)
from pylon.sandbox.firecracker_backend import (
    SandboxManager as RemoteSandboxManager,
)
from pylon.sandbox.manager import SandboxConfig, SandboxManager, SandboxStatus
from pylon.sandbox.policy import NetworkPolicy, ResourceLimits, ResourceUsage, SandboxPolicy
from pylon.types import SandboxTier

DEFAULT_SANDBOX_TIMEOUT_SECONDS = 300
DEFAULT_REMOTE_WORKSPACE_ROOT = "/workspace"
_NETWORK_COMMAND_PREFIXES = (
    "curl",
    "wget",
    "pip ",
    "pip3 ",
    "npm ",
    "pnpm ",
    "yarn ",
    "brew ",
    "apt ",
    "apt-get ",
    "ssh ",
    "scp ",
    "rsync ",
    "nc ",
    "telnet ",
)


@dataclass(frozen=True)
class ExperimentSandboxConfig:
    """Sandbox settings persisted on experiment campaigns."""

    tier: SandboxTier
    allow_internet: bool
    allowed_hosts: list[str]
    blocked_ports: list[int]
    timeout_seconds: int
    max_cpu_ms: int
    max_memory_bytes: int
    max_network_bytes: int
    provider: str = "auto"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ExperimentSandboxConfig:
        source = payload or {}
        raw_tier = str(source.get("tier", "docker")).strip().lower() or "docker"
        try:
            tier = SandboxTier(raw_tier)
        except ValueError as exc:
            raise ValueError(f"Unsupported sandbox tier: {raw_tier}") from exc

        default_policy = SandboxPolicy.for_tier(tier)
        default_limits = default_policy.resource_limits
        default_network = default_policy.network_policy
        allow_internet = bool(source.get("allow_internet", default_network.allow_internet))
        allowed_hosts = [
            str(host).strip()
            for host in source.get("allowed_hosts", default_network.allowed_hosts)
            if str(host).strip()
        ]
        blocked_ports = [
            int(port)
            for port in source.get("blocked_ports", default_network.blocked_ports)
            if isinstance(port, int)
        ]
        timeout_seconds = _positive_int(
            source.get(
                "timeout_seconds",
                default_limits.max_execution_time or DEFAULT_SANDBOX_TIMEOUT_SECONDS,
            ),
            field_name="sandbox.timeout_seconds",
            default=DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        )
        max_cpu_ms = _positive_int(
            source.get("max_cpu_ms", default_limits.max_cpu_ms),
            field_name="sandbox.max_cpu_ms",
            default=default_limits.max_cpu_ms,
        )
        max_memory_bytes = _positive_int(
            source.get("max_memory_bytes", default_limits.max_memory_bytes),
            field_name="sandbox.max_memory_bytes",
            default=default_limits.max_memory_bytes,
        )
        max_network_bytes = _positive_int(
            source.get("max_network_bytes", default_limits.max_network_bytes),
            field_name="sandbox.max_network_bytes",
            default=default_limits.max_network_bytes,
            allow_zero=True,
        )
        provider = _normalize_sandbox_provider(source.get("provider", "auto"))
        return cls(
            tier=tier,
            allow_internet=allow_internet,
            allowed_hosts=allowed_hosts,
            blocked_ports=blocked_ports,
            timeout_seconds=timeout_seconds,
            max_cpu_ms=max_cpu_ms,
            max_memory_bytes=max_memory_bytes,
            max_network_bytes=max_network_bytes,
            provider=provider,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "allow_internet": self.allow_internet,
            "allowed_hosts": list(self.allowed_hosts),
            "blocked_ports": list(self.blocked_ports),
            "timeout_seconds": self.timeout_seconds,
            "max_cpu_ms": self.max_cpu_ms,
            "max_memory_bytes": self.max_memory_bytes,
            "max_network_bytes": self.max_network_bytes,
            "provider": self.provider,
        }

    def policy(self) -> SandboxPolicy:
        return SandboxPolicy(
            resource_limits=ResourceLimits(
                max_cpu_ms=self.max_cpu_ms,
                max_memory_bytes=self.max_memory_bytes,
                max_network_bytes=self.max_network_bytes,
                max_execution_time=self.timeout_seconds,
            ),
            network_policy=NetworkPolicy(
                allowed_hosts=list(self.allowed_hosts),
                blocked_ports=list(self.blocked_ports),
                allow_internet=self.allow_internet,
            ),
        )


@dataclass(frozen=True)
class SandboxExecutionResult:
    """Normalized result for one sandboxed command execution."""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool
    resource_usage: ResourceUsage
    sandbox: dict[str, Any]


class LocalPolicySandboxRunner:
    """Executes commands either locally or via remote sandbox backends."""

    def __init__(
        self,
        manager: SandboxManager | None = None,
        *,
        remote_manager: RemoteSandboxManager | Any | None = None,
        firecracker_runner: str | None = None,
        firecracker_workspace_root: str | None = None,
        docker_image: str | None = None,
    ) -> None:
        self._manager = manager or SandboxManager()
        self._remote_manager = remote_manager or RemoteSandboxManager(
            firecracker_runner=firecracker_runner,
            firecracker_workspace_root=firecracker_workspace_root,
            docker_image=(
                docker_image
                or os.getenv("PYLON_SANDBOX_DOCKER_IMAGE", "python:3.12-slim")
            ),
        )

    def execute(
        self,
        *,
        sandbox_config: ExperimentSandboxConfig,
        command: str,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str],
        agent_id: str,
        sync_back: bool = False,
    ) -> SandboxExecutionResult:
        policy = sandbox_config.policy()
        allowed, reason = policy.validate_execution(command)
        if not allowed:
            raise SandboxError(
                f"Command blocked by sandbox policy: {reason}",
                details={"command": command, "reason": reason},
            )
        if not sandbox_config.allow_internet and _looks_like_network_command(command):
            raise SandboxError(
                "Network egress is blocked by sandbox policy",
                details={"command": command, "tier": sandbox_config.tier.value},
            )
        backend_type = _resolve_backend_type(sandbox_config)
        if backend_type is None:
            return self._execute_local(
                sandbox_config=sandbox_config,
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                env=env,
                agent_id=agent_id,
                policy=policy,
            )
        return self._execute_remote(
            sandbox_config=sandbox_config,
            backend_type=backend_type,
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
            sync_back=sync_back,
        )

    def _execute_local(
        self,
        *,
        sandbox_config: ExperimentSandboxConfig,
        command: str,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str],
        agent_id: str,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        sandbox = self._manager.create(
            SandboxConfig(
                tier=sandbox_config.tier,
                timeout=sandbox_config.timeout_seconds,
                agent_id=agent_id,
                resource_limits=policy.resource_limits,
                network_policy=policy.network_policy,
            )
        )
        effective_timeout = min(
            max(timeout_seconds, 1),
            policy.resource_limits.max_execution_time,
        )
        started = time.monotonic()
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                shell=True,
                executable="/bin/sh",
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env={**os.environ, **env},
                check=False,
            )
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage = _resource_delta(usage_before, usage_after)
            within_limits, limit_reason = policy.check_resources(usage)
            if not within_limits:
                raise SandboxError(
                    f"Sandbox resource limit exceeded: {limit_reason}",
                    details={"command": command, "sandbox_id": sandbox.id},
                )
            return SandboxExecutionResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=False,
                resource_usage=usage,
                sandbox=_sandbox_metadata(
                    sandbox, provider=_effective_local_provider(sandbox_config)
                ),
            )
        except subprocess.TimeoutExpired as exc:
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage = _resource_delta(usage_before, usage_after)
            return SandboxExecutionResult(
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                exit_code=124,
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
                resource_usage=usage,
                sandbox=_sandbox_metadata(
                    sandbox, provider=_effective_local_provider(sandbox_config)
                ),
            )
        finally:
            if sandbox.status == SandboxStatus.RUNNING:
                self._manager.stop(sandbox.id)
            self._manager.destroy(sandbox.id)

    def _execute_remote(
        self,
        *,
        sandbox_config: ExperimentSandboxConfig,
        backend_type: SandboxBackendType,
        command: str,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str],
        sync_back: bool,
    ) -> SandboxExecutionResult:
        backend = self._remote_manager.get_backend(backend_type)
        effective_timeout = min(
            max(timeout_seconds, 1),
            sandbox_config.timeout_seconds,
        )
        runtime_env = {
            **env,
            **_runner_control_env(sandbox_config),
        }
        local_snapshot = _collect_workspace_snapshot(cwd) if sync_back else None
        session = self._run_async(
            backend.create(
                template=_resolve_remote_template(),
                timeout=sandbox_config.timeout_seconds,
                env_vars=runtime_env,
            )
        )
        try:
            self._run_async(self._sync_workspace_to_remote(backend, session, cwd))
            result = self._run_async(
                backend.execute_command(
                    session,
                    command,
                    cwd=DEFAULT_REMOTE_WORKSPACE_ROOT,
                    timeout=effective_timeout,
                    env_vars=runtime_env,
                )
            )
            if result.error:
                raise SandboxError(
                    f"Remote sandbox execution failed: {result.error}",
                    details={"backend": backend_type.value, "command": command},
                )
            if sync_back and result.exit_code == 0 and not result.timed_out:
                self._run_async(
                    self._sync_workspace_from_remote(
                        backend,
                        session,
                        cwd,
                        local_snapshot or {},
                    )
                )
            return SandboxExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                duration_ms=int(result.duration_ms),
                timed_out=result.timed_out,
                resource_usage=ResourceUsage(
                    cpu_ms=min(int(result.duration_ms), sandbox_config.max_cpu_ms),
                    memory_bytes=0,
                    network_bytes_in=0,
                    network_bytes_out=0,
                ),
                sandbox=_remote_sandbox_metadata(
                    session,
                    sandbox_config=sandbox_config,
                    backend_type=backend_type,
                ),
            )
        except RuntimeError as exc:
            raise SandboxError(
                str(exc),
                details={"backend": backend_type.value, "command": command},
            ) from exc
        finally:
            self._run_async(backend.destroy(session))

    def _run_async(self, coro: Any) -> Any:
        return asyncio.run(coro)

    async def _sync_workspace_to_remote(
        self,
        backend: SandboxBackend,
        session: SandboxSession,
        cwd: Path,
    ) -> None:
        for local_path in _iter_workspace_files(cwd):
            relative_path = local_path.relative_to(cwd).as_posix()
            await backend.write_file(
                session,
                f"{DEFAULT_REMOTE_WORKSPACE_ROOT}/{relative_path}",
                local_path.read_bytes(),
            )
            if os.access(local_path, os.X_OK):
                chmod_result = await backend.execute_command(
                    session,
                    "chmod +x "
                    + json.dumps(
                        str(
                            PurePosixPath(DEFAULT_REMOTE_WORKSPACE_ROOT)
                            / relative_path
                        )
                    ),
                    cwd=DEFAULT_REMOTE_WORKSPACE_ROOT,
                    timeout=10,
                )
                if chmod_result.error or chmod_result.exit_code != 0:
                    raise RuntimeError(
                        chmod_result.error
                        or chmod_result.stderr
                        or "chmod failed"
                    )

    async def _sync_workspace_from_remote(
        self,
        backend: SandboxBackend,
        session: SandboxSession,
        cwd: Path,
        local_snapshot: dict[str, dict[str, Any]],
    ) -> None:
        remote_snapshot = await _remote_workspace_snapshot(backend, session)
        for relative_path, metadata in remote_snapshot.items():
            local_metadata = local_snapshot.get(relative_path)
            if local_metadata == metadata:
                continue
            content = await _read_remote_file_bytes(backend, session, relative_path)
            target = cwd / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if metadata.get("executable"):
                target.chmod(target.stat().st_mode | 0o111)
            else:
                target.chmod(target.stat().st_mode & ~0o111)
        for relative_path in local_snapshot:
            if relative_path in remote_snapshot:
                continue
            target = cwd / relative_path
            if target.exists():
                target.unlink()
        _prune_empty_directories(cwd)


def _resolve_backend_type(
    sandbox_config: ExperimentSandboxConfig,
) -> SandboxBackendType | None:
    provider = sandbox_config.provider.lower()
    if provider == "docker":
        return SandboxBackendType.DOCKER
    if provider == "firecracker":
        return SandboxBackendType.FIRECRACKER
    if sandbox_config.tier in {SandboxTier.FIRECRACKER, SandboxTier.GVISOR}:
        return SandboxBackendType.FIRECRACKER
    return None


def _effective_local_provider(sandbox_config: ExperimentSandboxConfig) -> str:
    provider = sandbox_config.provider.strip().lower()
    if provider in {"", "auto"}:
        return "local-policy"
    return provider


def _normalize_sandbox_provider(raw_provider: Any) -> str:
    provider = str(raw_provider or "auto").strip().lower() or "auto"
    if provider == "e2b":
        return "firecracker"
    return provider


def _resolve_remote_template() -> str:
    return (
        os.getenv("PYLON_FIRECRACKER_TEMPLATE")
        or os.getenv("PYLON_E2B_TEMPLATE")
        or "python"
    )


def _runner_control_env(
    sandbox_config: ExperimentSandboxConfig,
) -> dict[str, str]:
    return {
        "PYLON_RUNNER_ALLOW_INTERNET": "1" if sandbox_config.allow_internet else "0",
        "PYLON_RUNNER_ALLOWED_HOSTS": ",".join(sandbox_config.allowed_hosts),
        "PYLON_RUNNER_BLOCKED_PORTS": ",".join(
            str(port) for port in sandbox_config.blocked_ports
        ),
        "PYLON_RUNNER_TIMEOUT_SECONDS": str(sandbox_config.timeout_seconds),
        "PYLON_RUNNER_MAX_CPU_MS": str(sandbox_config.max_cpu_ms),
        "PYLON_RUNNER_MAX_MEMORY_BYTES": str(sandbox_config.max_memory_bytes),
        "PYLON_RUNNER_MAX_NETWORK_BYTES": str(sandbox_config.max_network_bytes),
    }


def _looks_like_network_command(command: str) -> bool:
    normalized = " ".join(command.strip().split()).lower()
    if any(prefix in normalized for prefix in ("http://", "https://", "ssh://", "git@")):
        return True
    return any(normalized.startswith(prefix) for prefix in _NETWORK_COMMAND_PREFIXES)


def _resource_delta(
    before: resource.struct_rusage,
    after: resource.struct_rusage,
) -> ResourceUsage:
    cpu_ms = int(
        max(
            (
                (after.ru_utime + after.ru_stime)
                - (before.ru_utime + before.ru_stime)
            )
            * 1000,
            0,
        )
    )
    memory_delta = int(max(after.ru_maxrss - before.ru_maxrss, 0))
    if memory_delta and memory_delta < 1024 * 1024:
        memory_bytes = memory_delta * 1024
    else:
        memory_bytes = memory_delta
    return ResourceUsage(
        cpu_ms=cpu_ms,
        memory_bytes=memory_bytes,
        network_bytes_in=0,
        network_bytes_out=0,
    )


def _sandbox_metadata(sandbox: Any, *, provider: str) -> dict[str, Any]:
    return {
        "id": str(sandbox.id),
        "tier": str(sandbox.tier.value),
        "provider": provider,
        "status": str(sandbox.status.value),
        "timeout_seconds": int(sandbox.config.timeout),
        "resource_limits": {
            "max_cpu_ms": int(sandbox.policy.resource_limits.max_cpu_ms),
            "max_memory_bytes": int(sandbox.policy.resource_limits.max_memory_bytes),
            "max_network_bytes": int(sandbox.policy.resource_limits.max_network_bytes),
            "max_execution_time": int(sandbox.policy.resource_limits.max_execution_time),
        },
        "network_policy": {
            "allow_internet": bool(sandbox.policy.network_policy.allow_internet),
            "allowed_hosts": list(sandbox.policy.network_policy.allowed_hosts),
            "blocked_ports": list(sandbox.policy.network_policy.blocked_ports),
        },
    }


def _remote_sandbox_metadata(
    session: SandboxSession,
    *,
    sandbox_config: ExperimentSandboxConfig,
    backend_type: SandboxBackendType,
) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "tier": sandbox_config.tier.value,
        "provider": backend_type.value,
        "status": "destroyed" if not session.is_active else "running",
        "timeout_seconds": session.timeout,
        "resource_limits": {
            "max_cpu_ms": sandbox_config.max_cpu_ms,
            "max_memory_bytes": sandbox_config.max_memory_bytes,
            "max_network_bytes": sandbox_config.max_network_bytes,
            "max_execution_time": sandbox_config.timeout_seconds,
        },
        "network_policy": {
            "allow_internet": sandbox_config.allow_internet,
            "allowed_hosts": list(sandbox_config.allowed_hosts),
            "blocked_ports": list(sandbox_config.blocked_ports),
        },
    }


def _iter_workspace_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip_workspace_path(path.relative_to(root)):
            continue
        files.append(path)
    files.sort()
    return files


def _collect_workspace_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for path in _iter_workspace_files(root):
        relative_path = path.relative_to(root).as_posix()
        snapshot[relative_path] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "executable": os.access(path, os.X_OK),
        }
    return snapshot


def _should_skip_workspace_path(relative_path: Path) -> bool:
    return any(part == ".git" for part in relative_path.parts)


async def _remote_workspace_snapshot(
    backend: SandboxBackend,
    session: SandboxSession,
) -> dict[str, dict[str, Any]]:
    script = """
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path("/workspace")
manifest = {}
for path in root.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    if rel.startswith(".git/") or rel == ".git":
        continue
    manifest[rel] = {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "executable": bool(os.access(path, os.X_OK)),
    }
print(json.dumps(manifest, sort_keys=True))
PY
""".strip()
    result = await backend.execute_command(
        session,
        script,
        cwd=DEFAULT_REMOTE_WORKSPACE_ROOT,
        timeout=30,
    )
    if result.error or result.exit_code != 0:
        raise RuntimeError(result.error or result.stderr or "failed to build remote manifest")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("remote manifest was not valid JSON") from exc
    return {
        str(path): {
            "sha256": str(metadata.get("sha256", "")),
            "executable": bool(metadata.get("executable", False)),
        }
        for path, metadata in payload.items()
    }


async def _read_remote_file_bytes(
    backend: SandboxBackend,
    session: SandboxSession,
    relative_path: str,
) -> bytes:
    remote_path = str(PurePosixPath(DEFAULT_REMOTE_WORKSPACE_ROOT) / PurePosixPath(relative_path))
    script = f"""
python3 - <<'PY'
import base64
from pathlib import Path

data = Path({json.dumps(remote_path)}).read_bytes()
print(base64.b64encode(data).decode("ascii"))
PY
""".strip()
    result = await backend.execute_command(
        session,
        script,
        cwd=DEFAULT_REMOTE_WORKSPACE_ROOT,
        timeout=30,
    )
    if result.error or result.exit_code != 0:
        raise RuntimeError(
            result.error or result.stderr or f"failed to read remote file {relative_path}"
        )
    return base64.b64decode((result.stdout or "").strip().encode("ascii"))


def _prune_empty_directories(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_dir():
            continue
        if path == root:
            continue
        if _should_skip_workspace_path(path.relative_to(root)):
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def _positive_int(
    value: Any,
    *,
    field_name: str,
    default: int,
    allow_zero: bool = False,
) -> int:
    if value in (None, ""):
        return default
    if not isinstance(value, int):
        raise ValueError(f"Field '{field_name}' must be a positive integer")
    if allow_zero and value == 0:
        return value
    if value <= 0:
        raise ValueError(f"Field '{field_name}' must be a positive integer")
    return value
