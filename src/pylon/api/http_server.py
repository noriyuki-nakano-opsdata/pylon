"""HTTP server adapter for the lightweight Pylon route server."""

from __future__ import annotations

import json
import logging
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from pylon.api.server import APIServer, Response

logger = logging.getLogger(__name__)


def _resolve_request_headers(headers: dict[str, str]) -> tuple[str, str]:
    request_id = headers.get("x-request-id", "") or uuid.uuid4().hex
    correlation_id = headers.get("x-correlation-id", "") or request_id
    return request_id, correlation_id


class _BoundHTTPRequestHandler(BaseHTTPRequestHandler):
    """Base handler bound to an APIServer instance through subclassing."""

    api_server: APIServer

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, format: str, *args: object) -> None:
        """Silence stdlib request logging by default."""

    def _handle(self) -> None:
        request_body = self._read_request_body()
        path = urlsplit(self.path).path
        request_headers = {key: value for key, value in self.headers.items()}
        request_id, correlation_id = _resolve_request_headers(
            {key.lower(): value for key, value in request_headers.items()}
        )
        try:
            response = self.api_server.handle_request(
                self.command,
                path,
                headers=request_headers,
                body=request_body,
            )
        except Exception:
            logger.exception("Unhandled exception while serving %s %s", self.command, path)
            response = Response(
                status_code=500,
                headers={
                    "x-request-id": request_id,
                    "x-correlation-id": correlation_id,
                },
                body={"error": "Internal server error"},
            )
        self._write_response(response)

    _MAX_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MiB

    def _read_request_body(self) -> Any:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return None
        if content_length > self._MAX_BODY_SIZE:
            self.send_error(413, "Request body too large")
            return None
        raw = self.rfile.read(content_length)
        if not raw:
            return None
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON body")
                return None
        return raw.decode("utf-8")

    def _write_response(self, response: Response) -> None:
        body_bytes: bytes
        if response.body is None:
            body_bytes = b""
        elif isinstance(response.body, (bytes, bytearray)):
            body_bytes = bytes(response.body)
        elif isinstance(response.body, str):
            body_bytes = response.body.encode("utf-8")
        else:
            body_bytes = response.json_body().encode("utf-8")

        headers = dict(response.headers)
        headers.setdefault("content-type", "application/json")
        headers["content-length"] = str(len(body_bytes))

        self.send_response(response.status_code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if body_bytes:
            self.wfile.write(body_bytes)


def build_http_handler(api_server: APIServer) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to the given APIServer."""

    class _Handler(_BoundHTTPRequestHandler):
        pass

    _Handler.api_server = api_server
    return _Handler


class PylonHTTPServer(ThreadingHTTPServer):
    """Thin stdlib HTTP server that delegates routing to APIServer."""

    def __init__(
        self,
        server_address: tuple[str, int],
        api_server: APIServer,
    ) -> None:
        super().__init__(server_address, build_http_handler(api_server))
        self.api_server = api_server


def create_http_server(
    api_server: APIServer,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> PylonHTTPServer:
    """Create a stdlib HTTP server around the given APIServer."""
    return PylonHTTPServer((host, port), api_server)
