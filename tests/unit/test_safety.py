"""Tests for safety module — Rule-of-Two+ and Autonomy Ladder."""

import pytest

from pylon.errors import ApprovalRequiredError, PolicyViolationError
from pylon.safety.autonomy import AutonomyEnforcer
from pylon.safety.capability import CapabilityValidator
from pylon.types import (
    AgentCapability,
    AgentConfig,
    AutonomyLevel,
    PolicyConfig,
    TrustLevel,
)


class TestCapabilityValidator:
    def test_safe_agent_passes(self):
        config = AgentConfig(
            name="reader",
            tools=["file-read"],
            input_trust=TrustLevel.UNTRUSTED,
        )
        CapabilityValidator.validate_agent_config(config)

    def test_forbidden_pair_fails(self):
        config = AgentConfig(
            name="dangerous",
            tools=["vault-read"],
            input_trust=TrustLevel.UNTRUSTED,
        )
        with pytest.raises(PolicyViolationError, match="Forbidden pair"):
            CapabilityValidator.validate_agent_config(config)

    def test_all_three_fails(self):
        config = AgentConfig(
            name="dangerous",
            tools=["vault-read", "github-pr-approve"],
            input_trust=TrustLevel.UNTRUSTED,
        )
        with pytest.raises(PolicyViolationError):
            CapabilityValidator.validate_agent_config(config)

    def test_tool_grant_safe(self):
        current = AgentCapability(can_write_external=True)
        merged = CapabilityValidator.validate_tool_grant(
            current,
            tool_trust=TrustLevel.TRUSTED,
            tool_writes_external=False,
            tool_accesses_secrets=True,
            agent_name="test",
        )
        assert merged.can_access_secrets
        assert merged.can_write_external

    def test_tool_grant_violation(self):
        current = AgentCapability(can_read_untrusted=True)
        with pytest.raises(PolicyViolationError, match="Forbidden pair"):
            CapabilityValidator.validate_tool_grant(
                current,
                tool_trust=TrustLevel.TRUSTED,
                tool_writes_external=False,
                tool_accesses_secrets=True,
                agent_name="test",
            )

    def test_subgraph_child_subset(self):
        parent = AgentCapability(can_write_external=True, can_access_secrets=True)
        child = AgentCapability(can_write_external=True)
        CapabilityValidator.validate_subgraph_inheritance(parent, child, child_name="child")

    def test_subgraph_child_escalation_fails(self):
        parent = AgentCapability(can_write_external=True)
        child = AgentCapability(can_access_secrets=True)
        with pytest.raises(PolicyViolationError, match="cannot have can_access_secrets"):
            CapabilityValidator.validate_subgraph_inheritance(parent, child, child_name="child")

    def test_a2a_delegation_rejects_transitive_forbidden_union(self):
        sender = AgentCapability(can_read_untrusted=True)
        receiver = AgentCapability(can_access_secrets=True)

        with pytest.raises(PolicyViolationError, match="Forbidden pair"):
            CapabilityValidator.validate_a2a_delegation(
                sender,
                receiver,
                receiver_name="peer",
            )

    def test_a2a_delegation_allows_narrower_receiver(self):
        sender = AgentCapability(can_write_external=True, can_access_secrets=True)
        receiver = AgentCapability(can_write_external=True)

        CapabilityValidator.validate_a2a_delegation(
            sender,
            receiver,
            receiver_name="peer",
        )


class TestAutonomyEnforcer:
    def test_a2_no_approval(self):
        policy = PolicyConfig()
        enforcer = AutonomyEnforcer(policy)
        result = enforcer.check_action("agent1", "read-file", AutonomyLevel.A2)
        assert result is None

    def test_a3_requires_approval(self):
        policy = PolicyConfig(require_approval_above=AutonomyLevel.A3)
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(ApprovalRequiredError):
            enforcer.check_action("agent1", "deploy", AutonomyLevel.A3)

    def test_a4_requires_approval(self):
        policy = PolicyConfig(require_approval_above=AutonomyLevel.A3)
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(ApprovalRequiredError):
            enforcer.check_action("agent1", "deploy", AutonomyLevel.A4)

    def test_blocked_action(self):
        policy = PolicyConfig(blocked_actions=["git push --force"])
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(PolicyViolationError, match="blocked"):
            enforcer.check_action("agent1", "git push --force", AutonomyLevel.A2)

    def test_approve_flow(self):
        policy = PolicyConfig(require_approval_above=AutonomyLevel.A3)
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(ApprovalRequiredError) as exc_info:
            enforcer.check_action("agent1", "merge-pr", AutonomyLevel.A3)
        request_id = exc_info.value.details["request_id"]

        result = enforcer.approve(request_id, "admin")
        assert result.approved is True
        assert result.approved_by == "admin"

    def test_deny_flow(self):
        policy = PolicyConfig(require_approval_above=AutonomyLevel.A3)
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(ApprovalRequiredError) as exc_info:
            enforcer.check_action("agent1", "deploy", AutonomyLevel.A3)
        request_id = exc_info.value.details["request_id"]

        result = enforcer.deny(request_id, "admin")
        assert result.approved is False

    def test_pending_list(self):
        policy = PolicyConfig(require_approval_above=AutonomyLevel.A3)
        enforcer = AutonomyEnforcer(policy)
        with pytest.raises(ApprovalRequiredError):
            enforcer.check_action("a1", "action1", AutonomyLevel.A3)
        with pytest.raises(ApprovalRequiredError):
            enforcer.check_action("a2", "action2", AutonomyLevel.A4)
        assert len(enforcer.get_pending()) == 2
