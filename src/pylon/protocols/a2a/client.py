"""A2A task delegation client (FR-09).

In-memory implementation. HTTP transport is a future concern.
"""

from __future__ import annotations

from pylon.protocols.mcp.types import JsonRpcRequest
from pylon.protocols.a2a.server import A2AServer
from pylon.protocols.a2a.types import A2ATask


class A2AClient:
    """Client for delegating tasks to an A2A peer via in-memory server."""

    def __init__(self, server: A2AServer, sender: str = "") -> None:
        self._server = server
        self._sender = sender

    def send_task(self, task: A2ATask) -> A2ATask:
        """Send a task to the peer server. Returns the updated task."""
        request = JsonRpcRequest(
            method="tasks/send",
            params={"sender": self._sender, "task": task.to_dict()},
            id=f"send-{task.id}",
        )
        response = self._server.handle_request(request)
        if response.error is not None:
            raise RuntimeError(
                f"A2A tasks/send failed: {response.error.message}"
            )
        return A2ATask.from_dict(response.result)

    def get_task(self, task_id: str) -> A2ATask:
        """Get the current state of a task."""
        request = JsonRpcRequest(
            method="tasks/get",
            params={"task_id": task_id},
            id=f"get-{task_id}",
        )
        response = self._server.handle_request(request)
        if response.error is not None:
            raise RuntimeError(
                f"A2A tasks/get failed: {response.error.message}"
            )
        return A2ATask.from_dict(response.result)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Returns True if canceled successfully."""
        request = JsonRpcRequest(
            method="tasks/cancel",
            params={"task_id": task_id},
            id=f"cancel-{task_id}",
        )
        response = self._server.handle_request(request)
        if response.error is not None:
            return False
        return response.result.get("state") == "canceled"
