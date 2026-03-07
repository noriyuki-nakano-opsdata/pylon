"""Tests for Pylon configuration management system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pylon.config.loader import ConfigLoader, ConfigSource
from pylon.config.registry import (
    ConfigRegistry,
    FrozenConfigError,
    get_registry,
    reset_registry,
)
from pylon.config.resolver import ConfigResolver, InMemorySecretProvider
from pylon.config.validator import (
    AgentConfigSchema,
    ConfigSchema,
    ConfigValidator,
    FieldConstraint,
    ServerConfigSchema,
    WorkflowConfigSchema,
)

# --- ConfigLoader ---

class TestConfigLoader:
    def test_load_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("name: test\nport: 8080\n")
        config = ConfigLoader.load_yaml(f)
        assert config["name"] == "test"
        assert config["port"] == 8080

    def test_load_yaml_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load_yaml(tmp_path / "nope.yaml")

    def test_load_yaml_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yaml"
        f.write_text("")
        assert ConfigLoader.load_yaml(f) == {}

    def test_load_json(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"host": "localhost", "port": 3000}))
        config = ConfigLoader.load_json(f)
        assert config["host"] == "localhost"
        assert config["port"] == 3000

    def test_load_json_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load_json(tmp_path / "nope.json")

    def test_load_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYLON_SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("PYLON_SERVER_PORT", "9090")
        monkeypatch.setenv("OTHER_VAR", "ignored")

        config = ConfigLoader.load_env("PYLON_")
        assert config["server"]["host"] == "0.0.0.0"
        assert config["server"]["port"] == "9090"
        assert "other" not in config

    def test_merge_simple(self) -> None:
        a = {"host": "localhost", "port": 8080}
        b = {"port": 9090, "debug": True}
        merged = ConfigLoader.merge(a, b)
        assert merged == {"host": "localhost", "port": 9090, "debug": True}

    def test_merge_deep(self) -> None:
        a = {"server": {"host": "localhost", "port": 8080}}
        b = {"server": {"port": 9090}}
        merged = ConfigLoader.merge(a, b)
        assert merged["server"]["host"] == "localhost"
        assert merged["server"]["port"] == 9090

    def test_merge_multiple(self) -> None:
        a = {"a": 1}
        b = {"b": 2}
        c = {"a": 3, "c": 4}
        merged = ConfigLoader.merge(a, b, c)
        assert merged == {"a": 3, "b": 2, "c": 4}

    def test_config_source_enum(self) -> None:
        assert ConfigSource.YAML.value == "yaml"
        assert ConfigSource.ENV.value == "env"
        assert ConfigSource.DEFAULT.value == "default"


# --- ConfigValidator ---

class TestConfigValidator:
    def test_valid_config(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("name", str, required=True)],
        )
        result = ConfigValidator.validate({"name": "hello"}, schema)
        assert result.valid
        assert len(result.errors) == 0

    def test_missing_required(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("name", str, required=True)],
        )
        result = ConfigValidator.validate({}, schema)
        assert not result.valid
        assert any("required" in e.message for e in result.errors)

    def test_type_mismatch(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("port", int)],
        )
        result = ConfigValidator.validate({"port": "not_a_number"}, schema)
        assert not result.valid

    def test_type_coercion_bool(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("debug", bool)],
        )
        config = {"debug": "true"}
        result = ConfigValidator.validate(config, schema)
        assert result.valid
        assert config["debug"] is True

    def test_type_coercion_int(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("port", int)],
        )
        config = {"port": "3600"}
        result = ConfigValidator.validate(config, schema)
        assert result.valid
        assert config["port"] == 3600

    def test_min_max_value(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("port", int, min_value=1, max_value=65535)],
        )
        assert ConfigValidator.validate({"port": 8080}, schema).valid
        assert not ConfigValidator.validate({"port": 0}, schema).valid
        assert not ConfigValidator.validate({"port": 70000}, schema).valid

    def test_choices(self) -> None:
        schema = ConfigSchema(
            name="test",
            fields=[FieldConstraint("level", str, choices=["A0", "A1", "A2"])],
        )
        assert ConfigValidator.validate({"level": "A1"}, schema).valid
        assert not ConfigValidator.validate({"level": "A5"}, schema).valid

    def test_agent_config_schema(self) -> None:
        config = {"name": "agent-1", "autonomy": "A2", "sandbox": "docker"}
        result = ConfigValidator.validate(config, AgentConfigSchema)
        assert result.valid

    def test_workflow_config_schema(self) -> None:
        assert ConfigValidator.validate({"type": "graph"}, WorkflowConfigSchema).valid
        assert not ConfigValidator.validate({"type": "pipeline"}, WorkflowConfigSchema).valid

    def test_server_config_schema(self) -> None:
        config = {"host": "0.0.0.0", "port": "8080", "debug": "false"}
        result = ConfigValidator.validate(config, ServerConfigSchema)
        assert result.valid
        assert config["port"] == 8080
        assert config["debug"] is False


# --- ConfigResolver ---

class TestConfigResolver:
    def test_resolve_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_HOST", "example.com")
        result = ConfigResolver.resolve_env("host=${MY_HOST}")
        assert result == "host=example.com"

    def test_resolve_env_missing(self) -> None:
        result = ConfigResolver.resolve_env("host=${NONEXISTENT_VAR_12345}")
        assert result == "host=${NONEXISTENT_VAR_12345}"

    def test_resolve_secrets_simple(self) -> None:
        provider = InMemorySecretProvider({"db_pass": "s3cret"})
        config = {"database": {"password": "${secret:db_pass}"}}
        resolved = ConfigResolver.resolve_secrets(config, provider)
        assert resolved["database"]["password"] == "s3cret"

    def test_resolve_secrets_nested(self) -> None:
        provider = InMemorySecretProvider({"key1": "val1", "key2": "val2"})
        config = {
            "a": {"b": "${secret:key1}"},
            "c": ["${secret:key2}", "plain"],
        }
        resolved = ConfigResolver.resolve_secrets(config, provider)
        assert resolved["a"]["b"] == "val1"
        assert resolved["c"][0] == "val2"
        assert resolved["c"][1] == "plain"

    def test_resolve_secrets_missing(self) -> None:
        provider = InMemorySecretProvider()
        config = {"key": "${secret:missing}"}
        resolved = ConfigResolver.resolve_secrets(config, provider)
        assert resolved["key"] == "${secret:missing}"

    def test_resolve_non_string_passthrough(self) -> None:
        provider = InMemorySecretProvider()
        config = {"count": 42, "flag": True}
        resolved = ConfigResolver.resolve_secrets(config, provider)
        assert resolved["count"] == 42
        assert resolved["flag"] is True

    def test_in_memory_provider_set(self) -> None:
        provider = InMemorySecretProvider()
        provider.set("key", "value")
        assert provider.get_secret("key") == "value"

    def test_in_memory_provider_missing(self) -> None:
        provider = InMemorySecretProvider()
        with pytest.raises(KeyError, match="Secret not found"):
            provider.get_secret("nope")


# --- ConfigRegistry ---

class TestConfigRegistry:
    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        reset_registry()

    def test_register_and_get(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"host": "localhost"})
        config = reg.get("app")
        assert config is not None
        assert config["host"] == "localhost"

    def test_get_returns_copy(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"host": "localhost"})
        config = reg.get("app")
        config["host"] = "modified"
        assert reg.get("app")["host"] == "localhost"

    def test_get_nonexistent(self) -> None:
        reg = ConfigRegistry()
        assert reg.get("nope") is None

    def test_watch_notification(self) -> None:
        reg = ConfigRegistry()
        notifications: list[dict] = []
        reg.watch("app", lambda c: notifications.append(c))

        reg.register("app", {"v": 1})
        assert len(notifications) == 1
        assert notifications[0]["v"] == 1

    def test_unwatch(self) -> None:
        reg = ConfigRegistry()
        notifications: list[dict] = []
        wid = reg.watch("app", lambda c: notifications.append(c))

        reg.register("app", {"v": 1})
        assert len(notifications) == 1

        reg.unwatch("app", wid)
        reg.register("app", {"v": 2})
        assert len(notifications) == 1  # no new notification

    def test_unwatch_nonexistent(self) -> None:
        reg = ConfigRegistry()
        assert reg.unwatch("app", "fake-id") is False

    def test_overlay(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"host": "localhost", "port": 8080})
        merged = reg.overlay("app", {"port": 9090, "debug": True})
        assert merged["host"] == "localhost"
        assert merged["port"] == 9090
        assert merged["debug"] is True

    def test_freeze(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"host": "localhost"})
        frozen = reg.freeze("app")
        assert frozen is not None
        assert frozen["host"] == "localhost"
        assert reg.is_frozen("app")

    def test_freeze_prevents_register(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"v": 1})
        reg.freeze("app")
        with pytest.raises(FrozenConfigError):
            reg.register("app", {"v": 2})

    def test_freeze_prevents_overlay(self) -> None:
        reg = ConfigRegistry()
        reg.register("app", {"v": 1})
        reg.freeze("app")
        with pytest.raises(FrozenConfigError):
            reg.overlay("app", {"v": 2})

    def test_global_singleton(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_global_singleton_reset(self) -> None:
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()
        assert r1 is not r2
