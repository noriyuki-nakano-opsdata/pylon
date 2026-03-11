"""Approval policy for agent operation authorization."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from pylon.types import AutonomyLevel


class ApprovalPolicy(enum.StrEnum):
    """Policy governing when human approval is required."""

    UNTRUSTED = "untrusted"
    ON_FAILURE = "on_failure"
    ON_REQUEST = "on_request"
    AUTO_APPROVE = "auto_approve"

    @classmethod
    def from_autonomy_level(cls, level: AutonomyLevel) -> ApprovalPolicy:
        """Map an autonomy level to the corresponding approval policy."""
        if level <= AutonomyLevel.A1:
            return cls.UNTRUSTED
        if level == AutonomyLevel.A2:
            return cls.ON_FAILURE
        if level == AutonomyLevel.A3:
            return cls.ON_REQUEST
        return cls.AUTO_APPROVE


class SandboxMode(enum.StrEnum):
    """Sandbox access level for agent operations."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass
class ApprovalRequest:
    """A pending approval request for a specific operation."""

    request_id: str
    operation: str
    description: str
    policy: ApprovalPolicy
    auto_approved: bool = False


class ApprovalGate:
    """Gate that checks operations against the active approval policy.

    Operations are checked and either auto-approved or held pending
    until explicitly approved or denied.
    """

    def __init__(
        self,
        default_policy: ApprovalPolicy = ApprovalPolicy.ON_FAILURE,
    ) -> None:
        self._default_policy = default_policy
        self._pending: dict[str, ApprovalRequest] = {}
        self._denied: set[str] = set()

    def check(
        self,
        operation: str,
        description: str,
        *,
        policy: ApprovalPolicy | None = None,
    ) -> ApprovalRequest:
        """Check whether an operation requires approval.

        Returns an ApprovalRequest with auto_approved=True for AUTO_APPROVE
        policy, or auto_approved=False for all other policies.
        """
        effective_policy = policy if policy is not None else self._default_policy
        request_id = uuid.uuid4().hex
        auto_approved = effective_policy == ApprovalPolicy.AUTO_APPROVE

        request = ApprovalRequest(
            request_id=request_id,
            operation=operation,
            description=description,
            policy=effective_policy,
            auto_approved=auto_approved,
        )

        if not auto_approved:
            self._pending[request_id] = request

        return request

    def approve(self, request_id: str) -> None:
        """Approve a pending request."""
        self._pending.pop(request_id, None)

    def deny(self, request_id: str) -> None:
        """Deny a pending request, recording it as explicitly denied."""
        self._pending.pop(request_id, None)
        self._denied.add(request_id)

    def is_denied(self, request_id: str) -> bool:
        """Check whether a request was explicitly denied."""
        return request_id in self._denied
