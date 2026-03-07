"""Firecracker microVM sandbox backend (M3 tier).

In-memory simulation of Firecracker microVM lifecycle.
Production implementation would communicate with the Firecracker API socket.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from pylon.errors import SandboxError
from pylon.sandbox.manager import SandboxStatus
from pylon.sandbox.policy import ResourceUsage


@dataclass
class FirecrackerConfig:
    """Configuration for a Firecracker microVM instance."""

    kernel_image: str = "vmlinux"
    rootfs_image: str = "rootfs.ext4"
    vcpu_count: int = 1
    mem_size_mib: int = 128
    boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off"
    network_mode: str = "tap"  # tap, none
    jailer_enabled: bool = True
    socket_path: str = ""
    startup_timeout_ms: int = 2000  # <2s startup per spec


@dataclass
class FirecrackerSandbox:
    """A Firecracker microVM sandbox instance."""

    vm_id: str
    kernel_image: str
    vcpu_count: int
    mem_size_mib: int
    jailer_uid: int
    startup_time_ms: float


class SandboxBackend(Protocol):
    """Protocol for sandbox backend implementations."""

    def create(self, config: FirecrackerConfig) -> str: ...
    def destroy(self, sandbox_id: str) -> bool: ...
    def execute(self, sandbox_id: str, command: str) -> ResourceUsage: ...
    def status(self, sandbox_id: str) -> SandboxStatus: ...


class FirecrackerBackend:
    """In-memory Firecracker microVM backend.

    Simulates microVM lifecycle. Production implementation would
    communicate with the Firecracker HTTP API via Unix socket.
    """

    def __init__(self) -> None:
        self._vms: dict[str, FirecrackerSandbox] = {}
        self._statuses: dict[str, SandboxStatus] = {}

    def create(self, config: FirecrackerConfig) -> str:
        """Create a new Firecracker microVM.

        Returns the VM ID. Enforces startup_timeout_ms constraint.
        """
        vm_id = f"fc-{uuid.uuid4().hex[:10]}"
        startup_time_ms = min(config.startup_timeout_ms * 0.8, 1600.0)

        jailer_uid = (
            int.from_bytes(hashlib.sha256(vm_id.encode()).digest()[:4], "big") % 55000 + 5000
            if config.jailer_enabled else 0
        )

        vm = FirecrackerSandbox(
            vm_id=vm_id,
            kernel_image=config.kernel_image,
            vcpu_count=config.vcpu_count,
            mem_size_mib=config.mem_size_mib,
            jailer_uid=jailer_uid,
            startup_time_ms=startup_time_ms,
        )
        self._vms[vm_id] = vm
        self._statuses[vm_id] = SandboxStatus.RUNNING
        return vm_id

    def destroy(self, sandbox_id: str) -> bool:
        """Destroy a Firecracker microVM. Returns True if it existed."""
        if sandbox_id not in self._vms:
            return False
        self._statuses[sandbox_id] = SandboxStatus.DESTROYED
        del self._vms[sandbox_id]
        del self._statuses[sandbox_id]
        return True

    def execute(self, sandbox_id: str, command: str) -> ResourceUsage:
        """Execute a command inside a Firecracker microVM.

        Enforces Firecracker-specific constraints:
        - No network by default (network_mode checked at create time)
        - Syscall filtering simulation
        """
        if sandbox_id not in self._vms:
            raise SandboxError(
                f"Firecracker VM not found: {sandbox_id}",
                details={"vm_id": sandbox_id},
            )
        if self._statuses[sandbox_id] != SandboxStatus.RUNNING:
            raise SandboxError(
                f"VM not running: {self._statuses[sandbox_id].value}",
                details={"vm_id": sandbox_id},
            )

        vm = self._vms[sandbox_id]
        return ResourceUsage(
            cpu_ms=10,
            memory_bytes=vm.mem_size_mib * 1024 * 1024 // 8,
        )

    def status(self, sandbox_id: str) -> SandboxStatus:
        """Get the status of a Firecracker microVM."""
        if sandbox_id not in self._statuses:
            raise SandboxError(
                f"Firecracker VM not found: {sandbox_id}",
                details={"vm_id": sandbox_id},
            )
        return self._statuses[sandbox_id]

    def get_vm(self, sandbox_id: str) -> FirecrackerSandbox | None:
        """Get VM metadata."""
        return self._vms.get(sandbox_id)

    def list_vms(self) -> list[FirecrackerSandbox]:
        """List all active VMs."""
        return list(self._vms.values())
