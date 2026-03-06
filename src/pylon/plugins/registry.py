"""PluginRegistry - Plugin lifecycle management."""

from __future__ import annotations

from pylon.plugins.loader import Plugin
from pylon.plugins.types import PluginCapability, PluginConfig, PluginState


class _PluginEntry:
    """Internal wrapper for a registered plugin."""

    def __init__(self, plugin: Plugin, config: PluginConfig | None = None) -> None:
        self.plugin = plugin
        self.config = config or PluginConfig()
        self.state = PluginState.LOADED


class PluginRegistry:
    """Manages plugin registration, activation, and querying."""

    def __init__(self) -> None:
        self._plugins: dict[str, _PluginEntry] = {}

    def register(self, plugin: Plugin, config: PluginConfig | None = None) -> None:
        """Register a plugin."""
        name = plugin.info().name
        if name in self._plugins:
            raise ValueError(f"Plugin already registered: {name}")
        self._plugins[name] = _PluginEntry(plugin, config)

    def unregister(self, name: str) -> bool:
        """Unregister a plugin. Deactivates first if active."""
        entry = self._plugins.get(name)
        if entry is None:
            return False
        if entry.state == PluginState.ACTIVE:
            entry.plugin.deactivate()
        del self._plugins[name]
        return True

    def get(self, name: str) -> Plugin | None:
        """Get a plugin by name."""
        entry = self._plugins.get(name)
        return entry.plugin if entry else None

    def get_state(self, name: str) -> PluginState | None:
        """Get the state of a registered plugin."""
        entry = self._plugins.get(name)
        return entry.state if entry else None

    def list(
        self,
        capability: PluginCapability | None = None,
        state: PluginState | None = None,
    ) -> list[Plugin]:
        """List plugins, optionally filtered by capability and/or state."""
        results: list[Plugin] = []
        for entry in self._plugins.values():
            if state is not None and entry.state != state:
                continue
            if capability is not None:
                if capability not in entry.plugin.info().capabilities:
                    continue
            results.append(entry.plugin)
        return results

    def get_by_capability(self, cap: PluginCapability) -> list[Plugin]:
        """Get all plugins with a specific capability."""
        return [
            entry.plugin
            for entry in self._plugins.values()
            if cap in entry.plugin.info().capabilities
        ]

    def enable(self, name: str) -> None:
        """Initialize and activate a plugin."""
        entry = self._plugins.get(name)
        if entry is None:
            raise KeyError(f"Plugin not found: {name}")
        entry.plugin.initialize(entry.config)
        entry.state = PluginState.INITIALIZED
        entry.plugin.activate()
        entry.state = PluginState.ACTIVE

    def disable(self, name: str) -> None:
        """Deactivate a plugin."""
        entry = self._plugins.get(name)
        if entry is None:
            raise KeyError(f"Plugin not found: {name}")
        entry.plugin.deactivate()
        entry.state = PluginState.DISABLED

    def activate_in_dependency_order(self) -> list[str]:
        """Activate all enabled plugins respecting dependency order.

        Returns list of activated plugin names in order.
        """
        activated: set[str] = set()
        order: list[str] = []

        def _activate(name: str, visiting: set[str]) -> None:
            if name in activated:
                return
            if name not in self._plugins:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency detected: {name}")

            visiting.add(name)
            entry = self._plugins[name]
            for dep in entry.plugin.info().dependencies:
                _activate(dep, visiting)
            visiting.discard(name)

            if entry.config.enabled:
                entry.plugin.initialize(entry.config)
                entry.state = PluginState.INITIALIZED
                entry.plugin.activate()
                entry.state = PluginState.ACTIVE
                activated.add(name)
                order.append(name)

        for name in list(self._plugins.keys()):
            _activate(name, set())

        return order

    @property
    def count(self) -> int:
        return len(self._plugins)
