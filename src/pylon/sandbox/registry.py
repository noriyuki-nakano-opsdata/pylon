"""Sandbox registry — tracks active sandboxes (FR-06).

In-memory storage for sandbox instance tracking,
with agent-based lookup and tier-based aggregation.
"""

from __future__ import annotations

from pylon.sandbox.manager import Sandbox
from pylon.types import SandboxTier


class SandboxRegistry:
    """Tracks active sandbox instances."""

    def __init__(self) -> None:
        self._sandboxes: dict[str, Sandbox] = {}
        self._by_agent: dict[str, list[str]] = {}  # agent_id -> [sandbox_id]

    def register(self, sandbox: Sandbox) -> None:
        """Register a sandbox instance."""
        self._sandboxes[sandbox.id] = sandbox
        if sandbox.agent_id:
            self._by_agent.setdefault(sandbox.agent_id, []).append(sandbox.id)

    def unregister(self, sandbox_id: str) -> bool:
        """Unregister a sandbox. Returns True if it existed."""
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            return False
        if sandbox.agent_id and sandbox.agent_id in self._by_agent:
            ids = self._by_agent[sandbox.agent_id]
            if sandbox_id in ids:
                ids.remove(sandbox_id)
            if not ids:
                del self._by_agent[sandbox.agent_id]
        return True

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID."""
        return self._sandboxes.get(sandbox_id)

    def get_by_agent(self, agent_id: str) -> list[Sandbox]:
        """Get all sandboxes belonging to an agent."""
        ids = self._by_agent.get(agent_id, [])
        return [self._sandboxes[sid] for sid in ids if sid in self._sandboxes]

    def count_by_tier(self) -> dict[SandboxTier, int]:
        """Count active sandboxes grouped by tier."""
        counts: dict[SandboxTier, int] = {}
        for sandbox in self._sandboxes.values():
            counts[sandbox.tier] = counts.get(sandbox.tier, 0) + 1
        return counts

    def count(self) -> int:
        """Total number of registered sandboxes."""
        return len(self._sandboxes)

    def list_all(self) -> list[Sandbox]:
        """List all registered sandboxes."""
        return list(self._sandboxes.values())
