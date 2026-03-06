"""ConfigLoader - Configuration file loading and merging."""

from __future__ import annotations

import copy
import enum
import json
import os
from pathlib import Path
from typing import Any

import yaml


class ConfigSource(enum.Enum):
    """Source type for configuration data."""

    YAML = "yaml"
    JSON = "json"
    ENV = "env"
    DEFAULT = "default"


class ConfigLoader:
    """Loads configuration from multiple sources and merges them."""

    @staticmethod
    def load_yaml(path: str | Path) -> dict[str, Any]:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        content = path.read_text()
        data = yaml.safe_load(content)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict at top level, got {type(data).__name__}")
        return data

    @staticmethod
    def load_json(path: str | Path) -> dict[str, Any]:
        """Load configuration from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        content = path.read_text()
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict at top level, got {type(data).__name__}")
        return data

    @staticmethod
    def load_env(prefix: str = "PYLON_") -> dict[str, Any]:
        """Load configuration from environment variables with a given prefix.

        PYLON_SERVER_HOST -> {"server": {"host": value}}
        Underscores after prefix are treated as nested key separators.
        """
        result: dict[str, Any] = {}
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].lower().split("_")
            d = result
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = value
        return result

    @staticmethod
    def merge(*configs: dict[str, Any]) -> dict[str, Any]:
        """Deep merge multiple configs. Later configs override earlier ones."""
        result: dict[str, Any] = {}
        for config in configs:
            _deep_merge(result, config)
        return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge override into base, mutating base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
