"""Workflow state primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class StatePatch:
    """Immutable state patch emitted by a node execution."""

    updates: dict[str, Any] = field(default_factory=dict)


def _strict_json_default(obj: Any) -> str:
    """Raise TypeError for non-JSON-serializable types to prevent unstable hashes."""
    raise TypeError(
        f"State values must be JSON-serializable primitives, got {type(obj).__name__}"
    )


def compute_state_hash(state: dict[str, Any]) -> str:
    """Compute a deterministic hash for a state payload.

    State values must be JSON-serializable primitives (str, int, float,
    bool, None, dict, list). Non-serializable types raise TypeError.
    """
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=_strict_json_default)
    return sha256(payload.encode("utf-8")).hexdigest()
