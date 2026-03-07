"""Runtime safety evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.safety.context import SafetyContext
from pylon.types import AgentCapability


@dataclass(frozen=True)
class SafetyDecision:
    """Decision returned by SafetyEngine."""

    allowed: bool
    reason: str = ""
    requires_approval: bool = False


class SafetyEngine:
    """Evaluates runtime safety decisions using context + capability unions."""

    @staticmethod
    def evaluate_delegation(
        parent: SafetyContext,
        receiver_capability: AgentCapability,
        *,
        receiver_name: str = "",
    ) -> SafetyDecision:
        merged_untrusted = (
            parent.held_capability.can_read_untrusted or receiver_capability.can_read_untrusted
        )
        merged_secrets = (
            parent.held_capability.can_access_secrets or receiver_capability.can_access_secrets
        )
        merged_write = (
            parent.held_capability.can_write_external or receiver_capability.can_write_external
        )

        target = receiver_name or "receiver"
        if all((merged_untrusted, merged_secrets, merged_write)):
            return SafetyDecision(
                allowed=False,
                reason=(
                    f"Rule-of-Two violation (A2A peer '{target}'): "
                    "agent cannot simultaneously process untrusted input, "
                    "access secrets, and modify external state"
                ),
            )
        if merged_untrusted and merged_secrets:
            return SafetyDecision(
                allowed=False,
                reason=(
                    f"Forbidden pair (A2A peer '{target}'): "
                    "agent cannot simultaneously process untrusted input "
                    "and access secrets (prompt injection exfiltration risk)"
                ),
            )

        return SafetyDecision(allowed=True)
