"""Runtime safety context models."""

from __future__ import annotations

from dataclasses import dataclass, field

from pylon.types import AgentCapability, TrustLevel


@dataclass(frozen=True)
class SafetyContext:
    """Execution-scoped safety context used for delegation and tool decisions."""

    agent_name: str
    run_id: str = ""
    held_capability: AgentCapability = field(default_factory=AgentCapability)
    data_taint: TrustLevel = TrustLevel.TRUSTED
    effect_scopes: frozenset[str] = field(default_factory=frozenset)
    secret_scopes: frozenset[str] = field(default_factory=frozenset)
    call_chain: tuple[str, ...] = field(default_factory=tuple)
    approval_token: str | None = None
