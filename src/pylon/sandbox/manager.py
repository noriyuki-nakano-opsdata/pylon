"""Sandbox lifecycle management (FR-06).

Creates, tracks, and destroys sandbox instances.
In-memory implementation — production backends (gVisor, Firecracker, Docker)
are injected via the SandboxBackend protocol.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field

from pylon.errors import SandboxError
from pylon.types import SandboxTier
from pylon.sandbox.policy import NetworkPolicy, ResourceLimits, ResourceUsage, SandboxPolicy


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


class SandboxManager:
    """Manages sandbox lifecycle: create, get, list, destroy."""

    def __init__(self) -> None:
        self._sandboxes: dict[str, Sandbox] = {}

    def create(self, config: SandboxConfig) -> Sandbox:
        """Create and start a new sandbox.

        Returns the sandbox in RUNNING status.
        Raises SandboxError if tier is NONE and no SuperAdmin context.
        """
        policy = SandboxPolicy(
            resource_limits=config.resource_limits,
            network_policy=config.network_policy,
        ) if config.resource_limits or config.network_policy else SandboxPolicy.for_tier(config.tier)

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
