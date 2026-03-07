"""Agent card generation and registry (FR-09) - RC v1.0.

Agent cards are served at /.well-known/agent-card.json for A2A discovery.
"""

from __future__ import annotations

from pylon.protocols.a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    AuthMethod,
)


def generate_card(
    name: str,
    url: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    capabilities: AgentCapabilities | None = None,
    skills: list[AgentSkill] | None = None,
    authentication: AuthMethod = AuthMethod.NONE,
    provider: str = "",
    documentation_url: str = "",
) -> AgentCard:
    """Generate an AgentCard from agent configuration."""
    return AgentCard(
        name=name,
        version=version,
        description=description,
        url=url,
        capabilities=capabilities or AgentCapabilities(),
        skills=skills or [],
        authentication=authentication,
        provider=provider,
        documentation_url=documentation_url,
    )


class AgentCardRegistry:
    """Registry of known A2A peers (allowlist).

    Only pre-registered peers are accepted for task delegation.
    """

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """Register a peer agent card. Validates the card first."""
        errors = card.validate()
        if errors:
            raise ValueError(f"Invalid agent card: {'; '.join(errors)}")
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

    def find_by_skill(self, skill_name: str) -> list[AgentCard]:
        """Find agents that offer a specific skill."""
        results: list[AgentCard] = []
        for card in self._cards.values():
            for skill in card.skills:
                if skill.name == skill_name:
                    results.append(card)
                    break
        return results

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        """Find agents with a specific capability enabled."""
        results: list[AgentCard] = []
        for card in self._cards.values():
            caps_dict = card.capabilities.to_dict()
            if caps_dict.get(capability):
                results.append(card)
        return results
