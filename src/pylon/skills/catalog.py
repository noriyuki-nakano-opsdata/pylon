"""Filesystem-backed skill catalog with lazy refresh."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from pylon.skills.models import SkillRecord, SkillToolSpec


def _bundled_skill_dir() -> Path:
    return Path(__file__).resolve().parent / "bundled" / "agency-agents"


def default_skill_dirs() -> tuple[str, ...]:
    return (
        str(_bundled_skill_dir()),
        str(Path.home() / ".codex" / "skills"),
        str(Path.home() / ".claude" / "skills"),
        str(Path("ui") / "scripts" / "skills"),
        str(Path(".pylon") / "skills"),
        str(Path(".pylon") / "tenants" / "{tenant_id}" / "skills"),
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    _, _, tail = text.partition("---\n")
    yaml_text, sep, body = tail.partition("\n---\n")
    if not sep:
        return {}, text
    loaded = yaml.safe_load(yaml_text) or {}
    return (loaded if isinstance(loaded, dict) else {}), body


def _iso_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _coerce_str_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        trimmed = value.strip()
        return (trimmed,) if trimmed else ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _coerce_mapping_list(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(key): item[key] for key in item})
    return tuple(result)


def _normalize_tool_spec(
    payload: dict[str, Any],
    *,
    tool_id: str,
) -> SkillToolSpec:
    input_schema = payload.get("args_schema") or payload.get("input_schema") or {
        "type": "object",
        "properties": {},
    }
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}
    return SkillToolSpec(
        id=str(payload.get("id", tool_id)).strip() or tool_id,
        name=str(payload.get("name", tool_id)).strip() or tool_id,
        kind=str(payload.get("kind", "local-script")).strip() or "local-script",
        description=str(payload.get("description", "")).strip(),
        input_schema=dict(input_schema),
        entrypoint=str(payload.get("entrypoint", "")).strip(),
        timeout_seconds=int(payload.get("timeout_seconds", 30) or 30),
        read_only=bool(payload.get("read_only", True)),
        sandbox=str(payload.get("sandbox", "inherit") or "inherit"),
        trust_class=str(payload.get("trust_class", "internal") or "internal"),
        approval_class=str(payload.get("approval_class", "auto") or "auto"),
        resource_limits=(
            dict(payload.get("resource_limits"))
            if isinstance(payload.get("resource_limits"), dict)
            else {}
        ),
    )


def _parse_tool_descriptors(
    skill_dir: Path,
    toolset_ids: tuple[str, ...],
) -> tuple[SkillToolSpec, ...]:
    descriptors: dict[str, SkillToolSpec] = {}
    tools_dir = skill_dir / "tools"
    if tools_dir.is_dir():
        for descriptor_path in sorted(tools_dir.glob("*.y*ml")):
            loaded = yaml.safe_load(descriptor_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                continue
            spec = _normalize_tool_spec(loaded, tool_id=descriptor_path.stem)
            descriptors[spec.id] = spec
    for tool_id in toolset_ids:
        if tool_id not in descriptors:
            descriptors[tool_id] = SkillToolSpec(
                id=tool_id,
                name=tool_id,
                kind="platform-ref",
                description="Platform tool reference",
            )
    return tuple(descriptors.values())


def parse_skill_dir(
    skill_dir: Path,
    *,
    source: str = "local",
    source_kind: str = "filesystem",
) -> SkillRecord | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    raw = skill_file.read_text(encoding="utf-8")
    frontmatter, body = _read_frontmatter(raw)
    metadata = frontmatter.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    skill_id = str(frontmatter.get("id", skill_dir.name)).strip() or skill_dir.name
    toolset_ids = _coerce_str_list(frontmatter.get("toolsets"))
    tools = _parse_tool_descriptors(skill_dir, toolset_ids)
    digest_payload = {
        "frontmatter": frontmatter,
        "body": body,
        "tools": [asdict(tool) for tool in tools],
    }
    preview = body.strip()[:240]
    return SkillRecord(
        id=skill_id,
        alias=str(frontmatter.get("alias", skill_id)).strip() or skill_id,
        skill_key=(
            str(frontmatter.get("skill_key", frontmatter.get("alias", skill_id))).strip()
            or skill_id
        ),
        name=str(frontmatter.get("name", skill_id)).strip() or skill_id,
        version=str(frontmatter.get("version", "0.0.1")).strip() or "0.0.1",
        description=str(frontmatter.get("description", "")).strip(),
        content=body.strip(),
        content_preview=preview,
        category=(
            str(frontmatter.get("category", metadata.get("category", "other"))).strip()
            or "other"
        ),
        risk=str(frontmatter.get("risk", metadata.get("risk", "unknown"))).strip() or "unknown",
        source=str(frontmatter.get("source", metadata.get("source", source))).strip() or source,
        source_kind=(
            str(frontmatter.get("source_kind", metadata.get("source_kind", source_kind))).strip()
            or source_kind
        ),
        tags=_coerce_str_list(frontmatter.get("tags", metadata.get("tags"))),
        path=str(skill_dir),
        installed_at=_iso_timestamp(skill_file),
        has_scripts=(
            (skill_dir / "scripts").is_dir()
            or any(skill_dir.glob("*.py"))
            or any(skill_dir.glob("*.sh"))
        ),
        dependencies=_coerce_str_list(frontmatter.get("dependencies")),
        toolsets=toolset_ids,
        tools=tools,
        prompt_priority=int(frontmatter.get("prompt_priority", 50) or 50),
        trust_class=str(frontmatter.get("trust_class", "internal")).strip() or "internal",
        approval_class=str(frontmatter.get("approval_class", "auto")).strip() or "auto",
        max_prompt_chars=int(frontmatter.get("max_prompt_chars", 5000) or 5000),
        digest=_sha256_text(json.dumps(digest_payload, sort_keys=True, ensure_ascii=False)),
        references=_coerce_str_list(frontmatter.get("references")),
        reference_assets=_coerce_mapping_list(frontmatter.get("reference_assets")),
        default_reference_bundle=_coerce_str_list(frontmatter.get("default_reference_bundle")),
        context_contracts=_coerce_mapping_list(frontmatter.get("context_contracts")),
        source_id=str(frontmatter.get("source_id", "")).strip(),
        source_revision=str(frontmatter.get("source_revision", "")).strip(),
        source_format=str(frontmatter.get("source_format", "")).strip(),
    )


class SkillCatalog:
    """Lazy-refreshing catalog for filesystem skill packages."""

    def __init__(
        self,
        *,
        skill_dirs: tuple[str, ...] | None = None,
        refresh_ttl_seconds: float = 2.0,
    ) -> None:
        self._skill_dirs = skill_dirs if skill_dirs is not None else default_skill_dirs()
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._shared_skills: dict[str, SkillRecord] = {}
        self._tenant_skills: dict[str, dict[str, SkillRecord]] = {}
        self._last_refresh_at = 0.0
        self._last_snapshot = ""
        self._lock = threading.RLock()

    def _scan_imported_skills_enabled(self) -> bool:
        # `skill_dirs=()` is an explicit opt-out for the implicit default import root,
        # but an explicit PYLON_SKILL_IMPORT_ROOT should still be honored.
        return bool(self._skill_dirs) or bool(os.getenv("PYLON_SKILL_IMPORT_ROOT", "").strip())

    def list_skills(self, *, tenant_id: str | None = None) -> list[SkillRecord]:
        self.refresh_if_stale(tenant_id=tenant_id)
        with self._lock:
            merged = dict(self._shared_skills)
            if tenant_id:
                merged.update(self._tenant_skills.get(tenant_id, {}))
            return [merged[key] for key in sorted(merged)]

    def get_skill(self, skill_id: str, *, tenant_id: str | None = None) -> SkillRecord | None:
        self.refresh_if_stale(tenant_id=tenant_id)
        with self._lock:
            if tenant_id and skill_id in self._tenant_skills.get(tenant_id, {}):
                return self._tenant_skills[tenant_id][skill_id]
            return self._shared_skills.get(skill_id)

    def rescan(self, *, tenant_id: str | None = None) -> dict[str, int]:
        with self._lock:
            before = self._effective_digest_map(tenant_id=tenant_id)
            shared, tenant_map, snapshot = self._scan_all(tenant_id=tenant_id)
            self._shared_skills = shared
            if tenant_id:
                self._tenant_skills[tenant_id] = tenant_map.get(tenant_id, {})
            else:
                self._tenant_skills = tenant_map
            self._last_snapshot = snapshot
            self._last_refresh_at = time.monotonic()
            after = self._effective_digest_map(tenant_id=tenant_id)
        before_keys = set(before)
        after_keys = set(after)
        return {
            "total": len(after),
            "new": len(after_keys - before_keys),
            "updated": sum(1 for key in before_keys & after_keys if before[key] != after[key]),
            "removed": len(before_keys - after_keys),
        }

    def refresh_if_stale(self, *, tenant_id: str | None = None) -> None:
        with self._lock:
            if (time.monotonic() - self._last_refresh_at) < self._refresh_ttl_seconds:
                return
            _, _, snapshot = self._scan_all(tenant_id=tenant_id)
            if snapshot == self._last_snapshot:
                self._last_refresh_at = time.monotonic()
                return
        self.rescan(tenant_id=tenant_id)

    def _effective_digest_map(self, *, tenant_id: str | None) -> dict[str, str]:
        merged = {skill.id: skill.digest for skill in self._shared_skills.values()}
        if tenant_id:
            merged.update({
                skill.id: skill.digest
                for skill in self._tenant_skills.get(tenant_id, {}).values()
            })
        else:
            for tenant_skills in self._tenant_skills.values():
                merged.update({skill.id: skill.digest for skill in tenant_skills.values()})
        return merged

    def _scan_all(
        self,
        *,
        tenant_id: str | None,
    ) -> tuple[dict[str, SkillRecord], dict[str, dict[str, SkillRecord]], str]:
        shared: dict[str, SkillRecord] = {}
        tenant_map: dict[str, dict[str, SkillRecord]] = {}
        snapshot_parts: list[str] = []
        for raw_dir in self._skill_dirs:
            if "{tenant_id}" in raw_dir:
                if not tenant_id:
                    continue
                candidate = Path(raw_dir.format(tenant_id=tenant_id)).expanduser()
                if not candidate.is_dir():
                    continue
                tenant_skills = self._scan_dir(candidate)
                tenant_map[tenant_id] = tenant_skills
                snapshot_parts.extend(
                    f"{tenant_id}:{skill_id}:{record.digest}"
                    for skill_id, record in tenant_skills.items()
                )
                continue
            candidate = Path(raw_dir).expanduser()
            if not candidate.is_dir():
                continue
            scanned = self._scan_dir(candidate)
            shared.update(scanned)
            snapshot_parts.extend(
                f"shared:{skill_id}:{record.digest}"
                for skill_id, record in scanned.items()
            )
        import_root = Path(
            os.getenv("PYLON_SKILL_IMPORT_ROOT", "").strip()
            or (Path(".pylon") / "imports")
        )
        if self._scan_imported_skills_enabled() and import_root.is_dir():
            for skills_root in sorted(import_root.glob("*/normalized/skills")):
                scanned = self._scan_dir(skills_root, source="imported", source_kind="imported")
                for skill_id, record in scanned.items():
                    shared.setdefault(skill_id, record)
                snapshot_parts.extend(
                    f"imported:{skill_id}:{record.digest}"
                    for skill_id, record in scanned.items()
                )
        snapshot = _sha256_text("|".join(sorted(snapshot_parts)))
        return shared, tenant_map, snapshot

    def _scan_dir(
        self,
        base_dir: Path,
        *,
        source: str = "local",
        source_kind: str = "filesystem",
    ) -> dict[str, SkillRecord]:
        results: dict[str, SkillRecord] = {}
        for child in sorted(base_dir.iterdir()):
            if not child.is_dir():
                continue
            parsed = parse_skill_dir(child, source=source, source_kind=source_kind)
            if parsed is not None:
                results[parsed.id] = parsed
        return results


@lru_cache(maxsize=1)
def get_default_skill_catalog() -> SkillCatalog:
    return SkillCatalog()
