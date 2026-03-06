"""Autonomy Ladder enforcement (ADR-004, FR-10).

Five-level graduated model: A0 (manual) through A4 (fully autonomous).
Actions at A3+ require human approval by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.errors import ApprovalRequiredError, PolicyViolationError
from pylon.types import AutonomyLevel, PolicyConfig


@dataclass
class ApprovalRequest:
    """Pending approval request for A3+ actions."""

    agent_name: str
    action: str
    autonomy_level: AutonomyLevel
    plan: Any | None = None
    approved: bool | None = None  # None = pending
    approved_by: str | None = None

    @property
    def is_pending(self) -> bool:
        return self.approved is None


class AutonomyEnforcer:
    """Enforces autonomy level policies.

    - A0: All actions require human execution
    - A1: Each step needs approval
    - A2: Within policy bounds, no approval needed
    - A3: Plan needs approval, then autonomous execution
    - A4: Fully autonomous within safety envelope
    """

    def __init__(self, policy: PolicyConfig) -> None:
        self._policy = policy
        self._pending: dict[str, ApprovalRequest] = {}

    def check_action(
        self,
        agent_name: str,
        action: str,
        autonomy: AutonomyLevel,
        *,
        plan: Any | None = None,
    ) -> ApprovalRequest | None:
        """Check if an action requires approval.

        Returns None if action can proceed.
        Returns ApprovalRequest if approval is needed.
        Raises PolicyViolationError if action is blocked.
        """
        if self._is_blocked_action(action):
            raise PolicyViolationError(
                f"Action '{action}' is blocked by policy",
                details={"agent": agent_name, "action": action},
            )

        if autonomy >= self._policy.require_approval_above:
            request = ApprovalRequest(
                agent_name=agent_name,
                action=action,
                autonomy_level=autonomy,
                plan=plan,
            )
            request_id = f"{agent_name}:{action}"
            self._pending[request_id] = request
            raise ApprovalRequiredError(
                f"Action requires approval (autonomy={autonomy.name})",
                details={
                    "request_id": request_id,
                    "agent": agent_name,
                    "action": action,
                    "autonomy_level": autonomy.name,
                },
            )

        return None

    def approve(self, request_id: str, approved_by: str) -> ApprovalRequest:
        """Approve a pending request."""
        if request_id not in self._pending:
            raise PolicyViolationError(f"No pending approval request: {request_id}")
        request = self._pending.pop(request_id)
        request.approved = True
        request.approved_by = approved_by
        return request

    def deny(self, request_id: str, denied_by: str) -> ApprovalRequest:
        """Deny a pending request."""
        if request_id not in self._pending:
            raise PolicyViolationError(f"No pending approval request: {request_id}")
        request = self._pending.pop(request_id)
        request.approved = False
        request.approved_by = denied_by
        return request

    def get_pending(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        return [r for r in self._pending.values() if r.is_pending]

    def _is_blocked_action(self, action: str) -> bool:
        return action in self._policy.blocked_actions
