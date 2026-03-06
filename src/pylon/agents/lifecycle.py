"""Agent lifecycle management (FR-02)."""

from __future__ import annotations

from pylon.agents.registry import AgentRegistry
from pylon.agents.runtime import Agent
from pylon.errors import AgentLifecycleError, PylonError
from pylon.types import AgentConfig, AgentState


class AgentNotFoundError(PylonError):
    """Raised when an agent is not found."""

    code = "AGENT_NOT_FOUND"
    status_code = 404


class AgentLifecycleManager:
    """Creates and manages agent lifecycles."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or AgentRegistry()

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    def create_agent(self, config: AgentConfig) -> Agent:
        """Create a new agent, validate capabilities, and register it.

        The agent is created in INIT state, then transitioned to READY.
        """
        config.capability.validate()
        agent = Agent(config=config, capability=config.capability)
        agent.initialize()
        self._registry.register(agent)
        return agent

    def start_agent(self, agent_id: str) -> Agent:
        """Transition agent from READY to RUNNING."""
        agent = self._get_agent(agent_id)
        agent.start()
        return agent

    def pause_agent(self, agent_id: str) -> Agent:
        """Transition agent from RUNNING to PAUSED."""
        agent = self._get_agent(agent_id)
        agent.pause()
        return agent

    def resume_agent(self, agent_id: str) -> Agent:
        """Transition agent from PAUSED to RUNNING."""
        agent = self._get_agent(agent_id)
        agent.resume()
        return agent

    def stop_agent(self, agent_id: str) -> Agent:
        """Transition agent to COMPLETED."""
        agent = self._get_agent(agent_id)
        agent.complete()
        return agent

    def kill_agent(self, agent_id: str) -> Agent:
        """Immediately kill an agent."""
        agent = self._get_agent(agent_id)
        agent.kill()
        return agent

    def get_agent(self, agent_id: str) -> Agent | None:
        return self._registry.get(agent_id)

    def _get_agent(self, agent_id: str) -> Agent:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(
                f"Agent '{agent_id}' not found",
                details={"agent_id": agent_id},
            )
        return agent
