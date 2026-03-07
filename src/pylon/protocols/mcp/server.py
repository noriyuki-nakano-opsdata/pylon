"""MCP Server (JSON-RPC 2.0) with all 4 primitives and OAuth 2.1 scoped access."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pylon.protocols.mcp.auth import METHOD_SCOPES, OAuthProvider, check_scope
from pylon.protocols.mcp.dto import (
    CursorParamsDTO,
    DtoValidationError,
    InitializeParamsDTO,
    InitializeResponseDTO,
    PromptGetParamsDTO,
    ResourceReadParamsDTO,
    ResourceSubscribeParamsDTO,
    SamplingCreateParamsDTO,
    ToolCallParamsDTO,
    paginated_payload,
)
from pylon.protocols.mcp.router import MethodRouter
from pylon.protocols.mcp.session import SessionManager
from pylon.protocols.mcp.types import (
    INVALID_PARAMS,
    InitializeResult,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    PromptDefinition,
    ResourceDefinition,
    ResourceTemplate,
    SamplingResponse,
    ServerCapabilities,
    ToolDefinition,
)
from pylon.safety.context import SafetyContext
from pylon.safety.engine import SafetyEngine
from pylon.safety.output_validator import OutputValidator
from pylon.safety.tools import ToolDescriptor, resolve_tool_descriptor

# Custom JSON-RPC error code for auth failures
UNAUTHORIZED = -32001
FORBIDDEN = -32003

DEFAULT_PAGE_SIZE = 10


class McpServer:
    def __init__(
        self,
        name: str = "pylon-mcp",
        version: str = "0.1.0",
        oauth_provider: OAuthProvider | None = None,
        safety_context: SafetyContext | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self._tools: dict[str, ToolDefinition] = {}
        self._tool_descriptors: dict[str, ToolDescriptor] = {}
        self._tool_handlers: dict[str, Callable] = {}
        self._resources: dict[str, ResourceDefinition] = {}
        self._resource_handlers: dict[str, Callable] = {}
        self._resource_templates: dict[str, ResourceTemplate] = {}
        self._resource_subscribers: dict[str, list[str]] = {}
        self._prompts: dict[str, PromptDefinition] = {}
        self._prompt_handlers: dict[str, Callable] = {}
        self._sampling_handler: Callable | None = None
        self._session_manager = SessionManager()
        self._router = MethodRouter()
        self._oauth: OAuthProvider | None = oauth_provider
        self._notifications: list[dict[str, Any]] = []
        self._output_validator = OutputValidator()
        self._safety_context = safety_context or SafetyContext(agent_name=name)
        self._register_builtin_methods()
        self._router.set_request_validator(self._validate_request)

    def _register_builtin_methods(self) -> None:
        self._router.register("initialize", self._handle_initialize)
        self._router.register("tools/list", self._handle_tools_list)
        self._router.register("tools/call", self._handle_tools_call)
        self._router.register("resources/list", self._handle_resources_list)
        self._router.register("resources/read", self._handle_resources_read)
        self._router.register("resources/subscribe", self._handle_resources_subscribe)
        self._router.register("resources/templates/list", self._handle_resources_templates_list)
        self._router.register("prompts/list", self._handle_prompts_list)
        self._router.register("prompts/get", self._handle_prompts_get)
        self._router.register("sampling/createMessage", self._handle_sampling_create)

    @property
    def capabilities(self) -> ServerCapabilities:
        return ServerCapabilities(
            tools=len(self._tools) > 0,
            resources=len(self._resources) > 0 or len(self._resource_templates) > 0,
            prompts=len(self._prompts) > 0,
            sampling=self._sampling_handler is not None,
        )

    def register_tool(
        self,
        tool: ToolDefinition,
        handler: Callable | None = None,
        *,
        descriptor: ToolDescriptor | None = None,
    ) -> None:
        if descriptor is not None:
            tool.safety = descriptor
        self._tools[tool.name] = tool
        self._tool_descriptors[tool.name] = descriptor or tool.safety or resolve_tool_descriptor(
            tool.name
        )
        if handler is not None:
            self._tool_handlers[tool.name] = handler
        self._emit_notification("notifications/tools/list_changed", {})

    def set_safety_context(self, context: SafetyContext) -> None:
        self._safety_context = context

    def register_resource(
        self, resource: ResourceDefinition, handler: Callable | None = None
    ) -> None:
        self._resources[resource.uri] = resource
        if handler is not None:
            self._resource_handlers[resource.uri] = handler
        self._emit_notification("notifications/resources/list_changed", {})

    def register_resource_template(self, template: ResourceTemplate) -> None:
        self._resource_templates[template.uri_template] = template

    def register_prompt(
        self, prompt: PromptDefinition, handler: Callable | None = None
    ) -> None:
        self._prompts[prompt.name] = prompt
        if handler is not None:
            self._prompt_handlers[prompt.name] = handler

    def register_sampling_handler(self, handler: Callable) -> None:
        self._sampling_handler = handler

    def _emit_notification(self, method: str, params: dict[str, Any]) -> None:
        self._notifications.append({"method": method, "params": params})

    def drain_notifications(self) -> list[dict[str, Any]]:
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications

    def handle_request(
        self, request: JsonRpcRequest, access_token: str | None = None
    ) -> JsonRpcResponse:
        if self._oauth is not None and request.method != "initialize":
            required_scope = METHOD_SCOPES.get(request.method)
            if required_scope is not None:
                if access_token is None:
                    return JsonRpcResponse(
                        error=JsonRpcError(
                            code=UNAUTHORIZED,
                            message="Authentication required",
                        ),
                        id=request.id,
                    )
                meta = self._oauth.validate_token(access_token)
                if meta is None:
                    return JsonRpcResponse(
                        error=JsonRpcError(
                            code=UNAUTHORIZED,
                            message="Invalid or expired token",
                        ),
                        id=request.id,
                    )
                if not check_scope(required_scope, meta["scopes"]):
                    return JsonRpcResponse(
                        error=JsonRpcError(
                            code=FORBIDDEN,
                            message=f"Insufficient scope: requires {required_scope}",
                        ),
                        id=request.id,
                    )
        response = self._router.dispatch(request)
        if response is None:
            return None
        if request.method == "initialize" and response.error is None:
            session_id = ""
            if isinstance(response.result, dict):
                session_id = str(response.result.get("sessionId", ""))
            if session_id:
                response.headers["Mcp-Session-Id"] = session_id
        return response

    # --- pagination helper ---

    def _paginate(
        self, items: list[Any], cursor: str | None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> tuple[list[Any], str | None]:
        start = 0
        if cursor is not None:
            try:
                start = int(cursor)
            except ValueError:
                start = 0
        end = start + page_size
        page = items[start:end]
        next_cursor = str(end) if end < len(items) else None
        return page, next_cursor

    # --- built-in handlers ---

    SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2024-11-05")

    def _handle_initialize(self, request: JsonRpcRequest) -> dict:
        InitializeParamsDTO.from_params(request.params)
        raw_params = request.params or {}
        client_version = raw_params.get("protocolVersion")
        if client_version and client_version not in self.SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError(
                f"Unsupported protocol version: {client_version}. "
                f"Supported: {', '.join(self.SUPPORTED_PROTOCOL_VERSIONS)}"
            )
        session = self._session_manager.create_session()
        session.server_capabilities = self.capabilities
        result = InitializeResult(
            capabilities=self.capabilities,
            server_info={"name": self.name, "version": self.version},
        )
        return InitializeResponseDTO(result=result, session_id=session.session_id).to_wire()

    def _handle_tools_list(self, request: JsonRpcRequest) -> dict:
        cursor = CursorParamsDTO.from_params(request.params).cursor
        all_tools = list(self._tools.values())
        page, next_cursor = self._paginate(all_tools, cursor)
        return paginated_payload(
            field_name="tools",
            items=[t.to_dict() for t in page],
            next_cursor=next_cursor,
        )

    def _handle_tools_call(self, request: JsonRpcRequest) -> Any:
        params = ToolCallParamsDTO.from_params(request.params)
        handler = self._tool_handlers.get(params.name)
        if handler is None:
            raise ValueError(f"Tool not found: {params.name}")
        return handler(params.arguments)

    def _validate_request(self, request: JsonRpcRequest) -> JsonRpcError | None:
        if request.method != "tools/call":
            return None
        try:
            params = ToolCallParamsDTO.from_params(request.params)
        except DtoValidationError as exc:
            return JsonRpcError(code=INVALID_PARAMS, message=str(exc))
        validation = self._output_validator.validate_tool_call_detailed(
            params.name,
            params.arguments,
        )
        if not validation.valid:
            return JsonRpcError(
                code=INVALID_PARAMS,
                message="Unsafe tool call arguments",
                data={"violations": validation.violations},
            )
        descriptor = self._tool_descriptors.get(params.name, resolve_tool_descriptor(params.name))
        decision = SafetyEngine.evaluate_tool_use(
            self._safety_context,
            descriptor,
            tool_name=params.name,
        )
        if not decision.allowed:
            return JsonRpcError(code=FORBIDDEN, message=decision.reason)
        if decision.requires_approval:
            return JsonRpcError(
                code=FORBIDDEN,
                message=f"Tool '{params.name}' requires approval before execution",
            )
        return None

    def _handle_resources_list(self, request: JsonRpcRequest) -> dict:
        cursor = CursorParamsDTO.from_params(request.params).cursor
        all_resources = list(self._resources.values())
        page, next_cursor = self._paginate(all_resources, cursor)
        return paginated_payload(
            field_name="resources",
            items=[r.to_dict() for r in page],
            next_cursor=next_cursor,
        )

    def _handle_resources_read(self, request: JsonRpcRequest) -> Any:
        params = ResourceReadParamsDTO.from_params(request.params)
        handler = self._resource_handlers.get(params.uri)
        if handler is None:
            raise ValueError(f"Resource not found: {params.uri}")
        return handler(params.uri)

    def _handle_resources_subscribe(self, request: JsonRpcRequest) -> dict:
        params = ResourceSubscribeParamsDTO.from_params(request.params)
        if params.uri not in self._resources:
            raise ValueError(f"Resource not found: {params.uri}")
        if params.uri not in self._resource_subscribers:
            self._resource_subscribers[params.uri] = []
        if params.session_id and params.session_id not in self._resource_subscribers[params.uri]:
            self._resource_subscribers[params.uri].append(params.session_id)
        return {"subscribed": True, "uri": params.uri}

    def _handle_resources_templates_list(self, request: JsonRpcRequest) -> dict:
        cursor = CursorParamsDTO.from_params(request.params).cursor
        all_templates = list(self._resource_templates.values())
        page, next_cursor = self._paginate(all_templates, cursor)
        return paginated_payload(
            field_name="resourceTemplates",
            items=[t.to_dict() for t in page],
            next_cursor=next_cursor,
        )

    def _handle_prompts_list(self, request: JsonRpcRequest) -> dict:
        cursor = CursorParamsDTO.from_params(request.params).cursor
        all_prompts = list(self._prompts.values())
        page, next_cursor = self._paginate(all_prompts, cursor)
        return paginated_payload(
            field_name="prompts",
            items=[p.to_dict() for p in page],
            next_cursor=next_cursor,
        )

    def _handle_prompts_get(self, request: JsonRpcRequest) -> Any:
        params = PromptGetParamsDTO.from_params(request.params)
        handler = self._prompt_handlers.get(params.name)
        if handler is None:
            raise ValueError(f"Prompt not found: {params.name}")
        return handler(params.name, params.arguments)

    def _handle_sampling_create(self, request: JsonRpcRequest) -> Any:
        if self._sampling_handler is None:
            raise ValueError("Sampling not supported")
        sampling_req = SamplingCreateParamsDTO.from_params(request.params).to_domain()
        result = self._sampling_handler(sampling_req)
        if isinstance(result, SamplingResponse):
            return result.to_dict()
        return result
