"""A2A protocol type definitions (FR-09) - RC v1.0."""

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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Artifact:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            parts=[Part.from_dict(p) for p in data.get("parts", [])],
            metadata=data.get("metadata", {}),
        )


@dataclass
class PushNotificationConfig:
    """Configuration for push notifications on task state changes."""

    url: str = ""
    token: str = ""
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "token": self.token,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PushNotificationConfig:
        return cls(
            url=data.get("url", ""),
            token=data.get("token", ""),
            events=data.get("events", []),
        )


@dataclass
class TaskEvent:
    """Server-sent event for streaming task updates."""

    type: str  # "status", "artifact", "message", "error"
    task_id: str = ""
    state: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "task_id": self.task_id,
            "state": self.state,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class A2ATask:
    """A2A task representing work delegated between agents."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: TaskState = TaskState.SUBMITTED
    messages: list[A2AMessage] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    push_notification: PushNotificationConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def transition_to(self, new_state: TaskState) -> None:
        if not self.state.can_transition_to(new_state):
            raise ValueError(
                f"Invalid transition: {self.state.value} -> {new_state.value}"
            )
        self.state = new_state
        self.updated_at = time.time()

    def add_message(self, message: A2AMessage) -> None:
        self.messages.append(message)
        self.updated_at = time.time()

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "state": self.state.value,
            "messages": [m.to_dict() for m in self.messages],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.push_notification:
            d["push_notification"] = self.push_notification.to_dict()
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict) -> A2ATask:
        pn = data.get("push_notification")
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            state=TaskState(data.get("state", "submitted")),
            messages=[A2AMessage.from_dict(m) for m in data.get("messages", [])],
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts", [])],
            push_notification=PushNotificationConfig.from_dict(pn) if pn else None,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


class AuthMethod(enum.Enum):
    """Authentication methods for agent cards."""

    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


@dataclass
class AgentSkill:
    """A skill offered by an agent."""

    name: str = ""
    description: str = ""
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_modes": self.input_modes,
            "output_modes": self.output_modes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentSkill:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_modes=data.get("input_modes", []),
            output_modes=data.get("output_modes", []),
        )


@dataclass
class AgentCapabilities:
    """Capabilities advertised in an agent card."""

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False

    def to_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "push_notifications": self.push_notifications,
            "state_transition_history": self.state_transition_history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentCapabilities:
        return cls(
            streaming=data.get("streaming", False),
            push_notifications=data.get("push_notifications", False),
            state_transition_history=data.get("state_transition_history", False),
        )


@dataclass
class AgentCard:
    """Agent card for A2A discovery (/.well-known/agent-card.json)."""

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    url: str = ""
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    authentication: AuthMethod = AuthMethod.NONE
    provider: str = ""
    documentation_url: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "url": self.url,
            "capabilities": self.capabilities.to_dict(),
            "skills": [s.to_dict() for s in self.skills],
            "authentication": self.authentication.value,
        }
        if self.provider:
            d["provider"] = self.provider
        if self.documentation_url:
            d["documentation_url"] = self.documentation_url
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AgentCard:
        caps = data.get("capabilities", {})
        if isinstance(caps, dict):
            capabilities = AgentCapabilities.from_dict(caps)
        else:
            capabilities = AgentCapabilities()

        skills_data = data.get("skills", [])
        skills: list[AgentSkill] = []
        for s in skills_data:
            if isinstance(s, dict):
                skills.append(AgentSkill.from_dict(s))
            elif isinstance(s, str):
                skills.append(AgentSkill(name=s))

        auth = data.get("authentication", "none")
        if isinstance(auth, str):
            try:
                authentication = AuthMethod(auth)
            except ValueError:
                authentication = AuthMethod.NONE
        else:
            authentication = AuthMethod.NONE

        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            url=data.get("url", ""),
            capabilities=capabilities,
            skills=skills,
            authentication=authentication,
            provider=data.get("provider", ""),
            documentation_url=data.get("documentation_url", ""),
        )

    def validate(self) -> list[str]:
        """Validate the agent card, returning a list of error messages."""
        errors: list[str] = []
        if not self.name:
            errors.append("Agent card must have a name")
        if not self.url:
            errors.append("Agent card must have a url")
        if not self.version:
            errors.append("Agent card must have a version")
        return errors
