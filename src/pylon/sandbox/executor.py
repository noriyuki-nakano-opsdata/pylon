"""Sandbox code execution (FR-06).

In-memory executor that simulates command execution within a sandbox,
enforcing timeout and resource limits via SandboxPolicy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pylon.errors import SandboxError
from pylon.sandbox.manager import SandboxManager, SandboxStatus
from pylon.sandbox.policy import ResourceUsage


@dataclass
class ExecutionResult:
    """Result of a command execution in a sandbox."""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    resource_usage: ResourceUsage


class SandboxExecutor:
    """Executes commands within managed sandboxes.

    In-memory implementation: simulates execution results.
    Production implementation would delegate to container runtimes.
    """

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    def execute(
        self,
        sandbox_id: str,
        command: str,
        *,
        timeout: int | None = None,
        simulated_stdout: str = "",
        simulated_stderr: str = "",
        simulated_exit_code: int = 0,
        simulated_cpu_ms: int = 10,
        simulated_memory_bytes: int = 1_048_576,
    ) -> ExecutionResult:
        """Execute a command in a sandbox.

        Args:
            sandbox_id: Target sandbox ID.
            command: Command string to execute.
            timeout: Override timeout in seconds (defaults to sandbox config).
            simulated_*: In-memory simulation parameters.

        Raises:
            SandboxError: If sandbox not found, not running, command blocked,
                         or resource limits exceeded.
        """
        sandbox = self._manager.get(sandbox_id)
        if sandbox is None:
            raise SandboxError(f"Sandbox not found: {sandbox_id}")
        if sandbox.status != SandboxStatus.RUNNING:
            raise SandboxError(
                f"Sandbox not running: {sandbox.status.value}",
                details={"sandbox_id": sandbox_id},
            )

        # Policy check: command allowed?
        allowed, reason = sandbox.policy.validate_execution(command)
        if not allowed:
            raise SandboxError(
                f"Command blocked by policy: {reason}",
                details={"sandbox_id": sandbox_id, "command": command},
            )

        effective_timeout = timeout or sandbox.config.timeout
        start = time.monotonic()

        # Simulate execution
        usage = ResourceUsage(
            cpu_ms=simulated_cpu_ms,
            memory_bytes=simulated_memory_bytes,
        )

        # Resource limit check
        within_limits, limit_reason = sandbox.policy.check_resources(usage)
        if not within_limits:
            raise SandboxError(
                f"Resource limit exceeded: {limit_reason}",
                details={"sandbox_id": sandbox_id},
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        # Timeout check (simulated: compare simulated CPU time against timeout)
        if simulated_cpu_ms > effective_timeout * 1000:
            raise SandboxError(
                f"Execution timed out after {effective_timeout}s",
                details={"sandbox_id": sandbox_id, "timeout": effective_timeout},
            )

        # Update sandbox cumulative resource usage
        sandbox.resource_usage.cpu_ms += usage.cpu_ms
        sandbox.resource_usage.memory_bytes = max(
            sandbox.resource_usage.memory_bytes, usage.memory_bytes
        )

        return ExecutionResult(
            stdout=simulated_stdout,
            stderr=simulated_stderr,
            exit_code=simulated_exit_code,
            duration_ms=duration_ms,
            resource_usage=usage,
        )
