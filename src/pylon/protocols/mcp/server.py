"""MCP Server (JSON-RPC 2.0)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pylon.protocols.mcp.router import MethodRouter, route
from pylon.protocols.mcp.session import McpSession, SessionManager
from pylon.protocols.mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    InitializeResult,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    PromptDefinition,
    ResourceDefinition,
    ServerCapabilities,
    ToolDefinition,
)


class McpServer:
    def __init__(self, name: str = "pylon-mcp", version: str = "0.1.0") -> None:
        self.name = name
        self.version = version
        self._tools: dict[str, ToolDefinition] = {}
        self._tool_handlers: dict[str, Callable] = {}
        self._resources: dict[str, ResourceDefinition] = {}
        self._resource_handlers: dict[str, Callable] = {}
        self._prompts: dict[str, PromptDefinition] = {}
        self._prompt_handlers: dict[str, Callable] = {}
        self._session_manager = SessionManager()
        self._router = MethodRouter()
        self._register_builtin_methods()

    def _register_builtin_methods(self) -> None:
        self._router.register("initialize", self._handle_initialize)
        self._router.register("tools/list", self._handle_tools_list)
        self._router.register("tools/call", self._handle_tools_call)
        self._router.register("resources/list", self._handle_resources_list)
        self._router.register("resources/read", self._handle_resources_read)
        self._router.register("prompts/list", self._handle_prompts_list)
        self._router.register("prompts/get", self._handle_prompts_get)

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(
            tools=len(self._tools) > 0,
            resources=len(self._resources) > 0,
            prompts=len(self._prompts) > 0,
        )

    def register_tool(
        self, tool: ToolDefinition, handler: Callable | None = None
    ) -> None:
        self._tools[tool.name] = tool
        if handler is not None:
            self._tool_handlers[tool.name] = handler

    def register_resource(
        self, resource: ResourceDefinition, handler: Callable | None = None
    ) -> None:
        self._resources[resource.uri] = resource
        if handler is not None:
            self._resource_handlers[resource.uri] = handler

    def register_prompt(
        self, prompt: PromptDefinition, handler: Callable | None = None
    ) -> None:
        self._prompts[prompt.name] = prompt
        if handler is not None:
            self._prompt_handlers[prompt.name] = handler

    def handle_request(self, request: JsonRpcRequest) -> JsonRpcResponse:
        return self._router.dispatch(request)

    # --- built-in handlers ---

    def _handle_initialize(self, request: JsonRpcRequest) -> dict:
        session = self._session_manager.create_session()
        session.server_capabilities = self.capabilities
        if request.params and "capabilities" in request.params:
            pass  # store client capabilities if needed
        result = InitializeResult(
            capabilities=self.capabilities,
            serverInfo={"name": self.name, "version": self.version},
        )
        return {**result.to_dict(), "sessionId": session.session_id}

    def _handle_tools_list(self, request: JsonRpcRequest) -> dict:
        return {"tools": [t.to_dict() for t in self._tools.values()]}

    def _handle_tools_call(self, request: JsonRpcRequest) -> Any:
        params = request.params or {}
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = self._tool_handlers.get(name)
        if handler is None:
            raise ValueError(f"Tool not found: {name}")
        return handler(arguments)

    def _handle_resources_list(self, request: JsonRpcRequest) -> dict:
        return {"resources": [r.to_dict() for r in self._resources.values()]}

    def _handle_resources_read(self, request: JsonRpcRequest) -> Any:
        params = request.params or {}
        uri = params.get("uri", "")
        handler = self._resource_handlers.get(uri)
        if handler is None:
            raise ValueError(f"Resource not found: {uri}")
        return handler(uri)

    def _handle_prompts_list(self, request: JsonRpcRequest) -> dict:
        return {"prompts": [p.to_dict() for p in self._prompts.values()]}

    def _handle_prompts_get(self, request: JsonRpcRequest) -> Any:
        params = request.params or {}
        name = params.get("name", "")
        handler = self._prompt_handlers.get(name)
        if handler is None:
            raise ValueError(f"Prompt not found: {name}")
        arguments = params.get("arguments", {})
        return handler(name, arguments)
