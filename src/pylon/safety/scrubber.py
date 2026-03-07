"""Secret scrubbing helpers for persisted workflow metadata."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PATTERNS = (
    re.compile(r"^(client[_-]?)?secret$", re.IGNORECASE),
    re.compile(r"^password$", re.IGNORECASE),
    re.compile(r"^(access[_-]?|refresh[_-]?|auth[_-]?|api[_-]?)?token$", re.IGNORECASE),
    re.compile(r"^api[_-]?key$", re.IGNORECASE),
    re.compile(r"^authorization$", re.IGNORECASE),
    re.compile(r"^credentials?$", re.IGNORECASE),
    re.compile(r"^private[_-]?key$", re.IGNORECASE),
)

_SAFE_KEY_OVERRIDES = frozenset({
    "token_type", "token_count", "token_usage", "max_tokens",
    "total_tokens", "prompt_tokens", "completion_tokens",
    "secret_version", "secret_count", "secret_name",
})

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_\-]{12,}\.[A-Za-z0-9_\-]{12,}\.[A-Za-z0-9_\-]{12,}\b"),
)


def scrub_secrets(value: Any) -> Any:
    """Recursively redact secret-like values from persisted metadata."""
    return _scrub(value, parent_key="")


def _scrub(value: Any, *, parent_key: str) -> Any:
    if _is_sensitive_key(parent_key):
        if isinstance(value, (int, float, bool, type(None))):
            return value
        return REDACTED

    if isinstance(value, dict):
        return {
            key: _scrub(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub(item, parent_key=parent_key) for item in value)
    if isinstance(value, str) and _looks_secret(value):
        return REDACTED
    return value


def _is_sensitive_key(key: str) -> bool:
    if key.lower() in _SAFE_KEY_OVERRIDES:
        return False
    return any(pattern.search(key) for pattern in _SENSITIVE_KEY_PATTERNS)


def _looks_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS)
