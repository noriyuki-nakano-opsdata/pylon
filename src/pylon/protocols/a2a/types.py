"""A2A protocol type definitions (FR-09)."""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class TaskState(enum.Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    def can_transition_to(self, target: TaskState) -> bool:
        return target in _VALID_TRANSITIONS.get(self, set())


_VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.WORKING: {
        TaskState.INPUT_REQUIRED,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
    },
    TaskState.INPUT_REQUIRED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELED: set(),
}


@dataclass
class Part:
    """Content part within a message or artifact."""

    type: str  # "text", "data", "file"
    content: Any = None

    def to_dict(self) -> dict:
        return {"type": self.type, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict) -> Part:
        return cls(type=data["type"], content=data.get("content"))


@dataclass
class A2AMessage:
    """Message exchanged between agents."""

    role: str  # "user", "agent"
    parts: list[Part] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> A2AMessage:
        return cls(
            role=data["role"],
            parts=[Part.from_dict(p) for p in data.get("parts", [])],
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class Artifact:
    """Output artifact produced by a task."""

    name: str = ""
    description: str = ""
    parts: list[Part] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parts": [p.to_dict() for p in self.parts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Artifact:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            parts=[Part.from_dict(p) for p in data.get("parts", [])],
        )


@dataclass
class A2ATask:
    """A2A task representing work delegated between agents."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: TaskState = TaskState.SUBMITTED
    messages: list[A2AMessage] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def transition_to(self, new_state: TaskState) -> None:
        if not self.state.can_transition_to(new_state):
            raise ValueError(
                f"Invalid transition: {self.state.value} -> {new_state.value}"
            )
        self.state = new_state
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "state": self.state.value,
            "messages": [m.to_dict() for m in self.messages],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> A2ATask:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            state=TaskState(data.get("state", "submitted")),
            messages=[A2AMessage.from_dict(m) for m in data.get("messages", [])],
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts", [])],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class AgentCard:
    """Agent card for A2A discovery (/.well-known/agent-card.json)."""

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    url: str = ""
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    authentication: str = "none"  # "none", "bearer", "api_key"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "url": self.url,
            "capabilities": self.capabilities,
            "skills": self.skills,
            "authentication": self.authentication,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentCard:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            url=data.get("url", ""),
            capabilities=data.get("capabilities", []),
            skills=data.get("skills", []),
            authentication=data.get("authentication", "none"),
        )
