"""Tests for sandbox isolation layer (FR-06)."""

import pytest

from pylon.errors import SandboxError
from pylon.types import SandboxTier
from pylon.sandbox.manager import Sandbox, SandboxConfig, SandboxManager, SandboxStatus
from pylon.sandbox.executor import ExecutionResult, SandboxExecutor
from pylon.sandbox.policy import (
    DEFAULT_POLICIES,
    NetworkPolicy,
    ResourceLimits,
    ResourceUsage,
    SandboxPolicy,
)
from pylon.sandbox.registry import SandboxRegistry


# ---------------------------------------------------------------------------
# SandboxManager CRUD
# ---------------------------------------------------------------------------

class TestSandboxManager:
    def test_create_returns_running_sandbox(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        assert sb.status == SandboxStatus.RUNNING
        assert sb.tier == SandboxTier.GVISOR
        assert len(sb.id) == 12

    def test_create_with_docker_tier(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig(tier=SandboxTier.DOCKER))
        assert sb.tier == SandboxTier.DOCKER

    def test_get_existing(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        assert mgr.get(sb.id) is sb

    def test_get_nonexistent(self):
        mgr = SandboxManager()
        assert mgr.get("nonexistent") is None

    def test_list_all(self):
        mgr = SandboxManager()
        mgr.create(SandboxConfig())
        mgr.create(SandboxConfig())
        assert len(mgr.list()) == 2

    def test_list_by_status(self):
        mgr = SandboxManager()
        sb1 = mgr.create(SandboxConfig())
        mgr.create(SandboxConfig())
        mgr.stop(sb1.id)
        assert len(mgr.list(SandboxStatus.RUNNING)) == 1
        assert len(mgr.list(SandboxStatus.STOPPED)) == 1

    def test_stop_running_sandbox(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        stopped = mgr.stop(sb.id)
        assert stopped.status == SandboxStatus.STOPPED

    def test_stop_nonexistent_raises(self):
        mgr = SandboxManager()
        with pytest.raises(SandboxError, match="not found"):
            mgr.stop("bad-id")

    def test_stop_already_stopped_raises(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        mgr.stop(sb.id)
        with pytest.raises(SandboxError, match="Cannot stop"):
            mgr.stop(sb.id)

    def test_destroy_returns_true(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        assert mgr.destroy(sb.id) is True
        assert mgr.get(sb.id) is None

    def test_destroy_nonexistent_returns_false(self):
        mgr = SandboxManager()
        assert mgr.destroy("nope") is False

    def test_create_with_custom_limits(self):
        mgr = SandboxManager()
        limits = ResourceLimits(max_cpu_ms=5000)
        sb = mgr.create(SandboxConfig(resource_limits=limits))
        assert sb.policy.resource_limits.max_cpu_ms == 5000

    def test_create_with_agent_id(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig(agent_id="agent-1"))
        assert sb.agent_id == "agent-1"


# ---------------------------------------------------------------------------
# SandboxPolicy — tier defaults and validation
# ---------------------------------------------------------------------------

class TestSandboxPolicy:
    def test_default_policies_exist_for_all_tiers(self):
        for tier in SandboxTier:
            assert tier in DEFAULT_POLICIES

    def test_for_tier_creates_correct_limits(self):
        policy = SandboxPolicy.for_tier(SandboxTier.DOCKER)
        assert policy.resource_limits.max_memory_bytes == 268_435_456

    def test_firecracker_allows_internet(self):
        policy = SandboxPolicy.for_tier(SandboxTier.FIRECRACKER)
        assert policy.network_policy.allow_internet is True

    def test_gvisor_denies_internet(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        assert policy.network_policy.allow_internet is False

    def test_validate_execution_allows_normal_command(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        allowed, reason = policy.validate_execution("ls -la")
        assert allowed is True
        assert reason == ""

    def test_validate_execution_blocks_dangerous_command(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        allowed, reason = policy.validate_execution("rm -rf /")
        assert allowed is False
        assert "rm -rf /" in reason

    def test_check_resources_within_limits(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        usage = ResourceUsage(cpu_ms=100, memory_bytes=1024)
        ok, reason = policy.check_resources(usage)
        assert ok is True

    def test_check_resources_cpu_exceeded(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        usage = ResourceUsage(cpu_ms=999_999)
        ok, reason = policy.check_resources(usage)
        assert ok is False
        assert "CPU" in reason

    def test_check_resources_memory_exceeded(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        usage = ResourceUsage(memory_bytes=999_999_999_999)
        ok, reason = policy.check_resources(usage)
        assert ok is False
        assert "Memory" in reason

    def test_check_resources_network_exceeded(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        usage = ResourceUsage(network_bytes_in=999_999_999)
        ok, reason = policy.check_resources(usage)
        assert ok is False
        assert "Network" in reason

    def test_check_host_allowed_with_internet(self):
        policy = SandboxPolicy.for_tier(SandboxTier.FIRECRACKER)
        assert policy.check_host("example.com") is True

    def test_check_host_denied_without_internet(self):
        policy = SandboxPolicy(network_policy=NetworkPolicy(allow_internet=False))
        assert policy.check_host("example.com") is False

    def test_check_host_in_allowlist(self):
        policy = SandboxPolicy(
            network_policy=NetworkPolicy(allowed_hosts=["api.safe.com"], allow_internet=False)
        )
        assert policy.check_host("api.safe.com") is True
        assert policy.check_host("evil.com") is False

    def test_check_port_blocked(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        assert policy.check_port(22) is False  # SSH blocked

    def test_check_port_allowed(self):
        policy = SandboxPolicy.for_tier(SandboxTier.GVISOR)
        assert policy.check_port(443) is True


# ---------------------------------------------------------------------------
# SandboxExecutor
# ---------------------------------------------------------------------------

class TestSandboxExecutor:
    def _running_sandbox(self) -> tuple[SandboxManager, str]:
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        return mgr, sb.id

    def test_execute_returns_result(self):
        mgr, sid = self._running_sandbox()
        executor = SandboxExecutor(mgr)
        result = executor.execute(sid, "echo hello", simulated_stdout="hello\n")
        assert result.stdout == "hello\n"
        assert result.exit_code == 0
        assert isinstance(result.duration_ms, int)

    def test_execute_nonexistent_sandbox_raises(self):
        mgr = SandboxManager()
        executor = SandboxExecutor(mgr)
        with pytest.raises(SandboxError, match="not found"):
            executor.execute("bad", "ls")

    def test_execute_stopped_sandbox_raises(self):
        mgr, sid = self._running_sandbox()
        mgr.stop(sid)
        executor = SandboxExecutor(mgr)
        with pytest.raises(SandboxError, match="not running"):
            executor.execute(sid, "ls")

    def test_execute_blocked_command_raises(self):
        mgr, sid = self._running_sandbox()
        executor = SandboxExecutor(mgr)
        with pytest.raises(SandboxError, match="blocked by policy"):
            executor.execute(sid, "rm -rf /")

    def test_execute_resource_limit_exceeded_raises(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig(
            resource_limits=ResourceLimits(max_cpu_ms=5),
        ))
        executor = SandboxExecutor(mgr)
        with pytest.raises(SandboxError, match="Resource limit"):
            executor.execute(sb.id, "heavy", simulated_cpu_ms=100)

    def test_execute_timeout_raises(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig(timeout=1))
        executor = SandboxExecutor(mgr)
        with pytest.raises(SandboxError, match="timed out"):
            executor.execute(sb.id, "sleep 999", simulated_cpu_ms=2000)

    def test_execute_accumulates_resource_usage(self):
        mgr, sid = self._running_sandbox()
        executor = SandboxExecutor(mgr)
        executor.execute(sid, "cmd1", simulated_cpu_ms=10)
        executor.execute(sid, "cmd2", simulated_cpu_ms=20)
        sb = mgr.get(sid)
        assert sb.resource_usage.cpu_ms == 30


# ---------------------------------------------------------------------------
# SandboxRegistry
# ---------------------------------------------------------------------------

class TestSandboxRegistry:
    def test_register_and_get(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        reg = SandboxRegistry()
        reg.register(sb)
        assert reg.get(sb.id) is sb

    def test_unregister(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig())
        reg = SandboxRegistry()
        reg.register(sb)
        assert reg.unregister(sb.id) is True
        assert reg.get(sb.id) is None

    def test_unregister_nonexistent(self):
        reg = SandboxRegistry()
        assert reg.unregister("nope") is False

    def test_get_by_agent(self):
        mgr = SandboxManager()
        sb1 = mgr.create(SandboxConfig(agent_id="a1"))
        sb2 = mgr.create(SandboxConfig(agent_id="a1"))
        sb3 = mgr.create(SandboxConfig(agent_id="a2"))
        reg = SandboxRegistry()
        reg.register(sb1)
        reg.register(sb2)
        reg.register(sb3)
        agent1_sbs = reg.get_by_agent("a1")
        assert len(agent1_sbs) == 2
        assert reg.get_by_agent("a2") == [sb3]
        assert reg.get_by_agent("a3") == []

    def test_count_by_tier(self):
        mgr = SandboxManager()
        sb1 = mgr.create(SandboxConfig(tier=SandboxTier.GVISOR))
        sb2 = mgr.create(SandboxConfig(tier=SandboxTier.GVISOR))
        sb3 = mgr.create(SandboxConfig(tier=SandboxTier.DOCKER))
        reg = SandboxRegistry()
        reg.register(sb1)
        reg.register(sb2)
        reg.register(sb3)
        counts = reg.count_by_tier()
        assert counts[SandboxTier.GVISOR] == 2
        assert counts[SandboxTier.DOCKER] == 1

    def test_count(self):
        mgr = SandboxManager()
        reg = SandboxRegistry()
        reg.register(mgr.create(SandboxConfig()))
        reg.register(mgr.create(SandboxConfig()))
        assert reg.count() == 2

    def test_list_all(self):
        mgr = SandboxManager()
        reg = SandboxRegistry()
        sb = mgr.create(SandboxConfig())
        reg.register(sb)
        assert reg.list_all() == [sb]

    def test_unregister_cleans_agent_index(self):
        mgr = SandboxManager()
        sb = mgr.create(SandboxConfig(agent_id="a1"))
        reg = SandboxRegistry()
        reg.register(sb)
        reg.unregister(sb.id)
        assert reg.get_by_agent("a1") == []
