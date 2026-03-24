"""Vault provider — HashiCorp Vault-compatible interface.

Defines the pluggable VaultProvider contract plus reference and production
backends. Secret path convention: ``{mount}/{tenant}/{key}``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request


class VaultError(RuntimeError):
    """Raised when a Vault backend operation fails."""


@dataclass(frozen=True)
class VaultConfig:
    """Configuration for connecting to a Vault instance."""

    address: str = "http://127.0.0.1:8200"
    token: str = ""
    mount_path: str = "secret"
    namespace: str = ""
    timeout_seconds: float = 5.0


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


_SALT_SIZE = 16
_KDF_ITERATIONS = 100_000


def _derive_key(master_key: bytes, salt: bytes, length: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", master_key, salt, _KDF_ITERATIONS, dklen=length)


def _xor_bytes(data: bytes, key_stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, key_stream))


def _encrypt_value(value: str, master_key: bytes) -> str:
    salt = os.urandom(_SALT_SIZE)
    plaintext = value.encode("utf-8")
    key_stream = _derive_key(master_key, salt, len(plaintext))
    ciphertext = _xor_bytes(plaintext, key_stream)
    return base64.b64encode(salt + ciphertext).decode("ascii")


def _decrypt_value(payload: str, master_key: bytes) -> str:
    try:
        raw = base64.b64decode(payload.encode("ascii"))
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise VaultError("Invalid encrypted vault payload") from exc
    salt = raw[:_SALT_SIZE]
    ciphertext = raw[_SALT_SIZE:]
    key_stream = _derive_key(master_key, salt, len(ciphertext))
    plaintext = _xor_bytes(ciphertext, key_stream)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VaultError("Vault payload could not be decrypted with the provided key") from exc


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


class FileVaultProvider:
    """Durable encrypted vault backend for bootstrap and single-node deployments."""

    def __init__(
        self,
        path: str | Path,
        *,
        config: VaultConfig | None = None,
        encryption_key: bytes | None = None,
    ) -> None:
        self._config = config or VaultConfig(address="file://local")
        self._path = Path(path).expanduser().resolve()
        key = encryption_key
        if key is None:
            env_key = os.getenv("PYLON_FILE_VAULT_KEY", "").encode("utf-8")
            key = env_key or None
        if not key:
            raise VaultError(
                "FileVaultProvider requires encryption_key or PYLON_FILE_VAULT_KEY"
            )
        self._master_key = bytes(key)

    @property
    def config(self) -> VaultConfig:
        return self._config

    @property
    def path(self) -> Path:
        return self._path

    def get(self, path: str) -> dict[str, str] | None:
        payload = self._load_store().get(path)
        if not isinstance(payload, dict):
            return None
        return {
            str(key): _decrypt_value(str(value), self._master_key)
            for key, value in payload.items()
        }

    def put(self, path: str, data: dict[str, str]) -> bool:
        store = self._load_store()
        store[path] = {
            str(key): _encrypt_value(str(value), self._master_key)
            for key, value in data.items()
        }
        self._write_store(store)
        return True

    def delete(self, path: str) -> bool:
        store = self._load_store()
        deleted = store.pop(path, None) is not None
        if deleted:
            self._write_store(store)
        return deleted

    def list(self, prefix: str) -> list[str]:
        return [key for key in self._load_store().keys() if key.startswith(prefix)]

    def _load_store(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            raise VaultError("File vault store must be a JSON object")
        store: dict[str, dict[str, str]] = {}
        for path, payload in raw.items():
            if isinstance(path, str) and isinstance(payload, dict):
                store[path] = {
                    str(key): str(value) for key, value in payload.items()
                }
        return store

    def _write_store(self, payload: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self._path)
        os.chmod(self._path, 0o600)


class HTTPVaultProvider:
    """HashiCorp Vault KV v2 backend over the HTTP API."""

    def __init__(self, config: VaultConfig) -> None:
        self._config = config

    @property
    def config(self) -> VaultConfig:
        return self._config

    def get(self, path: str) -> dict[str, str] | None:
        try:
            payload = self._request("GET", self._data_url(path))
        except urllib_error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise self._wrap_http_error("read", path, exc) from exc
        data = ((payload.get("data") or {}).get("data") or {})
        if not isinstance(data, dict):
            raise VaultError(f"Vault returned invalid secret payload for {path}")
        return {
            str(key): str(value)
            for key, value in data.items()
        }

    def put(self, path: str, data: dict[str, str]) -> bool:
        try:
            self._request(
                "POST",
                self._data_url(path),
                payload={"data": {str(key): str(value) for key, value in data.items()}},
            )
        except urllib_error.HTTPError as exc:
            raise self._wrap_http_error("write", path, exc) from exc
        return True

    def delete(self, path: str) -> bool:
        try:
            self._request("DELETE", self._metadata_url(path))
        except urllib_error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise self._wrap_http_error("delete", path, exc) from exc
        return True

    def list(self, prefix: str) -> list[str]:
        try:
            payload = self._request("LIST", self._metadata_url(prefix))
        except urllib_error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise self._wrap_http_error("list", prefix, exc) from exc
        keys = ((payload.get("data") or {}).get("keys") or [])
        if not isinstance(keys, list):
            raise VaultError(f"Vault returned invalid key listing for {prefix}")
        normalized_prefix = prefix.rstrip("/")
        return [
            f"{normalized_prefix}/{str(key).rstrip('/')}".strip("/")
            for key in keys
        ]

    def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {
            "accept": "application/json",
            "x-vault-token": self._config.token,
        }
        if body is not None:
            headers["content-type"] = "application/json"
        if self._config.namespace:
            headers["x-vault-namespace"] = self._config.namespace
        request = urllib_request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        with urllib_request.urlopen(
            request,
            timeout=self._config.timeout_seconds,
        ) as response:
            raw = response.read()
        parsed = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(parsed, dict):
            raise VaultError(f"Vault returned non-object JSON for {url}")
        return parsed

    def _data_url(self, path: str) -> str:
        mount, relative_path = self._split_path(path)
        if not relative_path:
            raise VaultError("Vault data path must include a key name")
        return f"{self._config.address.rstrip('/')}/v1/{mount}/data/{relative_path}"

    def _metadata_url(self, path: str) -> str:
        mount, relative_path = self._split_path(path)
        suffix = f"/{relative_path}" if relative_path else ""
        return f"{self._config.address.rstrip('/')}/v1/{mount}/metadata{suffix}"

    def _split_path(self, path: str) -> tuple[str, str]:
        normalized = path.strip("/")
        if not normalized:
            raise VaultError("Vault path cannot be empty")
        mount, _, relative_path = normalized.partition("/")
        return mount, relative_path

    @staticmethod
    def _wrap_http_error(action: str, path: str, exc: urllib_error.HTTPError) -> VaultError:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # pragma: no cover - defensive boundary
            payload = {}
        message = ""
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, list):
                message = "; ".join(str(item) for item in errors if str(item).strip())
        if not message:
            message = f"Vault {action} failed with HTTP {exc.code}"
        return VaultError(f"{message} ({path})")
