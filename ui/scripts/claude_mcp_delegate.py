#!/usr/bin/env python3
"""Run host-authenticated Claude MCP tasks from shell-capable Pylon agents."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CLAUDE_BIN = "/Users/noriyuki.nakano/.anyenv/envs/nodenv/versions/20.19.2/bin/claude"


def _resolve_claude_bin() -> str:
    configured = os.environ.get("CLAUDE_CLI_BIN", "").strip()
    candidates = [configured, DEFAULT_CLAUDE_BIN]
    candidates.extend(
        str(path)
        for path in sorted(Path("/Users/noriyuki.nakano/.anyenv/envs/nodenv/versions").glob("*/bin/claude"))
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("Claude CLI binary not found. Set CLAUDE_CLI_BIN.")


def _base_env(claude_bin: str) -> dict[str, str]:
    env = dict(os.environ)
    node_bin = str(Path(claude_bin).parent)
    current_path = env.get("PATH", "")
    env["PATH"] = f"{node_bin}:{current_path}" if current_path else node_bin
    return env


def _run(command: list[str], env: dict[str, str]) -> int:
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show Claude MCP health for one server")
    status_parser.add_argument("--server", required=True, help="Configured Claude MCP server name")

    run_parser = subparsers.add_parser("run", help="Run a Claude prompt against one host-authenticated MCP server")
    run_parser.add_argument("--server", required=True, help="Configured Claude MCP server name")
    run_parser.add_argument("--prompt", required=True, help="Task prompt passed to Claude")
    run_parser.add_argument("--model", default="", help="Optional Claude model alias or full model name")
    run_parser.add_argument(
        "--output-format",
        default="text",
        choices=("text", "json", "stream-json"),
        help="Claude print output format",
    )

    args = parser.parse_args()
    claude_bin = _resolve_claude_bin()
    env = _base_env(claude_bin)

    if args.command == "status":
        return _run([claude_bin, "mcp", "get", args.server], env)

    command = [
        claude_bin,
        "-p",
        "--output-format",
        args.output_format,
        "--dangerously-skip-permissions",
        "--append-system-prompt",
        (
            f"Prefer the configured MCP server named '{args.server}'. "
            "Use explicit links or identifiers instead of relying on local desktop state. "
            "If the requested server is unavailable or unauthenticated, say so directly."
        ),
    ]
    if args.model:
        command.extend(["--model", args.model])
    command.append(args.prompt)
    return _run(command, env)


if __name__ == "__main__":
    sys.exit(main())
