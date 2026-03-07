"""Runtime safety evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from pylon.safety.context import SafetyContext
from pylon.safety.tools import ToolDescriptor
from pylon.types import AgentCapability, TrustLevel


@dataclass(frozen=True)
class SafetyDecision:
    """Decision returned by SafetyEngine."""

    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    effective_capability: AgentCapability | None = None
    effective_context: SafetyContext | None = None


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
        if parent.data_taint == TrustLevel.UNTRUSTED:
            merged_untrusted = True
        merged_secrets = (
            parent.held_capability.can_access_secrets or receiver_capability.can_access_secrets
        )
        merged_write = (
            parent.held_capability.can_write_external or receiver_capability.can_write_external
        )

        target = receiver_name or "receiver"
        decision = SafetyEngine._evaluate_union(
            merged_untrusted=merged_untrusted,
            merged_secrets=merged_secrets,
            merged_write=merged_write,
            context=f"A2A peer '{target}'",
        )
        if not decision.allowed:
            return decision

        return SafetyDecision(allowed=True)

    @staticmethod
    def evaluate_tool_use(
        context: SafetyContext,
        descriptor: ToolDescriptor,
        *,
        tool_name: str | None = None,
    ) -> SafetyDecision:
        """Evaluate a structured tool usage request against runtime context."""
        effective_name = tool_name or descriptor.name
        tool_untrusted = (
            descriptor.reads_untrusted_input or descriptor.input_trust == TrustLevel.UNTRUSTED
        )
        merged_untrusted = context.held_capability.can_read_untrusted or tool_untrusted
        if context.data_taint == TrustLevel.UNTRUSTED:
            merged_untrusted = True
        merged_secrets = context.held_capability.can_access_secrets or descriptor.accesses_secrets
        merged_write = context.held_capability.can_write_external or descriptor.writes_external

        base_decision = SafetyEngine._evaluate_union(
            merged_untrusted=merged_untrusted,
            merged_secrets=merged_secrets,
            merged_write=merged_write,
            context=f"tool '{effective_name}'",
        )
        if not base_decision.allowed:
            return base_decision

        effective_capability = AgentCapability.__new__(AgentCapability)
        object.__setattr__(effective_capability, "can_read_untrusted", merged_untrusted)
        object.__setattr__(effective_capability, "can_access_secrets", merged_secrets)
        object.__setattr__(effective_capability, "can_write_external", merged_write)
        effective_context = SafetyContext(
            agent_name=context.agent_name,
            run_id=context.run_id,
            held_capability=effective_capability,
            data_taint=(
                TrustLevel.UNTRUSTED if merged_untrusted else context.data_taint
            ),
            effect_scopes=context.effect_scopes | descriptor.effect_scopes,
            secret_scopes=context.secret_scopes | descriptor.secret_scopes,
            call_chain=context.call_chain,
            approval_token=context.approval_token,
        )
        return SafetyDecision(
            allowed=True,
            requires_approval=descriptor.requires_approval,
            effective_capability=effective_capability,
            effective_context=effective_context,
        )

    @staticmethod
    def _evaluate_union(
        *,
        merged_untrusted: bool,
        merged_secrets: bool,
        merged_write: bool,
        context: str,
    ) -> SafetyDecision:
        if all((merged_untrusted, merged_secrets, merged_write)):
            return SafetyDecision(
                allowed=False,
                reason=(
                    f"Rule-of-Two violation ({context}): "
                    "agent cannot simultaneously process untrusted input, "
                    "access secrets, and modify external state"
                ),
            )
        if merged_untrusted and merged_secrets:
            return SafetyDecision(
                allowed=False,
                reason=(
                    f"Forbidden pair ({context}): "
                    "agent cannot simultaneously process untrusted input "
                    "and access secrets (prompt injection exfiltration risk)"
                ),
            )
        return SafetyDecision(allowed=True)
