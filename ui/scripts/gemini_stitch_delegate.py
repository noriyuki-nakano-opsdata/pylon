#!/usr/bin/env python3
"""Configure and run the official Stitch Gemini CLI extension from Pylon."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_GEMINI_BIN = "/Users/noriyuki.nakano/.nvm/versions/node/v24.13.0/bin/gemini"
STITCH_DIR = Path.home() / ".gemini" / "extensions" / "Stitch"
STITCH_CONFIG = STITCH_DIR / "gemini-extension.json"
STITCH_APIKEY_TEMPLATE = STITCH_DIR / "gemini-extension-apikey.json"
STITCH_ADC_TEMPLATE = STITCH_DIR / "gemini-extension-adc.json"


def _resolve_gemini_bin() -> str:
    configured = os.environ.get("GEMINI_CLI_BIN", "").strip()
    candidates = [configured, DEFAULT_GEMINI_BIN]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("Gemini CLI binary not found. Set GEMINI_CLI_BIN.")


def _base_env(gemini_bin: str) -> dict[str, str]:
    env = dict(os.environ)
    node_bin = str(Path(gemini_bin).parent)
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


def _write_stitch_config(payload: dict) -> None:
    STITCH_CONFIG.write_text(json.dumps(payload, indent=2) + "\n")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _configure_api_key(api_key: str) -> None:
    payload = _load_json(STITCH_APIKEY_TEMPLATE)
    payload["mcpServers"]["stitch"]["headers"]["X-Goog-Api-Key"] = api_key
    _write_stitch_config(payload)


def _configure_adc(project_id: str) -> None:
    payload = _load_json(STITCH_ADC_TEMPLATE)
    payload["mcpServers"]["stitch"]["headers"]["X-Goog-User-Project"] = project_id
    _write_stitch_config(payload)


def _status() -> None:
    if not STITCH_CONFIG.exists():
        print("stitch-config: missing")
        return
    payload = _load_json(STITCH_CONFIG)
    headers = payload.get("mcpServers", {}).get("stitch", {}).get("headers", {})
    if headers.get("X-Goog-Api-Key") and headers["X-Goog-Api-Key"] != "YOUR_API_KEY":
        print("stitch-config: api-key configured")
        return
    if headers.get("X-Goog-User-Project") and headers["X-Goog-User-Project"] != "YOUR_PROJECT_ID":
        print(f"stitch-config: adc configured ({headers['X-Goog-User-Project']})")
        return
    print("stitch-config: not configured")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show Stitch extension auth configuration state")

    api_key_parser = subparsers.add_parser("configure-api-key", help="Configure Stitch extension with an API key")
    api_key_parser.add_argument("--api-key", default=os.environ.get("STITCH_API_KEY", ""), help="Stitch API key")

    adc_parser = subparsers.add_parser("configure-adc", help="Configure Stitch extension with ADC project headers")
    adc_parser.add_argument("--project-id", required=True, help="Google Cloud project ID")

    run_parser = subparsers.add_parser("run", help="Run a Stitch prompt through Gemini CLI")
    run_parser.add_argument("--prompt", required=True, help="Prompt text passed to /stitch")
    run_parser.add_argument("--model", default="", help="Optional Gemini model")

    args = parser.parse_args()

    if args.command == "status":
        _status()
        return 0
    if args.command == "configure-api-key":
        api_key = args.api_key.strip()
        if not api_key:
            raise SystemExit("Provide --api-key or set STITCH_API_KEY.")
        _configure_api_key(api_key)
        print("Configured Stitch extension for API key auth.")
        return 0
    if args.command == "configure-adc":
        _configure_adc(args.project_id.strip())
        print(f"Configured Stitch extension for ADC auth with project {args.project_id}.")
        return 0

    gemini_bin = _resolve_gemini_bin()
    env = _base_env(gemini_bin)
    command = [gemini_bin, "-y", "-p", f"/stitch {args.prompt}"]
    if args.model:
        command[1:1] = ["--model", args.model]
    return _run(command, env)


if __name__ == "__main__":
    sys.exit(main())
