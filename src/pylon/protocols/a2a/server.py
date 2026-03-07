"""A2A JSON-RPC 2.0 server (FR-09) - RC v1.0.

Handles tasks/send, tasks/get, tasks/cancel, tasks/sendSubscribe methods.
Supports task handler callbacks, peer authentication, and rate limiting.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pylon.protocols.a2a.dto import (
    DtoValidationError,
    PushNotificationSetParamsDTO,
    SendTaskParamsDTO,
    TaskIdParamsDTO,
    push_notification_payload,
)
from pylon.protocols.a2a.types import (
    A2ATask,
    TaskEvent,
    TaskState,
)
from pylon.protocols.mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)
from pylon.safety.context import SafetyContext
from pylon.safety.engine import SafetyEngine
from pylon.types import AgentCapability, TrustLevel

TaskHandler = Callable[[A2ATask], Awaitable[A2ATask]]
StreamHandler = Callable[[A2ATask], AsyncIterator[TaskEvent]]

# Rate limit error code (custom, outside JSON-RPC reserved range)
RATE_LIMITED = -32000

# Application-defined error code for missing tasks
TASK_NOT_FOUND = -32001
FORBIDDEN = -32003


class A2AServer:
    """Async A2A JSON-RPC 2.0 server with full task lifecycle."""

    def __init__(
        self,
        allowed_peers: set[str] | None = None,
        rate_limit: int = 0,
        rate_window: float = 60.0,
        local_capability: AgentCapability | None = None,
        peer_policies: dict[str, SafetyContext] | None = None,
    ) -> None:
        self._tasks: dict[str, A2ATask] = {}
        self._allowed_peers: set[str] = allowed_peers or set()
        self._task_handler: TaskHandler | None = None
        self._stream_handler: StreamHandler | None = None
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._peer_requests: dict[str, list[float]] = defaultdict(list)
        self._local_capability = local_capability or AgentCapability()
        self._peer_policies = peer_policies or {}

    def on_task(self, handler: TaskHandler) -> TaskHandler:
        """Register a task handler callback (decorator-style)."""
        self._task_handler = handler
        return handler

    def on_stream(self, handler: StreamHandler) -> StreamHandler:
        """Register a streaming task handler (decorator-style)."""
        self._stream_handler = handler
        return handler

    async def handle_request(
        self,
        request: JsonRpcRequest,
        authenticated_peer: str | None = None,
    ) -> JsonRpcResponse:
        """Route a JSON-RPC request to the appropriate handler.

        Args:
            request: The JSON-RPC request to handle.
            authenticated_peer: If provided, the peer identity verified by an
                external authentication layer (e.g. mTLS CN). When set, the
                ``sender`` field in the request params must match this value;
                a mismatch returns a FORBIDDEN error.
        """
        # Verify sender matches authenticated identity when provided
        if authenticated_peer is not None:
            params = request.params or {}
            sender = params.get("sender", "")
            if sender != authenticated_peer:
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(
                        code=FORBIDDEN,
                        message="Sender does not match authenticated peer identity.",
                    ),
                )

        handlers: dict[str, Callable[..., Any]] = {
            "tasks/send": self._handle_send,
            "tasks/get": self._handle_get,
            "tasks/cancel": self._handle_cancel,
            "tasks/pushNotification/set": self._handle_push_notification_set,
            "tasks/pushNotification/get": self._handle_push_notification_get,
        }

        handler = handlers.get(request.method)
        if handler is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message=f"Unknown method: {request.method}",
                ),
            )

        try:
            return await handler(request)
        except DtoValidationError as exc:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=INVALID_PARAMS, message=str(exc)),
            )
        except Exception:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=INTERNAL_ERROR, message="Internal server error"),
            )

    async def handle_subscribe(
        self, request: JsonRpcRequest
    ) -> AsyncIterator[TaskEvent]:
        """Handle tasks/sendSubscribe for streaming updates."""
        params = SendTaskParamsDTO.from_params(request.params)

        sender = params.sender
        if self._allowed_peers and not self.is_peer_allowed(sender):
            raise PermissionError(f"Unknown peer: {sender}")

        if self._rate_limit and not self._check_rate_limit(sender):
            raise RuntimeError("Rate limit exceeded")

        task = A2ATask.from_dict(params.task)
        safety_error = self._validate_sender_task(sender, task)
        if safety_error is not None:
            raise PermissionError(safety_error.message)
        task.transition_to(TaskState.WORKING)
        self._tasks[task.id] = task

        yield TaskEvent(
            type="status",
            task_id=task.id,
            state=TaskState.WORKING.value,
        )

        if self._stream_handler:
            async for event in self._stream_handler(task):
                yield event
                if event.state:
                    try:
                        task.transition_to(TaskState(event.state))
                    except (ValueError, KeyError):
                        pass
        else:
            task.transition_to(TaskState.COMPLETED)
            yield TaskEvent(
                type="status",
                task_id=task.id,
                state=TaskState.COMPLETED.value,
                data=task.to_dict(),
            )

    def is_peer_allowed(self, peer_name: str) -> bool:
        if not self._allowed_peers:
            return True
        return peer_name in self._allowed_peers

    def add_peer(self, peer_name: str) -> None:
        self._allowed_peers.add(peer_name)

    def remove_peer(self, peer_name: str) -> None:
        self._allowed_peers.discard(peer_name)

    def get_task(self, task_id: str) -> A2ATask | None:
        return self._tasks.get(task_id)

    def _check_rate_limit(self, peer: str) -> bool:
        if self._rate_limit <= 0:
            return True
        now = time.time()
        cutoff = now - self._rate_window
        self._peer_requests[peer] = [
            t for t in self._peer_requests[peer] if t > cutoff
        ]
        if not self._peer_requests[peer]:
            del self._peer_requests[peer]
        if len(self._peer_requests.get(peer, [])) >= self._rate_limit:
            return False
        self._peer_requests.setdefault(peer, []).append(now)
        return True

    async def _handle_send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        params = SendTaskParamsDTO.from_params(request.params)

        sender = params.sender
        if self._allowed_peers and not self.is_peer_allowed(sender):
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message=f"Unknown peer: {sender}. Registration required.",
                ),
            )

        if self._rate_limit and not self._check_rate_limit(sender):
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=RATE_LIMITED,
                    message="Rate limit exceeded. Try again later.",
                ),
            )

        task = A2ATask.from_dict(params.task)
        safety_error = self._validate_sender_task(sender, task)
        if safety_error is not None:
            return JsonRpcResponse(id=request.id, error=safety_error)
        # Prevent overwrite of existing tasks
        if task.id in self._tasks:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message=f"Task already exists: {task.id}",
                ),
            )
        task.transition_to(TaskState.WORKING)
        self._tasks[task.id] = task

        if self._task_handler:
            task = await self._task_handler(task)
            self._tasks[task.id] = task

        return JsonRpcResponse(id=request.id, result=task.to_dict())

    async def _handle_get(self, request: JsonRpcRequest) -> JsonRpcResponse:
        task_id = TaskIdParamsDTO.from_params(request.params).task_id

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )

        return JsonRpcResponse(id=request.id, result=task.to_dict())

    async def _handle_cancel(self, request: JsonRpcRequest) -> JsonRpcResponse:
        task_id = TaskIdParamsDTO.from_params(request.params).task_id

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )

        if not task.state.can_transition_to(TaskState.CANCELED):
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message=f"Cannot cancel task in state: {task.state.value}",
                ),
            )

        task.transition_to(TaskState.CANCELED)
        return JsonRpcResponse(id=request.id, result=task.to_dict())

    async def _handle_push_notification_set(self, request: JsonRpcRequest) -> JsonRpcResponse:
        params = PushNotificationSetParamsDTO.from_params(request.params)
        task_id = params.task_id

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )

        task.push_notification = params.push_notification
        return JsonRpcResponse(
            id=request.id,
            result=push_notification_payload(
                task_id=task_id,
                push_notification=task.push_notification,
            ),
        )

    def _validate_sender_task(
        self,
        sender: str,
        task: A2ATask,
    ) -> JsonRpcError | None:
        sender_context = self._peer_policies.get(sender) or self._build_sender_context(sender, task)
        decision = SafetyEngine.evaluate_delegation(
            sender_context,
            self._local_capability,
            receiver_name="local-server",
        )
        if decision.allowed:
            return None
        return JsonRpcError(code=FORBIDDEN, message=decision.reason)

    def _build_sender_context(self, sender: str, task: A2ATask) -> SafetyContext:
        metadata = task.metadata.get("safety", {}) if isinstance(task.metadata, dict) else {}
        capability = AgentCapability.__new__(AgentCapability)
        object.__setattr__(
            capability,
            "can_read_untrusted",
            bool(metadata.get("can_read_untrusted", False)),
        )
        object.__setattr__(
            capability,
            "can_access_secrets",
            bool(metadata.get("can_access_secrets", False)),
        )
        object.__setattr__(
            capability,
            "can_write_external",
            bool(metadata.get("can_write_external", False)),
        )
        data_taint = TrustLevel.UNTRUSTED if task.messages else TrustLevel.TRUSTED
        if metadata.get("data_taint") == TrustLevel.UNTRUSTED.value:
            data_taint = TrustLevel.UNTRUSTED
        return SafetyContext(
            agent_name=sender,
            held_capability=capability,
            data_taint=data_taint,
            effect_scopes=frozenset(metadata.get("effect_scopes", [])),
            secret_scopes=frozenset(metadata.get("secret_scopes", [])),
            call_chain=tuple(metadata.get("call_chain", [])),
        )

    async def _handle_push_notification_get(self, request: JsonRpcRequest) -> JsonRpcResponse:
        task_id = TaskIdParamsDTO.from_params(request.params).task_id

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )

        return JsonRpcResponse(
            id=request.id,
            result=push_notification_payload(
                task_id=task_id,
                push_notification=task.push_notification,
            ),
        )
