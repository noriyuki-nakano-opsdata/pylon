"""StateStore - key-value state management with TTL, transactions, and change notifications."""

from __future__ import annotations

import fnmatch
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class StateOpType(StrEnum):
    SET = "SET"
    DELETE = "DELETE"
    INCREMENT = "INCREMENT"


@dataclass
class StateOp:
    op: StateOpType
    key: str
    value: Any = None
    ttl: float | None = None


class StateStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._ttls: dict[str, float] = {}  # key -> expiry timestamp
        self._subscribers: dict[int, tuple[str, Callable]] = {}
        self._sub_counter: int = 0

    def _is_expired(self, key: str) -> bool:
        expiry = self._ttls.get(key)
        if expiry is not None and time.monotonic() >= expiry:
            del self._data[key]
            del self._ttls[key]
            return True
        return False

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data and not self._is_expired(key):
            return self._data[key]
        return default

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        old = self._data.get(key)
        self._data[key] = value
        if ttl is not None:
            self._ttls[key] = time.monotonic() + ttl
        elif key in self._ttls:
            del self._ttls[key]
        self._notify(key, old, value)

    def delete(self, key: str) -> bool:
        if key in self._data:
            old = self._data.pop(key)
            self._ttls.pop(key, None)
            self._notify(key, old, None)
            return True
        return False

    def has(self, key: str) -> bool:
        if key not in self._data:
            return False
        return not self._is_expired(key)

    def keys(self) -> list[str]:
        self._purge_expired()
        return list(self._data.keys())

    def get_namespace(self, ns: str) -> dict[str, Any]:
        self._purge_expired()
        prefix = f"{ns}." if not ns.endswith(".") else ns
        return {k: v for k, v in self._data.items() if k.startswith(prefix)}

    def to_dict(self) -> dict[str, Any]:
        self._purge_expired()
        return dict(self._data)

    def load(self, data: dict[str, Any]) -> None:
        self._data = dict(data)
        self._ttls.clear()

    def transaction(self, ops: list[StateOp]) -> bool:
        backup_data = dict(self._data)
        backup_ttls = dict(self._ttls)
        try:
            for op in ops:
                if op.op == StateOpType.SET:
                    self.set(op.key, op.value, ttl=op.ttl)
                elif op.op == StateOpType.DELETE:
                    self.delete(op.key)
                elif op.op == StateOpType.INCREMENT:
                    current = self._data.get(op.key, 0)
                    if not isinstance(current, (int, float)):
                        raise TypeError(f"Cannot increment non-numeric key: {op.key}")
                    self.set(op.key, current + (op.value if op.value is not None else 1))
            return True
        except Exception as exc:
            warnings.warn(
                f"Transaction rolled back: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            self._data = backup_data
            self._ttls = backup_ttls
            return False

    def on_change(
        self,
        key_pattern: str,
        callback: Callable[[str, Any, Any], None],
    ) -> Callable[[], None]:
        self._sub_counter += 1
        sub_id = self._sub_counter
        self._subscribers[sub_id] = (key_pattern, callback)

        def unsubscribe() -> None:
            self._subscribers.pop(sub_id, None)

        return unsubscribe

    def _notify(self, key: str, old_value: Any, new_value: Any) -> None:
        for _, (pattern, cb) in list(self._subscribers.items()):
            if fnmatch.fnmatch(key, pattern):
                cb(key, old_value, new_value)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, exp in self._ttls.items() if now >= exp]
        for k in expired:
            self._data.pop(k, None)
            self._ttls.pop(k, None)
