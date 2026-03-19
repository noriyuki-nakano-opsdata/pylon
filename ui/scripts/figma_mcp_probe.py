#!/usr/bin/env python3
"""Probe or call a Figma MCP endpoint over HTTP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


def _build_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _post_jsonrpc(url: str, method: str, params: dict[str, Any], token: str | None) -> dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
    ).encode()
    request = urllib_request.Request(
        url,
        data=body,
        headers=_build_headers(token),
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=20.0) as response:  # noqa: S310
            raw = response.read().decode()
    except urllib_error.HTTPError as exc:
        payload = exc.read().decode()
        raise SystemExit(
            json.dumps(
                {
                    "ok": False,
                    "status": exc.code,
                    "reason": getattr(exc, "reason", ""),
                    "body": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from exc
    except urllib_error.URLError as exc:
        raise SystemExit(
            json.dumps(
                {"ok": False, "reason": str(exc.reason)},
                ensure_ascii=False,
                indent=2,
            )
        ) from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            json.dumps(
                {
                    "ok": False,
                    "reason": "invalid_json",
                    "body": raw,
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from exc


def _initialize(url: str, token: str | None) -> dict[str, Any]:
    return _post_jsonrpc(
        url,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {
                "name": "pylon-figma-mcp-probe",
                "version": "0.1.0",
            },
        },
        token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("FIGMA_MCP_URL", "http://127.0.0.1:3845/mcp"),
        help="Figma MCP endpoint URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("FIGMA_MCP_AUTH_TOKEN", ""),
        help="Optional bearer token for remote MCP experiments",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    subparsers.add_parser("tools")
    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("--tool", required=True)
    call_parser.add_argument("--arguments", default="{}")
    args = parser.parse_args()

    token = args.token or None
    if args.command == "initialize":
        print(json.dumps(_initialize(args.url, token), ensure_ascii=False, indent=2))
        return 0
    if args.command == "tools":
        _initialize(args.url, token)
        print(json.dumps(_post_jsonrpc(args.url, "tools/list", {}, token), ensure_ascii=False, indent=2))
        return 0

    try:
        arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--arguments must be valid JSON: {exc}") from exc
    _initialize(args.url, token)
    result = _post_jsonrpc(
        args.url,
        "tools/call",
        {"name": args.tool, "arguments": arguments},
        token,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
