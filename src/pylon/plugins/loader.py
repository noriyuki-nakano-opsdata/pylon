"""PluginLoader - Enhanced plugin discovery, loading, and validation."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import warnings
from pathlib import Path
from typing import Protocol, runtime_checkable

from pylon.plugins.types import (
    PluginConfig,
    PluginInfo,
    PluginManifest,
    PluginState,
    PluginType,
)


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

    @state.setter
    def state(self, value: PluginState) -> None:
        if not isinstance(value, PluginState):
            raise ValueError(
                f"state must be a PluginState member, got {type(value).__name__}: {value!r}"
            )
        self._state = value

    def initialize(self, config: PluginConfig) -> None:
        self._config = config
        self._state = PluginState.INITIALIZED

    def activate(self) -> None:
        self._state = PluginState.STARTED

    def deactivate(self) -> None:
        self._state = PluginState.STOPPED


class PluginLoader:
    """Discovers, loads, and validates plugins."""

    def __init__(self) -> None:
        self._loaded: dict[str, Plugin] = {}
        self._manifests: dict[str, PluginManifest] = {}

    def discover(self, paths: list[str]) -> list[PluginInfo]:
        """Scan directories for plugin manifests."""
        discovered: list[PluginInfo] = []
        for p in paths:
            path = Path(p)
            if not path.is_dir():
                continue
            for child in path.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    manifest_file = child / "plugin.json"
                    if manifest_file.exists():
                        manifest = self._load_manifest_file(manifest_file)
                        if manifest:
                            self._manifests[manifest.name] = manifest
                            discovered.append(self._manifest_to_info(manifest))
                            continue
                    discovered.append(
                        PluginInfo(name=child.name, description=f"Discovered in {p}")
                    )
        return discovered

    def discover_entry_points(self, group: str = "pylon.plugins") -> list[PluginInfo]:
        """Discover plugins via importlib entry points."""
        discovered: list[PluginInfo] = []
        try:
            eps = importlib.metadata.entry_points()
            plugin_eps = eps.get(group, []) if isinstance(eps, dict) else eps.select(group=group)
            for ep in plugin_eps:
                discovered.append(
                    PluginInfo(name=ep.name, description=f"Entry point: {ep.value}")
                )
        except Exception as exc:
            warnings.warn(
                f"Failed to discover entry points for group '{group}': {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        return discovered

    def _load_manifest_file(self, path: Path) -> PluginManifest | None:
        """Load and parse a plugin.json manifest file."""
        try:
            data = json.loads(path.read_text())
            return PluginManifest(
                name=data["name"],
                version=data["version"],
                plugin_type=PluginType(data["type"]),
                entry_point=data["entry_point"],
                dependencies=data.get("dependencies", []),
                config_schema=data.get("config_schema", {}),
                description=data.get("description", ""),
                author=data.get("author", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            warnings.warn(
                f"Failed to load plugin manifest from {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return None

    def _manifest_to_info(self, manifest: PluginManifest) -> PluginInfo:
        return PluginInfo(
            name=manifest.name,
            version=manifest.version,
            author=manifest.author,
            description=manifest.description,
            dependencies=manifest.dependencies,
            plugin_type=manifest.plugin_type,
        )

    def validate_manifest(self, manifest: PluginManifest) -> list[str]:
        """Validate a plugin manifest. Returns list of errors."""
        errors: list[str] = []
        if not manifest.name:
            errors.append("Plugin name is required")
        elif not isinstance(manifest.name, str) or not manifest.name.strip():
            errors.append("Plugin name must be a non-empty string")
        if not manifest.version:
            errors.append("Plugin version is required")
        elif not isinstance(manifest.version, str) or not manifest.version.strip():
            errors.append("Plugin version must be a non-empty string")
        if not manifest.entry_point:
            errors.append("Entry point is required")
        elif not isinstance(manifest.entry_point, str) or not manifest.entry_point.strip():
            errors.append("Entry point must be a non-empty string")
        return errors

    def validate(self, plugin_info: PluginInfo, available: set[str] | None = None) -> list[str]:
        """Validate plugin info. Returns list of error messages."""
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

    def resolve_dependencies(self, manifests: list[PluginManifest]) -> list[str]:
        """Topological sort of plugin names by dependencies. Raises on cycles."""
        graph: dict[str, list[str]] = {}
        for m in manifests:
            graph[m.name] = m.dependencies

        visited: set[str] = set()
        result: list[str] = []
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency detected: {name}")
            visiting.add(name)
            for dep in graph.get(name, []):
                if dep in graph:
                    visit(dep)
            visiting.remove(name)
            visited.add(name)
            result.append(name)

        for name in graph:
            visit(name)

        return result

    def check_version_compatibility(self, required: str, actual: str) -> bool:
        """Check if actual version satisfies required version (simple semver >=)."""
        try:
            req_parts = [int(x) for x in required.split(".")]
            act_parts = [int(x) for x in actual.split(".")]
            return act_parts >= req_parts
        except (ValueError, AttributeError):
            return False

    def load(self, plugin: Plugin) -> Plugin:
        """Register a loaded plugin instance."""
        info = plugin.info()
        self._loaded[info.name] = plugin
        return plugin

    def get_loaded(self, name: str) -> Plugin | None:
        return self._loaded.get(name)

    def get_manifest(self, name: str) -> PluginManifest | None:
        return self._manifests.get(name)
