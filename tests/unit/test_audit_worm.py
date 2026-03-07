"""Tests for WORM Audit Repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from pylon.errors import (
    ImmutableEntryError,
    ImportValidationError,
    IntegrityViolationError,
)
from pylon.repository.audit import AuditRepository
from pylon.repository.audit_worm import ArchiveReport, WORMAuditRepository

HMAC_KEY = b"test-key-minimum-16-bytes"


@pytest.fixture
def repo() -> WORMAuditRepository:
    return WORMAuditRepository(AuditRepository(HMAC_KEY))


@pytest.fixture
async def populated_repo(repo: WORMAuditRepository) -> WORMAuditRepository:
    await repo.append(event_type="login", actor="alice", action="authenticate")
    await repo.append(event_type="access", actor="bob", action="read_file", details={"path": "/etc/config"})
    await repo.append(event_type="logout", actor="alice", action="deauthenticate")
    return repo


# --- WORM Immutability ---


@pytest.mark.asyncio
async def test_update_raises_immutable_error(populated_repo: WORMAuditRepository) -> None:
    with pytest.raises(ImmutableEntryError, match="Cannot modify"):
        await populated_repo.update(1, action="tampered")


@pytest.mark.asyncio
async def test_delete_raises_immutable_error(populated_repo: WORMAuditRepository) -> None:
    with pytest.raises(ImmutableEntryError, match="Cannot delete"):
        await populated_repo.delete(1)


@pytest.mark.asyncio
async def test_update_error_includes_details(populated_repo: WORMAuditRepository) -> None:
    with pytest.raises(ImmutableEntryError) as exc_info:
        await populated_repo.update(2, action="hack", actor="mallory")
    assert exc_info.value.details["entry_id"] == 2
    assert sorted(exc_info.value.details["attempted_fields"]) == ["action", "actor"]


@pytest.mark.asyncio
async def test_delete_error_includes_details(populated_repo: WORMAuditRepository) -> None:
    with pytest.raises(ImmutableEntryError) as exc_info:
        await populated_repo.delete(3)
    assert exc_info.value.details["entry_id"] == 3


# --- Append & Read ---


@pytest.mark.asyncio
async def test_append_and_get(repo: WORMAuditRepository) -> None:
    entry = await repo.append(event_type="test", actor="user", action="create")
    assert entry.id == 1
    assert entry.event_type == "test"

    fetched = await repo.get(1)
    assert fetched is not None
    assert fetched.entry_hash == entry.entry_hash


@pytest.mark.asyncio
async def test_list_entries(populated_repo: WORMAuditRepository) -> None:
    entries = await populated_repo.list()
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_list_with_filter(populated_repo: WORMAuditRepository) -> None:
    entries = await populated_repo.list(event_type="login")
    assert len(entries) == 1
    assert entries[0].actor == "alice"


# --- Chain Integrity ---


@pytest.mark.asyncio
async def test_verify_integrity_valid(populated_repo: WORMAuditRepository) -> None:
    is_valid, msg = await populated_repo.verify_integrity()
    assert is_valid
    assert "3 entries" in msg


@pytest.mark.asyncio
async def test_verify_integrity_empty(repo: WORMAuditRepository) -> None:
    is_valid, msg = await repo.verify_integrity()
    assert is_valid
    assert "No entries" in msg


@pytest.mark.asyncio
async def test_verify_integrity_detects_tampered_hash(populated_repo: WORMAuditRepository) -> None:
    # Tamper with an entry hash
    populated_repo._repo._entries[1].entry_hash = "tampered_hash"
    with pytest.raises(IntegrityViolationError, match="prev_hash mismatch"):
        await populated_repo.verify_integrity()


@pytest.mark.asyncio
async def test_verify_integrity_detects_missing_hash(populated_repo: WORMAuditRepository) -> None:
    populated_repo._repo._entries[0].entry_hash = ""
    with pytest.raises(IntegrityViolationError, match="missing entry_hash"):
        await populated_repo.verify_integrity()


@pytest.mark.asyncio
async def test_verify_integrity_detects_missing_hmac(populated_repo: WORMAuditRepository) -> None:
    populated_repo._repo._entries[0].hmac_signature = ""
    with pytest.raises(IntegrityViolationError, match="missing hmac_signature"):
        await populated_repo.verify_integrity()


@pytest.mark.asyncio
async def test_verify_integrity_detects_broken_first_entry(populated_repo: WORMAuditRepository) -> None:
    populated_repo._repo._entries[0].prev_hash = "should_be_empty"
    with pytest.raises(IntegrityViolationError, match="first entry"):
        await populated_repo.verify_integrity()


# --- JSONL Export/Import ---


@pytest.mark.asyncio
async def test_archive_to_jsonl(populated_repo: WORMAuditRepository, tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    report = await populated_repo.archive_to_jsonl(path)

    assert isinstance(report, ArchiveReport)
    assert report.entries_exported == 3
    assert report.chain_valid is True
    assert report.hmac_valid is True
    assert report.file_path == str(path)
    assert report.exported_at is not None

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 3

    first = json.loads(lines[0])
    assert first["id"] == 1
    assert first["prev_hash"] == ""
    assert "entry_hash" in first
    assert "hmac_signature" in first
    assert "created_at" in first


@pytest.mark.asyncio
async def test_import_from_jsonl_roundtrip(populated_repo: WORMAuditRepository, tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    await populated_repo.archive_to_jsonl(path)

    imported = await populated_repo.import_from_jsonl(path)
    assert len(imported) == 3
    assert imported[0].event_type == "login"
    assert imported[1].event_type == "access"
    assert imported[2].event_type == "logout"

    # Verify chain linkage
    assert imported[0].prev_hash == ""
    assert imported[1].prev_hash == imported[0].entry_hash
    assert imported[2].prev_hash == imported[1].entry_hash


@pytest.mark.asyncio
async def test_import_detects_corrupted_chain(populated_repo: WORMAuditRepository, tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    await populated_repo.archive_to_jsonl(path)

    # Corrupt the second line's prev_hash
    lines = path.read_text().strip().split("\n")
    entry = json.loads(lines[1])
    entry["prev_hash"] = "corrupted_hash"
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ImportValidationError, match="chain broken"):
        await populated_repo.import_from_jsonl(path)


@pytest.mark.asyncio
async def test_import_detects_invalid_json(tmp_path) -> None:
    repo = WORMAuditRepository(AuditRepository(HMAC_KEY))
    path = tmp_path / "bad.jsonl"
    path.write_text("not valid json\n")

    with pytest.raises(ImportValidationError, match="invalid JSON"):
        await repo.import_from_jsonl(path)


@pytest.mark.asyncio
async def test_import_detects_missing_fields(tmp_path) -> None:
    repo = WORMAuditRepository(AuditRepository(HMAC_KEY))
    path = tmp_path / "incomplete.jsonl"
    path.write_text(json.dumps({"id": 1, "tenant_id": "default"}) + "\n")

    with pytest.raises(ImportValidationError, match="missing fields"):
        await repo.import_from_jsonl(path)


@pytest.mark.asyncio
async def test_import_detects_bad_first_entry(tmp_path) -> None:
    repo = WORMAuditRepository(AuditRepository(HMAC_KEY))
    path = tmp_path / "bad_first.jsonl"
    entry = {
        "id": 1, "tenant_id": "default", "event_type": "test",
        "actor": "x", "action": "y", "details": {},
        "prev_hash": "should_be_empty", "entry_hash": "abc",
        "hmac_signature": "def", "created_at": "2026-03-07T00:00:00+00:00",
    }
    path.write_text(json.dumps(entry) + "\n")

    with pytest.raises(ImportValidationError, match="first entry"):
        await repo.import_from_jsonl(path)


# --- Retention Policy ---


@pytest.mark.asyncio
async def test_get_archivable_entries_none_old(populated_repo: WORMAuditRepository) -> None:
    archivable = populated_repo.get_archivable_entries(older_than_days=30)
    assert len(archivable) == 0


@pytest.mark.asyncio
async def test_get_archivable_entries_with_old_entries(populated_repo: WORMAuditRepository) -> None:
    # Backdate entries
    old_time = datetime.now(UTC) - timedelta(days=60)
    populated_repo._repo._entries[0].created_at = old_time
    populated_repo._repo._entries[1].created_at = old_time

    archivable = populated_repo.get_archivable_entries(older_than_days=30)
    assert len(archivable) == 2
    assert archivable[0].id == 1
    assert archivable[1].id == 2


# --- Count Property ---


@pytest.mark.asyncio
async def test_count(populated_repo: WORMAuditRepository) -> None:
    assert populated_repo.count == 3
