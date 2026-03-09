"""Event type definitions for Pylon event bus."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# Event type constants
AGENT_CREATED = "agent.created"
AGENT_STARTED = "agent.started"
AGENT_STOPPED = "agent.stopped"
AGENT_FAILED = "agent.failed"
WORKFLOW_STARTED = "workflow.started"
WORKFLOW_COMPLETED = "workflow.completed"
WORKFLOW_FAILED = "workflow.failed"
TASK_ASSIGNED = "task.assigned"
TASK_COMPLETED = "task.completed"
KILL_SWITCH_ACTIVATED = "kill_switch.activated"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_GRANTED = "approval.granted"
PROVIDER_HEALTH_CHANGED = "provider.health_changed"
PROVIDER_FALLBACK_TRIGGERED = "provider.fallback_triggered"
BUDGET_THRESHOLD_REACHED = "budget.threshold_reached"


@dataclass
class Event:
    """Core event payload for the event bus."""

    type: str
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            type=d["type"],
            source=d.get("source", ""),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", time.time()),
            correlation_id=d.get("correlation_id"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class EventFilter:
    """Filter for matching events by type, source, or correlation."""

    event_types: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    correlation_id: str | None = None

    def matches(self, event: Event) -> bool:
        if self.event_types and event.type not in self.event_types:
            return False
        if self.sources and event.source not in self.sources:
            return False
        if self.correlation_id is not None and event.correlation_id != self.correlation_id:
            return False
        return True
