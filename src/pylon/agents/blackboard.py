"""Shared blackboard for multi-agent knowledge exchange.

A namespaced, searchable shared knowledge space where agents can
read and write structured information. Built on top of Pylon's
workflow state but adds:
- Namespacing (sections) to avoid key collisions
- Semantic search over blackboard contents
- Write audit trail per agent
- Read/write access control
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlackboardEntry:
    """A single entry on the blackboard."""

    key: str
    value: Any
    section: str = "default"
    author: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BlackboardEvent:
    """Audit event for blackboard operations."""

    action: str  # "write", "read", "delete", "query"
    agent_id: str
    key: str
    section: str
    timestamp: float = field(default_factory=time.time)


class Blackboard:
    """Shared knowledge space for multi-agent collaboration.

    Usage:
        board = Blackboard()
        board.write("lead", "requirements", "Build a REST API", section="planning")
        board.write("architect", "design", {"pattern": "MVC"}, section="planning")

        # Coder reads the requirements
        req = board.read("requirements", section="planning")

        # Query across sections
        results = board.query("REST API")
    """

    def __init__(
        self,
        *,
        max_entries: int = 10000,
        access_control: dict[str, set[str]] | None = None,
    ) -> None:
        self._entries: dict[str, dict[str, BlackboardEntry]] = {}  # section -> key -> entry
        self._max_entries = max_entries
        self._access_control = access_control  # agent -> allowed sections
        self._events: list[BlackboardEvent] = []
        self._events_max = 5000

    def write(
        self,
        agent_id: str,
        key: str,
        value: Any,
        *,
        section: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> BlackboardEntry:
        """Write or update an entry on the blackboard."""
        if not self._can_access(agent_id, section, "write"):
            raise PermissionError(
                f"Agent '{agent_id}' not allowed to write to section '{section}'"
            )

        if section not in self._entries:
            self._entries[section] = {}

        existing = self._entries[section].get(key)
        if existing is not None:
            existing.value = value
            existing.updated_at = time.time()
            existing.version += 1
            existing.author = agent_id
            if metadata:
                existing.metadata.update(metadata)
            entry = existing
        else:
            entry = BlackboardEntry(
                key=key,
                value=value,
                section=section,
                author=agent_id,
                metadata=metadata or {},
            )
            self._entries[section][key] = entry

        self._record_event("write", agent_id, key, section)
        return entry

    def read(
        self,
        key: str,
        *,
        section: str = "default",
        agent_id: str = "",
    ) -> Any:
        """Read an entry from the blackboard.

        Returns None if key doesn't exist.
        """
        if agent_id and not self._can_access(agent_id, section, "read"):
            raise PermissionError(
                f"Agent '{agent_id}' not allowed to read section '{section}'"
            )

        entries = self._entries.get(section, {})
        entry = entries.get(key)

        if agent_id:
            self._record_event("read", agent_id, key, section)

        return entry.value if entry is not None else None

    def get_entry(self, key: str, *, section: str = "default") -> BlackboardEntry | None:
        """Get the full entry (including metadata) for a key."""
        return self._entries.get(section, {}).get(key)

    def delete(
        self, agent_id: str, key: str, *, section: str = "default"
    ) -> bool:
        """Delete an entry from the blackboard."""
        if not self._can_access(agent_id, section, "write"):
            raise PermissionError(
                f"Agent '{agent_id}' not allowed to modify section '{section}'"
            )

        entries = self._entries.get(section, {})
        if key in entries:
            del entries[key]
            self._record_event("delete", agent_id, key, section)
            return True
        return False

    def list_keys(self, *, section: str | None = None) -> list[str]:
        """List all keys, optionally filtered by section."""
        if section is not None:
            return list(self._entries.get(section, {}).keys())
        keys: list[str] = []
        for sec_entries in self._entries.values():
            keys.extend(sec_entries.keys())
        return keys

    def list_sections(self) -> list[str]:
        """List all sections."""
        return list(self._entries.keys())

    def query(self, query_text: str, *, section: str | None = None) -> list[BlackboardEntry]:
        """Search blackboard entries by keyword matching."""
        query_lower = query_text.lower()
        results: list[BlackboardEntry] = []

        sections = (
            {section: self._entries.get(section, {})}
            if section
            else self._entries
        )

        for sec_entries in sections.values():
            for entry in sec_entries.values():
                searchable = f"{entry.key} {entry.value}".lower()
                if query_lower in searchable:
                    results.append(entry)

        return results

    def get_section_snapshot(self, section: str) -> dict[str, Any]:
        """Get a snapshot of all key-value pairs in a section."""
        entries = self._entries.get(section, {})
        return {key: entry.value for key, entry in entries.items()}

    def to_state_patch(self, section: str = "default") -> dict[str, Any]:
        """Convert a section to a workflow state patch.

        This bridges the Blackboard with Pylon's CommitEngine —
        blackboard contents can be committed as state patches.
        """
        entries = self._entries.get(section, {})
        return {
            f"blackboard.{section}.{key}": entry.value
            for key, entry in entries.items()
        }

    def get_audit_trail(
        self,
        *,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[BlackboardEvent]:
        """Get audit trail of blackboard operations."""
        events = self._events
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        return events[-limit:]

    @property
    def total_entries(self) -> int:
        return sum(len(entries) for entries in self._entries.values())

    def _can_access(self, agent_id: str, section: str, operation: str) -> bool:
        """Check if an agent can access a section."""
        if self._access_control is None:
            return True  # No ACL = open access
        allowed = self._access_control.get(agent_id, set())
        return section in allowed or "*" in allowed

    def _record_event(
        self, action: str, agent_id: str, key: str, section: str
    ) -> None:
        """Record an audit event."""
        self._events.append(
            BlackboardEvent(
                action=action, agent_id=agent_id, key=key, section=section
            )
        )
        if len(self._events) > self._events_max:
            self._events = self._events[-self._events_max :]
