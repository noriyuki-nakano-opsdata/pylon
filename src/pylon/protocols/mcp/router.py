"""JSON-RPC method router."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pylon.protocols.mcp.dto import DtoValidationError

logger = logging.getLogger(__name__)
from pylon.protocols.mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)


class MethodRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}

    def register(self, method: str, handler: Callable) -> None:
        self._handlers[method] = handler

    def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse | None:
        handler = self._handlers.get(request.method)
        if handler is None:
            if request.id is None:
                return None
            return JsonRpcResponse(
                error=JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message=f"Method not found: {request.method}",
                ),
                id=request.id,
            )
        try:
            result = handler(request)
            if request.id is None:
                return None
            return JsonRpcResponse(result=result, id=request.id)
        except DtoValidationError as exc:
            if request.id is None:
                return None
            return JsonRpcResponse(
                error=JsonRpcError(code=INVALID_PARAMS, message=str(exc)),
                id=request.id,
            )
        except Exception:
            logger.exception("Unhandled error in JSON-RPC handler for method %s", request.method)
            if request.id is None:
                return None
            return JsonRpcResponse(
                error=JsonRpcError(
                    code=INTERNAL_ERROR,
                    message="Internal error",
                ),
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
