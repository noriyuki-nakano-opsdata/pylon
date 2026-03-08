"""Multi-path Kill Switch (FR-10).

| Path      | Mechanism        | Latency |
|-----------|------------------|---------|
| Primary   | NATS publish     | <1s     |
| Fallback  | ConfigMap poll   | <5s     |
| Emergency | namespace delete | <10s    |

This module provides the in-memory implementation.
NATS and K8s backends are injected in production.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pylon.types import KillSwitchEvent


@dataclass
class _ActiveSwitch:
    """Internal record of an active kill switch."""

    event: KillSwitchEvent
    activated_at: float


class KillSwitch:
    """In-memory kill switch for agent/workflow/tenant/global scopes."""

    def __init__(self) -> None:
        self._active: dict[str, _ActiveSwitch] = {}
        self._parent_scopes: dict[str, str] = {}

    def register_scope(self, scope: str, *, parent_scope: str = "") -> None:
        """Register a scope relationship for inheritance checks."""
        if scope == "global":
            self._parent_scopes.pop(scope, None)
            return
        self._parent_scopes[scope] = parent_scope

    def activate(
        self,
        scope: str,
        reason: str,
        issued_by: str,
        *,
        parent_scope: str = "",
    ) -> KillSwitchEvent:
        """Activate kill switch for a given scope.

        Args:
            scope: "global", "tenant:{id}", "workflow:{id}", "agent:{id}"
            reason: Human-readable reason for activation
            issued_by: Identity of the person/system activating
        """
        if parent_scope:
            self.register_scope(scope, parent_scope=parent_scope)
        event = KillSwitchEvent(
            scope=scope,
            reason=reason,
            issued_by=issued_by,
            parent_scope=parent_scope,
        )
        self._active[scope] = _ActiveSwitch(event=event, activated_at=time.monotonic())
        return event

    def is_active(self, scope: str) -> bool:
        """Check if kill switch is active for a scope.

        Also checks registered parent scopes: if an ancestor scope is active,
        descendants are considered active.
        """
        for candidate in self._lineage(scope):
            if candidate in self._active:
                return True
        return False

    def deactivate(self, scope: str) -> KillSwitchEvent | None:
        """Deactivate kill switch for a scope.

        Returns the original event if it was active, None otherwise.
        """
        entry = self._active.pop(scope, None)
        return entry.event if entry else None

    def get_active_scopes(self) -> list[str]:
        """Return all currently active scopes."""
        return list(self._active.keys())

    def get_event(self, scope: str) -> KillSwitchEvent | None:
        """Get the event for an active scope."""
        entry = self._active.get(scope)
        return entry.event if entry else None

    def get_parent_scope(self, scope: str) -> str:
        """Return the registered parent scope for a scope."""
        return self._parent_scopes.get(scope, "")

    def _lineage(self, scope: str) -> list[str]:
        lineage = [scope]
        seen = {scope}
        current = scope

        while True:
            parent = self._parent_scopes.get(current, "")
            if not parent or parent in seen:
                break
            lineage.append(parent)
            seen.add(parent)
            current = parent

        if "global" not in seen:
            lineage.append("global")
        return lineage
