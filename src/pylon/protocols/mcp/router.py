"""JSON-RPC method router."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pylon.protocols.mcp.types import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    METHOD_NOT_FOUND,
    INTERNAL_ERROR,
)


class MethodRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}

    def register(self, method: str, handler: Callable) -> None:
        self._handlers[method] = handler

    def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse:
        handler = self._handlers.get(request.method)
        if handler is None:
            return JsonRpcResponse(
                error=JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message=f"Method not found: {request.method}",
                ),
                id=request.id,
            )
        try:
            result = handler(request)
            return JsonRpcResponse(result=result, id=request.id)
        except Exception as exc:
            return JsonRpcResponse(
                error=JsonRpcError(code=INTERNAL_ERROR, message=str(exc)),
                id=request.id,
            )

    def list_methods(self) -> list[str]:
        return sorted(self._handlers.keys())


def route(method: str) -> Callable:
    """Decorator that tags a function with its JSON-RPC method name."""

    def decorator(fn: Callable) -> Callable:
        fn._rpc_method = method  # type: ignore[attr-defined]
        return fn

    return decorator
