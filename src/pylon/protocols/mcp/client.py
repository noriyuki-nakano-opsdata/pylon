"""MCP Client (in-memory direct call implementation)."""

from __future__ import annotations

from typing import Any

from pylon.protocols.mcp.server import McpServer
from pylon.protocols.mcp.types import (
    InitializeResult,
    JsonRpcRequest,
    ResourceDefinition,
    ServerCapabilities,
    ToolDefinition,
)


class McpClient:
    def __init__(self) -> None:
        self._server: McpServer | None = None
        self._session_id: str | None = None
        self._request_id: int = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def connect(self, server: McpServer) -> None:
        """Connect to an MCP server (in-memory direct call)."""
        self._server = server

    def _call(self, method: str, params: dict | None = None) -> Any:
        if self._server is None:
            raise RuntimeError("Not connected to a server")
        request = JsonRpcRequest(
            method=method, params=params, id=self._next_id()
        )
        response = self._server.handle_request(request)
        if response.error is not None:
            raise RuntimeError(
                f"RPC error {response.error.code}: {response.error.message}"
            )
        return response.result

    def initialize(self) -> InitializeResult:
        result = self._call("initialize", {"capabilities": {}})
        self._session_id = result.get("sessionId")
        return InitializeResult(
            protocolVersion=result["protocolVersion"],
            capabilities=ServerCapabilities(**result["capabilities"]),
            serverInfo=result["serverInfo"],
        )

    def list_tools(self) -> list[ToolDefinition]:
        result = self._call("tools/list")
        return [ToolDefinition(**t) for t in result["tools"]]

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        return self._call("tools/call", {"name": name, "arguments": arguments or {}})

    def list_resources(self) -> list[ResourceDefinition]:
        result = self._call("resources/list")
        return [ResourceDefinition(**r) for r in result["resources"]]

    def read_resource(self, uri: str) -> Any:
        return self._call("resources/read", {"uri": uri})

    def list_prompts(self) -> list[dict]:
        result = self._call("prompts/list")
        return result["prompts"]

    def get_prompt(self, name: str, arguments: dict | None = None) -> Any:
        return self._call("prompts/get", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        self._server = None
        self._session_id = None
