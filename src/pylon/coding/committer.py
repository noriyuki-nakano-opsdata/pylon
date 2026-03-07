from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretPattern:
    name: str
    pattern: re.Pattern[str]


DEFAULT_SECRET_PATTERNS: list[SecretPattern] = [
    SecretPattern("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    SecretPattern("Generic API Key", re.compile(r"""(?i)api[_-]?key\s*[:=]\s*["']?\w{16,}""")),
    SecretPattern("Generic Token", re.compile(r"""(?i)token\s*[:=]\s*["']?\w{16,}""")),
    SecretPattern("Generic Password", re.compile(r"""(?i)password\s*[:=]\s*["'][^"']{8,}["']""")),
    SecretPattern("Private Key", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    SecretPattern("Generic Secret", re.compile(r"""(?i)secret\s*[:=]\s*["']?\w{16,}""")),
]

MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB


@dataclass(frozen=True)
class CommitPlan:
    files_to_add: list[str]
    files_to_modify: list[str]
    files_to_delete: list[str]
    message: str


@dataclass(frozen=True)
class FileContent:
    """A file path paired with its content, used for secret scanning."""

    path: str
    content: str
    size_bytes: int = 0


class GitCommitter:
    """Prepares and validates git commits."""

    def __init__(
        self,
        *,
        secret_patterns: list[SecretPattern] | None = None,
        max_file_size: int = MAX_FILE_SIZE_BYTES,
    ) -> None:
        self.secret_patterns = (
            secret_patterns if secret_patterns is not None else list(DEFAULT_SECRET_PATTERNS)
        )
        self.max_file_size = max_file_size

    async def prepare_commit(
        self,
        changes: list[FileContent],
        message: str,
    ) -> CommitPlan:
        if not message or not message.strip():
            raise ValueError("commit message must not be empty")

        files_to_add: list[str] = []
        files_to_modify: list[str] = []
        files_to_delete: list[str] = []

        for change in changes:
            if not change.content and change.size_bytes == 0:
                files_to_delete.append(change.path)
            elif change.path.startswith("new:"):
                files_to_add.append(change.path.removeprefix("new:"))
            else:
                files_to_modify.append(change.path)

        return CommitPlan(
            files_to_add=files_to_add,
            files_to_modify=files_to_modify,
            files_to_delete=files_to_delete,
            message=message.strip(),
        )

    async def validate_commit(
        self,
        plan: CommitPlan,
        file_contents: list[FileContent] | None = None,
    ) -> tuple[bool, list[str]]:
        """Validate a commit plan. Returns (valid, list_of_issues)."""
        issues: list[str] = []

        if not plan.message or not plan.message.strip():
            issues.append("Commit message is empty")

        if file_contents:
            for fc in file_contents:
                self._check_secrets(fc, issues)
                self._check_file_size(fc, issues)

        return len(issues) == 0, issues

    # ------------------------------------------------------------------

    def _check_secrets(self, fc: FileContent, issues: list[str]) -> None:
        for sp in self.secret_patterns:
            if sp.pattern.search(fc.content):
                issues.append(f"Potential {sp.name} detected in {fc.path}")

    def _check_file_size(self, fc: FileContent, issues: list[str]) -> None:
        size = fc.size_bytes or len(fc.content.encode())
        if size > self.max_file_size:
            issues.append(
                f"File {fc.path} exceeds max size "
                f"({size} > {self.max_file_size} bytes)"
            )
