"""Agent registration and discovery."""

from __future__ import annotations

from pylon.agents.runtime import Agent
from pylon.errors import PylonError
from pylon.types import AgentState


class AgentRegistryError(PylonError):
    """Error raised by the agent registry."""

    code = "AGENT_REGISTRY_ERROR"
    status_code = 400


class AgentRegistry:
    """In-memory agent registry with search capabilities."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if agent.id in self._agents:
            raise AgentRegistryError(
                f"Agent '{agent.id}' is already registered",
                details={"agent_id": agent.id},
            )
        self._agents[agent.id] = agent

    def unregister(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            raise AgentRegistryError(
                f"Agent '{agent_id}' not found",
                details={"agent_id": agent_id},
            )
        del self._agents[agent_id]

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def find_by_role(self, role: str) -> list[Agent]:
        return [a for a in self._agents.values() if a.config.role == role]

    def find_by_status(self, status: AgentState) -> list[Agent]:
        return [a for a in self._agents.values() if a.state == status]

    def count(self) -> int:
        return len(self._agents)

    def all(self) -> list[Agent]:
        return list(self._agents.values())
