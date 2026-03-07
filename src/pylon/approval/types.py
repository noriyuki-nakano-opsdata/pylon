"""Approval workflow types."""

from __future__ import annotations

import enum
import json
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
    plan_hash: str = ""
    effect_hash: str = ""
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


def _strict_json_default(obj: Any) -> str:
    """Raise TypeError for non-JSON-serializable types to prevent unstable hashes."""
    raise TypeError(
        f"Approval binding values must be JSON-serializable, got {type(obj).__name__}"
    )


def compute_approval_binding_hash(value: Any) -> str:
    """Compute a stable hash for approval-bound plan/effect payloads.

    Values must be JSON-serializable primitives (str, int, float,
    bool, None, dict, list). Non-serializable types raise TypeError.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_strict_json_default)
    return uuid.uuid5(uuid.NAMESPACE_OID, payload).hex
