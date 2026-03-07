"""A2A JSON-RPC 2.0 server (FR-09) - RC v1.0.

Handles tasks/send, tasks/get, tasks/cancel, tasks/sendSubscribe methods.
Supports task handler callbacks, peer authentication, and rate limiting.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any, AsyncIterator, Awaitable, Callable

from pylon.protocols.mcp.types import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)
from pylon.protocols.a2a.types import (
    A2AMessage,
    A2ATask,
    Artifact,
    Part,
    TaskEvent,
    TaskState,
)

TaskHandler = Callable[[A2ATask], Awaitable[A2ATask]]
StreamHandler = Callable[[A2ATask], AsyncIterator[TaskEvent]]

# Rate limit error code (custom, outside JSON-RPC reserved range)
RATE_LIMITED = -32000


class A2AServer:
    """Async A2A JSON-RPC 2.0 server with full task lifecycle."""

    def __init__(
        self,
        allowed_peers: set[str] | None = None,
        rate_limit: int = 0,
        rate_window: float = 60.0,
    ) -> None:
        self._tasks: dict[str, A2ATask] = {}
        self._allowed_peers: set[str] = allowed_peers or set()
        self._task_handler: TaskHandler | None = None
        self._stream_handler: StreamHandler | None = None
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._peer_requests: dict[str, list[float]] = defaultdict(list)

    def on_task(self, handler: TaskHandler) -> TaskHandler:
        """Register a task handler callback (decorator-style)."""
        self._task_handler = handler
        return handler

    def on_stream(self, handler: StreamHandler) -> StreamHandler:
        """Register a streaming task handler (decorator-style)."""
        self._stream_handler = handler
        return handler

    async def handle_request(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Route a JSON-RPC request to the appropriate handler."""
        handlers: dict[str, Callable[..., Any]] = {
            "tasks/send": self._handle_send,
            "tasks/get": self._handle_get,
            "tasks/cancel": self._handle_cancel,
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
        except Exception as e:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=INTERNAL_ERROR, message="Internal server error"),
            )

    async def handle_subscribe(
        self, request: JsonRpcRequest
    ) -> AsyncIterator[TaskEvent]:
        """Handle tasks/sendSubscribe for streaming updates."""
        params = request.params or {}

        sender = params.get("sender", "")
        if self._allowed_peers and not self.is_peer_allowed(sender):
            raise PermissionError(f"Unknown peer: {sender}")

        if self._rate_limit and not self._check_rate_limit(sender):
            raise RuntimeError("Rate limit exceeded")

        task_data = params.get("task")
        if not task_data:
            raise ValueError("Missing 'task' in params")

        task = A2ATask.from_dict(task_data)
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
        if len(self._peer_requests[peer]) >= self._rate_limit:
            return False
        self._peer_requests[peer].append(now)
        return True

    async def _handle_send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        params = request.params or {}

        sender = params.get("sender", "")
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

        task_data = params.get("task")
        if not task_data:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message="Missing 'task' in params.",
                ),
            )

        task = A2ATask.from_dict(task_data)
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
        params = request.params or {}
        task_id = params.get("task_id")
        if not task_id:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message="Missing 'task_id' in params.",
                ),
            )

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message=f"Task not found: {task_id}",
                ),
            )

        return JsonRpcResponse(id=request.id, result=task.to_dict())

    async def _handle_cancel(self, request: JsonRpcRequest) -> JsonRpcResponse:
        params = request.params or {}
        task_id = params.get("task_id")
        if not task_id:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
                    message="Missing 'task_id' in params.",
                ),
            )

        task = self._tasks.get(task_id)
        if task is None:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=INVALID_PARAMS,
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
