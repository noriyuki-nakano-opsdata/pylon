#!/usr/bin/env python3
"""Minimal Figma REST API helper for shell-enabled Pylon agents."""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://api.figma.com/v1"


def _token() -> str:
    token = os.environ.get("FIGMA_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("FIGMA_ACCESS_TOKEN is required.")
    return token


def _request(path: str, query: dict[str, str] | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v})
    req = urllib.request.Request(url, headers={"X-Figma-Token": _token()})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"X-Figma-Token": _token()})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def cmd_me(_: argparse.Namespace) -> int:
    print(json.dumps(_request("/me"), ensure_ascii=False, indent=2))
    return 0


def cmd_file(args: argparse.Namespace) -> int:
    query = {}
    if args.branch_data:
        query["branch_data"] = "true"
    if args.depth:
        query["depth"] = str(args.depth)
    if args.ids:
        query["ids"] = args.ids
    print(json.dumps(_request(f"/files/{args.file_key}", query), ensure_ascii=False, indent=2))
    return 0


def cmd_nodes(args: argparse.Namespace) -> int:
    query = {"ids": args.node_ids}
    if args.depth:
        query["depth"] = str(args.depth)
    print(json.dumps(_request(f"/files/{args.file_key}/nodes", query), ensure_ascii=False, indent=2))
    return 0


def cmd_images(args: argparse.Namespace) -> int:
    query = {
        "ids": args.node_ids,
        "format": args.format,
        "scale": str(args.scale),
    }
    payload = _request(f"/images/{args.file_key}", query)
    if args.download_dir:
        out_dir = Path(args.download_dir).expanduser()
        images = payload.get("images", {})
        downloaded: dict[str, str] = {}
        for node_id, url in images.items():
            if not url:
                continue
            suffix = ".svg" if args.format == "svg" else f".{args.format}"
            dest = out_dir / f"{node_id.replace(':', '_')}{suffix}"
            _download(url, dest)
            downloaded[node_id] = str(dest)
        payload["downloaded"] = downloaded
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_comments(args: argparse.Namespace) -> int:
    print(json.dumps(_request(f"/files/{args.file_key}/comments"), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    me = sub.add_parser("me")
    me.set_defaults(func=cmd_me)

    file_p = sub.add_parser("file")
    file_p.add_argument("--file-key", required=True)
    file_p.add_argument("--depth", type=int)
    file_p.add_argument("--ids")
    file_p.add_argument("--branch-data", action="store_true")
    file_p.set_defaults(func=cmd_file)

    nodes = sub.add_parser("nodes")
    nodes.add_argument("--file-key", required=True)
    nodes.add_argument("--node-ids", required=True, help="Comma-separated node ids")
    nodes.add_argument("--depth", type=int)
    nodes.set_defaults(func=cmd_nodes)

    images = sub.add_parser("images")
    images.add_argument("--file-key", required=True)
    images.add_argument("--node-ids", required=True, help="Comma-separated node ids")
    images.add_argument("--format", default="png", choices=["png", "jpg", "svg", "pdf"])
    images.add_argument("--scale", type=float, default=1.0)
    images.add_argument("--download-dir")
    images.set_defaults(func=cmd_images)

    comments = sub.add_parser("comments")
    comments.add_argument("--file-key", required=True)
    comments.set_defaults(func=cmd_comments)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
