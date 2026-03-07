"""A2A task delegation client (FR-09) - RC v1.0.

Async client with retry, connection pooling, and streaming support.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator

from pylon.protocols.a2a.dto import TaskIdParamsDTO
from pylon.protocols.a2a.server import A2AServer
from pylon.protocols.a2a.types import A2ATask, TaskEvent
from pylon.protocols.mcp.types import JsonRpcRequest


class A2AClient:
    """Async client for delegating tasks to an A2A peer via in-memory server."""

    def __init__(
        self,
        server: A2AServer,
        sender: str = "",
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
    ) -> None:
        self._server = server
        self._sender = sender
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def send_task(self, task: A2ATask) -> A2ATask:
        """Send a task to the peer server with auto-retry. Returns the updated task."""
        request = JsonRpcRequest(
            method="tasks/send",
            params={"sender": self._sender, "task": task.to_dict()},
            id=f"send-{task.id}",
        )
        response = await self._send_with_retry(request)
        if response.error is not None:
            raise RuntimeError(
                f"A2A tasks/send failed: {response.error.message}"
            )
        return A2ATask.from_dict(response.result)

    async def get_task(self, task_id: str) -> A2ATask:
        """Get the current state of a task."""
        params = TaskIdParamsDTO.from_client_input(task_id).to_wire()
        request = JsonRpcRequest(
            method="tasks/get",
            params=params,
            id=f"get-{task_id}",
        )
        response = await self._send_with_retry(request)
        if response.error is not None:
            raise RuntimeError(
                f"A2A tasks/get failed: {response.error.message}"
            )
        return A2ATask.from_dict(response.result)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Returns True if canceled successfully."""
        params = TaskIdParamsDTO.from_client_input(task_id).to_wire()
        request = JsonRpcRequest(
            method="tasks/cancel",
            params=params,
            id=f"cancel-{task_id}",
        )
        response = await self._send_with_retry(request)
        if response.error is not None:
            return False
        return response.result.get("state") == "canceled"

    async def send_subscribe(self, task: A2ATask) -> AsyncIterator[TaskEvent]:
        """Send a task and subscribe to streaming updates."""
        request = JsonRpcRequest(
            method="tasks/sendSubscribe",
            params={"sender": self._sender, "task": task.to_dict()},
            id=f"subscribe-{task.id}",
        )
        async for event in self._server.handle_subscribe(request):
            yield event

    async def _send_with_retry(self, request: JsonRpcRequest):
        """Send request with exponential backoff retry."""
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._server.handle_request(request)
                # Don't retry on application-level errors (invalid params, etc.)
                if response.error and response.error.code == -32000:
                    # Rate limited - retry
                    last_error = RuntimeError(response.error.message)
                    if attempt < self._max_retries:
                        delay = min(
                            self._base_delay * (2 ** attempt)
                            + random.uniform(0, self._base_delay),
                            self._max_delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                return response
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = min(
                        self._base_delay * (2 ** attempt)
                        + random.uniform(0, self._base_delay),
                        self._max_delay,
                    )
                    await asyncio.sleep(delay)
        raise RuntimeError(f"Request failed after {self._max_retries + 1} attempts") from last_error


class A2AConnectionPool:
    """Simple connection pool for managing multiple A2A client connections."""

    def __init__(self) -> None:
        self._clients: dict[str, A2AClient] = {}

    def add(self, peer_name: str, client: A2AClient) -> None:
        self._clients[peer_name] = client

    def get(self, peer_name: str) -> A2AClient | None:
        return self._clients.get(peer_name)

    def remove(self, peer_name: str) -> None:
        self._clients.pop(peer_name, None)

    def list_peers(self) -> list[str]:
        return list(self._clients.keys())

    def __len__(self) -> int:
        return len(self._clients)
