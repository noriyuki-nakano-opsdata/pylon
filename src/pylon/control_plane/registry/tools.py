"""Tool registration, discovery, and trust level management (FR-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from pylon.errors import PylonError
from pylon.types import TrustLevel


class ToolRegistryError(PylonError):
    """Error raised by the tool registry."""

    code = "TOOL_REGISTRY_ERROR"
    status_code = 400


@dataclass(frozen=True)
class ToolDefinition:
    """A registered tool with metadata and handler."""

    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, Any]]
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    parameters: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Registry for tool definitions with trust-level filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        if tool_def.name in self._tools:
            raise ToolRegistryError(
                f"Tool '{tool_def.name}' is already registered",
                details={"tool": tool_def.name},
            )
        self._tools[tool_def.name] = tool_def

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self, trust_level: TrustLevel | None = None) -> list[ToolDefinition]:
        tools = list(self._tools.values())
        if trust_level is not None:
            tools = [t for t in tools if t.trust_level == trust_level]
        return tools

    def discover(self) -> list[ToolDefinition]:
        """Return all registered tools. Placeholder for future MCP dynamic discovery."""
        return self.list()

    def unregister(self, name: str) -> None:
        if name not in self._tools:
            raise ToolRegistryError(
                f"Tool '{name}' not found",
                details={"tool": name},
            )
        del self._tools[name]


def tool(
    *,
    name: str,
    description: str,
    trust_level: str = "untrusted",
    parameters: dict[str, Any] | None = None,
) -> Callable:
    """Decorator to convert an async function into a ToolDefinition.

    Usage:
        @tool(name="github-pr-read", description="Read PR details", trust_level="untrusted")
        async def read_pr(...): ...
    """

    def decorator(fn: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
        fn._tool_definition = ToolDefinition(  # type: ignore[attr-defined]
            name=name,
            description=description,
            handler=fn,
            trust_level=TrustLevel(trust_level),
            parameters=parameters or {},
        )
        return fn

    return decorator
