"""MCP session management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pylon.protocols.mcp.types import ClientCapabilities, ServerCapabilities


@dataclass
class McpSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    server_capabilities: ServerCapabilities = field(default_factory=ServerCapabilities)
    client_capabilities: ClientCapabilities = field(default_factory=ClientCapabilities)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, McpSession] = {}

    def create_session(self) -> McpSession:
        session = McpSession()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> McpSession | None:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False
