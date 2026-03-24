"""Profile adapter for importing The Agency / agency-agents repositories."""

from __future__ import annotations

from pathlib import Path

from pylon.skills.adapters.base import (
    CompatibilityAdapter,
    agent_skills_frontmatter,
    file_digest,
    markdown_title,
    slugify,
)
from pylon.skills.import_types import (
    ContextContract,
    ImportedReference,
    ImportedSkillRecord,
)

_EXCLUDED_ROOTS = {"examples", "integrations", "scripts", "strategy"}
_CATEGORY_REFERENCE_PATHS: dict[str, tuple[str, ...]] = {
    "engineering": ("strategy/playbooks/phase-3-build.md",),
    "design": (
        "strategy/playbooks/phase-1-strategy.md",
        "strategy/playbooks/phase-2-foundation.md",
    ),
    "marketing": ("strategy/playbooks/phase-5-launch.md",),
    "paid-media": ("strategy/playbooks/phase-5-launch.md",),
    "product": (
        "strategy/playbooks/phase-0-discovery.md",
        "strategy/playbooks/phase-1-strategy.md",
    ),
    "project-management": (
        "strategy/QUICKSTART.md",
        "strategy/coordination/handoff-templates.md",
    ),
    "sales": ("strategy/playbooks/phase-5-launch.md",),
    "specialized": ("strategy/nexus-strategy.md",),
    "support": ("strategy/playbooks/phase-6-operate.md",),
    "testing": (
        "strategy/playbooks/phase-4-hardening.md",
        "strategy/coordination/handoff-templates.md",
    ),
}
_SKILL_REFERENCE_PATHS: dict[str, tuple[str, ...]] = {
    "agents-orchestrator": (
        "strategy/QUICKSTART.md",
        "strategy/nexus-strategy.md",
        "strategy/coordination/handoff-templates.md",
        "strategy/coordination/agent-activation-prompts.md",
    ),
    "backend-architect": (
        "strategy/playbooks/phase-1-strategy.md",
        "strategy/playbooks/phase-3-build.md",
    ),
    "devops-automator": (
        "strategy/playbooks/phase-2-foundation.md",
        "strategy/playbooks/phase-4-hardening.md",
        "strategy/playbooks/phase-6-operate.md",
    ),
    "evidence-collector": (
        "strategy/coordination/handoff-templates.md",
        "strategy/playbooks/phase-4-hardening.md",
    ),
    "frontend-developer": (
        "strategy/playbooks/phase-2-foundation.md",
        "strategy/playbooks/phase-3-build.md",
    ),
    "reality-checker": (
        "strategy/coordination/handoff-templates.md",
        "strategy/playbooks/phase-4-hardening.md",
    ),
}
_DEFAULT_REFERENCE_BUNDLES: dict[str, tuple[str, ...]] = {
    "agents-orchestrator": (
        "strategy/QUICKSTART.md",
        "strategy/coordination/handoff-templates.md",
    ),
    "evidence-collector": ("strategy/coordination/handoff-templates.md",),
    "reality-checker": ("strategy/coordination/handoff-templates.md",),
}


class AgencyAgentsAdapter(CompatibilityAdapter):
    profile_name = "agency-agents"
    source_format = "agency-agents"
    priority = 90

    def matches_repository(self, root: Path) -> bool:
        return (
            (root / "README.md").exists()
            and (root / "strategy" / "nexus-strategy.md").exists()
            and (root / "specialized" / "agents-orchestrator.md").exists()
        )

    def import_records(
        self,
        *,
        source_root: Path,
        source_payload: dict[str, object],
        source_revision: str,
    ) -> list[ImportedSkillRecord]:
        records: list[ImportedSkillRecord] = []
        used_ids: set[str] = set()
        for markdown_file in self._iter_agent_files(source_root):
            relative_path = markdown_file.relative_to(source_root)
            category = relative_path.parts[0] if relative_path.parts else "other"
            frontmatter, body = agent_skills_frontmatter(markdown_file)
            external_name = (
                str(frontmatter.get("name", "")).strip()
                or markdown_title(markdown_file)
            )
            normalized_id = self._normalized_id(
                relative_path=relative_path,
                external_name=external_name,
                used_ids=used_ids,
            )
            references = self._build_references(
                source_root=source_root,
                skill_id=normalized_id,
                category=category,
            )
            default_reference_bundle = tuple(
                path for path in _DEFAULT_REFERENCE_BUNDLES.get(normalized_id, ()) if any(
                    reference.path == path for reference in references
                )
            )
            context_contracts = self._build_context_contracts(skill_id=normalized_id, body=body)
            inference_log = [
                f"profile={self.profile_name}",
                f"source_format={self.source_format}",
                f"category={category}",
                f"references={len(references)}",
                f"context_contracts={len(context_contracts)}",
                "tool_candidates=0",
            ]
            records.append(
                ImportedSkillRecord(
                    source_id=str(source_payload["id"]),
                    source_revision=source_revision,
                    source_skill_path=str(relative_path),
                    source_format=self.source_format,
                    source_name=external_name,
                    normalized_id=normalized_id,
                    normalized_name=external_name,
                    description=str(frontmatter.get("description", "")).strip(),
                    content=body,
                    version="0.0.1",
                    category=category,
                    references=tuple(references),
                    default_reference_bundle=default_reference_bundle,
                    context_contracts=tuple(context_contracts),
                    tool_candidates=(),
                    inference_log=tuple(inference_log),
                )
            )
        return records

    def _iter_agent_files(self, source_root: Path) -> list[Path]:
        results: list[Path] = []
        for child in sorted(source_root.iterdir()):
            if not child.is_dir() or child.name in _EXCLUDED_ROOTS:
                continue
            for markdown_file in sorted(child.rglob("*.md")):
                if markdown_file.name.upper() == "README.md":
                    continue
                results.append(markdown_file)
        return results

    def _normalized_id(
        self,
        *,
        relative_path: Path,
        external_name: str,
        used_ids: set[str],
    ) -> str:
        candidate = slugify(external_name, prefix=slugify(relative_path.stem, prefix="skill"))
        if candidate in used_ids:
            candidate = slugify(
                f"{relative_path.parent.name}-{relative_path.stem}",
                prefix=candidate,
            )
        used_ids.add(candidate)
        return candidate

    def _build_references(
        self,
        *,
        source_root: Path,
        skill_id: str,
        category: str,
    ) -> list[ImportedReference]:
        references: list[ImportedReference] = []
        seen_paths: set[str] = set()
        for relative_path in [
            *_CATEGORY_REFERENCE_PATHS.get(category, ()),
            *_SKILL_REFERENCE_PATHS.get(skill_id, ()),
        ]:
            if relative_path in seen_paths:
                continue
            source_path = source_root / relative_path
            if not source_path.exists() or not source_path.is_file():
                continue
            seen_paths.add(relative_path)
            references.append(
                ImportedReference(
                    skill_id=skill_id,
                    path=relative_path,
                    absolute_path=str(source_path.resolve()),
                    title=markdown_title(source_path),
                    digest=file_digest(source_path),
                )
            )
        return references

    def _build_context_contracts(self, *, skill_id: str, body: str) -> list[ContextContract]:
        contracts = super().build_context_contracts(skill_id=skill_id, body=body)
        if skill_id in {"evidence-collector", "reality-checker"}:
            contracts.append(
                ContextContract(
                    contract_id=f"{skill_id}:qa-screenshot-results",
                    skill_id=skill_id,
                    path_patterns=("public/qa-screenshots/test-results.json",),
                    mode="read",
                    required=False,
                    description="Playwright QA capture results for evidence-based verification.",
                    discovery_hint=(
                        "Load the QA capture summary before issuing a pass/fail verdict."
                    ),
                    max_chars=6000,
                )
            )
        deduped: dict[str, ContextContract] = {}
        for contract in contracts:
            deduped[contract.contract_id] = contract
        return list(deduped.values())
