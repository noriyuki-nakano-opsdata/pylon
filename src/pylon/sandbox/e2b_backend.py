"""Compatibility shim for legacy E2B-named imports.

Experiment sandboxes now use self-hosted Firecracker and Docker backends.
This module preserves the old import path while re-exporting the current
implementation.
"""

from __future__ import annotations

from pylon.sandbox.firecracker_backend import (
    DockerSandboxBackend,
    ExecutionResult,
    FirecrackerSandboxBackend,
    SandboxBackend,
    SandboxBackendType,
    SandboxManager,
    SandboxSession,
)

# Legacy alias kept for older imports.
E2BSandboxBackend = FirecrackerSandboxBackend

__all__ = [
    "DockerSandboxBackend",
    "E2BSandboxBackend",
    "ExecutionResult",
    "FirecrackerSandboxBackend",
    "SandboxBackend",
    "SandboxBackendType",
    "SandboxManager",
    "SandboxSession",
]
