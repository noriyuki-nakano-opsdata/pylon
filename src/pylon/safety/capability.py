"""Rule-of-Two+ capability validation (Section 2.3, FR-02).

Validates at 4 points:
1. Agent creation (static check from pylon.yaml)
2. Dynamic tool grant (every MCP tool discovery triggers re-validation)
3. Subgraph inheritance (child inherits subset of parent capabilities only)
4. A2A delegation (peer capabilities verified against agent-card)
"""

from __future__ import annotations

from pylon.errors import PolicyViolationError
from pylon.safety.context import SafetyContext
from pylon.safety.engine import SafetyEngine
from pylon.safety.tools import ToolDescriptor, resolve_tool_descriptor
from pylon.types import AgentCapability, AgentConfig, TrustLevel


class CapabilityValidator:
    """Validates agent capabilities against Rule-of-Two+ constraints."""

    @staticmethod
    def resolve_agent_capability(config: AgentConfig) -> AgentCapability:
        """Resolve effective capability from explicit + inferred flags.

        Effective capability is the union of:
        - Explicit capability in AgentConfig.capability
        - Inferred capability from input_trust and tool set
        """
        inferred_untrusted, inferred_secrets, inferred_write = _infer_capability_flags(config)

        merged = _make_cap(
            untrusted=config.capability.can_read_untrusted or inferred_untrusted,
            secrets=config.capability.can_access_secrets or inferred_secrets,
            write=config.capability.can_write_external or inferred_write,
        )

        _enforce_rule_of_two_plus(merged, context=f"agent '{config.name}'")
        return merged

    @staticmethod
    def validate_agent_config(config: AgentConfig) -> None:
        """Validate at agent creation time (checkpoint 1)."""
        CapabilityValidator.resolve_agent_capability(config)

    @staticmethod
    def validate_tool_grant(
        current: AgentCapability,
        tool_trust: TrustLevel | None = None,
        tool_writes_external: bool | None = None,
        tool_accesses_secrets: bool | None = None,
        *,
        agent_name: str = "",
        tool_descriptor: ToolDescriptor | None = None,
        tool_name: str = "",
    ) -> AgentCapability:
        """Validate dynamic tool grant (checkpoint 2).

        Returns the merged capability if valid.
        Raises PolicyViolationError if grant would violate Rule-of-Two+.
        """
        descriptor = tool_descriptor
        if descriptor is None:
            if tool_name:
                descriptor = resolve_tool_descriptor(tool_name)
            else:
                descriptor = ToolDescriptor(
                    name=tool_name or "tool",
                    input_trust=tool_trust or TrustLevel.TRUSTED,
                    reads_untrusted_input=(tool_trust == TrustLevel.UNTRUSTED),
                    accesses_secrets=bool(tool_accesses_secrets),
                    writes_external=bool(tool_writes_external),
                )

        decision = SafetyEngine.evaluate_tool_use(
            SafetyContext(
                agent_name=agent_name or "agent",
                held_capability=current,
                data_taint=(
                    TrustLevel.UNTRUSTED
                    if current.can_read_untrusted
                    else TrustLevel.TRUSTED
                ),
            ),
            descriptor,
            tool_name=tool_name or descriptor.name,
        )
        if not decision.allowed or decision.effective_capability is None:
            raise PolicyViolationError(decision.reason)
        return decision.effective_capability

    @staticmethod
    def validate_subgraph_inheritance(
        parent: AgentCapability, child: AgentCapability, *, child_name: str = ""
    ) -> None:
        """Validate subgraph inheritance (checkpoint 3).

        Child must be a subset of parent capabilities.
        """
        if child.can_read_untrusted and not parent.can_read_untrusted:
            raise PolicyViolationError(
                f"Child agent '{child_name}' cannot have can_read_untrusted "
                "when parent does not",
            )
        if child.can_access_secrets and not parent.can_access_secrets:
            raise PolicyViolationError(
                f"Child agent '{child_name}' cannot have can_access_secrets "
                "when parent does not",
            )
        if child.can_write_external and not parent.can_write_external:
            raise PolicyViolationError(
                f"Child agent '{child_name}' cannot have can_write_external "
                "when parent does not",
            )
        _enforce_rule_of_two_plus(child, context=f"child agent '{child_name}'")

    @staticmethod
    def validate_a2a_delegation(
        sender_cap: AgentCapability,
        receiver_declared_cap: AgentCapability,
        *,
        receiver_name: str = "",
    ) -> None:
        """Validate A2A delegation (checkpoint 4).

        Receiver capabilities are verified against their agent-card declaration.
        Sender cannot escalate beyond its own capabilities.
        """
        sender_context = SafetyContext(
            agent_name="sender",
            held_capability=sender_cap,
            data_taint=TrustLevel.UNTRUSTED
            if sender_cap.can_read_untrusted
            else TrustLevel.TRUSTED,
        )
        decision = SafetyEngine.evaluate_delegation(
            sender_context,
            receiver_declared_cap,
            receiver_name=receiver_name,
        )
        if not decision.allowed:
            raise PolicyViolationError(decision.reason)

        merged = _make_cap(
            untrusted=sender_cap.can_read_untrusted or receiver_declared_cap.can_read_untrusted,
            secrets=sender_cap.can_access_secrets or receiver_declared_cap.can_access_secrets,
            write=sender_cap.can_write_external or receiver_declared_cap.can_write_external,
        )
        _enforce_rule_of_two_plus(
            merged,
            context=f"A2A peer '{receiver_name}'",
        )


def _make_cap(
    *,
    untrusted: bool = False,
    secrets: bool = False,
    write: bool = False,
) -> AgentCapability:
    """Create AgentCapability without triggering __post_init__ validation."""
    cap = AgentCapability.__new__(AgentCapability)
    object.__setattr__(cap, "can_read_untrusted", untrusted)
    object.__setattr__(cap, "can_access_secrets", secrets)
    object.__setattr__(cap, "can_write_external", write)
    return cap


def _infer_capability_flags(config: AgentConfig) -> tuple[bool, bool, bool]:
    """Infer capability flags from agent config without constructing AgentCapability."""
    can_read_untrusted = config.input_trust == TrustLevel.UNTRUSTED
    can_access_secrets = any(resolve_tool_descriptor(t).accesses_secrets for t in config.tools)
    can_write_external = any(resolve_tool_descriptor(t).writes_external for t in config.tools)
    return can_read_untrusted, can_access_secrets, can_write_external


def _enforce_rule_of_two_plus(cap: AgentCapability, *, context: str) -> None:
    """Enforce Rule-of-Two+ constraint with descriptive error."""
    flags = [cap.can_read_untrusted, cap.can_access_secrets, cap.can_write_external]
    if all(flags):
        raise PolicyViolationError(
            f"Rule-of-Two violation ({context}): "
            "agent cannot simultaneously process untrusted input, "
            "access secrets, and modify external state",
        )
    if cap.can_read_untrusted and cap.can_access_secrets:
        raise PolicyViolationError(
            f"Forbidden pair ({context}): "
            "agent cannot simultaneously process untrusted input "
            "and access secrets (prompt injection exfiltration risk)",
        )
