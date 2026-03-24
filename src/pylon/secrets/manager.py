"""Secret Manager — versioned in-memory secret storage.

Stores secrets with PBKDF2-derived key encryption, version tracking,
expiry, and metadata.

NOTE: This implementation uses PBKDF2-HMAC + XOR stream cipher for
at-rest obfuscation. For production deployments, integrate with a
dedicated secrets backend such as HashiCorp Vault, AWS KMS, or
GCP Secret Manager for proper encryption and key management.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field

from pylon.secrets.audit import AccessAction, SecretAudit
from pylon.secrets.vault import VaultProvider, build_path


@dataclass
class SecretMeta:
    """Secret metadata (no value)."""

    key: str
    version: int
    created_at: float
    expires_at: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class SecretValue:
    """Full secret including value."""

    value: str
    version: int
    created_at: float
    expires_at: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class _StoredSecret:
    """Internal versioned storage entry."""

    encrypted_value: bytes  # salt + ciphertext (PBKDF2 + XOR)
    version: int
    created_at: float
    expires_at: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)


_SALT_SIZE = 16
_KDF_ITERATIONS = 100_000


def _derive_key(master_key: bytes, salt: bytes, length: int) -> bytes:
    """Derive a key stream of the given length using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", master_key, salt, _KDF_ITERATIONS, dklen=length)


def _xor_bytes(data: bytes, key_stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, key_stream))


def _encrypt(value: str, master_key: bytes) -> bytes:
    """Encrypt a string value. Returns salt + ciphertext."""
    salt = os.urandom(_SALT_SIZE)
    plaintext = value.encode("utf-8")
    key_stream = _derive_key(master_key, salt, len(plaintext))
    ciphertext = _xor_bytes(plaintext, key_stream)
    return salt + ciphertext


def _decrypt(encrypted: bytes, master_key: bytes) -> str:
    """Decrypt a salt + ciphertext blob back to string."""
    salt = encrypted[:_SALT_SIZE]
    ciphertext = encrypted[_SALT_SIZE:]
    key_stream = _derive_key(master_key, salt, len(ciphertext))
    plaintext = _xor_bytes(ciphertext, key_stream)
    return plaintext.decode("utf-8")


class SecretManager:
    """In-memory versioned secret manager with PBKDF2+XOR encryption.

    NOTE: For production, use Vault or a KMS integration. See module docstring.
    """

    def __init__(self, *, encryption_key: bytes | None = None) -> None:
        # key -> list of versions (index 0 = version 1)
        self._store: dict[str, list[_StoredSecret]] = {}
        self._master_key = encryption_key or secrets.token_bytes(32)

    def store(
        self,
        key: str,
        value: str,
        *,
        metadata: dict[str, str] | None = None,
        expires_at: float | None = None,
    ) -> SecretMeta:
        """Store a secret. Creates a new version if key exists."""
        versions = self._store.setdefault(key, [])
        version = len(versions) + 1
        now = time.time()
        entry = _StoredSecret(
            encrypted_value=_encrypt(value, self._master_key),
            version=version,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        versions.append(entry)
        return SecretMeta(
            key=key,
            version=version,
            created_at=now,
            expires_at=expires_at,
            metadata=entry.metadata,
        )

    def get(self, key: str) -> SecretValue | None:
        """Get the latest version of a secret."""
        versions = self._store.get(key)
        if not versions:
            return None
        return self._to_value(versions[-1])

    def get_version(self, key: str, version: int) -> SecretValue | None:
        """Get a specific version of a secret."""
        versions = self._store.get(key)
        if not versions or version < 1 or version > len(versions):
            return None
        return self._to_value(versions[version - 1])

    def delete(self, key: str) -> bool:
        """Delete all versions of a secret. Returns True if existed."""
        return self._store.pop(key, None) is not None

    def list(self, prefix: str = "") -> list[SecretMeta]:
        """List secret metadata, optionally filtered by key prefix."""
        result: list[SecretMeta] = []
        for key, versions in self._store.items():
            if key.startswith(prefix) and versions:
                latest = versions[-1]
                result.append(SecretMeta(
                    key=key,
                    version=latest.version,
                    created_at=latest.created_at,
                    expires_at=latest.expires_at,
                    metadata=latest.metadata,
                ))
        return result

    def version_count(self, key: str) -> int:
        """Return the number of versions stored for a key."""
        versions = self._store.get(key)
        return len(versions) if versions else 0

    def _to_value(self, entry: _StoredSecret) -> SecretValue:
        return SecretValue(
            value=_decrypt(entry.encrypted_value, self._master_key),
            version=entry.version,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
            metadata=entry.metadata,
        )


class VaultSecretManager:
    """Tenant-aware secret manager backed by a pluggable VaultProvider."""

    _BUNDLE_FIELD = "_pylon_versions"

    def __init__(
        self,
        tenant: str,
        provider: VaultProvider,
        *,
        mount_path: str = "secret",
        audit: SecretAudit | None = None,
    ) -> None:
        self._tenant = tenant.strip()
        self._provider = provider
        self._mount_path = mount_path.strip("/") or "secret"
        self._audit = audit

    @property
    def tenant(self) -> str:
        return self._tenant

    def store(
        self,
        key: str,
        value: str,
        *,
        metadata: dict[str, str] | None = None,
        expires_at: float | None = None,
        actor: str = "system",
    ) -> SecretMeta:
        versions = self._load_versions(key)
        version = len(versions) + 1
        now = time.time()
        versions.append(
            {
                "value": value,
                "version": version,
                "created_at": now,
                "expires_at": expires_at,
                "metadata": dict(metadata or {}),
            }
        )
        self._save_versions(key, versions)
        self._log(key, actor, AccessAction.WRITE, details=f"v{version}")
        return SecretMeta(
            key=key,
            version=version,
            created_at=now,
            expires_at=expires_at,
            metadata=dict(metadata or {}),
        )

    def get(
        self,
        key: str,
        *,
        actor: str = "system",
    ) -> SecretValue | None:
        versions = self._load_versions(key)
        if not versions:
            return None
        self._log(key, actor, AccessAction.READ)
        return self._to_value_dict(versions[-1])

    def get_version(
        self,
        key: str,
        version: int,
        *,
        actor: str = "system",
    ) -> SecretValue | None:
        versions = self._load_versions(key)
        if version < 1 or version > len(versions):
            return None
        self._log(key, actor, AccessAction.READ, details=f"v{version}")
        return self._to_value_dict(versions[version - 1])

    def delete(
        self,
        key: str,
        *,
        actor: str = "system",
    ) -> bool:
        deleted = self._provider.delete(self._path_for(key))
        if deleted:
            self._log(key, actor, AccessAction.DELETE)
        return deleted

    def list(
        self,
        prefix: str = "",
        *,
        actor: str = "system",
    ) -> list[SecretMeta]:
        records: list[SecretMeta] = []
        for path in self._provider.list(self._path_for(prefix).rstrip("/")):
            key = self._key_from_path(path)
            if not key.startswith(prefix):
                continue
            versions = self._load_versions(key)
            if not versions:
                continue
            latest = versions[-1]
            records.append(
                SecretMeta(
                    key=key,
                    version=int(latest["version"]),
                    created_at=float(latest["created_at"]),
                    expires_at=(
                        float(latest["expires_at"])
                        if latest.get("expires_at") is not None
                        else None
                    ),
                    metadata={
                        str(item_key): str(item_value)
                        for item_key, item_value in dict(latest.get("metadata") or {}).items()
                    },
                )
            )
        self._log(prefix or "*", actor, AccessAction.LIST, details=f"{len(records)} keys")
        return records

    def version_count(self, key: str) -> int:
        return len(self._load_versions(key))

    def as_secret_provider(self, *, actor: str = "system") -> VaultSecretProvider:
        return VaultSecretProvider(self, actor=actor)

    def _path_for(self, key: str) -> str:
        return build_path(self._mount_path, self._tenant, key)

    def _key_from_path(self, path: str) -> str:
        prefix = build_path(self._mount_path, self._tenant, "")
        normalized_prefix = prefix.rstrip("/")
        return path.removeprefix(f"{normalized_prefix}/")

    def _load_versions(self, key: str) -> list[dict[str, object]]:
        payload = self._provider.get(self._path_for(key))
        if payload is None:
            return []
        raw_versions = payload.get(self._BUNDLE_FIELD)
        if not raw_versions:
            return []
        parsed = json.loads(raw_versions)
        if not isinstance(parsed, list):
            raise ValueError(f"Invalid secret version payload for {key}")
        return [
            {
                "value": str(item["value"]),
                "version": int(item["version"]),
                "created_at": float(item["created_at"]),
                "expires_at": (
                    float(item["expires_at"])
                    if item.get("expires_at") is not None
                    else None
                ),
                "metadata": {
                    str(meta_key): str(meta_value)
                    for meta_key, meta_value in dict(item.get("metadata") or {}).items()
                },
            }
            for item in parsed
            if isinstance(item, dict)
        ]

    def _save_versions(self, key: str, versions: list[dict[str, object]]) -> None:
        self._provider.put(
            self._path_for(key),
            {
                self._BUNDLE_FIELD: json.dumps(versions, ensure_ascii=False),
            },
        )

    def _to_value_dict(self, entry: dict[str, object]) -> SecretValue:
        return SecretValue(
            value=str(entry["value"]),
            version=int(entry["version"]),
            created_at=float(entry["created_at"]),
            expires_at=(
                float(entry["expires_at"])
                if entry.get("expires_at") is not None
                else None
            ),
            metadata={
                str(key): str(value)
                for key, value in dict(entry.get("metadata") or {}).items()
            },
        )

    def _log(
        self,
        key: str,
        actor: str,
        action: AccessAction,
        *,
        details: str = "",
    ) -> None:
        if self._audit is not None:
            self._audit.log_access(key, actor, action, details=details)


class VaultSecretProvider:
    """ConfigResolver-compatible adapter over VaultSecretManager."""

    def __init__(self, manager: VaultSecretManager, *, actor: str = "system") -> None:
        self._manager = manager
        self._actor = actor

    def get_secret(self, key: str) -> str:
        secret = self._manager.get(key, actor=self._actor)
        if secret is None:
            raise KeyError(f"Secret not found: {key}")
        return secret.value
