"""PluginLoader - Plugin discovery, loading, and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pylon.plugins.types import PluginConfig, PluginInfo, PluginState


@runtime_checkable
class Plugin(Protocol):
    """Protocol that all plugins must implement."""

    def info(self) -> PluginInfo: ...
    def initialize(self, config: PluginConfig) -> None: ...
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...


class BasePlugin:
    """Convenience base class for plugins."""

    def __init__(self, plugin_info: PluginInfo) -> None:
        self._info = plugin_info
        self._config: PluginConfig | None = None
        self._state = PluginState.DISCOVERED

    def info(self) -> PluginInfo:
        return self._info

    @property
    def state(self) -> PluginState:
        return self._state

    def initialize(self, config: PluginConfig) -> None:
        self._config = config
        self._state = PluginState.INITIALIZED

    def activate(self) -> None:
        self._state = PluginState.ACTIVE

    def deactivate(self) -> None:
        self._state = PluginState.DISABLED


class PluginLoader:
    """Discovers, loads, and validates plugins."""

    def __init__(self) -> None:
        self._loaded: dict[str, Plugin] = {}

    def discover(self, paths: list[str]) -> list[PluginInfo]:
        """Scan directories for plugin manifests (plugin.json or __plugin__.py).

        Returns discovered PluginInfo entries. Currently returns empty for
        non-existent paths (real implementation would scan for entry points).
        """
        discovered: list[PluginInfo] = []
        for p in paths:
            path = Path(p)
            if not path.is_dir():
                continue
            for child in path.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    discovered.append(
                        PluginInfo(name=child.name, description=f"Discovered in {p}")
                    )
        return discovered

    def load(self, plugin: Plugin) -> Plugin:
        """Register a loaded plugin instance."""
        info = plugin.info()
        self._loaded[info.name] = plugin
        return plugin

    def validate(self, plugin_info: PluginInfo, available: set[str] | None = None) -> list[str]:
        """Validate plugin info. Returns list of error messages (empty = valid)."""
        errors: list[str] = []
        if not plugin_info.name:
            errors.append("Plugin name is required")
        if not plugin_info.version:
            errors.append("Plugin version is required")
        if available is not None:
            for dep in plugin_info.dependencies:
                if dep not in available:
                    errors.append(f"Missing dependency: {dep}")
        return errors

    def get_loaded(self, name: str) -> Plugin | None:
        return self._loaded.get(name)
