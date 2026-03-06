"""Tests for Pylon plugin system."""

from __future__ import annotations

import pytest

from pylon.plugins.types import (
    PluginCapability,
    PluginConfig,
    PluginInfo,
    PluginState,
)
from pylon.plugins.loader import BasePlugin, PluginLoader
from pylon.plugins.registry import PluginRegistry
from pylon.plugins.hooks import HookResult, HookSystem


def _make_plugin(
    name: str,
    *,
    version: str = "1.0.0",
    deps: list[str] | None = None,
    caps: list[PluginCapability] | None = None,
) -> BasePlugin:
    return BasePlugin(
        PluginInfo(
            name=name,
            version=version,
            dependencies=deps or [],
            capabilities=caps or [],
        )
    )


# --- types ---

class TestPluginTypes:
    def test_plugin_info_to_dict(self) -> None:
        info = PluginInfo(
            name="my-plugin",
            version="1.0.0",
            author="test",
            capabilities=[PluginCapability.TOOL_PROVIDER],
        )
        d = info.to_dict()
        assert d["name"] == "my-plugin"
        assert "tool_provider" in d["capabilities"]

    def test_plugin_state_values(self) -> None:
        assert PluginState.DISCOVERED.value == "discovered"
        assert PluginState.ACTIVE.value == "active"
        assert PluginState.ERROR.value == "error"

    def test_plugin_capability_values(self) -> None:
        assert PluginCapability.MIDDLEWARE.value == "middleware"
        assert len(PluginCapability) == 5

    def test_plugin_config_defaults(self) -> None:
        config = PluginConfig()
        assert config.enabled is True
        assert config.priority == 100
        assert config.settings == {}


# --- BasePlugin ---

class TestBasePlugin:
    def test_lifecycle(self) -> None:
        plugin = _make_plugin("test")
        assert plugin.state == PluginState.DISCOVERED

        plugin.initialize(PluginConfig())
        assert plugin.state == PluginState.INITIALIZED

        plugin.activate()
        assert plugin.state == PluginState.ACTIVE

        plugin.deactivate()
        assert plugin.state == PluginState.DISABLED

    def test_info(self) -> None:
        plugin = _make_plugin("my-plugin", version="2.0.0")
        assert plugin.info().name == "my-plugin"
        assert plugin.info().version == "2.0.0"


# --- PluginLoader ---

class TestPluginLoader:
    def test_load(self) -> None:
        loader = PluginLoader()
        plugin = _make_plugin("test-plugin")
        loaded = loader.load(plugin)
        assert loaded is plugin
        assert loader.get_loaded("test-plugin") is plugin

    def test_get_loaded_missing(self) -> None:
        loader = PluginLoader()
        assert loader.get_loaded("nope") is None

    def test_validate_valid(self) -> None:
        info = PluginInfo(name="p", version="1.0")
        errors = PluginLoader().validate(info)
        assert errors == []

    def test_validate_missing_name(self) -> None:
        info = PluginInfo(name="", version="1.0")
        errors = PluginLoader().validate(info)
        assert any("name" in e.lower() for e in errors)

    def test_validate_missing_dependency(self) -> None:
        info = PluginInfo(name="p", version="1.0", dependencies=["dep-a"])
        errors = PluginLoader().validate(info, available={"dep-b"})
        assert any("dep-a" in e for e in errors)

    def test_validate_dependency_available(self) -> None:
        info = PluginInfo(name="p", version="1.0", dependencies=["dep-a"])
        errors = PluginLoader().validate(info, available={"dep-a"})
        assert errors == []

    def test_discover_empty(self, tmp_path) -> None:
        discovered = PluginLoader().discover([str(tmp_path)])
        assert discovered == []

    def test_discover_finds_packages(self, tmp_path) -> None:
        pkg = tmp_path / "my_plugin"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        discovered = PluginLoader().discover([str(tmp_path)])
        assert len(discovered) == 1
        assert discovered[0].name == "my_plugin"


# --- PluginRegistry ---

class TestPluginRegistry:
    def test_register_and_get(self) -> None:
        reg = PluginRegistry()
        plugin = _make_plugin("alpha")
        reg.register(plugin)
        assert reg.get("alpha") is plugin

    def test_register_duplicate(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("alpha"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_make_plugin("alpha"))

    def test_unregister(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("alpha"))
        assert reg.unregister("alpha") is True
        assert reg.get("alpha") is None

    def test_unregister_nonexistent(self) -> None:
        reg = PluginRegistry()
        assert reg.unregister("nope") is False

    def test_enable_disable(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("alpha"))
        reg.enable("alpha")
        assert reg.get_state("alpha") == PluginState.ACTIVE

        reg.disable("alpha")
        assert reg.get_state("alpha") == PluginState.DISABLED

    def test_enable_nonexistent(self) -> None:
        reg = PluginRegistry()
        with pytest.raises(KeyError):
            reg.enable("nope")

    def test_list_by_state(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("a"))
        reg.register(_make_plugin("b"))
        reg.enable("a")

        active = reg.list(state=PluginState.ACTIVE)
        assert len(active) == 1
        assert active[0].info().name == "a"

    def test_list_by_capability(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("a", caps=[PluginCapability.TOOL_PROVIDER]))
        reg.register(_make_plugin("b", caps=[PluginCapability.MIDDLEWARE]))

        tools = reg.list(capability=PluginCapability.TOOL_PROVIDER)
        assert len(tools) == 1
        assert tools[0].info().name == "a"

    def test_get_by_capability(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("a", caps=[PluginCapability.EVENT_LISTENER]))
        reg.register(_make_plugin("b", caps=[PluginCapability.EVENT_LISTENER]))
        reg.register(_make_plugin("c", caps=[PluginCapability.MIDDLEWARE]))

        listeners = reg.get_by_capability(PluginCapability.EVENT_LISTENER)
        assert len(listeners) == 2

    def test_dependency_order_activation(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("core"))
        reg.register(_make_plugin("ext", deps=["core"]))

        order = reg.activate_in_dependency_order()
        assert order.index("core") < order.index("ext")

    def test_circular_dependency_detected(self) -> None:
        reg = PluginRegistry()
        reg.register(_make_plugin("a", deps=["b"]))
        reg.register(_make_plugin("b", deps=["a"]))

        with pytest.raises(ValueError, match="Circular dependency"):
            reg.activate_in_dependency_order()

    def test_count(self) -> None:
        reg = PluginRegistry()
        assert reg.count == 0
        reg.register(_make_plugin("a"))
        reg.register(_make_plugin("b"))
        assert reg.count == 2

    def test_unregister_deactivates(self) -> None:
        reg = PluginRegistry()
        plugin = _make_plugin("a")
        reg.register(plugin)
        reg.enable("a")
        assert plugin.state == PluginState.ACTIVE

        reg.unregister("a")
        assert plugin.state == PluginState.DISABLED


# --- HookSystem ---

class TestHookSystem:
    def test_predefined_hooks_exist(self) -> None:
        hooks = HookSystem()
        for name in ["pre_agent_create", "post_agent_create", "pre_workflow_execute", "post_workflow_execute", "on_error"]:
            assert hooks.get_hook(name) is not None

    def test_register_custom_hook(self) -> None:
        hooks = HookSystem()
        hp = hooks.register_hook("custom_hook", "my hook")
        assert hp.name == "custom_hook"
        assert hooks.get_hook("custom_hook") is not None

    def test_register_duplicate_hook(self) -> None:
        hooks = HookSystem()
        with pytest.raises(ValueError, match="already registered"):
            hooks.register_hook("on_error")

    def test_subscribe_and_trigger(self) -> None:
        hooks = HookSystem()
        results_collector: list[str] = []
        hooks.subscribe("on_error", lambda ctx: results_collector.append("handled"), handler_name="err_handler")

        results = hooks.trigger("on_error", {"error": "test"})
        assert len(results) == 1
        assert results[0].handler_name == "err_handler"
        assert results[0].error is None
        assert len(results_collector) == 1

    def test_trigger_priority_order(self) -> None:
        hooks = HookSystem()
        order: list[str] = []
        hooks.subscribe("on_error", lambda ctx: order.append("low"), priority=200, handler_name="low")
        hooks.subscribe("on_error", lambda ctx: order.append("high"), priority=10, handler_name="high")

        hooks.trigger("on_error")
        assert order == ["high", "low"]

    def test_trigger_captures_errors(self) -> None:
        hooks = HookSystem()
        hooks.subscribe("on_error", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")), handler_name="bad")

        results = hooks.trigger("on_error")
        assert len(results) == 1
        assert results[0].error == "boom"

    def test_trigger_returns_results(self) -> None:
        hooks = HookSystem()
        hooks.subscribe("on_error", lambda ctx: 42, handler_name="calc")

        results = hooks.trigger("on_error")
        assert results[0].result == 42

    def test_trigger_unknown_hook(self) -> None:
        hooks = HookSystem()
        with pytest.raises(KeyError, match="Unknown hook"):
            hooks.trigger("nonexistent")

    def test_subscribe_unknown_hook(self) -> None:
        hooks = HookSystem()
        with pytest.raises(KeyError, match="Unknown hook"):
            hooks.subscribe("nonexistent", lambda ctx: None)

    def test_unsubscribe(self) -> None:
        hooks = HookSystem()
        sub_id = hooks.subscribe("on_error", lambda ctx: None)
        assert hooks.subscriber_count("on_error") == 1

        assert hooks.unsubscribe("on_error", sub_id) is True
        assert hooks.subscriber_count("on_error") == 0

    def test_unsubscribe_nonexistent(self) -> None:
        hooks = HookSystem()
        assert hooks.unsubscribe("on_error", "fake") is False

    def test_hook_result_duration(self) -> None:
        hooks = HookSystem()
        hooks.subscribe("on_error", lambda ctx: None, handler_name="fast")
        results = hooks.trigger("on_error")
        assert results[0].duration >= 0

    def test_list_hooks(self) -> None:
        hooks = HookSystem()
        all_hooks = hooks.list_hooks()
        assert len(all_hooks) >= 5
        names = {h.name for h in all_hooks}
        assert "pre_agent_create" in names

    def test_trigger_with_context(self) -> None:
        hooks = HookSystem()
        received: list[dict] = []
        hooks.subscribe("pre_agent_create", lambda ctx: received.append(ctx))

        hooks.trigger("pre_agent_create", {"agent_name": "test-agent"})
        assert received[0]["agent_name"] == "test-agent"
