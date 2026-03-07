"""Plugin SDK - Decorators and base classes for easy plugin creation."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from pylon.plugins.loader import BasePlugin
from pylon.plugins.types import (
    PluginCapability,
    PluginConfig,
    PluginInfo,
    PluginType,
)

F = TypeVar("F", bound=Callable[..., Any])


def plugin(
    name: str,
    version: str = "0.1.0",
    plugin_type: PluginType | None = None,
    description: str = "",
    author: str = "",
    dependencies: list[str] | None = None,
    capabilities: list[PluginCapability] | None = None,
) -> Callable[[type], type]:
    """Decorator to register a class as a plugin with metadata."""

    def decorator(cls: type) -> type:
        info = PluginInfo(
            name=name,
            version=version,
            author=author,
            description=description,
            dependencies=dependencies or [],
            capabilities=capabilities or [],
            plugin_type=plugin_type,
        )
        cls._plugin_info = info  # type: ignore[attr-defined]

        original_init = cls.__init__ if hasattr(cls, "__init__") else None

        @functools.wraps(original_init or cls.__init__)
        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            if not hasattr(self, "_info"):
                self._info = info
                self._config = None
                self._state = None
            if original_init and original_init is not object.__init__:
                original_init(self, *args, **kwargs)

        cls.__init__ = new_init  # type: ignore[attr-defined]

        if not hasattr(cls, "info"):
            cls.info = lambda self: self._info  # type: ignore[attr-defined]

        return cls

    return decorator


class SandboxPlugin(BasePlugin):
    """Base class for sandbox plugins."""

    def __init__(self, name: str, version: str = "0.1.0", **kwargs: Any) -> None:
        super().__init__(PluginInfo(
            name=name,
            version=version,
            plugin_type=PluginType.SANDBOX,
            **kwargs,
        ))
        self._logger = logging.getLogger(f"pylon.plugin.sandbox.{name}")

    def create_sandbox(self, config: dict[str, Any]) -> Any:
        raise NotImplementedError

    def destroy_sandbox(self, sandbox_id: str) -> None:
        raise NotImplementedError

    def execute_in_sandbox(self, sandbox_id: str, code: str) -> Any:
        raise NotImplementedError


class LLMProviderPlugin(BasePlugin):
    """Base class for LLM provider plugins."""

    def __init__(self, name: str, version: str = "0.1.0", **kwargs: Any) -> None:
        super().__init__(PluginInfo(
            name=name,
            version=version,
            plugin_type=PluginType.LLM_PROVIDER,
            **kwargs,
        ))
        self._logger = logging.getLogger(f"pylon.plugin.llm.{name}")

    def complete(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError


class PolicyPlugin(BasePlugin):
    """Base class for policy plugins."""

    def __init__(self, name: str, version: str = "0.1.0", **kwargs: Any) -> None:
        super().__init__(PluginInfo(
            name=name,
            version=version,
            plugin_type=PluginType.POLICY,
            **kwargs,
        ))
        self._logger = logging.getLogger(f"pylon.plugin.policy.{name}")

    def evaluate(self, action: str, context: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_rules(self) -> list[str]:
        raise NotImplementedError


class ToolProviderPlugin(BasePlugin):
    """Base class for tool provider plugins."""

    def __init__(self, name: str, version: str = "0.1.0", **kwargs: Any) -> None:
        super().__init__(PluginInfo(
            name=name,
            version=version,
            plugin_type=PluginType.TOOL_PROVIDER,
            capabilities=[PluginCapability.TOOL_PROVIDER],
            **kwargs,
        ))
        self._logger = logging.getLogger(f"pylon.plugin.tool.{name}")

    def list_tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def execute_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        raise NotImplementedError


def validate_config(config: PluginConfig, schema: dict[str, Any]) -> list[str]:
    """Validate plugin configuration against a schema. Returns list of errors."""
    errors: list[str] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for key in required:
        if key not in config.settings:
            errors.append(f"Missing required setting: {key}")

    for key, value in config.settings.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Setting '{key}' must be a string")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"Setting '{key}' must be an integer")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Setting '{key}' must be a boolean")

    return errors
