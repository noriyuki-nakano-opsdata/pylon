"""Plugin type definitions."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class PluginState(enum.Enum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class PluginCapability(enum.Enum):
    """Capabilities a plugin can provide."""

    TOOL_PROVIDER = "tool_provider"
    AGENT_EXTENSION = "agent_extension"
    WORKFLOW_STEP = "workflow_step"
    EVENT_LISTENER = "event_listener"
    MIDDLEWARE = "middleware"


@dataclass
class PluginInfo:
    """Metadata about a plugin."""

    name: str
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[PluginCapability] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "dependencies": self.dependencies,
            "capabilities": [c.value for c in self.capabilities],
        }


@dataclass
class PluginConfig:
    """Runtime configuration for a plugin."""

    enabled: bool = True
    priority: int = 100
    settings: dict[str, Any] = field(default_factory=dict)
