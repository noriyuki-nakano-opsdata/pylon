"""Tests for agent lifecycle, pool, supervisor, and registry."""

from __future__ import annotations

import pytest

from pylon.agents.lifecycle import AgentLifecycleManager, AgentNotFoundError
from pylon.agents.pool import AgentPool, AgentPoolConfig, PoolExhaustedError
from pylon.agents.registry import AgentRegistry, AgentRegistryError
from pylon.agents.runtime import Agent
from pylon.agents.supervisor import (
    AgentSupervisor,
    HealthStatus,
    SupervisorConfig,
)
from pylon.errors import AgentLifecycleError, PolicyViolationError
from pylon.safety.capability import CapabilityValidator, _make_cap
from pylon.types import AgentCapability, AgentConfig, AgentState, TrustLevel

# --- Helper ---

def _config(name: str = "test-agent", role: str = "worker") -> AgentConfig:
    return AgentConfig(name=name, role=role)


# === AgentLifecycleManager Tests ===


class TestAgentLifecycleManager:
    def test_create_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config("a1"))
        assert agent.state == AgentState.READY
        assert agent.config.name == "a1"

    def test_create_registers_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        assert mgr.get_agent(agent.id) is agent

    def test_create_validates_capability(self):
        """AgentCapability validates in __post_init__, so forbidden pairs
        raise PolicyViolationError at construction time."""
        with pytest.raises(PolicyViolationError):
            AgentCapability(
                can_read_untrusted=True,
                can_access_secrets=True,
            )

    def test_create_infers_capability_from_config(self):
        mgr = AgentLifecycleManager()
        cfg = AgentConfig(
            name="writer",
            input_trust=TrustLevel.UNTRUSTED,
            tools=["github-pr-approve"],
        )
        agent = mgr.create_agent(cfg)
        assert agent.capability.can_read_untrusted is True
        assert agent.capability.can_write_external is True

    def test_create_rejects_inferred_forbidden_pair(self):
        mgr = AgentLifecycleManager()
        cfg = AgentConfig(
            name="dangerous",
            input_trust=TrustLevel.UNTRUSTED,
            tools=["secret-read"],
        )
        with pytest.raises(PolicyViolationError, match="Forbidden pair"):
            mgr.create_agent(cfg)

    def test_start_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        result = mgr.start_agent(agent.id)
        assert result.state == AgentState.RUNNING

    def test_pause_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        result = mgr.pause_agent(agent.id)
        assert result.state == AgentState.PAUSED

    def test_resume_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        mgr.pause_agent(agent.id)
        result = mgr.resume_agent(agent.id)
        assert result.state == AgentState.RUNNING

    def test_stop_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        result = mgr.stop_agent(agent.id)
        assert result.state == AgentState.COMPLETED

    def test_kill_agent(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        result = mgr.kill_agent(agent.id)
        assert result.state == AgentState.KILLED

    def test_kill_clears_memory(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        agent.working_memory["key"] = "value"
        mgr.kill_agent(agent.id)
        assert agent.working_memory == {}

    def test_invalid_transition_raises(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        # READY -> PAUSED is invalid
        with pytest.raises(AgentLifecycleError):
            mgr.pause_agent(agent.id)

    def test_start_completed_raises(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        mgr.stop_agent(agent.id)
        with pytest.raises(AgentLifecycleError):
            mgr.start_agent(agent.id)

    def test_agent_not_found_raises(self):
        mgr = AgentLifecycleManager()
        with pytest.raises(AgentNotFoundError):
            mgr.start_agent("nonexistent")

    def test_get_agent_returns_none_for_missing(self):
        mgr = AgentLifecycleManager()
        assert mgr.get_agent("nonexistent") is None

    def test_full_lifecycle(self):
        mgr = AgentLifecycleManager()
        agent = mgr.create_agent(_config())
        assert agent.state == AgentState.READY
        mgr.start_agent(agent.id)
        assert agent.state == AgentState.RUNNING
        mgr.pause_agent(agent.id)
        assert agent.state == AgentState.PAUSED
        mgr.resume_agent(agent.id)
        assert agent.state == AgentState.RUNNING
        mgr.stop_agent(agent.id)
        assert agent.state == AgentState.COMPLETED
        assert agent.is_terminal


# === AgentRegistry Tests ===


class TestAgentRegistry:
    def test_register_and_get(self):
        reg = AgentRegistry()
        agent = Agent(config=_config())
        reg.register(agent)
        assert reg.get(agent.id) is agent

    def test_register_duplicate_raises(self):
        reg = AgentRegistry()
        agent = Agent(config=_config())
        reg.register(agent)
        with pytest.raises(AgentRegistryError):
            reg.register(agent)

    def test_unregister(self):
        reg = AgentRegistry()
        agent = Agent(config=_config())
        reg.register(agent)
        reg.unregister(agent.id)
        assert reg.get(agent.id) is None

    def test_unregister_missing_raises(self):
        reg = AgentRegistry()
        with pytest.raises(AgentRegistryError):
            reg.unregister("nonexistent")

    def test_find_by_role(self):
        reg = AgentRegistry()
        a1 = Agent(config=_config(role="coder"))
        a2 = Agent(config=_config(role="tester"))
        a3 = Agent(config=_config(role="coder"))
        reg.register(a1)
        reg.register(a2)
        reg.register(a3)
        coders = reg.find_by_role("coder")
        assert len(coders) == 2

    def test_find_by_status(self):
        reg = AgentRegistry()
        a1 = Agent(config=_config())
        a2 = Agent(config=_config())
        a1.initialize()
        a1.start()
        reg.register(a1)
        reg.register(a2)
        running = reg.find_by_status(AgentState.RUNNING)
        assert len(running) == 1
        assert running[0] is a1

    def test_count(self):
        reg = AgentRegistry()
        assert reg.count() == 0
        reg.register(Agent(config=_config()))
        reg.register(Agent(config=_config()))
        assert reg.count() == 2


# === AgentPool Tests ===


class TestAgentPool:
    def test_acquire_creates_agent(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr)
        agent = pool.acquire("worker")
        assert agent.state == AgentState.RUNNING
        assert pool.stats.active_count == 1

    def test_release_returns_to_idle(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr)
        agent = pool.acquire("worker")
        pool.release(agent.id)
        assert pool.stats.active_count == 0
        assert pool.stats.idle_count == 1

    def test_acquire_reuses_idle(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr)
        a1 = pool.acquire("worker")
        pool.release(a1.id)
        # total_created should be 2 (original + recycled), acquiring idle should not create more
        created_before = pool.stats.total_created
        a2 = pool.acquire("worker")
        assert pool.stats.total_created == created_before  # reused, not created
        assert a2.state == AgentState.RUNNING

    def test_pool_max_size_enforced(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr, AgentPoolConfig(max_size=2))
        pool.acquire("worker")
        pool.acquire("worker")
        with pytest.raises(PoolExhaustedError):
            pool.acquire("worker")

    def test_fill_to_min(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr, AgentPoolConfig(min_size=3, max_size=5))
        created = pool.fill_to_min("worker")
        assert created == 3
        assert pool.stats.idle_count == 3

    def test_fill_to_min_respects_max(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr, AgentPoolConfig(min_size=5, max_size=2))
        created = pool.fill_to_min()
        assert created == 2

    def test_destroy_agent(self):
        mgr = AgentLifecycleManager()
        pool = AgentPool(mgr)
        agent = pool.acquire("worker")
        pool.destroy(agent.id)
        assert pool.stats.active_count == 0
        assert pool.stats.total_destroyed == 1


# === AgentSupervisor Tests ===


class TestAgentSupervisor:
    def test_check_health_running_is_healthy(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id)
        assert sup.check_health(agent.id) == HealthStatus.HEALTHY

    def test_check_health_paused_is_degraded(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        mgr.pause_agent(agent.id)
        sup.register(agent.id)
        assert sup.check_health(agent.id) == HealthStatus.DEGRADED

    def test_check_health_killed_is_unhealthy(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id)
        mgr.kill_agent(agent.id)
        assert sup.check_health(agent.id) == HealthStatus.UNHEALTHY

    def test_check_health_unregistered_is_unknown(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        assert sup.check_health("nonexistent") == HealthStatus.UNKNOWN

    def test_custom_health_fn(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id, health_fn=lambda _: HealthStatus.DEGRADED)
        assert sup.check_health(agent.id) == HealthStatus.DEGRADED

    def test_on_health_change_callback(self):
        changes: list[tuple[str, HealthStatus, HealthStatus]] = []
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(
            mgr,
            on_health_change=lambda aid, old, new: changes.append((aid, old, new)),
        )
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id)
        sup.check_health(agent.id)  # UNKNOWN -> HEALTHY
        assert len(changes) == 1
        assert changes[0] == (agent.id, HealthStatus.UNKNOWN, HealthStatus.HEALTHY)

    def test_handle_unhealthy_restarts(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr, SupervisorConfig(max_restarts=3))
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id)
        mgr.kill_agent(agent.id)

        new_agent = sup.handle_unhealthy(agent.id)
        assert new_agent is not None
        assert new_agent.id != agent.id
        assert new_agent.state == AgentState.RUNNING

    def test_handle_unhealthy_max_restarts(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr, SupervisorConfig(max_restarts=1))
        agent = mgr.create_agent(_config())
        mgr.start_agent(agent.id)
        sup.register(agent.id)
        mgr.kill_agent(agent.id)

        # First restart succeeds
        new_agent = sup.handle_unhealthy(agent.id)
        assert new_agent is not None

        # Kill again
        mgr.kill_agent(new_agent.id)

        # Second restart exceeds max_restarts
        result = sup.handle_unhealthy(new_agent.id)
        assert result is None

    def test_list_supervised(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        sup.register(agent.id)
        assert len(sup.list_supervised()) == 1

    def test_unregister_supervised(self):
        mgr = AgentLifecycleManager()
        sup = AgentSupervisor(mgr)
        agent = mgr.create_agent(_config())
        sup.register(agent.id)
        sup.unregister(agent.id)
        assert len(sup.list_supervised()) == 0


# === A2A Delegation Tests (M18) ===


class TestA2ADelegation:
    """Tests for CapabilityValidator.validate_a2a_delegation."""

    def test_safe_delegation_both_no_untrusted(self):
        """Delegation where receiver is subset of sender should pass."""
        sender = _make_cap(write=True, secrets=True)
        receiver = _make_cap(secrets=True)
        # Should not raise — receiver is within sender's envelope
        CapabilityValidator.validate_a2a_delegation(
            sender, receiver, receiver_name="safe-peer"
        )

    def test_safe_delegation_minimal_caps(self):
        """Delegation between agents with no dangerous capabilities."""
        sender = _make_cap()
        receiver = _make_cap()
        CapabilityValidator.validate_a2a_delegation(
            sender, receiver, receiver_name="minimal-peer"
        )

    def test_delegation_rejected_receiver_forbidden_pair(self):
        """Receiver with untrusted + secrets violates Rule-of-Two+."""
        sender = _make_cap()
        receiver = _make_cap(untrusted=True, secrets=True)
        with pytest.raises(PolicyViolationError, match="Forbidden pair"):
            CapabilityValidator.validate_a2a_delegation(
                sender, receiver, receiver_name="bad-peer"
            )

    def test_delegation_rejected_receiver_all_three(self):
        """Receiver with all three flags violates Rule-of-Two+."""
        receiver = _make_cap(untrusted=True, secrets=True, write=True)
        sender = _make_cap()
        with pytest.raises(PolicyViolationError, match="Rule-of-Two"):
            CapabilityValidator.validate_a2a_delegation(
                sender, receiver, receiver_name="triple-peer"
            )

    def test_delegation_allowed_untrusted_write_no_secrets(self):
        """Untrusted + write (no secrets) is allowed by Rule-of-Two+."""
        sender = _make_cap(untrusted=True, write=True)
        receiver = _make_cap(untrusted=True, write=True)
        CapabilityValidator.validate_a2a_delegation(
            sender, receiver, receiver_name="rw-peer"
        )

    def test_delegation_allowed_secrets_write_no_untrusted(self):
        """Secrets + write (no untrusted) is allowed by Rule-of-Two+."""
        sender = _make_cap(secrets=True, write=True)
        receiver = _make_cap(secrets=True, write=True)
        CapabilityValidator.validate_a2a_delegation(
            sender, receiver, receiver_name="sw-peer"
        )
