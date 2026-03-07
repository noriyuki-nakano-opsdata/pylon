"""ConfigResolver - Environment variable and secret resolution."""

from __future__ import annotations

import os
import re
from typing import Any, Protocol


class SecretProvider(Protocol):
    """Protocol for secret providers."""

    def get_secret(self, key: str) -> str: ...


class InMemorySecretProvider:
    """In-memory secret provider for testing."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = secrets or {}

    def set(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def get_secret(self, key: str) -> str:
        if key not in self._secrets:
            raise KeyError(f"Secret not found: {key}")
        return self._secrets[key]


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_PATTERN = re.compile(r"\$\{secret:([^}]+)\}")


class ConfigResolver:
    """Resolves ${ENV_VAR} and ${secret:key} patterns in configuration."""

    @staticmethod
    def resolve_env(value: str) -> str:
        """Resolve ${ENV_VAR} patterns in a string using os.environ."""
        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is None:
                return match.group(0)  # leave unresolved
            return env_val

        return _ENV_PATTERN.sub(replacer, value)

    @staticmethod
    def resolve_secrets(config: dict[str, Any], provider: SecretProvider) -> dict[str, Any]:
        """Resolve ${secret:key} patterns recursively in a config dict."""
        return _resolve_recursive(config, provider)


def _resolve_recursive(obj: Any, provider: SecretProvider) -> Any:
    if isinstance(obj, str):
        return _resolve_string(obj, provider)
    if isinstance(obj, dict):
        return {k: _resolve_recursive(v, provider) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_recursive(item, provider) for item in obj]
    return obj


def _resolve_string(value: str, provider: SecretProvider) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        try:
            return provider.get_secret(key)
        except KeyError:
            return match.group(0)  # leave unresolved

    return _SECRET_PATTERN.sub(replacer, value)
