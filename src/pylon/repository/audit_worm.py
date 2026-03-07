"""WORM Audit Repository — Write-Once Read-Many wrapper over AuditRepository.

Enforces immutability of audit entries after creation, provides JSONL
export/import with integrity verification, and retention policy support.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pylon.errors import (
    ImmutableEntryError,
    ImportValidationError,
    IntegrityViolationError,
)
from pylon.repository.audit import AuditEntry, AuditRepository


@dataclass
class ArchiveReport:
    entries_exported: int
    file_path: str
    chain_valid: bool
    hmac_valid: bool
    exported_at: datetime


class WORMAuditRepository:
    """Write-Once Read-Many wrapper around AuditRepository.

    Once an entry is appended, it cannot be modified or deleted.
    """

    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    async def append(
        self,
        *,
        tenant_id: str = "default",
        event_type: str,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        return await self._repo.append(
            tenant_id=tenant_id,
            event_type=event_type,
            actor=actor,
            action=action,
            details=details,
        )

    async def get(self, id: int) -> AuditEntry | None:
        return await self._repo.get(id)

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        return await self._repo.list(
            tenant_id=tenant_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )

    async def update(self, id: int, **kwargs: Any) -> None:
        raise ImmutableEntryError(
            f"Cannot modify WORM audit entry {id}",
            details={"entry_id": id, "attempted_fields": list(kwargs.keys())},
        )

    async def delete(self, id: int) -> None:
        raise ImmutableEntryError(
            f"Cannot delete WORM audit entry {id}",
            details={"entry_id": id},
        )

    async def verify_integrity(self) -> tuple[bool, str]:
        """Full chain verification including hash chain and HMAC presence check."""
        entries = await self._repo.list(limit=self._repo.count)
        if not entries:
            return True, "No entries to verify"

        for i, entry in enumerate(entries):
            if i == 0:
                if entry.prev_hash != "":
                    raise IntegrityViolationError(
                        f"Entry {entry.id}: first entry should have empty prev_hash",
                        details={"entry_id": entry.id},
                    )
            else:
                if entry.prev_hash != entries[i - 1].entry_hash:
                    raise IntegrityViolationError(
                        f"Entry {entry.id}: prev_hash mismatch (chain broken)",
                        details={
                            "entry_id": entry.id,
                            "expected": entries[i - 1].entry_hash,
                            "actual": entry.prev_hash,
                        },
                    )

            if not entry.entry_hash:
                raise IntegrityViolationError(
                    f"Entry {entry.id}: missing entry_hash",
                    details={"entry_id": entry.id},
                )
            if not entry.hmac_signature:
                raise IntegrityViolationError(
                    f"Entry {entry.id}: missing hmac_signature",
                    details={"entry_id": entry.id},
                )

        return True, f"Chain integrity verified ({len(entries)} entries)"

    def _entry_to_dict(self, entry: AuditEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "tenant_id": entry.tenant_id,
            "event_type": entry.event_type,
            "actor": entry.actor,
            "action": entry.action,
            "details": entry.details,
            "prev_hash": entry.prev_hash,
            "entry_hash": entry.entry_hash,
            "hmac_signature": entry.hmac_signature,
            "created_at": entry.created_at.isoformat(),
        }

    async def archive_to_jsonl(self, path: str | Path) -> ArchiveReport:
        """Export all entries to a JSONL file with integrity metadata."""
        entries = await self._repo.list(limit=self._repo.count)
        is_valid, msg = await self._repo.verify_chain()

        raw_path = Path(path)
        # Prevent path traversal: reject paths containing '..' before resolving
        if ".." in raw_path.parts:
            raise ValueError(f"Archive path must not contain '..': {path}")
        path = raw_path.resolve()
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(self._entry_to_dict(entry), sort_keys=True) + "\n")

        return ArchiveReport(
            entries_exported=len(entries),
            file_path=str(path),
            chain_valid=is_valid,
            hmac_valid=all(e.hmac_signature for e in entries),
            exported_at=datetime.now(timezone.utc),
        )

    async def import_from_jsonl(self, path: str | Path) -> list[AuditEntry]:
        """Import entries from JSONL, verifying chain integrity."""
        path = Path(path)
        imported: list[AuditEntry] = []

        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ImportValidationError(
                        f"Line {line_num}: invalid JSON",
                        details={"line": line_num, "error": str(exc)},
                    ) from exc

                required = {"id", "tenant_id", "event_type", "actor", "action",
                            "entry_hash", "hmac_signature", "prev_hash", "created_at"}
                missing = required - set(data.keys())
                if missing:
                    raise ImportValidationError(
                        f"Line {line_num}: missing fields {missing}",
                        details={"line": line_num, "missing": sorted(missing)},
                    )

                entry = AuditEntry(
                    id=data["id"],
                    tenant_id=data["tenant_id"],
                    event_type=data["event_type"],
                    actor=data["actor"],
                    action=data["action"],
                    details=data.get("details", {}),
                    prev_hash=data["prev_hash"],
                    entry_hash=data["entry_hash"],
                    hmac_signature=data["hmac_signature"],
                    created_at=datetime.fromisoformat(data["created_at"]),
                )

                if imported:
                    if entry.prev_hash != imported[-1].entry_hash:
                        raise ImportValidationError(
                            f"Line {line_num}: chain broken at entry {entry.id}",
                            details={
                                "line": line_num,
                                "entry_id": entry.id,
                                "expected_prev": imported[-1].entry_hash,
                                "actual_prev": entry.prev_hash,
                            },
                        )
                else:
                    if entry.prev_hash != "":
                        raise ImportValidationError(
                            f"Line {line_num}: first entry should have empty prev_hash",
                            details={"line": line_num, "entry_id": entry.id},
                        )

                imported.append(entry)

        return imported

    def get_archivable_entries(
        self, older_than_days: int
    ) -> list[AuditEntry]:
        """Return entries older than the specified number of days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        return [e for e in self._repo._entries if e.created_at < cutoff]

    @property
    def count(self) -> int:
        return self._repo.count
