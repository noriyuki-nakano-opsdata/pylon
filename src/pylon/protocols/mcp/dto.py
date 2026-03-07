"""MCP wire DTOs and boundary validation.

This module owns JSON wire-format mapping (camelCase) and validation.
Core protocol models in `types.py` remain snake_case internal models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pylon.protocols.mcp.types import (
    InitializeResult,
    SamplingMessage,
    SamplingRequest,
    ServerCapabilities,
)


class DtoValidationError(ValueError):
    """Raised when JSON-RPC params/result violate MCP DTO contract."""


def _as_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DtoValidationError(f"'{field_name}' must be an object")
    return value


def _as_optional_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _as_object(value, field_name=field_name)


def _get_required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise DtoValidationError(f"'{key}' must be a non-empty string")
    return value


def _get_optional_str(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DtoValidationError(f"'{key}' must be a string")
    return value


def _get_optional_int(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    if not isinstance(value, int):
        raise DtoValidationError(f"'{key}' must be an integer")
    return value


@dataclass(frozen=True)
class CursorParamsDTO:
    cursor: str | None

    @classmethod
    def from_params(cls, params: Any) -> CursorParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        return cls(cursor=_get_optional_str(obj, "cursor"))


@dataclass(frozen=True)
class InitializeParamsDTO:
    capabilities: dict[str, Any]

    @classmethod
    def from_params(cls, params: Any) -> InitializeParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        capabilities = obj.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise DtoValidationError("'capabilities' must be an object")
        return cls(capabilities=capabilities)


@dataclass(frozen=True)
class ToolCallParamsDTO:
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_params(cls, params: Any) -> ToolCallParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        arguments = obj.get("arguments", {})
        if not isinstance(arguments, dict):
            raise DtoValidationError("'arguments' must be an object")
        return cls(
            name=_get_required_str(obj, "name"),
            arguments=arguments,
        )


@dataclass(frozen=True)
class ResourceReadParamsDTO:
    uri: str

    @classmethod
    def from_params(cls, params: Any) -> ResourceReadParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        return cls(uri=_get_required_str(obj, "uri"))


@dataclass(frozen=True)
class ResourceSubscribeParamsDTO:
    uri: str
    session_id: str | None

    @classmethod
    def from_params(cls, params: Any) -> ResourceSubscribeParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        session_id = _get_optional_str(obj, "mcpSessionId")
        if session_id is None:
            session_id = _get_optional_str(obj, "sessionId")
        return cls(
            uri=_get_required_str(obj, "uri"),
            session_id=session_id,
        )


@dataclass(frozen=True)
class PromptGetParamsDTO:
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_params(cls, params: Any) -> PromptGetParamsDTO:
        obj = _as_optional_object(params, field_name="params")
        arguments = obj.get("arguments", {})
        if not isinstance(arguments, dict):
            raise DtoValidationError("'arguments' must be an object")
        return cls(
            name=_get_required_str(obj, "name"),
            arguments=arguments,
        )


@dataclass(frozen=True)
class SamplingCreateParamsDTO:
    messages: list[SamplingMessage]
    system_prompt: str
    max_tokens: int
    model_preferences: dict[str, Any]

    @classmethod
    def from_params(cls, params: Any) -> SamplingCreateParamsDTO:
        obj = _as_optional_object(params, field_name="params")

        wire_messages = obj.get("messages", [])
        if not isinstance(wire_messages, list):
            raise DtoValidationError("'messages' must be an array")

        messages: list[SamplingMessage] = []
        for index, item in enumerate(wire_messages):
            msg = _as_object(item, field_name=f"messages[{index}]")
            role = _get_required_str(msg, "role")
            content = _get_required_str(msg, "content")
            messages.append(SamplingMessage(role=role, content=content))

        model_preferences = obj.get("modelPreferences", {})
        if not isinstance(model_preferences, dict):
            raise DtoValidationError("'modelPreferences' must be an object")

        system_prompt = obj.get("systemPrompt", "")
        if not isinstance(system_prompt, str):
            raise DtoValidationError("'systemPrompt' must be a string")

        max_tokens = _get_optional_int(obj, "maxTokens", 1024)

        return cls(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            model_preferences=model_preferences,
        )

    def to_domain(self) -> SamplingRequest:
        return SamplingRequest(
            messages=self.messages,
            model_preferences=self.model_preferences,
            system_prompt=self.system_prompt,
            max_tokens=self.max_tokens,
        )

    @classmethod
    def from_client_inputs(
        cls,
        *,
        messages: list[dict[str, str]],
        system_prompt: str,
        max_tokens: int,
        model_preferences: dict[str, Any] | None,
    ) -> SamplingCreateParamsDTO:
        wire_params: dict[str, Any] = {
            "messages": messages,
            "systemPrompt": system_prompt,
            "maxTokens": max_tokens,
            "modelPreferences": model_preferences or {},
        }
        return cls.from_params(wire_params)

    def to_wire(self) -> dict[str, Any]:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "systemPrompt": self.system_prompt,
            "maxTokens": self.max_tokens,
            "modelPreferences": self.model_preferences,
        }


@dataclass(frozen=True)
class InitializeResponseDTO:
    result: InitializeResult
    session_id: str | None = None

    @classmethod
    def from_wire(cls, payload: Any) -> InitializeResponseDTO:
        obj = _as_object(payload, field_name="result")
        protocol_version = _get_required_str(obj, "protocolVersion")

        capabilities_obj = _as_object(obj.get("capabilities"), field_name="capabilities")
        server_info = _as_object(obj.get("serverInfo"), field_name="serverInfo")

        session_id = obj.get("sessionId")
        if session_id is not None and not isinstance(session_id, str):
            raise DtoValidationError("'sessionId' must be a string")

        capabilities = ServerCapabilities(
            tools=bool(capabilities_obj.get("tools")),
            resources=bool(capabilities_obj.get("resources")),
            prompts=bool(capabilities_obj.get("prompts")),
            sampling="sampling" in capabilities_obj,
        )
        return cls(
            result=InitializeResult(
                protocol_version=protocol_version,
                capabilities=capabilities,
                server_info=server_info,
            ),
            session_id=session_id,
        )

    def to_wire(self) -> dict[str, Any]:
        payload = self.result.to_dict()
        if self.session_id:
            payload["sessionId"] = self.session_id
        return payload


def paginated_payload(
    *,
    field_name: str,
    items: list[dict[str, Any]],
    next_cursor: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {field_name: items}
    if next_cursor is not None:
        payload["nextCursor"] = next_cursor
    return payload
