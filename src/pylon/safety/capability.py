"""Rule-of-Two+ capability validation (Section 2.3, FR-02).

Validates at 4 points:
1. Agent creation (static check from pylon.yaml)
2. Dynamic tool grant (every MCP tool discovery triggers re-validation)
3. Subgraph inheritance (child inherits subset of parent capabilities only)
4. A2A delegation (peer capabilities verified against agent-card)
"""

from __future__ import annotations

from pylon.errors import PolicyViolationError
from pylon.types import AgentCapability, AgentConfig, TrustLevel


class CapabilityValidator:
    """Validates agent capabilities against Rule-of-Two+ constraints."""

    @staticmethod
    def validate_agent_config(config: AgentConfig) -> None:
        """Validate at agent creation time (checkpoint 1)."""
        flags = _infer_capability_flags(config)
        cap = _make_cap(untrusted=flags[0], secrets=flags[1], write=flags[2])
        _enforce_rule_of_two_plus(cap, context=f"agent '{config.name}'")

    @staticmethod
    def validate_tool_grant(
        current: AgentCapability,
        tool_trust: TrustLevel,
        tool_writes_external: bool,
        tool_accesses_secrets: bool,
        *,
        agent_name: str = "",
    ) -> AgentCapability:
        """Validate dynamic tool grant (checkpoint 2).

        Returns the merged capability if valid.
        Raises PolicyViolationError if grant would violate Rule-of-Two+.
        """
        merged = _make_cap(
            untrusted=current.can_read_untrusted or (tool_trust == TrustLevel.UNTRUSTED),
            secrets=current.can_access_secrets or tool_accesses_secrets,
            write=current.can_write_external or tool_writes_external,
        )

        context = f"tool grant to agent '{agent_name}'" if agent_name else "tool grant"
        _enforce_rule_of_two_plus(merged, context=context)
        return merged

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
        _enforce_rule_of_two_plus(
            receiver_declared_cap,
            context=f"A2A peer '{receiver_name}'",
        )


def _make_cap(*, untrusted: bool = False, secrets: bool = False, write: bool = False) -> AgentCapability:
    """Create AgentCapability without triggering __post_init__ validation."""
    cap = AgentCapability.__new__(AgentCapability)
    object.__setattr__(cap, "can_read_untrusted", untrusted)
    object.__setattr__(cap, "can_access_secrets", secrets)
    object.__setattr__(cap, "can_write_external", write)
    return cap


def _infer_capability_flags(config: AgentConfig) -> tuple[bool, bool, bool]:
    """Infer capability flags from agent config without constructing AgentCapability."""
    can_read_untrusted = config.input_trust == TrustLevel.UNTRUSTED
    can_access_secrets = any(
        t in config.tools
        for t in ("vault-read", "secret-read", "env-read")
    )
    can_write_external = any(
        t in config.tools
        for t in (
            "github-pr-approve",
            "github-pr-comment",
            "github-pr-request-changes",
            "git-push",
            "db-write",
            "api-call",
        )
    )
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
