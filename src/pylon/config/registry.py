"""ConfigRegistry - Namespace-based config registry with watch and freeze."""

from __future__ import annotations

import copy
import uuid
from typing import Any, Callable

from pylon.config.loader import ConfigLoader


class FrozenConfigError(Exception):
    """Raised when trying to modify a frozen config namespace."""


class ConfigRegistry:
    """Registry for managing namespaced configurations."""

    def __init__(self) -> None:
        self._configs: dict[str, dict[str, Any]] = {}
        self._watchers: dict[str, dict[str, Callable[[dict[str, Any]], None]]] = {}
        self._frozen: set[str] = set()

    def register(self, namespace: str, config: dict[str, Any]) -> None:
        """Register a configuration under a namespace."""
        if namespace in self._frozen:
            raise FrozenConfigError(f"Namespace '{namespace}' is frozen")
        self._configs[namespace] = copy.deepcopy(config)
        self._notify(namespace)

    def get(self, namespace: str) -> dict[str, Any] | None:
        """Get config for a namespace. Returns a copy."""
        config = self._configs.get(namespace)
        if config is None:
            return None
        return copy.deepcopy(config)

    def watch(
        self,
        namespace: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> str:
        """Watch a namespace for changes. Returns an unwatch ID."""
        watch_id = str(uuid.uuid4())
        self._watchers.setdefault(namespace, {})[watch_id] = callback
        return watch_id

    def unwatch(self, namespace: str, watch_id: str) -> bool:
        """Remove a watcher. Returns True if it existed."""
        ns_watchers = self._watchers.get(namespace, {})
        return ns_watchers.pop(watch_id, None) is not None

    def overlay(self, namespace: str, overrides: dict[str, Any]) -> dict[str, Any]:
        """Apply overrides on top of existing config. Returns merged result."""
        if namespace in self._frozen:
            raise FrozenConfigError(f"Namespace '{namespace}' is frozen")
        base = self._configs.get(namespace, {})
        merged = ConfigLoader.merge(base, overrides)
        self._configs[namespace] = merged
        self._notify(namespace)
        return copy.deepcopy(merged)

    def freeze(self, namespace: str) -> dict[str, Any] | None:
        """Freeze a namespace, preventing further modifications."""
        self._frozen.add(namespace)
        return self.get(namespace)

    def is_frozen(self, namespace: str) -> bool:
        return namespace in self._frozen

    def _notify(self, namespace: str) -> None:
        config = self._configs.get(namespace)
        if config is None:
            return
        for callback in list(self._watchers.get(namespace, {}).values()):
            callback(copy.deepcopy(config))


# Global singleton
_global_registry: ConfigRegistry | None = None


def get_registry() -> ConfigRegistry:
    """Get the global config registry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ConfigRegistry()
    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _global_registry
    _global_registry = None
