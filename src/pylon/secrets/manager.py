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
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field


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
