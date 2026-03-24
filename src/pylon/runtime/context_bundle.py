"""Reusable helpers for advisory runtime context bundles."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class ContextBundleFile:
    """One file that belongs to a materialized context bundle."""

    relative_path: str
    content: str
    executable: bool = False
    mutable: bool = False

    def normalized_path(self) -> PurePosixPath:
        return normalize_context_bundle_path(self.relative_path)


@dataclass(frozen=True)
class ContextBundleLayout:
    """Location of a bundle in durable runtime storage and workspaces."""

    runtime_root: Path
    workspace_relative_root: str

    def normalized_workspace_root(self) -> PurePosixPath:
        return normalize_context_bundle_path(self.workspace_relative_root)


def normalize_context_bundle_path(value: str | PurePosixPath) -> PurePosixPath:
    """Normalize and validate a bundle-relative path."""

    normalized = PurePosixPath(str(value).strip())
    if not str(normalized) or str(normalized) == ".":
        raise ValueError("Context bundle paths must not be empty")
    if normalized.is_absolute():
        raise ValueError("Context bundle paths must be relative")
    if ".." in normalized.parts:
        raise ValueError("Context bundle paths must not traverse parent directories")
    return normalized


def context_bundle_workspace_root(
    layout: ContextBundleLayout,
    *,
    workspace_root: Path,
) -> Path:
    """Return the bundle root inside the provided workspace."""

    return workspace_root / layout.normalized_workspace_root()


def materialize_context_bundle(
    layout: ContextBundleLayout,
    files: Iterable[ContextBundleFile],
) -> None:
    """Write the durable bundle contents under the runtime root."""

    runtime_root = Path(layout.runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    for file_spec in files:
        target = runtime_root / file_spec.normalized_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_spec.content, encoding="utf-8")
        _set_executable(target, file_spec.executable)


def mirror_context_bundle_to_workspace(
    layout: ContextBundleLayout,
    *,
    workspace_root: Path,
) -> None:
    """Copy the durable bundle into a disposable workspace tree."""

    source_root = Path(layout.runtime_root)
    target_root = context_bundle_workspace_root(layout, workspace_root=workspace_root)
    if target_root.exists():
        if target_root.is_dir():
            shutil.rmtree(target_root)
        else:
            target_root.unlink()
    target_root.mkdir(parents=True, exist_ok=True)
    if not source_root.exists():
        return
    for source_path in sorted(source_root.rglob("*")):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source_root)
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        _set_executable(target, os.access(source_path, os.X_OK))


def sync_mutable_context_files_from_workspace(
    layout: ContextBundleLayout,
    *,
    workspace_root: Path,
    files: Iterable[ContextBundleFile],
) -> None:
    """Copy mutable bundle files back from a workspace into durable storage."""

    source_root = context_bundle_workspace_root(layout, workspace_root=workspace_root)
    runtime_root = Path(layout.runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    for file_spec in files:
        if not file_spec.mutable:
            continue
        relative_path = file_spec.normalized_path()
        source = source_root / relative_path
        if not source.is_file():
            continue
        target = runtime_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        _set_executable(target, os.access(source, os.X_OK))


def _set_executable(path: Path, executable: bool) -> None:
    mode = path.stat().st_mode
    if executable:
        path.chmod(mode | 0o111)
        return
    path.chmod(mode & ~0o111)
