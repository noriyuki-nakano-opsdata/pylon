"""MCP protocol type definitions (JSON-RPC 2.0 + MCP 2025-11-25)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class JsonRpcError:
    code: int = 0
    message: str = ""
    data: Any = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


@dataclass
class JsonRpcRequest:
    jsonrpc: str = "2.0"
    method: str = ""
    params: dict | None = None
    id: str | int | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params is not None:
            d["params"] = self.params
        if self.id is not None:
            d["id"] = self.id
        return d


@dataclass
class JsonRpcResponse:
    jsonrpc: str = "2.0"
    result: Any = None
    error: JsonRpcError | None = None
    id: str | int | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error.to_dict()
        else:
            d["result"] = self.result
        return d


@dataclass
class ToolDefinition:
    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class ResourceDefinition:
    uri: str = ""
    name: str = ""
    description: str = ""
    mime_type: str = ""

    def to_dict(self) -> dict:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass
class ResourceTemplate:
    uri_template: str = ""
    name: str = ""
    description: str = ""
    mime_type: str = ""

    def to_dict(self) -> dict:
        return {
            "uriTemplate": self.uri_template,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


@dataclass
class PromptArgument:
    name: str = ""
    description: str = ""
    required: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


@dataclass
class PromptDefinition:
    name: str = ""
    description: str = ""
    arguments: list[PromptArgument] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [a.to_dict() for a in self.arguments],
        }


@dataclass
class SamplingMessage:
    role: str = ""
    content: str = ""

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class SamplingRequest:
    messages: list[SamplingMessage] = field(default_factory=list)
    model_preferences: dict = field(default_factory=dict)
    system_prompt: str = ""
    max_tokens: int = 1024

    def to_dict(self) -> dict:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "modelPreferences": self.model_preferences,
            "systemPrompt": self.system_prompt,
            "maxTokens": self.max_tokens,
        }


@dataclass
class SamplingResponse:
    role: str = "assistant"
    content: str = ""
    model: str = ""
    stop_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "model": self.model,
            "stopReason": self.stop_reason,
        }


@dataclass
class PaginationCursor:
    cursor: str = ""

    def to_dict(self) -> dict:
        return {"cursor": self.cursor}


@dataclass
class PaginatedResult:
    items: list[Any] = field(default_factory=list)
    next_cursor: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {}
        if self.next_cursor is not None:
            d["nextCursor"] = self.next_cursor
        return d


@dataclass
class ServerCapabilities:
    tools: bool = False
    resources: bool = False
    prompts: bool = False
    sampling: bool = False

    def to_dict(self) -> dict:
        d: dict[str, Any] = {}
        if self.tools:
            d["tools"] = {"listChanged": True}
        if self.resources:
            d["resources"] = {"listChanged": True, "subscribe": True}
        if self.prompts:
            d["prompts"] = {"listChanged": True}
        if self.sampling:
            d["sampling"] = {}
        return d


@dataclass
class ClientCapabilities:
    sampling: bool = False

    def to_dict(self) -> dict:
        return {"sampling": self.sampling}


@dataclass
class InitializeResult:
    protocol_version: str = "2025-11-25"
    capabilities: ServerCapabilities = field(default_factory=ServerCapabilities)
    server_info: dict = field(default_factory=lambda: {"name": "pylon-mcp", "version": "0.1.0"})

    def to_dict(self) -> dict:
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities.to_dict(),
            "serverInfo": self.server_info,
        }
