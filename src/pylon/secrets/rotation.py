"""Secret rotation — scheduling and expiry detection.

Manages rotation policies per key, checks for expiring secrets,
and records rotation events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pylon.secrets.manager import SecretManager, SecretMeta


@dataclass(frozen=True)
class RotationPolicy:
    """Rotation policy for a secret."""

    interval_seconds: int = 86400      # 24h
    max_age_seconds: int = 604800      # 7 days
    notify_before_seconds: int = 3600  # 1h


@dataclass
class RotationEvent:
    """Record of a rotation occurrence."""

    key: str
    old_version: int
    new_version: int
    rotated_at: float


class SecretRotation:
    """Manages secret rotation scheduling and expiry checks."""

    def __init__(self, manager: SecretManager) -> None:
        self._manager = manager
        self._policies: dict[str, RotationPolicy] = {}
        self._events: list[RotationEvent] = []

    def schedule_rotation(self, key: str, policy: RotationPolicy) -> None:
        """Register a rotation policy for a key."""
        self._policies[key] = policy

    def cancel_rotation(self, key: str) -> bool:
        """Cancel rotation for a key. Returns True if policy existed."""
        return self._policies.pop(key, None) is not None

    def get_policy(self, key: str) -> RotationPolicy | None:
        """Get the rotation policy for a key."""
        return self._policies.get(key)

    def check_expiring(self, threshold_seconds: float | None = None) -> list[SecretMeta]:
        """Return secrets that are expiring within threshold.

        If threshold is None, uses each policy's notify_before_seconds.
        Only checks secrets that have a rotation policy.
        """
        now = time.time()
        expiring: list[SecretMeta] = []

        for key, policy in self._policies.items():
            secret = self._manager.get(key)
            if secret is None:
                continue

            check_threshold = threshold_seconds if threshold_seconds is not None else policy.notify_before_seconds
            age = now - secret.created_at
            remaining = policy.max_age_seconds - age

            if remaining <= check_threshold:
                expiring.append(SecretMeta(
                    key=key,
                    version=secret.version,
                    created_at=secret.created_at,
                    expires_at=secret.expires_at,
                    metadata=secret.metadata,
                ))

        return expiring

    def rotate(self, key: str, new_value: str) -> RotationEvent | None:
        """Rotate a secret to a new value. Returns event or None if key not found."""
        current = self._manager.get(key)
        if current is None:
            return None

        old_version = current.version
        meta = self._manager.store(key, new_value, metadata=current.metadata)

        event = RotationEvent(
            key=key,
            old_version=old_version,
            new_version=meta.version,
            rotated_at=time.time(),
        )
        self._events.append(event)
        return event

    def get_events(self, key: str | None = None) -> list[RotationEvent]:
        """Get rotation events, optionally filtered by key."""
        if key is None:
            return list(self._events)
        return [e for e in self._events if e.key == key]
