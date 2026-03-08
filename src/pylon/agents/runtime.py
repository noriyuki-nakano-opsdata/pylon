"""Agent runtime with lifecycle state machine (FR-02).

Lifecycle: INIT -> READY -> RUNNING -> PAUSED -> COMPLETED | FAILED | KILLED
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pylon.errors import AgentLifecycleError
from pylon.types import AgentCapability, AgentConfig, AgentState, AutonomyLevel


@dataclass(frozen=True)
class HandoffData:
    """Context preserved across agent restarts."""

    agent_id: str
    config_name: str
    working_memory: dict[str, Any]
    state_before_kill: str
    restart_count: int
    note: str = ""


@dataclass
class Agent:
    """Agent instance with lifecycle management."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    config: AgentConfig = field(default_factory=lambda: AgentConfig(name="unnamed"))
    state: AgentState = AgentState.INIT
    capability: AgentCapability = field(default_factory=AgentCapability)
    working_memory: dict[str, Any] = field(default_factory=dict)
    last_handoff: HandoffData | None = None

    def transition_to(self, target: AgentState) -> None:
        """Transition to target state, enforcing valid transitions."""
        if not self.state.can_transition_to(target):
            raise AgentLifecycleError(
                f"Invalid transition: {self.state.value} -> {target.value}",
                details={"agent_id": self.id, "agent_name": self.config.name},
            )
        if target in (AgentState.COMPLETED, AgentState.FAILED, AgentState.KILLED):
            self.last_handoff = self.generate_handoff()
        self.state = target
        if target in (AgentState.COMPLETED, AgentState.FAILED, AgentState.KILLED):
            self.working_memory.clear()

    def initialize(self) -> None:
        """Move from INIT to READY."""
        self.transition_to(AgentState.READY)

    def start(self) -> None:
        """Move from READY to RUNNING."""
        self.transition_to(AgentState.RUNNING)

    def pause(self) -> None:
        """Move from RUNNING to PAUSED."""
        self.transition_to(AgentState.PAUSED)

    def resume(self) -> None:
        """Move from PAUSED to RUNNING."""
        self.transition_to(AgentState.RUNNING)

    def complete(self) -> None:
        """Move to COMPLETED (terminal)."""
        self.transition_to(AgentState.COMPLETED)

    def fail(self) -> None:
        """Move to FAILED (terminal)."""
        self.transition_to(AgentState.FAILED)

    def kill(self) -> None:
        """Move to KILLED (terminal). Clears working memory."""
        self.transition_to(AgentState.KILLED)

    def generate_handoff(self, *, restart_count: int = 0, note: str = "") -> HandoffData:
        """Capture current context before a terminal transition."""
        return HandoffData(
            agent_id=self.id,
            config_name=self.config.name,
            working_memory=dict(self.working_memory),
            state_before_kill=self.state.value,
            restart_count=restart_count,
            note=note,
        )

    def restore_from_handoff(self, handoff: HandoffData) -> None:
        """Restore working memory from a prior handoff."""
        self.working_memory.update(handoff.working_memory)

    @property
    def is_terminal(self) -> bool:
        return self.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.KILLED)

    @property
    def autonomy(self) -> AutonomyLevel:
        return self.config.autonomy

    def requires_approval(self, require_above: AutonomyLevel) -> bool:
        return self.config.autonomy >= require_above
