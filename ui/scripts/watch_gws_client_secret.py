#!/usr/bin/env python3
"""Watch Downloads for a Google OAuth client JSON and install it for gws."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path


DOWNLOADS_DIR = Path.home() / "Downloads"
TARGET_PATH = Path.home() / ".config" / "gws" / "client_secret.json"
POLL_SECONDS = 2


def looks_like_google_oauth_client(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    section = payload.get("installed") or payload.get("web")
    if not isinstance(section, dict):
        return False
    required_keys = {"client_id", "auth_uri", "token_uri"}
    return required_keys.issubset(section.keys())


def load_candidate(path: Path) -> dict | None:
    if path.suffix.lower() != ".json" or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if looks_like_google_oauth_client(payload):
        return payload
    return None


def install(path: Path, payload: dict) -> None:
    TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = TARGET_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
    shutil.move(str(temp_path), TARGET_PATH)
    os.chmod(TARGET_PATH, stat.S_IRUSR | stat.S_IWUSR)


def find_matching_file(since_ts: float) -> Path | None:
    if not DOWNLOADS_DIR.exists():
        return None
    candidates = sorted(DOWNLOADS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            if path.stat().st_mtime < since_ts:
                continue
        except FileNotFoundError:
            continue
        if load_candidate(path) is not None:
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Watch ~/Downloads for a Google OAuth client JSON and install it for gws."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="How long to wait for a downloaded OAuth client JSON. Default: 900",
    )
    args = parser.parse_args()

    started_at = time.time()
    deadline = started_at + args.timeout_seconds
    print(f"Watching {DOWNLOADS_DIR} for a Google OAuth client JSON...")
    print(f"Target path: {TARGET_PATH}")
    sys.stdout.flush()

    existing = find_matching_file(0)
    if existing is not None and TARGET_PATH.exists():
        print("Existing client_secret.json already present. No changes made.")
        return 0

    while time.time() < deadline:
        match = find_matching_file(started_at)
        if match is None:
            time.sleep(POLL_SECONDS)
            continue
        payload = load_candidate(match)
        if payload is None:
            time.sleep(POLL_SECONDS)
            continue
        install(match, payload)
        print(f"Installed OAuth client config from: {match}")
        print(f"Saved to: {TARGET_PATH}")
        return 0

    print("Timed out waiting for a Google OAuth client JSON in Downloads.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
