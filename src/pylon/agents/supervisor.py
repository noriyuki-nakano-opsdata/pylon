"""Agent supervisor with health checking and auto-restart."""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass

from pylon.agents.lifecycle import AgentLifecycleManager
from pylon.agents.runtime import Agent
from pylon.errors import ExitCode, PylonError, resolve_exit_code
from pylon.types import AgentState


class HealthStatus(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RecoveryAction(enum.Enum):
    """Supervisor recovery decision."""

    RESTARTED = "restarted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class SupervisorConfig:
    """Supervisor configuration."""

    health_check_interval_seconds: float = 30.0
    max_restarts: int = 3
    restart_backoff_seconds: float = 5.0


@dataclass
class SupervisedAgent:
    """Tracking data for a supervised agent."""

    agent_id: str
    health_check_interval: float
    last_status: HealthStatus = HealthStatus.UNKNOWN
    restart_count: int = 0
    health_fn: Callable[[str], HealthStatus] | None = None


@dataclass(frozen=True)
class RecoveryResult:
    """Structured outcome for supervisor recovery attempts."""

    agent_id: str
    health_status: HealthStatus
    action: RecoveryAction
    exit_code: ExitCode
    reason: str
    restart_count: int = 0
    restarted_agent_id: str | None = None
    error_code: str | None = None
    agent: Agent | None = None

    @property
    def success(self) -> bool:
        return self.action is RecoveryAction.RESTARTED


class AgentSupervisor:
    """Monitors agent health and performs auto-restarts."""

    def __init__(
        self,
        lifecycle: AgentLifecycleManager,
        config: SupervisorConfig | None = None,
        on_health_change: Callable[[str, HealthStatus, HealthStatus], None] | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._config = config or SupervisorConfig()
        self._supervised: dict[str, SupervisedAgent] = {}
        self._on_health_change = on_health_change

    def register(
        self,
        agent_id: str,
        health_check_interval: float | None = None,
        health_fn: Callable[[str], HealthStatus] | None = None,
    ) -> None:
        """Register an agent for supervision."""
        interval = health_check_interval or self._config.health_check_interval_seconds
        self._supervised[agent_id] = SupervisedAgent(
            agent_id=agent_id,
            health_check_interval=interval,
            health_fn=health_fn,
        )

    def unregister(self, agent_id: str) -> None:
        self._supervised.pop(agent_id, None)

    def check_health(self, agent_id: str) -> HealthStatus:
        """Check health of a supervised agent."""
        supervised = self._supervised.get(agent_id)
        if supervised is None:
            return HealthStatus.UNKNOWN

        agent = self._lifecycle.get_agent(agent_id)
        if agent is None:
            new_status = HealthStatus.UNHEALTHY
        elif supervised.health_fn is not None:
            new_status = supervised.health_fn(agent_id)
        else:
            new_status = self._default_health_check(agent)

        old_status = supervised.last_status
        if old_status != new_status:
            supervised.last_status = new_status
            if self._on_health_change is not None:
                self._on_health_change(agent_id, old_status, new_status)

        return new_status

    def recover_unhealthy(self, agent_id: str) -> RecoveryResult:
        """Handle an unhealthy agent and return a structured recovery result."""
        supervised = self._supervised.get(agent_id)
        if supervised is None:
            return RecoveryResult(
                agent_id=agent_id,
                health_status=HealthStatus.UNKNOWN,
                action=RecoveryAction.SKIPPED,
                exit_code=ExitCode.AGENT_LIFECYCLE_ERROR,
                reason="agent is not registered with supervisor",
            )

        health_status = self.check_health(agent_id)
        if health_status is not HealthStatus.UNHEALTHY:
            return RecoveryResult(
                agent_id=agent_id,
                health_status=health_status,
                action=RecoveryAction.SKIPPED,
                exit_code=ExitCode.SUCCESS,
                reason=f"agent is not unhealthy ({health_status.value})",
                restart_count=supervised.restart_count,
            )

        if supervised.restart_count >= self._config.max_restarts:
            return RecoveryResult(
                agent_id=agent_id,
                health_status=health_status,
                action=RecoveryAction.SKIPPED,
                exit_code=ExitCode.AGENT_LIFECYCLE_ERROR,
                reason="restart limit exceeded",
                restart_count=supervised.restart_count,
            )

        agent = self._lifecycle.get_agent(agent_id)
        if agent is None:
            return RecoveryResult(
                agent_id=agent_id,
                health_status=health_status,
                action=RecoveryAction.FAILED,
                exit_code=ExitCode.AGENT_LIFECYCLE_ERROR,
                reason="agent not found in lifecycle manager",
            )

        # Save config before killing
        config = agent.config
        health_fn = supervised.health_fn
        interval = supervised.health_check_interval
        restart_count = supervised.restart_count + 1
        try:
            if agent.last_handoff is not None:
                handoff = agent.last_handoff
                handoff = type(handoff)(
                    agent_id=handoff.agent_id,
                    config_name=handoff.config_name,
                    working_memory=dict(handoff.working_memory),
                    state_before_kill=handoff.state_before_kill,
                    restart_count=restart_count,
                    note="auto-restart by supervisor",
                )
            else:
                handoff = agent.generate_handoff(
                    restart_count=restart_count,
                    note="auto-restart by supervisor",
                )

            # Kill and unregister old agent
            if not agent.is_terminal:
                self._lifecycle.kill_agent(agent_id)
            self._lifecycle.registry.unregister(agent_id)
            self.unregister(agent_id)

            # Create new agent
            new_agent = self._lifecycle.create_agent(config)
            new_agent.restore_from_handoff(handoff)
            self._lifecycle.start_agent(new_agent.id)

            # Re-register with supervisor
            self.register(new_agent.id, interval, health_fn)
            new_supervised = self._supervised[new_agent.id]
            new_supervised.restart_count = restart_count
            new_supervised.last_status = HealthStatus.HEALTHY
            return RecoveryResult(
                agent_id=agent_id,
                health_status=health_status,
                action=RecoveryAction.RESTARTED,
                exit_code=ExitCode.SUCCESS,
                reason="agent restarted successfully",
                restart_count=restart_count,
                restarted_agent_id=new_agent.id,
                agent=new_agent,
            )
        except PylonError as exc:
            return RecoveryResult(
                agent_id=agent_id,
                health_status=health_status,
                action=RecoveryAction.FAILED,
                exit_code=resolve_exit_code(exc),
                reason=exc.message,
                restart_count=supervised.restart_count,
                error_code=getattr(exc, "code", None),
            )

    def handle_unhealthy(self, agent_id: str) -> Agent | None:
        """Backward-compatible wrapper returning only the restarted agent."""
        return self.recover_unhealthy(agent_id).agent

    def get_supervised(self, agent_id: str) -> SupervisedAgent | None:
        return self._supervised.get(agent_id)

    def list_supervised(self) -> list[SupervisedAgent]:
        return list(self._supervised.values())

    @staticmethod
    def _default_health_check(agent: Agent) -> HealthStatus:
        if agent.state == AgentState.RUNNING:
            return HealthStatus.HEALTHY
        if agent.state == AgentState.PAUSED:
            return HealthStatus.DEGRADED
        if agent.is_terminal:
            return HealthStatus.UNHEALTHY
        # INIT, READY
        return HealthStatus.HEALTHY
