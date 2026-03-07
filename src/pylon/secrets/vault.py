"""Vault provider — HashiCorp Vault-compatible interface.

Defines a VaultProvider protocol and an in-memory implementation.
Secret path convention: {mount}/{tenant}/{key}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VaultConfig:
    """Configuration for connecting to a Vault instance."""

    address: str = "http://127.0.0.1:8200"
    token: str = ""
    mount_path: str = "secret"
    namespace: str = ""


class VaultProvider(Protocol):
    """Protocol for Vault-compatible secret backends."""

    def get(self, path: str) -> dict[str, str] | None: ...
    def put(self, path: str, data: dict[str, str]) -> bool: ...
    def delete(self, path: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


def build_path(mount: str, tenant: str, key: str) -> str:
    """Build a Vault secret path: {mount}/{tenant}/{key}."""
    parts = [p for p in (mount, tenant, key) if p]
    return "/".join(parts)


class InMemoryVaultProvider:
    """In-memory Vault provider for testing."""

    def __init__(self, config: VaultConfig | None = None) -> None:
        self._config = config or VaultConfig()
        self._store: dict[str, dict[str, str]] = {}

    @property
    def config(self) -> VaultConfig:
        return self._config

    def get(self, path: str) -> dict[str, str] | None:
        return self._store.get(path)

    def put(self, path: str, data: dict[str, str]) -> bool:
        self._store[path] = dict(data)
        return True

    def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    def list(self, prefix: str) -> list[str]:
        return [k for k in self._store if k.startswith(prefix)]
