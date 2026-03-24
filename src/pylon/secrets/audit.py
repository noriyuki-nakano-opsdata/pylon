"""Secret access audit logging.

Records all access to secrets with actor, action, and timestamp
for compliance and forensics.
"""

from __future__ import annotations

import enum
import json
import time
from dataclasses import dataclass
from pathlib import Path


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


class JSONLSecretAudit(SecretAudit):
    """Durable audit backend backed by an append-only JSONL file."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path).expanduser().resolve()
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def log_access(
        self,
        key: str,
        actor: str,
        action: AccessAction,
        *,
        details: str = "",
    ) -> AccessLogEntry:
        entry = super().log_access(key, actor, action, details=details)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "key": entry.key,
                        "actor": entry.actor,
                        "action": entry.action.value,
                        "timestamp": entry.timestamp,
                        "details": entry.details,
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
        return entry

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            self._entries.append(
                AccessLogEntry(
                    key=str(payload["key"]),
                    actor=str(payload["actor"]),
                    action=AccessAction(str(payload["action"])),
                    timestamp=float(payload["timestamp"]),
                    details=str(payload.get("details", "")),
                )
            )
