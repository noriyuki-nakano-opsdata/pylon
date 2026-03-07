"""SnapshotManager - state snapshot creation, restoration, and diff-based storage."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pylon.state.diff import DiffEntry, apply_diff, compute_diff
from pylon.state.store import StateStore


@dataclass
class SnapshotMeta:
    id: str
    label: str
    created_at: datetime
    size_bytes: int
    is_diff: bool = False
    parent_id: str | None = None


@dataclass
class Snapshot:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    diff: list[DiffEntry] | None = None
    parent_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    size_bytes: int = 0

    def meta(self) -> SnapshotMeta:
        return SnapshotMeta(
            id=self.id,
            label=self.label,
            created_at=self.created_at,
            size_bytes=self.size_bytes,
            is_diff=self.diff is not None,
            parent_id=self.parent_id,
        )


class SnapshotManager:
    def __init__(self) -> None:
        self._snapshots: dict[str, Snapshot] = {}
        self._order: list[str] = []

    def create_snapshot(self, store: StateStore, label: str = "") -> Snapshot:
        data = store.to_dict()
        size = len(json.dumps(data, default=str).encode())

        # Diff-based if previous snapshot exists
        diff: list[DiffEntry] | None = None
        parent_id: str | None = None
        if self._order:
            parent = self._snapshots[self._order[-1]]
            parent_data = self._resolve_full_data(parent)
            diff = compute_diff(parent_data, data)
            parent_id = parent.id

        snap = Snapshot(
            label=label,
            data=data if diff is None else {},
            diff=diff,
            parent_id=parent_id,
            size_bytes=size,
        )
        self._snapshots[snap.id] = snap
        self._order.append(snap.id)
        return snap

    def restore_snapshot(self, snapshot_id: str) -> StateStore:
        snap = self._snapshots.get(snapshot_id)
        if snap is None:
            raise KeyError(f"Snapshot not found: {snapshot_id}")
        data = self._resolve_full_data(snap)
        store = StateStore()
        store.load(data)
        return store

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> list[SnapshotMeta]:
        return [self._snapshots[sid].meta() for sid in self._order]

    def delete_snapshot(self, snapshot_id: str) -> bool:
        if snapshot_id not in self._snapshots:
            return False
        # Materialize any children that depend on this snapshot
        for sid in self._order:
            snap = self._snapshots[sid]
            if snap.parent_id == snapshot_id:
                snap.data = self._resolve_full_data(snap)
                snap.diff = None
                snap.parent_id = None
        del self._snapshots[snapshot_id]
        self._order.remove(snapshot_id)
        return True

    def _resolve_full_data(self, snap: Snapshot) -> dict[str, Any]:
        if snap.diff is None:
            return dict(snap.data)
        # Walk up the chain
        chain: list[Snapshot] = [snap]
        current = snap
        while current.parent_id is not None:
            parent = self._snapshots.get(current.parent_id)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        # Build from base
        chain.reverse()
        base = dict(chain[0].data)
        for s in chain[1:]:
            if s.diff is not None:
                base = apply_diff(base, s.diff)
        return base
