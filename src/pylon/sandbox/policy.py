"""Sandbox resource limits and network policies (FR-06).

Defines per-tier default policies and validates execution requests
against resource and network constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pylon.types import SandboxTier


@dataclass(frozen=True)
class ResourceLimits:
    """Resource constraints for a sandbox."""

    max_cpu_ms: int = 60_000          # 60s CPU time
    max_memory_bytes: int = 536_870_912  # 512 MiB
    max_network_bytes: int = 10_485_760  # 10 MiB
    max_execution_time: int = 300     # 5 minutes wall-clock


@dataclass(frozen=True)
class NetworkPolicy:
    """Network access policy for a sandbox."""

    allowed_hosts: list[str] = field(default_factory=list)
    blocked_ports: list[int] = field(default_factory=lambda: [22, 25, 445, 3389])
    allow_internet: bool = False


# Dangerous command prefixes/patterns checked before execution
_BLOCKED_COMMANDS: list[str] = [
    "rm -rf /",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",
    "chmod -R 777 /",
]


DEFAULT_POLICIES: dict[SandboxTier, tuple[ResourceLimits, NetworkPolicy]] = {
    SandboxTier.FIRECRACKER: (
        ResourceLimits(
            max_cpu_ms=120_000,
            max_memory_bytes=1_073_741_824,  # 1 GiB
            max_network_bytes=52_428_800,    # 50 MiB
            max_execution_time=600,
        ),
        NetworkPolicy(allow_internet=True, blocked_ports=[22, 25]),
    ),
    SandboxTier.GVISOR: (
        ResourceLimits(
            max_cpu_ms=60_000,
            max_memory_bytes=536_870_912,  # 512 MiB
            max_network_bytes=10_485_760,  # 10 MiB
            max_execution_time=300,
        ),
        NetworkPolicy(allow_internet=False),
    ),
    SandboxTier.DOCKER: (
        ResourceLimits(
            max_cpu_ms=30_000,
            max_memory_bytes=268_435_456,  # 256 MiB
            max_network_bytes=5_242_880,   # 5 MiB
            max_execution_time=120,
        ),
        NetworkPolicy(allow_internet=False),
    ),
    SandboxTier.NONE: (
        ResourceLimits(
            max_cpu_ms=10_000,
            max_memory_bytes=134_217_728,  # 128 MiB
            max_network_bytes=0,
            max_execution_time=60,
        ),
        NetworkPolicy(allow_internet=False, blocked_ports=[]),
    ),
}


class SandboxPolicy:
    """Validates sandbox operations against resource and network policies."""

    def __init__(
        self,
        resource_limits: ResourceLimits | None = None,
        network_policy: NetworkPolicy | None = None,
    ) -> None:
        self._resource_limits = resource_limits or ResourceLimits()
        self._network_policy = network_policy or NetworkPolicy()

    @classmethod
    def for_tier(cls, tier: SandboxTier) -> SandboxPolicy:
        """Create a policy with defaults for the given tier."""
        limits, network = DEFAULT_POLICIES[tier]
        return cls(resource_limits=limits, network_policy=network)

    @property
    def resource_limits(self) -> ResourceLimits:
        return self._resource_limits

    @property
    def network_policy(self) -> NetworkPolicy:
        return self._network_policy

    def validate_execution(self, command: str) -> tuple[bool, str]:
        """Check if a command is allowed to execute.

        Returns (allowed, reason).
        """
        for blocked in _BLOCKED_COMMANDS:
            if blocked in command:
                return False, f"Blocked command pattern: {blocked}"
        return True, ""

    def check_resources(self, usage: ResourceUsage) -> tuple[bool, str]:
        """Check if resource usage is within limits.

        Returns (within_limits, reason).
        """
        if usage.cpu_ms > self._resource_limits.max_cpu_ms:
            return False, (
                f"CPU limit exceeded: {usage.cpu_ms}ms > "
                f"{self._resource_limits.max_cpu_ms}ms"
            )
        if usage.memory_bytes > self._resource_limits.max_memory_bytes:
            return False, (
                f"Memory limit exceeded: {usage.memory_bytes}B > "
                f"{self._resource_limits.max_memory_bytes}B"
            )
        total_network = usage.network_bytes_in + usage.network_bytes_out
        if total_network > self._resource_limits.max_network_bytes:
            return False, (
                f"Network limit exceeded: {total_network}B > "
                f"{self._resource_limits.max_network_bytes}B"
            )
        return True, ""

    def check_host(self, host: str) -> bool:
        """Check if a host is allowed by network policy."""
        if self._network_policy.allow_internet:
            return True
        return host in self._network_policy.allowed_hosts

    def check_port(self, port: int) -> bool:
        """Check if a port is allowed by network policy."""
        return port not in self._network_policy.blocked_ports


@dataclass
class ResourceUsage:
    """Tracked resource consumption of a sandbox execution."""

    cpu_ms: int = 0
    memory_bytes: int = 0
    network_bytes_in: int = 0
    network_bytes_out: int = 0
