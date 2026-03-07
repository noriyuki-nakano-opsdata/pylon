"""Lightweight ASGI-compatible API server (no FastAPI dependency).

Supports path parameter extraction, middleware chains, and JSON responses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Request:
    """Incoming HTTP request."""

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    path_params: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    """HTTP response."""

    status_code: int = 200
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})
    body: Any = None

    def json_body(self) -> str:
        if self.body is None:
            return ""
        return json.dumps(self.body)


class HandlerFunc(Protocol):
    def __call__(self, request: Request) -> Response: ...


class Middleware(Protocol):
    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response: ...


@dataclass
class _Route:
    """Internal route entry."""

    method: str
    pattern: re.Pattern[str]
    param_names: list[str]
    handler: HandlerFunc


# Matches {param_name} in paths
_PARAM_RE = re.compile(r"\{(\w+)\}")


def _compile_path(path: str) -> tuple[re.Pattern[str], list[str]]:
    """Convert a path template to a regex pattern and extract param names."""
    params: list[str] = _PARAM_RE.findall(path)
    regex = "^" + _PARAM_RE.sub(r"([^/]+)", path) + "$"
    return re.compile(regex), params


class APIServer:
    """Lightweight HTTP API server with routing and middleware."""

    def __init__(self) -> None:
        self._routes: list[_Route] = []
        self._middlewares: list[Middleware] = []

    def add_route(self, method: str, path: str, handler: HandlerFunc) -> None:
        """Register a route handler."""
        pattern, param_names = _compile_path(path)
        self._routes.append(_Route(
            method=method.upper(),
            pattern=pattern,
            param_names=param_names,
            handler=handler,
        ))

    def add_middleware(self, middleware: Middleware) -> None:
        """Add middleware (executed in registration order)."""
        self._middlewares.append(middleware)

    def handle_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> Response:
        """Route and handle an incoming request."""
        request = Request(
            method=method.upper(),
            path=path,
            headers={k.lower(): v for k, v in (headers or {}).items()},
            body=body,
        )

        # Match route
        route = self._match_route(request.method, request.path)
        if route is None:
            # Check if path exists with different method
            allowed_methods: list[str] = []
            for r in self._routes:
                if r.pattern.match(request.path):
                    allowed_methods.append(r.method)
            if allowed_methods:
                return Response(
                    status_code=405,
                    headers={
                        "content-type": "application/json",
                        "allow": ", ".join(sorted(set(allowed_methods))),
                    },
                    body={"error": "Method not allowed"},
                )
            return Response(status_code=404, body={"error": "Not found"})

        # Extract path params
        match = route.pattern.match(request.path)
        if match:
            request.path_params = dict(zip(route.param_names, match.groups()))

        # Build middleware chain
        handler = route.handler
        for mw in reversed(self._middlewares):
            handler = _wrap_middleware(mw, handler)

        return handler(request)

    def _match_route(self, method: str, path: str) -> _Route | None:
        for route in self._routes:
            if route.method == method and route.pattern.match(path):
                return route
        return None


def _wrap_middleware(mw: Middleware, next_handler: HandlerFunc) -> HandlerFunc:
    """Wrap a middleware around a handler."""
    def wrapped(request: Request) -> Response:
        return mw(request, next_handler)
    return wrapped
