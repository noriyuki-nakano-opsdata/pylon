"""MCP Client with full primitive support and auto-reconnect."""

from __future__ import annotations

from typing import Any

from pylon.protocols.mcp.dto import InitializeResponseDTO, SamplingCreateParamsDTO
from pylon.protocols.mcp.server import McpServer
from pylon.protocols.mcp.types import (
    InitializeResult,
    JsonRpcRequest,
    ServerCapabilities,
)


class McpClient:
    def __init__(self, access_token: str | None = None) -> None:
        self._server: McpServer | None = None
        self._session_id: str | None = None
        self._request_id: int = 0
        self._access_token: str | None = access_token
        self._server_capabilities: ServerCapabilities | None = None
        self._auto_reconnect: bool = True
        self._last_server: McpServer | None = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def connect(self, server: McpServer) -> None:
        self._server = server
        self._last_server = server

    def disconnect(self) -> None:
        self._server = None
        self._session_id = None
        self._server_capabilities = None

    def _ensure_connected(self) -> None:
        if self._server is None:
            if self._auto_reconnect and self._last_server is not None:
                self._server = self._last_server
                self.initialize()
            else:
                raise RuntimeError("Not connected to a server")

    def _call(self, method: str, params: dict | None = None) -> Any:
        self._ensure_connected()
        assert self._server is not None
        request = JsonRpcRequest(
            method=method, params=params, id=self._next_id()
        )
        response = self._server.handle_request(request, access_token=self._access_token)
        if response.error is not None:
            raise RuntimeError(
                f"RPC error {response.error.code}: {response.error.message}"
            )
        return response.result

    def initialize(self) -> InitializeResult:
        self._ensure_connected()
        assert self._server is not None
        request = JsonRpcRequest(
            method="initialize",
            params={"capabilities": {}},
            id=self._next_id(),
        )
        response = self._server.handle_request(request, access_token=self._access_token)
        if response.error is not None:
            raise RuntimeError(
                f"RPC error {response.error.code}: {response.error.message}"
            )
        init_dto = InitializeResponseDTO.from_wire(response.result)
        result = init_dto.result
        header_session = response.headers.get("Mcp-Session-Id", "")
        self._session_id = header_session or init_dto.session_id
        caps = result.capabilities
        self._server_capabilities = caps
        return result

    # --- Tools ---

    def list_tools(self, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("tools/list", params)

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        return self._call("tools/call", {"name": name, "arguments": arguments or {}})

    # --- Resources ---

    def list_resources(self, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("resources/list", params)

    def read_resource(self, uri: str) -> Any:
        return self._call("resources/read", {"uri": uri})

    def subscribe_resource(self, uri: str) -> Any:
        params: dict[str, Any] = {"uri": uri}
        if self._session_id:
            params["mcpSessionId"] = self._session_id
        return self._call("resources/subscribe", params)

    def list_resource_templates(self) -> dict[str, Any]:
        return self._call("resources/templates/list")

    # --- Prompts ---

    def list_prompts(self, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("prompts/list", params)

    def get_prompt(self, name: str, arguments: dict | None = None) -> Any:
        return self._call("prompts/get", {"name": name, "arguments": arguments or {}})

    # --- Sampling ---

    def create_sampling_message(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "",
        max_tokens: int = 1024,
        model_preferences: dict | None = None,
    ) -> Any:
        dto = SamplingCreateParamsDTO.from_client_inputs(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            model_preferences=model_preferences,
        )
        return self._call(
            "sampling/createMessage",
            dto.to_wire(),
        )

    def close(self) -> None:
        self._server = None
        self._session_id = None
