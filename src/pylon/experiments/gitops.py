"""Git and worktree helpers for experiment campaigns."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_GIT_AUTHOR_NAME = "Pylon Experiments"
DEFAULT_GIT_AUTHOR_EMAIL = "experiments@pylon.local"


@dataclass(frozen=True)
class GitCommandResult:
    """Normalized subprocess result for git commands."""

    returncode: int
    stdout: str
    stderr: str


def resolve_repo_root(path: str | Path) -> Path:
    """Resolve the git repository root for the provided path."""

    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        msg = f"Repository path does not exist: {candidate}"
        raise FileNotFoundError(msg)
    result = run_git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to resolve repository root for {candidate}"
        raise ValueError(msg)
    return Path(result.stdout.strip()).resolve()


def resolve_ref(repo_root: str | Path, ref: str) -> str:
    """Return a full commit SHA for the provided ref."""

    result = run_git(repo_root, "rev-parse", ref)
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Unknown git ref: {ref}"
        raise ValueError(msg)
    return result.stdout.strip()


def branch_exists(repo_root: str | Path, branch: str) -> bool:
    result = run_git(repo_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return result.returncode == 0


def create_detached_worktree(
    repo_root: str | Path,
    *,
    worktree_path: str | Path,
    ref: str,
) -> None:
    _prepare_worktree_parent(worktree_path)
    result = run_git(repo_root, "worktree", "add", "--detach", str(worktree_path), ref)
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to create detached worktree at {worktree_path}"
        raise RuntimeError(msg)


def create_branch_worktree(
    repo_root: str | Path,
    *,
    worktree_path: str | Path,
    branch: str,
    ref: str,
) -> None:
    _prepare_worktree_parent(worktree_path)
    if branch_exists(repo_root, branch):
        delete_branch(repo_root, branch)
    result = run_git(repo_root, "worktree", "add", "-b", branch, str(worktree_path), ref)
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to create worktree branch {branch}"
        raise RuntimeError(msg)


def remove_worktree(repo_root: str | Path, worktree_path: str | Path) -> None:
    path = Path(worktree_path)
    if not path.exists():
        return
    result = run_git(repo_root, "worktree", "remove", "--force", str(path))
    if result.returncode != 0 and path.exists():
        shutil.rmtree(path, ignore_errors=True)


def delete_branch(repo_root: str | Path, branch: str) -> None:
    result = run_git(repo_root, "branch", "-D", branch)
    if result.returncode != 0 and "not found" not in result.stderr.lower():
        msg = result.stderr.strip() or f"Failed to delete branch {branch}"
        raise RuntimeError(msg)


def force_branch_ref(repo_root: str | Path, branch: str, ref: str) -> None:
    result = run_git(repo_root, "branch", "-f", branch, ref)
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to update branch {branch}"
        raise RuntimeError(msg)


def worktree_has_changes(worktree_path: str | Path) -> bool:
    result = run_git(worktree_path, "status", "--porcelain")
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to inspect worktree status at {worktree_path}"
        raise RuntimeError(msg)
    return bool(result.stdout.strip())


def commit_all(worktree_path: str | Path, *, message: str) -> str:
    run_git(worktree_path, "add", "-A", check=True)
    env = _git_identity_env()
    result = run_git(
        worktree_path,
        "commit",
        "--no-gpg-sign",
        "--no-verify",
        "-m",
        message,
        env=env,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or "Failed to create experiment commit"
        raise RuntimeError(msg)
    return resolve_ref(worktree_path, "HEAD")


def diff_stat(repo_root: str | Path, base_ref: str, target_ref: str) -> str:
    result = run_git(repo_root, "diff", "--stat", "--compact-summary", base_ref, target_ref)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def changed_files(repo_root: str | Path, base_ref: str, target_ref: str) -> list[str]:
    result = run_git(repo_root, "diff", "--name-only", base_ref, target_ref)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def ensure_worktree_excludes(
    worktree_path: str | Path,
    patterns: list[str],
) -> Path:
    """Ensure worktree-local exclude rules exist for disposable files."""

    normalized_patterns = [pattern.strip() for pattern in patterns if pattern.strip()]
    result = run_git(worktree_path, "rev-parse", "--git-path", "info/exclude")
    if result.returncode != 0:
        msg = result.stderr.strip() or f"Failed to resolve git exclude path for {worktree_path}"
        raise RuntimeError(msg)
    exclude_path = Path(result.stdout.strip()).resolve()
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = (
        exclude_path.read_text(encoding="utf-8").splitlines()
        if exclude_path.exists()
        else []
    )
    known_patterns = {line.strip() for line in existing_lines if line.strip()}
    missing = [pattern for pattern in normalized_patterns if pattern not in known_patterns]
    if not missing:
        return exclude_path
    with exclude_path.open("a", encoding="utf-8") as handle:
        if existing_lines and existing_lines[-1].strip():
            handle.write("\n")
        for pattern in missing:
            handle.write(f"{pattern}\n")
    return exclude_path


def run_git(
    cwd: str | Path,
    *args: str,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> GitCommandResult:
    """Run a git command and return stdout/stderr text."""

    completed = subprocess.run(
        ["git", *args],
        cwd=str(Path(cwd).expanduser()),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    result = GitCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        msg = result.stderr.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(msg)
    return result


def _prepare_worktree_parent(worktree_path: str | Path) -> None:
    path = Path(worktree_path)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)


def _git_identity_env() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": DEFAULT_GIT_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": DEFAULT_GIT_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": DEFAULT_GIT_AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": DEFAULT_GIT_AUTHOR_EMAIL,
    }
