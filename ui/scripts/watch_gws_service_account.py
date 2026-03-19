#!/usr/bin/env python3
"""Watch Downloads for a service account JSON key and install it for gws delegation."""

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
TARGET_PATH = Path.home() / ".config" / "gws" / "service-account.json"
POLL_SECONDS = 2


def load_candidate(path: Path) -> dict | None:
    if path.suffix.lower() != ".json" or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    required = {"type", "private_key", "client_email", "private_key_id"}
    if payload.get("type") == "service_account" and required.issubset(payload.keys()):
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
        description="Watch ~/Downloads for a Google service account key JSON and install it for gws delegation."
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    started_at = time.time()
    deadline = started_at + args.timeout_seconds
    print(f"Watching {DOWNLOADS_DIR} for a Google service account JSON...")
    print(f"Target path: {TARGET_PATH}")
    sys.stdout.flush()

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
        print(f"Installed service account JSON from: {match}")
        print(f"Saved to: {TARGET_PATH}")
        return 0

    print("Timed out waiting for a Google service account JSON in Downloads.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
