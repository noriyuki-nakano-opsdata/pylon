"""A2A JSON-RPC 2.0 server (FR-09).

Handles tasks/send, tasks/get, tasks/cancel methods.
"""

from __future__ import annotations

from pylon.protocols.mcp.types import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)
from pylon.protocols.a2a.types import A2ATask, TaskState


class A2AServer:
    """In-memory A2A JSON-RPC 2.0 server."""

    def __init__(self, allowed_peers: set[str] | None = None) -> None:
        self._tasks: dict[str, A2ATask] = {}
        self._allowed_peers: set[str] = allowed_peers or set()

    def handle_request(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Route a JSON-RPC request to the appropriate handler."""
        handlers = {
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
            return handler(request)
        except Exception as e:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=INTERNAL_ERROR, message=str(e)),
            )

    def is_peer_allowed(self, peer_name: str) -> bool:
        if not self._allowed_peers:
            return True
        return peer_name in self._allowed_peers

    def add_peer(self, peer_name: str) -> None:
        self._allowed_peers.add(peer_name)

    def _handle_send(self, request: JsonRpcRequest) -> JsonRpcResponse:
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
        task.transition_to(TaskState.WORKING)
        self._tasks[task.id] = task

        return JsonRpcResponse(id=request.id, result=task.to_dict())

    def _handle_get(self, request: JsonRpcRequest) -> JsonRpcResponse:
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

    def _handle_cancel(self, request: JsonRpcRequest) -> JsonRpcResponse:
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
