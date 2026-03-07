"""Approval workflow types."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.types import AutonomyLevel


class ApprovalStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A request for human approval of an A3+ action."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    action: str = ""
    autonomy_level: AutonomyLevel = AutonomyLevel.A3
    context: dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


@dataclass
class ApprovalDecision:
    """The outcome of an approval request."""

    request_id: str = ""
    approved: bool = False
    decided_by: str = ""
    reason: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))
