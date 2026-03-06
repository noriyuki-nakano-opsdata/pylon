"""Tests for core type definitions and Rule-of-Two+ enforcement."""

import pytest

from pylon.types import (
    AgentCapability,
    AgentState,
    AutonomyLevel,
    PolicyViolation,
    SandboxTier,
    TrustLevel,
)


class TestAgentCapability:
    """Rule-of-Two+ enforcement tests."""

    def test_no_capabilities_valid(self):
        cap = AgentCapability()
        assert not cap.can_read_untrusted
        assert not cap.can_access_secrets
        assert not cap.can_write_external

    def test_single_capability_valid(self):
        AgentCapability(can_read_untrusted=True)
        AgentCapability(can_access_secrets=True)
        AgentCapability(can_write_external=True)

    def test_secrets_and_write_valid(self):
        """Secret access + external write is allowed (no untrusted input)."""
        cap = AgentCapability(can_access_secrets=True, can_write_external=True)
        assert cap.can_access_secrets and cap.can_write_external

    def test_untrusted_and_write_valid(self):
        """Untrusted input + external write is allowed (no secret access)."""
        cap = AgentCapability(can_read_untrusted=True, can_write_external=True)
        assert cap.can_read_untrusted and cap.can_write_external

    def test_all_three_violation(self):
        """All three capabilities violates Rule-of-Two."""
        with pytest.raises(PolicyViolation, match="Rule-of-Two"):
            AgentCapability(
                can_read_untrusted=True,
                can_access_secrets=True,
                can_write_external=True,
            )

    def test_forbidden_pair_violation(self):
        """Untrusted input + secret access is a forbidden pair."""
        with pytest.raises(PolicyViolation, match="Forbidden pair"):
            AgentCapability(can_read_untrusted=True, can_access_secrets=True)

    def test_can_grant_safe(self):
        cap = AgentCapability(can_write_external=True)
        additional = AgentCapability(can_access_secrets=True)
        assert cap.can_grant(additional)

    def test_can_grant_would_violate(self):
        cap = AgentCapability(can_read_untrusted=True)
        additional = AgentCapability(can_access_secrets=True)
        assert not cap.can_grant(additional)


class TestAgentState:
    """Agent lifecycle state machine tests."""

    def test_init_to_ready(self):
        assert AgentState.INIT.can_transition_to(AgentState.READY)

    def test_ready_to_running(self):
        assert AgentState.READY.can_transition_to(AgentState.RUNNING)

    def test_running_to_paused(self):
        assert AgentState.RUNNING.can_transition_to(AgentState.PAUSED)

    def test_running_to_completed(self):
        assert AgentState.RUNNING.can_transition_to(AgentState.COMPLETED)

    def test_running_to_killed(self):
        assert AgentState.RUNNING.can_transition_to(AgentState.KILLED)

    def test_completed_is_terminal(self):
        assert not AgentState.COMPLETED.can_transition_to(AgentState.RUNNING)
        assert not AgentState.COMPLETED.can_transition_to(AgentState.READY)

    def test_killed_is_terminal(self):
        assert not AgentState.KILLED.can_transition_to(AgentState.RUNNING)

    def test_invalid_transition(self):
        assert not AgentState.INIT.can_transition_to(AgentState.RUNNING)
        assert not AgentState.PAUSED.can_transition_to(AgentState.COMPLETED)


class TestAutonomyLevel:
    """Autonomy Ladder ordering tests."""

    def test_ordering(self):
        assert AutonomyLevel.A0 < AutonomyLevel.A1 < AutonomyLevel.A2
        assert AutonomyLevel.A2 < AutonomyLevel.A3 < AutonomyLevel.A4

    def test_a3_requires_approval(self):
        assert AutonomyLevel.A3 >= AutonomyLevel.A3
        assert AutonomyLevel.A4 >= AutonomyLevel.A3
        assert not AutonomyLevel.A2 >= AutonomyLevel.A3
