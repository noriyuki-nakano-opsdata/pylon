"""Output formatting for Pylon CLI (json/table/yaml)."""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

import yaml


def auto_detect_format() -> str:
    """Return 'table' if stdout is a TTY, else 'json'."""
    return "table" if sys.stdout.isatty() else "json"


class OutputFormatter:
    """Formats CLI output as json, table, or yaml."""

    def __init__(self, fmt: str | None = None) -> None:
        self.fmt = fmt or auto_detect_format()

    def render(self, data: Any, headers: Sequence[str] | None = None) -> str:
        if self.fmt == "json":
            return self.format_json(data)
        if self.fmt == "yaml":
            return self.format_yaml(data)
        return self.format_table(data, headers)

    @staticmethod
    def format_json(data: Any) -> str:
        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def format_yaml(data: Any) -> str:
        return yaml.dump(data, default_flow_style=False, allow_unicode=True).rstrip()

    @staticmethod
    def format_table(data: Any, headers: Sequence[str] | None = None) -> str:
        if isinstance(data, dict):
            rows = [[str(k), str(v)] for k, v in data.items()]
            headers = headers or ["Key", "Value"]
        elif isinstance(data, list):
            if not data:
                return "(empty)"
            if isinstance(data[0], dict):
                headers = headers or list(data[0].keys())
                rows = [[str(row.get(h, "")) for h in headers] for row in data]
            else:
                headers = headers or ["Value"]
                rows = [[str(item)] for item in data]
        else:
            return str(data)

        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(cell))

        def fmt_row(cells: Sequence[str]) -> str:
            return "  ".join(c.ljust(col_widths[i]) for i, c in enumerate(cells))

        lines = [fmt_row(headers), fmt_row(["-" * w for w in col_widths])]
        for row in rows:
            lines.append(fmt_row(row))
        return "\n".join(lines)
