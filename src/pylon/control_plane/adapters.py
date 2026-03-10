"""Adapters that bind approval/audit workflows to the control-plane store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pylon.approval.store import ApprovalStore
from pylon.approval.types import ApprovalRequest, ApprovalStatus
from pylon.repository.audit import AuditEntry, AuditRepository

if TYPE_CHECKING:
    from pylon.control_plane.workflow_service import WorkflowControlPlaneStore


class StoreBackedApprovalStore(ApprovalStore):
    """ApprovalStore adapter backed by the shared control-plane store."""

    def __init__(self, store: WorkflowControlPlaneStore) -> None:
        super().__init__()
        self._store = store

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        self._store.put_approval_record(self._merge_request_payload(request))
        return request

    async def get(self, request_id: str) -> ApprovalRequest | None:
        payload = self._store.get_approval_record(request_id)
        return None if payload is None else ApprovalRequest.from_dict(payload)

    async def update(self, request: ApprovalRequest) -> ApprovalRequest:
        self._store.put_approval_record(self._merge_request_payload(request))
        return request

    async def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        agent_id: str | None = None,
        action: str | None = None,
    ) -> list[ApprovalRequest]:
        results = [
            ApprovalRequest.from_dict(payload)
            for payload in self._store.list_all_approval_records()
        ]
        if status is not None:
            results = [request for request in results if request.status == status]
        if agent_id is not None:
            results = [request for request in results if request.agent_id == agent_id]
        if action is not None:
            results = [request for request in results if request.action == action]
        results.sort(key=lambda request: request.created_at)
        return results

    async def delete(self, request_id: str) -> bool:
        return False

    def _merge_request_payload(self, request: ApprovalRequest) -> dict[str, Any]:
        existing = self._store.get_approval_record(request.id) or {}
        payload = dict(existing)
        payload.update(request.to_dict())
        payload["run_id"] = payload.get("run_id") or payload.get("context", {}).get("run_id", "")
        return payload


class StoreBackedAuditRepository(AuditRepository):
    """AuditRepository adapter backed by the shared control-plane store."""

    def __init__(self, store: WorkflowControlPlaneStore, hmac_key: bytes) -> None:
        super().__init__(hmac_key=hmac_key)
        self._store = store

    async def append(
        self,
        *,
        tenant_id: str = "default",
        event_type: str,
        actor: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        last_entry = self._store.get_last_audit_record()
        entry_id = self._store.allocate_sequence_value("audit_entries")
        prev_hash = str(last_entry.get("entry_hash", "")) if last_entry is not None else ""
        created_at = datetime.now(UTC)
        normalized_details = details or {}
        entry_data = self._serialize_entry_data(
            entry_id=entry_id,
            tenant_id=tenant_id,
            event_type=event_type,
            actor=actor,
            action=action,
            details=normalized_details,
            prev_hash=prev_hash,
            created_at=created_at,
        )
        entry_hash = self._compute_hash(entry_data)
        hmac_sig = self._compute_hmac(entry_data)
        entry = AuditEntry(
            id=entry_id,
            tenant_id=tenant_id,
            event_type=event_type,
            actor=actor,
            action=action,
            details=normalized_details,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            hmac_signature=hmac_sig,
            created_at=created_at,
        )
        self._store.put_audit_record(_entry_to_payload(entry))
        return entry

    async def get(self, id: int) -> AuditEntry | None:
        payload = self._store.get_audit_record(id)
        return None if payload is None else _entry_from_payload(payload)

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        payloads = self._store.list_audit_records(
            tenant_id=tenant_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return [_entry_from_payload(payload) for payload in payloads]

    async def verify_chain(self) -> tuple[bool, str]:
        entries = await self.list(limit=1_000_000, offset=0)
        for index, entry in enumerate(entries):
            if index == 0:
                if entry.prev_hash != "":
                    return False, f"Entry {entry.id}: first entry should have empty prev_hash"
            else:
                if entry.prev_hash != entries[index - 1].entry_hash:
                    return False, f"Entry {entry.id}: prev_hash mismatch (chain broken)"
            expected_data = self._serialize_entry_data(
                entry_id=entry.id,
                tenant_id=entry.tenant_id,
                event_type=entry.event_type,
                actor=entry.actor,
                action=entry.action,
                details=entry.details,
                prev_hash=entry.prev_hash,
                created_at=entry.created_at,
            )
            if entry.entry_hash != self._compute_hash(expected_data):
                return False, f"Entry {entry.id}: entry_hash mismatch"
            if entry.hmac_signature != self._compute_hmac(expected_data):
                return False, f"Entry {entry.id}: hmac_signature mismatch"
        return True, "Chain integrity verified"

    @property
    def count(self) -> int:
        return len(self._store.list_audit_records(limit=1_000_000, offset=0))


def _entry_from_payload(payload: dict[str, Any]) -> AuditEntry:
    created_at = payload.get("created_at")
    if isinstance(created_at, datetime):
        normalized_created_at = (
            created_at.astimezone(UTC) if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        )
    else:
        normalized_created_at = datetime.fromisoformat(str(created_at))
        if normalized_created_at.tzinfo is None:
            normalized_created_at = normalized_created_at.replace(tzinfo=UTC)
        else:
            normalized_created_at = normalized_created_at.astimezone(UTC)
    return AuditEntry(
        id=int(payload.get("id", 0)),
        tenant_id=str(payload.get("tenant_id", "default")),
        event_type=str(payload.get("event_type", "")),
        actor=str(payload.get("actor", "")),
        action=str(payload.get("action", "")),
        details=dict(payload.get("details", {})),
        prev_hash=str(payload.get("prev_hash", "")),
        entry_hash=str(payload.get("entry_hash", "")),
        hmac_signature=str(payload.get("hmac_signature", "")),
        created_at=normalized_created_at,
    )


def _entry_to_payload(entry: AuditEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "tenant_id": entry.tenant_id,
        "event_type": entry.event_type,
        "actor": entry.actor,
        "action": entry.action,
        "details": dict(entry.details),
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
        "hmac_signature": entry.hmac_signature,
        "created_at": entry.created_at.astimezone(UTC).isoformat(),
    }
