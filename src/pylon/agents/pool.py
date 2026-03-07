"""Agent pool management with auto-scaling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pylon.agents.lifecycle import AgentLifecycleManager
from pylon.agents.runtime import Agent
from pylon.errors import PylonError
from pylon.types import AgentConfig


class PoolExhaustedError(PylonError):
    """Raised when the pool has reached max capacity."""

    code = "POOL_EXHAUSTED"
    status_code = 429


@dataclass
class AgentPoolConfig:
    """Pool configuration."""

    min_size: int = 0
    max_size: int = 10
    idle_timeout_seconds: float = 300.0


@dataclass
class PoolStats:
    """Pool statistics."""

    active_count: int = 0
    idle_count: int = 0
    total_created: int = 0
    total_destroyed: int = 0


class AgentPool:
    """Agent pool with acquire/release and auto-scaling."""

    def __init__(
        self,
        lifecycle: AgentLifecycleManager,
        config: AgentPoolConfig | None = None,
        agent_factory: Callable[[str], AgentConfig] | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._config = config or AgentPoolConfig()
        self._agent_factory = agent_factory or self._default_agent_factory
        self._idle: dict[str, Agent] = {}  # agent_id -> Agent (READY state)
        self._active: dict[str, Agent] = {}  # agent_id -> Agent (RUNNING state)
        self._stats = PoolStats()

    @property
    def stats(self) -> PoolStats:
        self._stats.active_count = len(self._active)
        self._stats.idle_count = len(self._idle)
        return self._stats

    def acquire(self, role: str = "worker") -> Agent:
        """Acquire an agent from the pool. Creates one if none available."""
        # Try to find an idle agent with matching role
        for agent_id, agent in list(self._idle.items()):
            if agent.config.role == role:
                del self._idle[agent_id]
                self._lifecycle.start_agent(agent.id)
                self._active[agent.id] = agent
                return agent

        # No idle agent found - create a new one if within limits
        total = len(self._active) + len(self._idle)
        if total >= self._config.max_size:
            raise PoolExhaustedError(
                f"Pool exhausted: {total}/{self._config.max_size} agents",
                details={"active": len(self._active), "idle": len(self._idle)},
            )

        agent_config = self._agent_factory(role)
        agent = self._lifecycle.create_agent(agent_config)
        self._lifecycle.start_agent(agent.id)
        self._active[agent.id] = agent
        self._stats.total_created += 1
        return agent

    def release(self, agent_id: str) -> None:
        """Return an agent to the pool (stop it and make it idle)."""
        agent = self._active.pop(agent_id, None)
        if agent is None:
            return

        # Stop the agent and recreate as idle (READY state)
        self._lifecycle.stop_agent(agent_id)
        self._lifecycle.registry.unregister(agent_id)

        # Create a fresh agent in READY state for reuse
        new_agent = self._lifecycle.create_agent(agent.config)
        self._idle[new_agent.id] = new_agent
        self._stats.total_destroyed += 1
        self._stats.total_created += 1

    def destroy(self, agent_id: str) -> None:
        """Permanently remove an agent from the pool."""
        agent = self._active.pop(agent_id, None) or self._idle.pop(agent_id, None)
        if agent is None:
            return
        if not agent.is_terminal:
            self._lifecycle.kill_agent(agent_id)
        self._lifecycle.registry.unregister(agent_id)
        self._stats.total_destroyed += 1

    def fill_to_min(self, role: str = "worker") -> int:
        """Ensure pool has at least min_size idle agents. Returns number created."""
        current_idle = len(self._idle)
        needed = self._config.min_size - current_idle
        created = 0
        for _ in range(max(0, needed)):
            total = len(self._active) + len(self._idle)
            if total >= self._config.max_size:
                break
            agent_config = self._agent_factory(role)
            agent = self._lifecycle.create_agent(agent_config)
            self._idle[agent.id] = agent
            self._stats.total_created += 1
            created += 1
        return created

    @staticmethod
    def _default_agent_factory(role: str) -> AgentConfig:
        return AgentConfig(name=f"pool-{role}", role=role)
