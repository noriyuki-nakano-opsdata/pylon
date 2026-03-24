"""Sandbox lifecycle management (FR-06).

Creates, tracks, and destroys sandbox instances.
In-memory implementation — production backends (gVisor, Firecracker, Docker)
are injected via the SandboxBackend protocol.
"""

from __future__ import annotations

import asyncio
import enum
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from pylon.errors import SandboxError
from pylon.sandbox.firecracker_backend import (
    SandboxBackend,
    SandboxBackendType,
    SandboxSession,
)
from pylon.sandbox.firecracker_backend import SandboxManager as RuntimeSandboxManager
from pylon.sandbox.policy import NetworkPolicy, ResourceLimits, ResourceUsage, SandboxPolicy
from pylon.types import SandboxTier


class SandboxStatus(enum.Enum):
    """Sandbox lifecycle states."""

    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    DESTROYED = "destroyed"


@dataclass
class SandboxConfig:
    """Configuration for creating a sandbox."""

    tier: SandboxTier = SandboxTier.GVISOR
    resource_limits: ResourceLimits | None = None
    network_policy: NetworkPolicy | None = None
    timeout: int = 300  # seconds
    agent_id: str = ""
    template: str = "python"
    env_vars: dict[str, str] = field(default_factory=dict)
    provider: str = "auto"


@dataclass
class Sandbox:
    """A sandbox instance."""

    id: str
    tier: SandboxTier
    status: SandboxStatus
    created_at: float
    config: SandboxConfig
    policy: SandboxPolicy
    resource_usage: ResourceUsage = field(default_factory=ResourceUsage)
    agent_id: str = ""
    runtime_backend: str | None = None
    runtime_session_id: str | None = None
    runtime_metadata: dict[str, Any] = field(default_factory=dict)


class SandboxManager:
    """Manages sandbox lifecycle: create, get, list, destroy."""

    def __init__(self) -> None:
        self._sandboxes: dict[str, Sandbox] = {}

    def create(self, config: SandboxConfig) -> Sandbox:
        """Create and start a new sandbox.

        Returns the sandbox in RUNNING status.
        Raises SandboxError if tier is NONE and no SuperAdmin context.
        """
        policy = _policy_for_config(config)

        sandbox_id = uuid.uuid4().hex[:12]
        sandbox = Sandbox(
            id=sandbox_id,
            tier=config.tier,
            status=SandboxStatus.RUNNING,
            created_at=time.monotonic(),
            config=config,
            policy=policy,
            agent_id=config.agent_id,
        )
        self._sandboxes[sandbox_id] = sandbox
        return sandbox

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID. Returns None if not found."""
        return self._sandboxes.get(sandbox_id)

    def list(self, status: SandboxStatus | None = None) -> list[Sandbox]:
        """List sandboxes, optionally filtered by status."""
        if status is None:
            return list(self._sandboxes.values())
        return [s for s in self._sandboxes.values() if s.status == status]

    def stop(self, sandbox_id: str) -> Sandbox:
        """Stop a running sandbox.

        Raises SandboxError if sandbox not found or not running.
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise SandboxError(f"Sandbox not found: {sandbox_id}")
        if sandbox.status != SandboxStatus.RUNNING:
            raise SandboxError(
                f"Cannot stop sandbox in state {sandbox.status.value}",
                details={"sandbox_id": sandbox_id, "status": sandbox.status.value},
            )
        sandbox.status = SandboxStatus.STOPPED
        return sandbox

    def destroy(self, sandbox_id: str) -> bool:
        """Destroy a sandbox. Returns True if destroyed, False if not found."""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return False
        sandbox.status = SandboxStatus.DESTROYED
        del self._sandboxes[sandbox_id]
        return True


class ProductionSandboxManager:
    """Lifecycle manager backed by self-hosted runtime backends and durable state."""

    def __init__(
        self,
        *,
        state_path: str | Path | None = None,
        runtime_router: RuntimeSandboxManager | Any | None = None,
        firecracker_runner: str | None = None,
        firecracker_workspace_root: str | None = None,
        docker_image: str = "python:3.12-slim",
    ) -> None:
        self._sandboxes: dict[str, Sandbox] = {}
        self._runtime_sessions: dict[str, tuple[SandboxBackend, SandboxSession]] = {}
        self._state_path = (
            Path(state_path).expanduser().resolve()
            if state_path is not None
            else None
        )
        self._runtime_router = runtime_router or RuntimeSandboxManager(
            firecracker_runner=firecracker_runner,
            firecracker_workspace_root=firecracker_workspace_root,
            docker_image=docker_image,
        )
        self._load_state()

    def create(self, config: SandboxConfig) -> Sandbox:
        policy = _policy_for_config(config)
        backend_type = _runtime_backend_for(config)
        backend = self._runtime_router.get_backend(backend_type)
        session = self._run_async(
            backend.create(
                template=config.template,
                timeout=config.timeout,
                env_vars={
                    **dict(config.env_vars),
                    **_runner_control_env(policy),
                },
            )
        )
        sandbox = Sandbox(
            id=session.id,
            tier=config.tier,
            status=SandboxStatus.RUNNING,
            created_at=time.time(),
            config=config,
            policy=policy,
            agent_id=config.agent_id,
            runtime_backend=backend_type.value,
            runtime_session_id=session.id,
            runtime_metadata=dict(session.metadata),
        )
        self._sandboxes[sandbox.id] = sandbox
        self._runtime_sessions[sandbox.id] = (backend, session)
        self._persist_state()
        return sandbox

    def get(self, sandbox_id: str) -> Sandbox | None:
        return self._sandboxes.get(sandbox_id)

    def list(self, status: SandboxStatus | None = None) -> list[Sandbox]:
        if status is None:
            return list(self._sandboxes.values())
        return [sandbox for sandbox in self._sandboxes.values() if sandbox.status == status]

    def stop(self, sandbox_id: str) -> Sandbox:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise SandboxError(f"Sandbox not found: {sandbox_id}")
        if sandbox.status != SandboxStatus.RUNNING:
            raise SandboxError(
                f"Cannot stop sandbox in state {sandbox.status.value}",
                details={"sandbox_id": sandbox_id, "status": sandbox.status.value},
            )
        runtime = self._runtime_sessions.pop(sandbox.id, None)
        if runtime is not None:
            backend, session = runtime
            self._run_async(backend.destroy(session))
        sandbox.status = SandboxStatus.STOPPED
        self._persist_state()
        return sandbox

    def destroy(self, sandbox_id: str) -> bool:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return False
        runtime = self._runtime_sessions.pop(sandbox.id, None)
        if runtime is not None:
            backend, session = runtime
            self._run_async(backend.destroy(session))
        else:
            workspace_dir = str(sandbox.runtime_metadata.get("workspace_dir", "")).strip()
            if workspace_dir:
                shutil.rmtree(workspace_dir, ignore_errors=True)
        sandbox.status = SandboxStatus.DESTROYED
        del self._sandboxes[sandbox_id]
        self._persist_state()
        return True

    def reap_expired(self) -> list[str]:
        expired_ids: list[str] = []
        now = time.time()
        for sandbox in list(self._sandboxes.values()):
            if sandbox.status != SandboxStatus.RUNNING:
                continue
            if (now - sandbox.created_at) < max(sandbox.config.timeout, 1):
                continue
            if self.destroy(sandbox.id):
                expired_ids.append(sandbox.id)
        return expired_ids

    def resolve_backend_session(
        self,
        sandbox_id: str,
    ) -> tuple[SandboxBackend, SandboxSession] | None:
        return self._runtime_sessions.get(sandbox_id)

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        payload = {
            "sandboxes": [
                _serialize_sandbox(sandbox)
                for sandbox in self._sandboxes.values()
            ]
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._state_path)

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        raw = json.loads(self._state_path.read_text(encoding="utf-8") or "{}")
        for item in raw.get("sandboxes", []):
            sandbox = _deserialize_sandbox(item)
            if sandbox.status == SandboxStatus.RUNNING:
                sandbox.status = SandboxStatus.STOPPED
                sandbox.runtime_metadata = {
                    **dict(sandbox.runtime_metadata),
                    "recovered_after_restart": True,
                }
            self._sandboxes[sandbox.id] = sandbox

    @staticmethod
    def _run_async(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None or not loop.is_running():
            return asyncio.run(coro)
        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - defensive boundary
                error["value"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if "value" in error:
            raise error["value"]
        return result.get("value")


def _policy_for_config(config: SandboxConfig) -> SandboxPolicy:
    if config.resource_limits or config.network_policy:
        return SandboxPolicy(
            resource_limits=config.resource_limits,
            network_policy=config.network_policy,
        )
    return SandboxPolicy.for_tier(config.tier)


def _runtime_backend_for(config: SandboxConfig) -> SandboxBackendType:
    provider = config.provider.strip().lower() or "auto"
    if provider == "firecracker":
        return SandboxBackendType.FIRECRACKER
    if provider == "docker":
        return SandboxBackendType.DOCKER
    if provider in {"local", "none", "process"}:
        return SandboxBackendType.LOCAL
    if config.tier is SandboxTier.FIRECRACKER:
        return SandboxBackendType.FIRECRACKER
    if config.tier is SandboxTier.NONE:
        return SandboxBackendType.LOCAL
    return SandboxBackendType.DOCKER


def _runner_control_env(policy: SandboxPolicy) -> dict[str, str]:
    limits = policy.resource_limits
    network = policy.network_policy
    return {
        "PYLON_RUNNER_ALLOW_INTERNET": "1" if network.allow_internet else "0",
        "PYLON_RUNNER_ALLOWED_HOSTS": ",".join(network.allowed_hosts),
        "PYLON_RUNNER_BLOCKED_PORTS": ",".join(str(port) for port in network.blocked_ports),
        "PYLON_RUNNER_TIMEOUT_SECONDS": str(limits.max_execution_time),
        "PYLON_RUNNER_MAX_CPU_MS": str(limits.max_cpu_ms),
        "PYLON_RUNNER_MAX_MEMORY_BYTES": str(limits.max_memory_bytes),
        "PYLON_RUNNER_MAX_NETWORK_BYTES": str(limits.max_network_bytes),
    }


def _serialize_sandbox(sandbox: Sandbox) -> dict[str, Any]:
    return {
        "id": sandbox.id,
        "tier": sandbox.tier.value,
        "status": sandbox.status.value,
        "created_at": sandbox.created_at,
        "agent_id": sandbox.agent_id,
        "config": {
            "timeout": sandbox.config.timeout,
            "template": sandbox.config.template,
            "provider": sandbox.config.provider,
            "env_vars": dict(sandbox.config.env_vars),
        },
        "runtime_backend": sandbox.runtime_backend,
        "runtime_session_id": sandbox.runtime_session_id,
        "runtime_metadata": dict(sandbox.runtime_metadata),
        "resource_usage": {
            "cpu_ms": sandbox.resource_usage.cpu_ms,
            "memory_bytes": sandbox.resource_usage.memory_bytes,
            "network_bytes_in": sandbox.resource_usage.network_bytes_in,
            "network_bytes_out": sandbox.resource_usage.network_bytes_out,
        },
        "policy": {
            "resource_limits": {
                "max_cpu_ms": sandbox.policy.resource_limits.max_cpu_ms,
                "max_memory_bytes": sandbox.policy.resource_limits.max_memory_bytes,
                "max_network_bytes": sandbox.policy.resource_limits.max_network_bytes,
                "max_execution_time": sandbox.policy.resource_limits.max_execution_time,
            },
            "network_policy": {
                "allowed_hosts": list(sandbox.policy.network_policy.allowed_hosts),
                "blocked_ports": list(sandbox.policy.network_policy.blocked_ports),
                "allow_internet": sandbox.policy.network_policy.allow_internet,
            },
        },
    }


def _deserialize_sandbox(payload: dict[str, Any]) -> Sandbox:
    resource_limits = ResourceLimits(**dict(payload.get("policy", {}).get("resource_limits", {})))
    network_policy = NetworkPolicy(**dict(payload.get("policy", {}).get("network_policy", {})))
    config_payload = dict(payload.get("config", {}))
    config = SandboxConfig(
        tier=SandboxTier(str(payload["tier"])),
        timeout=int(config_payload.get("timeout", 300) or 300),
        agent_id=str(payload.get("agent_id", "")),
        template=str(config_payload.get("template", "python")),
        env_vars={
            str(key): str(value)
            for key, value in dict(config_payload.get("env_vars") or {}).items()
        },
        provider=str(config_payload.get("provider", "auto")),
        resource_limits=resource_limits,
        network_policy=network_policy,
    )
    usage_payload = dict(payload.get("resource_usage", {}))
    return Sandbox(
        id=str(payload["id"]),
        tier=SandboxTier(str(payload["tier"])),
        status=SandboxStatus(str(payload["status"])),
        created_at=float(payload.get("created_at", time.time())),
        config=config,
        policy=SandboxPolicy(
            resource_limits=resource_limits,
            network_policy=network_policy,
        ),
        resource_usage=ResourceUsage(
            cpu_ms=int(usage_payload.get("cpu_ms", 0) or 0),
            memory_bytes=int(usage_payload.get("memory_bytes", 0) or 0),
            network_bytes_in=int(usage_payload.get("network_bytes_in", 0) or 0),
            network_bytes_out=int(usage_payload.get("network_bytes_out", 0) or 0),
        ),
        agent_id=str(payload.get("agent_id", "")),
        runtime_backend=(
            str(payload["runtime_backend"])
            if payload.get("runtime_backend") is not None
            else None
        ),
        runtime_session_id=(
            str(payload["runtime_session_id"])
            if payload.get("runtime_session_id") is not None
            else None
        ),
        runtime_metadata=dict(payload.get("runtime_metadata") or {}),
    )
