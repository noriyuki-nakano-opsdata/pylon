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

    id: str = field(default_factory=lambda: f"apr_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    action: str = ""
    autonomy_level: AutonomyLevel = AutonomyLevel.A3
    context: dict[str, Any] = field(default_factory=dict)
    plan_hash: str = ""
    effect_hash: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "action": self.action,
            "autonomy_level": self.autonomy_level.name,
            "context": dict(self.context),
            "plan_hash": self.plan_hash,
            "effect_hash": self.effect_hash,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ApprovalRequest:
        expires_at = payload.get("expires_at")
        created_at = payload.get("created_at")
        return cls(
            id=str(payload.get("id", f"apr_{uuid.uuid4().hex[:12]}")),
            agent_id=str(payload.get("agent_id", "")),
            action=str(payload.get("action", "")),
            autonomy_level=_safe_autonomy_level(payload.get("autonomy_level", "A3")),
            context=dict(payload.get("context", {})),
            plan_hash=str(payload.get("plan_hash", "")),
            effect_hash=str(payload.get("effect_hash", "")),
            status=ApprovalStatus(str(payload.get("status", ApprovalStatus.PENDING.value))),
            created_at=(
                _parse_datetime(created_at) if created_at is not None else datetime.now(UTC)
            ),
            expires_at=_parse_datetime(expires_at) if expires_at else None,
        )


@dataclass
class ApprovalDecision:
    """The outcome of an approval request."""

    request_id: str = ""
    approved: bool = False
    decided_by: str = ""
    reason: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _safe_autonomy_level(value: Any) -> AutonomyLevel:
    try:
        return AutonomyLevel[str(value)]
    except KeyError:
        return AutonomyLevel.A3


def _strict_json_default(obj: Any) -> str:
    """Raise TypeError for non-JSON-serializable types to prevent unstable hashes."""
    raise TypeError(
        f"Approval binding values must be JSON-serializable, got {type(obj).__name__}"
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def compute_approval_binding_hash(value: Any) -> str:
    """Compute a stable hash for approval-bound plan/effect payloads.

    Values must be JSON-serializable primitives (str, int, float,
    bool, None, dict, list). Non-serializable types raise TypeError.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_strict_json_default)
    return uuid.uuid5(uuid.NAMESPACE_OID, payload).hex
