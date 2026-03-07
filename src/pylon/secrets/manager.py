"""Secret Manager — versioned in-memory secret storage.

Stores secrets with base64 encoding, version tracking,
expiry, and metadata.

WARNING: base64 encoding is used solely for transport/storage formatting
and provides NO security or confidentiality. Secrets are trivially
recoverable from base64. In production, use proper encryption at rest
(e.g., AES-256-GCM via a KMS).
"""

from __future__ import annotations

import base64
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

    encoded_value: str  # base64-encoded (NOT encrypted — see module docstring)
    version: int
    created_at: float
    expires_at: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)


def _encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode(encoded: str) -> str:
    return base64.b64decode(encoded.encode("ascii")).decode("utf-8")


class SecretManager:
    """In-memory versioned secret manager with base64 encoding.

    WARNING: base64 is an encoding, not encryption. It provides no
    confidentiality. See module docstring for details.
    """

    def __init__(self) -> None:
        # key -> list of versions (index 0 = version 1)
        self._store: dict[str, list[_StoredSecret]] = {}

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
            encoded_value=_encode(value),
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

    @staticmethod
    def _to_value(entry: _StoredSecret) -> SecretValue:
        return SecretValue(
            value=_decode(entry.encoded_value),
            version=entry.version,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
            metadata=entry.metadata,
        )
