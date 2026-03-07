"""Plugin type definitions - Enhanced with PluginType, PluginManifest, and ExtensionPoints."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class PluginState(enum.Enum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"

    # Aliases for backward compatibility with existing code
    ACTIVE = "started"
    DISABLED = "stopped"


class PluginType(enum.Enum):
    """Types of plugins supported by the system."""

    SANDBOX = "sandbox"
    LLM_PROVIDER = "llm_provider"
    POLICY = "policy"
    TOOL_PROVIDER = "tool_provider"
    MEMORY_BACKEND = "memory_backend"


class PluginCapability(enum.Enum):
    """Capabilities a plugin can provide."""

    TOOL_PROVIDER = "tool_provider"
    AGENT_EXTENSION = "agent_extension"
    WORKFLOW_STEP = "workflow_step"
    EVENT_LISTENER = "event_listener"
    MIDDLEWARE = "middleware"


@dataclass
class PluginManifest:
    """Manifest describing a plugin package."""

    name: str
    version: str
    plugin_type: PluginType
    entry_point: str
    dependencies: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    author: str = ""
    min_pylon_version: str = ""


@dataclass
class PluginInfo:
    """Metadata about a plugin."""

    name: str
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[PluginCapability] = field(default_factory=list)
    plugin_type: PluginType | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "dependencies": self.dependencies,
            "capabilities": [c.value for c in self.capabilities],
            "plugin_type": self.plugin_type.value if self.plugin_type else None,
        }


@dataclass
class PluginConfig:
    """Runtime configuration for a plugin."""

    enabled: bool = True
    priority: int = 100
    settings: dict[str, Any] = field(default_factory=dict)


# --- Extension Point Protocols ---

@runtime_checkable
class SandboxExtension(Protocol):
    """Extension point for sandbox plugins."""

    def create_sandbox(self, config: dict[str, Any]) -> Any: ...
    def destroy_sandbox(self, sandbox_id: str) -> None: ...
    def execute_in_sandbox(self, sandbox_id: str, code: str) -> Any: ...


@runtime_checkable
class LLMProviderExtension(Protocol):
    """Extension point for LLM provider plugins."""

    def complete(self, prompt: str, **kwargs: Any) -> str: ...
    def list_models(self) -> list[str]: ...


@runtime_checkable
class PolicyExtension(Protocol):
    """Extension point for policy plugins."""

    def evaluate(self, action: str, context: dict[str, Any]) -> bool: ...
    def list_rules(self) -> list[str]: ...


@runtime_checkable
class ToolProviderExtension(Protocol):
    """Extension point for tool provider plugins."""

    def list_tools(self) -> list[dict[str, Any]]: ...
    def execute_tool(self, tool_name: str, args: dict[str, Any]) -> Any: ...


@runtime_checkable
class MemoryBackendExtension(Protocol):
    """Extension point for memory backend plugins."""

    def store(self, key: str, value: Any) -> None: ...
    def retrieve(self, key: str) -> Any: ...
    def search(self, query: str, limit: int = 10) -> list[Any]: ...
    def delete(self, key: str) -> bool: ...


EXTENSION_POINT_MAP: dict[PluginType, type] = {
    PluginType.SANDBOX: SandboxExtension,
    PluginType.LLM_PROVIDER: LLMProviderExtension,
    PluginType.POLICY: PolicyExtension,
    PluginType.TOOL_PROVIDER: ToolProviderExtension,
    PluginType.MEMORY_BACKEND: MemoryBackendExtension,
}
