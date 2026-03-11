"""MCP client bridge for connecting to external MCP servers.

Implements JSON-RPC 2.0 over stdio to communicate with MCP-compliant
tool servers. Manages subprocess lifecycle and request/response pairing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class MCPClientBridge:
    """Client for MCP servers communicating via JSON-RPC 2.0 over stdio."""

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 0

    def _get_next_id(self) -> int:
        """Return the next JSON-RPC request ID."""
        self._next_id += 1
        return self._next_id

    async def connect(
        self,
        server_command: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Start an MCP server subprocess and establish stdio connection."""
        if self._process is not None:
            await self.disconnect()
        self._process = await asyncio.create_subprocess_exec(
            *server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def _send_jsonrpc(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Not connected. Call connect() first.")
        if self._process.stdout is None:
            raise RuntimeError("Server stdout not available.")

        request = {
            "jsonrpc": "2.0",
            "id": self._get_next_id(),
            "method": method,
            "params": params,
        }
        data = json.dumps(request, separators=(",", ":")) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=30.0,
        )
        if not line:
            raise RuntimeError("Server closed connection.")

        try:
            response = json.loads(line.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from server: {line.decode()!r}") from exc
        if "error" in response:
            error = response["error"]
            raise RuntimeError(
                f"JSON-RPC error {error.get('code', -1)}: "
                f"{error.get('message', 'Unknown error')}"
            )
        return response.get("result", {})

    async def list_tools(self) -> list[dict]:
        """Request the list of available tools from the server."""
        result = await self._send_jsonrpc("tools/list", {})
        if isinstance(result, list):
            return result
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        """Call a tool on the MCP server."""
        return await self._send_jsonrpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    async def disconnect(self) -> None:
        """Terminate the MCP server subprocess."""
        if self._process is None:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except (TimeoutError, ProcessLookupError):
            self._process.kill()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        finally:
            self._process = None

    @property
    def is_connected(self) -> bool:
        """Check whether the MCP server process is alive."""
        return self._process is not None and self._process.returncode is None
