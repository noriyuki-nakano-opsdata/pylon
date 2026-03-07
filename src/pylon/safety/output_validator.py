"""LLM output validation before tool execution.

Validates tool call arguments for:
- Shell injection patterns
- Path traversal attempts
- Forbidden argument values
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SHELL_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r";\s*\w",          # command chaining
        r"\|\s*\w",         # pipe
        r"`[^`]+`",         # backtick execution
        r"\$\([^)]+\)",     # subshell
        r"\$\{[^}]+\}",    # variable expansion
        r"&&\s*\w",         # AND chain
        r"\|\|\s*\w",       # OR chain
        r">\s*/",           # redirect to absolute path
        r">>\s*/",          # append to absolute path
    ]
]

_PATH_TRAVERSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"\.\./",           # parent directory
        r"\.\.$",           # trailing ..
        r"~\/",             # home directory
        r"^/etc/",          # system config
        r"^/proc/",         # proc filesystem
        r"^/sys/",          # sys filesystem
    ]
]


@dataclass
class ValidationResult:
    """Result of tool call validation."""

    valid: bool
    violations: list[str]


class OutputValidator:
    """Validates LLM output before tool execution."""

    def __init__(
        self,
        *,
        blocked_tools: list[str] | None = None,
    ) -> None:
        self._blocked_tools = set(blocked_tools or [])

    def validate_tool_call(self, name: str, args: dict) -> bool:
        """Validate a tool call. Returns True if safe, False if blocked."""
        result = self.validate_tool_call_detailed(name, args)
        return result.valid

    def validate_tool_call_detailed(self, name: str, args: dict) -> ValidationResult:
        """Validate a tool call with detailed violation info."""
        violations: list[str] = []

        if name in self._blocked_tools:
            violations.append(f"Tool '{name}' is blocked by policy")

        for key, value in args.items():
            if not isinstance(value, str):
                continue
            for pattern in _SHELL_INJECTION_PATTERNS:
                if pattern.search(value):
                    violations.append(
                        f"Shell injection pattern in arg '{key}': {pattern.pattern}"
                    )
                    break
            for pattern in _PATH_TRAVERSAL_PATTERNS:
                if pattern.search(value):
                    violations.append(
                        f"Path traversal pattern in arg '{key}': {pattern.pattern}"
                    )
                    break

        return ValidationResult(valid=len(violations) == 0, violations=violations)
