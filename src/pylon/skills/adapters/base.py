"""Base adapter interfaces and helpers for skills compatibility imports."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pylon.sdk.decorators import ToolRegistry as SDKToolRegistry
from pylon.skills.catalog import _read_frontmatter
from pylon.skills.import_types import (
    ContextContract,
    ImportedReference,
    ImportedSkillRecord,
    ToolCandidate,
)


def slugify(value: str, *, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or prefix


def file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def markdown_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return path.stem.replace("-", " ").strip()


def parse_markdown_table(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = [line.rstrip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        if index + 1 >= len(lines):
            continue
        divider = lines[index + 1]
        if "|" not in divider or "-" not in divider:
            continue
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row_index = index + 2
        while row_index < len(lines):
            current = lines[row_index].strip()
            if not current.startswith("|"):
                break
            cells = [cell.strip() for cell in current.strip("|").split("|")]
            if len(cells) != len(headers):
                row_index += 1
                continue
            rows.append({
                headers[cell_index]: cells[cell_index]
                for cell_index in range(len(headers))
            })
            row_index += 1
        break
    return rows


def agent_skills_frontmatter(raw: Path) -> tuple[dict[str, Any], str]:
    text = raw.read_text(encoding="utf-8")
    frontmatter, body = _read_frontmatter(text)
    return frontmatter, body.strip()


def tool_registry_index(registry_path: Path) -> dict[str, dict[str, str]]:
    if not registry_path.exists():
        return {}
    index: dict[str, dict[str, str]] = {}
    for row in parse_markdown_table(registry_path.read_text(encoding="utf-8")):
        tool_name = str(row.get("Tool", "")).strip()
        if not tool_name:
            continue
        normalized = tool_name.replace("**", "").strip()
        index[normalized] = {str(key): str(value) for key, value in row.items()}
    return index


class CompatibilityAdapter(ABC):
    """Profile adapter for external skill repositories."""

    profile_name: str = ""
    source_format: str = "agent-skills-spec"
    priority: int = 100

    @abstractmethod
    def matches_repository(self, root: Path) -> bool:
        raise NotImplementedError

    def normalize_skill(
        self,
        *,
        source_root: Path,
        source_payload: dict[str, Any],
        source_revision: str,
        skill_dir: Path,
    ) -> ImportedSkillRecord:
        frontmatter, body = agent_skills_frontmatter(skill_dir / "SKILL.md")
        external_name = str(frontmatter.get("name", skill_dir.name)).strip() or skill_dir.name
        skill_id = self.normalize_skill_key(external_name=external_name, skill_dir=skill_dir)
        references = self.build_references(skill_dir=skill_dir, skill_id=skill_id)
        default_reference_bundle = self.default_reference_bundle(
            skill_id=skill_id,
            references=references,
            body=body,
        )
        context_contracts = self.build_context_contracts(skill_id=skill_id, body=body)
        tool_candidates = self.build_tool_candidates(
            source_root=source_root,
            skill_id=skill_id,
        )
        inference_log = [
            f"profile={self.profile_name}",
            f"source_format={self.source_format}",
            f"references={len(references)}",
            f"context_contracts={len(context_contracts)}",
            f"tool_candidates={len(tool_candidates)}",
        ]
        metadata = frontmatter.get("metadata", {})
        version = ""
        if isinstance(metadata, dict):
            version = str(metadata.get("version", "")).strip()
        return ImportedSkillRecord(
            source_id=str(source_payload["id"]),
            source_revision=source_revision,
            source_skill_path=str(skill_dir.relative_to(source_root)),
            source_format=self.source_format,
            source_name=external_name,
            normalized_id=skill_id,
            normalized_name=external_name,
            description=str(frontmatter.get("description", "")).strip(),
            content=body,
            version=version or "0.0.1",
            references=tuple(references),
            default_reference_bundle=tuple(default_reference_bundle),
            context_contracts=tuple(context_contracts),
            tool_candidates=tuple(tool_candidates),
            inference_log=tuple(inference_log),
        )

    def normalize_skill_key(self, *, external_name: str, skill_dir: Path) -> str:
        return slugify(external_name, prefix=slugify(skill_dir.name, prefix="skill"))

    def build_references(self, *, skill_dir: Path, skill_id: str) -> list[ImportedReference]:
        references: list[ImportedReference] = []
        references_dir = skill_dir / "references"
        if not references_dir.is_dir():
            return references
        for path in sorted(references_dir.rglob("*.md")):
            references.append(
                ImportedReference(
                    skill_id=skill_id,
                    path=str(path.relative_to(skill_dir)),
                    absolute_path=str(path.resolve()),
                    title=markdown_title(path),
                    digest=file_digest(path),
                )
            )
        return references

    def build_context_contracts(self, *, skill_id: str, body: str) -> list[ContextContract]:
        contracts: list[ContextContract] = []
        generic_paths = re.findall(r"`(\.[^`]+)`", body)
        for match in generic_paths:
            if not match.startswith("."):
                continue
            contracts.append(
                ContextContract(
                    contract_id=f"{skill_id}:{slugify(match, prefix='context')}",
                    skill_id=skill_id,
                    path_patterns=(match,),
                    mode="read",
                    required=False,
                    description=f"Compatibility-inferred context contract for {match}.",
                    discovery_hint=f"Check whether {match} exists before running the skill.",
                )
            )
        deduped: dict[str, ContextContract] = {}
        for contract in contracts:
            deduped[contract.contract_id] = contract
        return list(deduped.values())

    def default_reference_bundle(
        self,
        *,
        skill_id: str,
        references: list[ImportedReference],
        body: str,
    ) -> list[str]:
        return []

    def build_tool_candidates(self, *, source_root: Path, skill_id: str) -> list[ToolCandidate]:
        return []

    def guide_candidate(
        self,
        *,
        source_root: Path,
        skill_id: str,
        tool_id: str,
        guide_path: Path,
    ) -> ToolCandidate:
        kind = "platform-ref" if SDKToolRegistry.get(tool_id) is not None else "doc-ref"
        return ToolCandidate(
            candidate_id=f"{skill_id}:{tool_id}:guide",
            skill_id=skill_id,
            origin_path=str(guide_path.relative_to(source_root)),
            adapter_kind="integration-guide",
            proposed_tool_id=tool_id,
            confidence=0.8,
            descriptor_payload={
                "id": tool_id,
                "name": tool_id,
                "kind": kind,
                "description": f"Imported from compatibility source guide {guide_path.name}",
                "input_schema": {"type": "object", "properties": {}},
                "approval_class": "auto" if kind == "platform-ref" else "manual",
                "resource_limits": {"guide_path": str(guide_path.relative_to(source_root))},
            },
            review_required=(kind != "platform-ref"),
        )
