"""OpenClaw Gateway HTTP client bridge.

Communicates with an OpenClaw Gateway instance over HTTP using only
stdlib (urllib.request). Async wrappers use asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
import urllib.error
from typing import Any


class OpenClawBridge:
    """HTTP client for the OpenClaw Gateway API."""

    def __init__(
        self,
        base_url: str = "http://localhost:18789",
        token: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers with optional auth token."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict:
        """Execute a synchronous HTTP request and return parsed JSON."""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode() if exc.fp else ""
            return {"error": raw, "status": exc.code}
        except urllib.error.URLError as exc:
            return {"error": str(exc.reason)}

    async def send_message(
        self,
        channel: str,
        message: str,
        thread_id: str = "",
    ) -> dict:
        """Send a message to a channel via the gateway."""
        body: dict[str, Any] = {"channel": channel, "message": message}
        if thread_id:
            body["thread_id"] = thread_id
        return await asyncio.to_thread(
            self._request, "POST", "/api/v1/messages", body
        )

    async def execute_skill(
        self,
        skill_name: str,
        params: dict[str, Any],
    ) -> dict:
        """Execute a skill on the gateway."""
        body = {"skill": skill_name, "params": params}
        return await asyncio.to_thread(
            self._request, "POST", "/api/v1/skills/execute", body
        )

    async def list_channels(self) -> list[dict]:
        """List available channels."""
        result = await asyncio.to_thread(
            self._request, "GET", "/api/v1/channels"
        )
        if isinstance(result, list):
            return result
        return result.get("channels", [])

    async def health_check(self) -> dict:
        """Check gateway health."""
        return await asyncio.to_thread(
            self._request, "GET", "/api/v1/health"
        )
