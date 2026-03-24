"""Tests for sandbox isolation layer (FR-06)."""

from pathlib import Path

import pytest

from pylon.errors import SandboxError
from pylon.sandbox.firecracker_backend import (
    ExecutionResult as BackendExecutionResult,
)
from pylon.sandbox.firecracker_backend import SandboxBackendType, SandboxSession
from pylon.sandbox.executor import SandboxExecutor
from pylon.sandbox.manager import (
    ProductionSandboxManager,
    SandboxConfig,
    SandboxManager,
    SandboxStatus,
)
from pylon.sandbox.policy import (
    DEFAULT_POLICIES,
    NetworkPolicy,
    ResourceLimits,
    ResourceUsage,
    SandboxPolicy,
)
from pylon.sandbox.registry import SandboxRegistry
from pylon.types import SandboxTier


class _FakeRuntimeBackend:
    def __init__(self, *, backend_type: SandboxBackendType = SandboxBackendType.LOCAL) -> None:
        self.backend_type = backend_type
        self.create_calls: list[dict[str, object]] = []
        self.command_calls: list[dict[str, object]] = []
        self.destroy_calls: list[str] = []
        self._session_counter = 0
        self.next_result = BackendExecutionResult(stdout="ok\n", duration_ms=10.0)

    async def create(
        self,
        template: str = "python",
        *,
        timeout: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxSession:
        self._session_counter += 1
        session_id = f"{self.backend_type.value}-{self._session_counter}"
        workspace_dir = Path("/tmp") / session_id
        self.create_calls.append(
            {
                "template": template,
                "timeout": timeout,
                "env_vars": dict(env_vars or {}),
            }
        )
        return SandboxSession(
            id=session_id,
            backend=self.backend_type,
            template=template,
            timeout=timeout,
            metadata={
                "workspace_dir": str(workspace_dir),
                "env_vars": dict(env_vars or {}),
            },
        )

    async def execute(self, session: SandboxSession, code: str, *, language: str = "python", timeout: int = 30) -> BackendExecutionResult:
        return self.next_result

    async def execute_command(
        self,
        session: SandboxSession,
        command: str,
        *,
        cwd: str = "/workspace",
        timeout: int = 30,
        env_vars: dict[str, str] | None = None,
    ) -> BackendExecutionResult:
        self.command_calls.append(
            {
                "session_id": session.id,
                "command": command,
                "cwd": cwd,
                "timeout": timeout,
                "env_vars": dict(env_vars or {}),
            }
        )
        return self.next_result

    async def write_file(self, session: SandboxSession, path: str, content: str | bytes) -> None:
        return None

    async def read_file(self, session: SandboxSession, path: str) -> str:
        return ""

    async def destroy(self, session: SandboxSession) -> None:
        self.destroy_calls.append(session.id)


class _FakeRuntimeRouter:
    def __init__(self, backend: _FakeRuntimeBackend) -> None:
        self.backend = backend
        self.backend_requests: list[SandboxBackendType] = []

    def get_backend(self, backend_type: SandboxBackendType) -> _FakeRuntimeBackend:
        self.backend_requests.append(backend_type)
        return self.backend

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


class TestProductionSandboxManager:
    def test_create_persists_runtime_metadata_and_routes_to_backend(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        router = _FakeRuntimeRouter(backend)
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=router,
        )

        sandbox = mgr.create(
            SandboxConfig(
                tier=SandboxTier.NONE,
                timeout=45,
                template="python",
                provider="local",
                env_vars={"APP_ENV": "test"},
            )
        )

        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.runtime_backend == SandboxBackendType.LOCAL.value
        assert sandbox.runtime_session_id == sandbox.id
        assert router.backend_requests == [SandboxBackendType.LOCAL]
        assert backend.create_calls[0]["timeout"] == 45
        assert backend.create_calls[0]["env_vars"]["APP_ENV"] == "test"
        assert "PYLON_RUNNER_TIMEOUT_SECONDS" in backend.create_calls[0]["env_vars"]
        assert (tmp_path / "sandboxes.json").exists()

    def test_stop_releases_runtime_resources(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))

        stopped = mgr.stop(sandbox.id)

        assert stopped.status == SandboxStatus.STOPPED
        assert backend.destroy_calls == [sandbox.id]
        assert mgr.resolve_backend_session(sandbox.id) is None

    def test_destroy_releases_runtime_resources(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))

        assert mgr.destroy(sandbox.id) is True

        assert backend.destroy_calls == [sandbox.id]
        assert mgr.get(sandbox.id) is None

    def test_reload_marks_running_sandbox_as_stopped(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        state_path = tmp_path / "sandboxes.json"
        mgr = ProductionSandboxManager(
            state_path=state_path,
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))

        reloaded = ProductionSandboxManager(
            state_path=state_path,
            runtime_router=_FakeRuntimeRouter(_FakeRuntimeBackend()),
        )
        restored = reloaded.get(sandbox.id)

        assert restored is not None
        assert restored.status == SandboxStatus.STOPPED
        assert restored.runtime_metadata["recovered_after_restart"] is True

    def test_reap_expired_destroys_old_sandboxes(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(
            SandboxConfig(
                tier=SandboxTier.NONE,
                provider="local",
                timeout=1,
            )
        )
        sandbox.created_at -= 10

        expired = mgr.reap_expired()

        assert expired == [sandbox.id]
        assert backend.destroy_calls == [sandbox.id]


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

    def test_execute_delegates_to_runtime_backend(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        backend.next_result = BackendExecutionResult(
            stdout="hello\n",
            stderr="",
            exit_code=0,
            duration_ms=14.0,
        )
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))
        executor = SandboxExecutor(mgr)

        result = executor.execute(sandbox.id, "echo hello")

        assert result.stdout == "hello\n"
        assert result.exit_code == 0
        assert backend.command_calls[0]["command"] == "echo hello"
        assert backend.command_calls[0]["timeout"] == sandbox.config.timeout
        assert mgr.get(sandbox.id).resource_usage.cpu_ms >= 14

    def test_execute_runtime_timeout_raises(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        backend.next_result = BackendExecutionResult(
            stdout="",
            stderr="",
            exit_code=124,
            duration_ms=1000.0,
            timed_out=True,
        )
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))
        executor = SandboxExecutor(mgr)

        with pytest.raises(SandboxError, match="timed out"):
            executor.execute(sandbox.id, "sleep 999")

    def test_execute_runtime_backend_error_raises(self, tmp_path: Path):
        backend = _FakeRuntimeBackend()
        backend.next_result = BackendExecutionResult(
            stdout="",
            stderr="backend failed",
            exit_code=1,
            duration_ms=5.0,
            error="backend failed",
        )
        mgr = ProductionSandboxManager(
            state_path=tmp_path / "sandboxes.json",
            runtime_router=_FakeRuntimeRouter(backend),
        )
        sandbox = mgr.create(SandboxConfig(tier=SandboxTier.NONE, provider="local"))
        executor = SandboxExecutor(mgr)

        with pytest.raises(SandboxError, match="Sandbox backend failed"):
            executor.execute(sandbox.id, "echo hello")


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
