"""StateDiff - state difference computation and application."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DiffOp(StrEnum):
    ADD = "ADD"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


@dataclass
class DiffEntry:
    key: str
    op: DiffOp
    old_value: Any = None
    new_value: Any = None


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    items: dict[str, Any] = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten(v, full_key))
        else:
            items[full_key] = v
    return items


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        d = result
        for part in parts[:-1]:
            if part not in d or not isinstance(d[part], dict):
                d[part] = {}
            d = d[part]
        d[parts[-1]] = value
    return result


def compute_diff(old: dict[str, Any], new: dict[str, Any]) -> list[DiffEntry]:
    old_flat = _flatten(old)
    new_flat = _flatten(new)
    entries: list[DiffEntry] = []

    all_keys = sorted(set(old_flat) | set(new_flat))
    for key in all_keys:
        in_old = key in old_flat
        in_new = key in new_flat
        if in_old and not in_new:
            entries.append(DiffEntry(key=key, op=DiffOp.DELETE, old_value=old_flat[key]))
        elif not in_old and in_new:
            entries.append(DiffEntry(key=key, op=DiffOp.ADD, new_value=new_flat[key]))
        elif old_flat[key] != new_flat[key]:
            entries.append(DiffEntry(
                key=key, op=DiffOp.MODIFY,
                old_value=old_flat[key], new_value=new_flat[key],
            ))

    return entries


def apply_diff(state: dict[str, Any], diff: list[DiffEntry]) -> dict[str, Any]:
    flat = _flatten(state)
    for entry in diff:
        if entry.op == DiffOp.ADD or entry.op == DiffOp.MODIFY:
            flat[entry.key] = entry.new_value
        elif entry.op == DiffOp.DELETE:
            flat.pop(entry.key, None)
    return _unflatten(flat)
