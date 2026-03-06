"""Agent card generation and registry (FR-09).

Agent cards are served at /.well-known/agent-card.json for A2A discovery.
"""

from __future__ import annotations

from pylon.protocols.a2a.types import AgentCard


def generate_card(
    name: str,
    url: str,
    *,
    version: str = "0.1.0",
    description: str = "",
    capabilities: list[str] | None = None,
    skills: list[str] | None = None,
    authentication: str = "none",
) -> AgentCard:
    """Generate an AgentCard from agent configuration."""
    return AgentCard(
        name=name,
        version=version,
        description=description,
        url=url,
        capabilities=capabilities or [],
        skills=skills or [],
        authentication=authentication,
    )


class AgentCardRegistry:
    """Registry of known A2A peers (allowlist).

    Only pre-registered peers are accepted for task delegation.
    """

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """Register a peer agent card."""
        if not card.name:
            raise ValueError("Agent card must have a name")
        self._cards[card.name] = card

    def unregister(self, name: str) -> None:
        """Remove a peer from the registry."""
        self._cards.pop(name, None)

    def get(self, name: str) -> AgentCard | None:
        """Look up a registered peer by name."""
        return self._cards.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if a peer is registered."""
        return name in self._cards

    def list_peers(self) -> list[AgentCard]:
        """List all registered peer cards."""
        return list(self._cards.values())
