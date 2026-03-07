"""Secret access audit logging.

Records all access to secrets with actor, action, and timestamp
for compliance and forensics.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass


class AccessAction(enum.Enum):
    """Types of secret access."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ROTATE = "rotate"
    LIST = "list"


@dataclass
class AccessLogEntry:
    """A single audit log entry."""

    key: str
    actor: str
    action: AccessAction
    timestamp: float
    details: str = ""


class SecretAudit:
    """In-memory secret access audit log."""

    def __init__(self) -> None:
        self._entries: list[AccessLogEntry] = []

    def log_access(
        self,
        key: str,
        actor: str,
        action: AccessAction,
        *,
        details: str = "",
    ) -> AccessLogEntry:
        """Record a secret access event."""
        entry = AccessLogEntry(
            key=key,
            actor=actor,
            action=action,
            timestamp=time.time(),
            details=details,
        )
        self._entries.append(entry)
        return entry

    def query(
        self,
        *,
        key: str | None = None,
        actor: str | None = None,
        action: AccessAction | None = None,
        from_time: float | None = None,
        to_time: float | None = None,
    ) -> list[AccessLogEntry]:
        """Query audit log with optional filters."""
        results: list[AccessLogEntry] = []
        for entry in self._entries:
            if key is not None and entry.key != key:
                continue
            if actor is not None and entry.actor != actor:
                continue
            if action is not None and entry.action != action:
                continue
            if from_time is not None and entry.timestamp < from_time:
                continue
            if to_time is not None and entry.timestamp > to_time:
                continue
            results.append(entry)
        return results

    def count(self) -> int:
        """Total number of audit entries."""
        return len(self._entries)
