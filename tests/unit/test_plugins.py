"""Tests for the enhanced plugin system."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from pylon.plugins.hooks import HookSystem
from pylon.plugins.lifecycle import LifecycleError, PluginLifecycleManager
from pylon.plugins.loader import BasePlugin, PluginLoader
from pylon.plugins.registry import PluginRegistry
from pylon.plugins.sdk import (
    LLMProviderPlugin,
    PolicyPlugin,
    SandboxPlugin,
    ToolProviderPlugin,
    plugin,
    validate_config,
)
from pylon.plugins.types import (
    PluginCapability,
    PluginConfig,
    PluginInfo,
    PluginManifest,
    PluginState,
    PluginType,
)

# --- Helpers ---

def make_plugin(name: str = "test-plugin", version: str = "1.0.0", **kwargs: Any) -> BasePlugin:
    return BasePlugin(PluginInfo(name=name, version=version, **kwargs))


def make_manifest(
    name: str = "test",
    version: str = "1.0.0",
    plugin_type: PluginType = PluginType.TOOL_PROVIDER,
    entry_point: str = "test_module:TestPlugin",
    **kwargs: Any,
) -> PluginManifest:
    return PluginManifest(
        name=name,
        version=version,
        plugin_type=plugin_type,
        entry_point=entry_point,
        **kwargs,
    )


# === Types Tests ===

class TestPluginTypes:
    def test_plugin_state_values(self):
        assert PluginState.DISCOVERED.value == "discovered"
        assert PluginState.LOADED.value == "loaded"
        assert PluginState.INITIALIZED.value == "initialized"
        assert PluginState.STARTED.value == "started"
        assert PluginState.STOPPED.value == "stopped"
        assert PluginState.ERROR.value == "error"

    def test_plugin_type_values(self):
        assert PluginType.SANDBOX.value == "sandbox"
        assert PluginType.LLM_PROVIDER.value == "llm_provider"
        assert PluginType.POLICY.value == "policy"
        assert PluginType.TOOL_PROVIDER.value == "tool_provider"
        assert PluginType.MEMORY_BACKEND.value == "memory_backend"

    def test_plugin_manifest_creation(self):
        manifest = make_manifest(description="A test plugin", dependencies=["dep-a"])
        assert manifest.name == "test"
        assert manifest.version == "1.0.0"
        assert manifest.plugin_type == PluginType.TOOL_PROVIDER
        assert manifest.entry_point == "test_module:TestPlugin"
        assert manifest.dependencies == ["dep-a"]
        assert manifest.description == "A test plugin"

    def test_plugin_info_to_dict(self):
        info = PluginInfo(
            name="foo",
            version="2.0.0",
            plugin_type=PluginType.POLICY,
            capabilities=[PluginCapability.MIDDLEWARE],
        )
        d = info.to_dict()
        assert d["name"] == "foo"
        assert d["plugin_type"] == "policy"
        assert d["capabilities"] == ["middleware"]


# === Loader Tests ===

class TestPluginLoader:
    def test_discover_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "my_plugin"
            plugin_dir.mkdir()
            (plugin_dir / "__init__.py").touch()
            loader = PluginLoader()
            discovered = loader.discover([tmpdir])
            assert len(discovered) == 1
            assert discovered[0].name == "my_plugin"

    def test_discover_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "my_plugin"
            plugin_dir.mkdir()
            (plugin_dir / "__init__.py").touch()
            manifest_data = {
                "name": "my-plugin",
                "version": "1.2.3",
                "type": "tool_provider",
                "entry_point": "my_plugin:MyPlugin",
                "description": "From manifest",
            }
            (plugin_dir / "plugin.json").write_text(json.dumps(manifest_data))
            loader = PluginLoader()
            discovered = loader.discover([tmpdir])
            assert len(discovered) == 1
            assert discovered[0].name == "my-plugin"
            assert discovered[0].version == "1.2.3"
            assert discovered[0].plugin_type == PluginType.TOOL_PROVIDER

    def test_discover_nonexistent_path(self):
        loader = PluginLoader()
        discovered = loader.discover(["/nonexistent/path"])
        assert discovered == []

    def test_discover_entry_points(self):
        loader = PluginLoader()
        # Should not raise, returns empty for non-existent group
        discovered = loader.discover_entry_points(group="pylon.test.nonexistent")
        assert isinstance(discovered, list)

    def test_validate_valid_plugin(self):
        loader = PluginLoader()
        info = PluginInfo(name="valid", version="1.0.0")
        errors = loader.validate(info)
        assert errors == []

    def test_validate_missing_name(self):
        loader = PluginLoader()
        info = PluginInfo(name="", version="1.0.0")
        errors = loader.validate(info)
        assert "Plugin name is required" in errors

    def test_validate_missing_version(self):
        loader = PluginLoader()
        info = PluginInfo(name="test", version="")
        errors = loader.validate(info)
        assert "Plugin version is required" in errors

    def test_validate_missing_dependency(self):
        loader = PluginLoader()
        info = PluginInfo(name="test", version="1.0.0", dependencies=["missing-dep"])
        errors = loader.validate(info, available={"other-dep"})
        assert "Missing dependency: missing-dep" in errors

    def test_validate_manifest(self):
        loader = PluginLoader()
        manifest = make_manifest(name="", entry_point="")
        errors = loader.validate_manifest(manifest)
        assert "Plugin name is required" in errors
        assert "Entry point is required" in errors

    def test_load_and_get(self):
        loader = PluginLoader()
        p = make_plugin("my-plugin")
        loader.load(p)
        assert loader.get_loaded("my-plugin") is p
        assert loader.get_loaded("nonexistent") is None

    def test_resolve_dependencies_simple(self):
        loader = PluginLoader()
        manifests = [
            make_manifest("c", dependencies=["a", "b"]),
            make_manifest("a"),
            make_manifest("b", dependencies=["a"]),
        ]
        order = loader.resolve_dependencies(manifests)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_resolve_dependencies_circular(self):
        loader = PluginLoader()
        manifests = [
            make_manifest("a", dependencies=["b"]),
            make_manifest("b", dependencies=["a"]),
        ]
        with pytest.raises(ValueError, match="Circular dependency"):
            loader.resolve_dependencies(manifests)

    def test_version_compatibility(self):
        loader = PluginLoader()
        assert loader.check_version_compatibility("1.0.0", "1.0.0") is True
        assert loader.check_version_compatibility("1.0.0", "2.0.0") is True
        assert loader.check_version_compatibility("2.0.0", "1.0.0") is False
        assert loader.check_version_compatibility("invalid", "1.0.0") is False

    def test_validate_manifest_missing_name(self):
        loader = PluginLoader()
        manifest = make_manifest(name="", version="1.0.0", entry_point="mod:Cls")
        errors = loader.validate_manifest(manifest)
        assert any("name" in e.lower() for e in errors)

    def test_validate_manifest_missing_version(self):
        loader = PluginLoader()
        manifest = make_manifest(name="valid", version="", entry_point="mod:Cls")
        errors = loader.validate_manifest(manifest)
        assert any("version" in e.lower() for e in errors)

    def test_validate_manifest_valid(self):
        loader = PluginLoader()
        manifest = make_manifest(
            name="valid-plugin", version="1.0.0", entry_point="mod:Cls"
        )
        errors = loader.validate_manifest(manifest)
        assert errors == []

    def test_plugin_state_transitions(self):
        p = make_plugin("lifecycle")
        assert p.state == PluginState.DISCOVERED
        p.initialize(PluginConfig())
        assert p.state == PluginState.INITIALIZED
        p.activate()
        assert p.state == PluginState.STARTED
        p.deactivate()
        assert p.state == PluginState.STOPPED


# === Registry Tests ===

class TestPluginRegistry:
    def test_register_and_get(self):
        registry = PluginRegistry()
        p = make_plugin("my-plugin")
        registry.register(p)
        assert registry.get("my-plugin") is p
        assert registry.count == 1

    def test_register_duplicate_raises(self):
        registry = PluginRegistry()
        p = make_plugin("dup")
        registry.register(p)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(make_plugin("dup"))

    def test_unregister(self):
        registry = PluginRegistry()
        p = make_plugin("rm-me")
        registry.register(p)
        assert registry.unregister("rm-me") is True
        assert registry.get("rm-me") is None
        assert registry.unregister("rm-me") is False

    def test_get_state(self):
        registry = PluginRegistry()
        p = make_plugin("s")
        registry.register(p)
        assert registry.get_state("s") == PluginState.LOADED
        assert registry.get_state("nonexistent") is None

    def test_enable_and_disable(self):
        registry = PluginRegistry()
        p = make_plugin("toggle")
        registry.register(p)
        registry.enable("toggle")
        assert registry.get_state("toggle") == PluginState.STARTED
        registry.disable("toggle")
        assert registry.get_state("toggle") == PluginState.STOPPED

    def test_enable_nonexistent_raises(self):
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.enable("ghost")

    def test_list_by_state(self):
        registry = PluginRegistry()
        p1 = make_plugin("a")
        p2 = make_plugin("b")
        registry.register(p1)
        registry.register(p2)
        registry.enable("a")
        started = registry.list(state=PluginState.STARTED)
        assert len(started) == 1
        assert started[0].info().name == "a"

    def test_get_by_type(self):
        registry = PluginRegistry()
        p = make_plugin("typed", plugin_type=PluginType.POLICY)
        registry.register(p)
        result = registry.get_by_type(PluginType.POLICY)
        assert len(result) == 1
        assert result[0].info().name == "typed"

    def test_configure(self):
        registry = PluginRegistry()
        p = make_plugin("cfg")
        registry.register(p)
        new_cfg = PluginConfig(settings={"key": "value"})
        registry.configure("cfg", new_cfg)
        # No error means success

    def test_configure_nonexistent_raises(self):
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.configure("ghost", PluginConfig())

    def test_plugin_registry_register_and_get(self):
        registry = PluginRegistry()
        p = make_plugin("fetched")
        registry.register(p)
        assert registry.get("fetched") is p

    def test_plugin_registry_list(self):
        registry = PluginRegistry()
        p1 = make_plugin("alpha")
        p2 = make_plugin("beta")
        p3 = make_plugin("gamma")
        registry.register(p1)
        registry.register(p2)
        registry.register(p3)
        all_plugins = registry.list()
        names = {pl.info().name for pl in all_plugins}
        assert names == {"alpha", "beta", "gamma"}

    def test_activate_in_dependency_order(self):
        registry = PluginRegistry()
        p1 = make_plugin("base")
        p2 = make_plugin("dependent", dependencies=["base"])
        registry.register(p1)
        registry.register(p2)
        order = registry.activate_in_dependency_order()
        assert order.index("base") < order.index("dependent")


# === Lifecycle Tests ===

class TestLifecycleManager:
    def test_full_lifecycle(self):
        mgr = PluginLifecycleManager()
        p = make_plugin("lc")
        mgr.load(p)
        assert mgr.get_state("lc") == PluginState.LOADED
        mgr.initialize("lc")
        assert mgr.get_state("lc") == PluginState.INITIALIZED
        mgr.start("lc")
        assert mgr.get_state("lc") == PluginState.STARTED
        mgr.stop("lc")
        assert mgr.get_state("lc") == PluginState.STOPPED

    def test_invalid_transition_raises(self):
        mgr = PluginLifecycleManager()
        p = make_plugin("bad")
        mgr.load(p)
        with pytest.raises(LifecycleError, match="Invalid transition"):
            mgr.start("bad")  # LOADED -> STARTED not valid

    def test_cannot_start_without_load(self):
        mgr = PluginLifecycleManager()
        with pytest.raises(LifecycleError, match="not loaded"):
            mgr.initialize("ghost")

    def test_restart(self):
        mgr = PluginLifecycleManager()
        p = make_plugin("rs")
        mgr.load(p)
        mgr.initialize("rs")
        mgr.start("rs")
        mgr.stop("rs")
        mgr.restart("rs")
        assert mgr.get_state("rs") == PluginState.STARTED

    def test_managed_plugins_list(self):
        mgr = PluginLifecycleManager()
        mgr.load(make_plugin("a"))
        mgr.load(make_plugin("b"))
        assert set(mgr.managed_plugins) == {"a", "b"}

    def test_get_plugin(self):
        mgr = PluginLifecycleManager()
        p = make_plugin("gp")
        mgr.load(p)
        assert mgr.get_plugin("gp") is p
        assert mgr.get_plugin("missing") is None

    def test_error_on_bad_initialize(self):
        class BadPlugin(BasePlugin):
            def initialize(self, config):
                raise RuntimeError("init boom")

        mgr = PluginLifecycleManager()
        p = BadPlugin(PluginInfo(name="boom"))
        mgr.load(p)
        with pytest.raises(LifecycleError, match="Initialization failed"):
            mgr.initialize("boom")
        assert mgr.get_state("boom") == PluginState.ERROR


# === SDK Tests ===

class TestSDK:
    def test_plugin_decorator(self):
        @plugin(name="decorated", version="3.0.0", plugin_type=PluginType.POLICY)
        class MyPlugin:
            pass

        p = MyPlugin()
        assert p._plugin_info.name == "decorated"
        assert p._plugin_info.version == "3.0.0"
        assert p._plugin_info.plugin_type == PluginType.POLICY

    def test_plugin_decorator_info_method(self):
        @plugin(name="with-info", version="1.0.0")
        class InfoPlugin:
            pass

        p = InfoPlugin()
        assert p.info().name == "with-info"

    def test_sandbox_plugin_base(self):
        p = SandboxPlugin("my-sandbox", "1.0.0")
        assert p.info().plugin_type == PluginType.SANDBOX
        with pytest.raises(NotImplementedError):
            p.create_sandbox({})

    def test_llm_provider_plugin_base(self):
        p = LLMProviderPlugin("my-llm", "1.0.0")
        assert p.info().plugin_type == PluginType.LLM_PROVIDER
        with pytest.raises(NotImplementedError):
            p.complete("hello")
        with pytest.raises(NotImplementedError):
            p.list_models()

    def test_policy_plugin_base(self):
        p = PolicyPlugin("my-policy", "1.0.0")
        assert p.info().plugin_type == PluginType.POLICY
        with pytest.raises(NotImplementedError):
            p.evaluate("action", {})

    def test_tool_provider_plugin_base(self):
        p = ToolProviderPlugin("my-tools", "1.0.0")
        assert p.info().plugin_type == PluginType.TOOL_PROVIDER
        assert PluginCapability.TOOL_PROVIDER in p.info().capabilities
        with pytest.raises(NotImplementedError):
            p.list_tools()

    def test_validate_config_required(self):
        schema = {"required": ["api_key"], "properties": {}}
        cfg = PluginConfig(settings={})
        errors = validate_config(cfg, schema)
        assert "Missing required setting: api_key" in errors

    def test_validate_config_type_check(self):
        schema = {
            "required": [],
            "properties": {"port": {"type": "integer"}},
        }
        cfg = PluginConfig(settings={"port": "not-int"})
        errors = validate_config(cfg, schema)
        assert "Setting 'port' must be an integer" in errors

    def test_validate_config_valid(self):
        schema = {
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        cfg = PluginConfig(settings={"name": "test"})
        errors = validate_config(cfg, schema)
        assert errors == []


# === Hook System Tests ===

class TestHookSystem:
    def test_predefined_hooks_exist(self):
        hs = HookSystem()
        assert hs.get_hook("pre_agent_create") is not None
        assert hs.get_hook("on_error") is not None

    def test_subscribe_and_trigger(self):
        hs = HookSystem()
        results = []
        hs.subscribe("on_error", lambda ctx: results.append(ctx.get("msg")))
        hs.trigger("on_error", {"msg": "boom"})
        assert results == ["boom"]

    def test_trigger_priority_order(self):
        hs = HookSystem()
        order = []
        hs.subscribe("on_error", lambda ctx: order.append("second"), priority=200)
        hs.subscribe("on_error", lambda ctx: order.append("first"), priority=50)
        hs.trigger("on_error")
        assert order == ["first", "second"]

    def test_unsubscribe(self):
        hs = HookSystem()
        sid = hs.subscribe("on_error", lambda ctx: None, handler_name="h1")
        assert hs.subscriber_count("on_error") == 1
        assert hs.unsubscribe("on_error", sid) is True
        assert hs.subscriber_count("on_error") == 0

    def test_trigger_with_error_handler(self):
        hs = HookSystem()
        hs.subscribe("on_error", lambda ctx: 1 / 0, handler_name="bad")
        results = hs.trigger("on_error")
        assert len(results) == 1
        assert results[0].error is not None
        assert "division by zero" in results[0].error

    def test_reentrant_hook_is_blocked(self):
        """A handler that triggers the same hook must not cause infinite recursion."""
        hs = HookSystem()
        call_count = 0

        def recursive_handler(ctx: dict) -> None:
            nonlocal call_count
            call_count += 1
            hs.trigger("on_error", {"recursive": True})

        hs.subscribe("on_error", recursive_handler, handler_name="recursive")
        results = hs.trigger("on_error")
        assert call_count == 1
        assert len(results) == 1

    def test_different_hooks_not_blocked(self):
        """Reentrancy guard is per-hook; different hooks fire normally."""
        hs = HookSystem()
        inner_results = []

        def cross_hook_handler(ctx: dict) -> str:
            r = hs.trigger("post_agent_create", {"from": "on_error"})
            inner_results.extend(r)
            return "outer"

        hs.subscribe("on_error", cross_hook_handler, handler_name="cross")
        hs.subscribe("post_agent_create", lambda ctx: "inner", handler_name="inner")
        results = hs.trigger("on_error")
        assert len(results) == 1
        assert results[0].result == "outer"
        assert len(inner_results) == 1
        assert inner_results[0].result == "inner"

    def test_guard_cleanup_allows_retrigger(self):
        """After a hook completes, it can be triggered again."""
        hs = HookSystem()
        call_count = 0

        def counting_handler(ctx: dict) -> None:
            nonlocal call_count
            call_count += 1

        hs.subscribe("on_error", counting_handler, handler_name="counter")
        hs.trigger("on_error")
        hs.trigger("on_error")
        assert call_count == 2
