"""PluginLifecycleManager - State machine enforcement for plugin lifecycle."""

from __future__ import annotations

import logging

from pylon.plugins.loader import Plugin
from pylon.plugins.types import PluginConfig, PluginState

logger = logging.getLogger(__name__)

# Valid state transitions
_VALID_TRANSITIONS: dict[PluginState, set[PluginState]] = {
    PluginState.DISCOVERED: {PluginState.LOADED, PluginState.ERROR},
    PluginState.LOADED: {PluginState.INITIALIZED, PluginState.ERROR},
    PluginState.INITIALIZED: {PluginState.STARTED, PluginState.ERROR},
    PluginState.STARTED: {PluginState.STOPPED, PluginState.ERROR},
    PluginState.STOPPED: {PluginState.INITIALIZED, PluginState.ERROR},
    PluginState.ERROR: {PluginState.DISCOVERED},
}


class LifecycleError(Exception):
    """Raised when a lifecycle state transition is invalid."""


class PluginLifecycleManager:
    """Manages plugin lifecycle with state machine enforcement."""

    def __init__(self) -> None:
        self._states: dict[str, PluginState] = {}
        self._plugins: dict[str, Plugin] = {}
        self._configs: dict[str, PluginConfig] = {}

    def _transition(self, name: str, target: PluginState) -> None:
        current = self._states.get(name, PluginState.DISCOVERED)
        valid = _VALID_TRANSITIONS.get(current, set())
        if target not in valid:
            raise LifecycleError(
                f"Invalid transition for '{name}': {current.value} -> {target.value}"
            )
        self._states[name] = target

    def get_state(self, name: str) -> PluginState | None:
        return self._states.get(name)

    def load(self, plugin: Plugin) -> None:
        """Load a plugin (DISCOVERED -> LOADED)."""
        name = plugin.info().name
        if name not in self._states:
            self._states[name] = PluginState.DISCOVERED
        try:
            self._transition(name, PluginState.LOADED)
            self._plugins[name] = plugin
        except LifecycleError:
            self._states[name] = PluginState.ERROR
            raise

    def initialize(self, name: str, config: PluginConfig | None = None) -> None:
        """Initialize a plugin (LOADED -> INITIALIZED)."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise LifecycleError(f"Plugin not loaded: {name}")
        cfg = config or PluginConfig()
        try:
            self._transition(name, PluginState.INITIALIZED)
            plugin.initialize(cfg)
            self._configs[name] = cfg
        except LifecycleError:
            raise
        except Exception as e:
            self._states[name] = PluginState.ERROR
            logger.error("Failed to initialize plugin '%s': %s", name, e)
            raise LifecycleError(f"Initialization failed for '{name}': {e}") from e

    def start(self, name: str) -> None:
        """Start a plugin (INITIALIZED -> STARTED)."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise LifecycleError(f"Plugin not loaded: {name}")
        try:
            self._transition(name, PluginState.STARTED)
            plugin.activate()
        except LifecycleError:
            raise
        except Exception as e:
            self._states[name] = PluginState.ERROR
            logger.error("Failed to start plugin '%s': %s", name, e)
            raise LifecycleError(f"Start failed for '{name}': {e}") from e

    def stop(self, name: str) -> None:
        """Stop a plugin (STARTED -> STOPPED)."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise LifecycleError(f"Plugin not loaded: {name}")
        try:
            self._transition(name, PluginState.STOPPED)
            plugin.deactivate()
        except LifecycleError:
            raise
        except Exception as e:
            self._states[name] = PluginState.ERROR
            logger.error("Failed to stop plugin '%s': %s", name, e)
            raise LifecycleError(f"Stop failed for '{name}': {e}") from e

    def restart(self, name: str) -> None:
        """Restart a plugin (STOPPED -> INITIALIZED -> STARTED)."""
        self.initialize(name, self._configs.get(name))
        self.start(name)

    def get_plugin(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    @property
    def managed_plugins(self) -> list[str]:
        return list(self._plugins.keys())
