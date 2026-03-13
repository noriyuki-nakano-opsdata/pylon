"""Compatibility layer for importing external Agent Skills repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from pylon.skills.adapters.base import slugify
from pylon.skills.adapters.registry import (
    CompatibilityAdapterRegistry,
    get_default_adapter_registry,
)
from pylon.skills.import_types import (
    ImportSession,
    ImportSnapshot,
    ImportedSkillRecord,
    ToolCandidate,
    ToolCandidateDecision,
    ToolCandidateReview,
    tool_candidate_fingerprint,
    utc_now_iso,
)
from pylon.skills.models import SkillHandle, SkillVersionRef


def default_import_root() -> Path:
    configured = os.getenv("PYLON_SKILL_IMPORT_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(".pylon") / "imports"


def _repo_digest(root: Path) -> str:
    import hashlib

    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in {".git", "node_modules", "__pycache__"} for part in path.parts):
            continue
        stat = path.stat()
        entries.append(
            f"{path.relative_to(root)}:{int(stat.st_mtime)}:{stat.st_size}"
        )
    return hashlib.sha256("|".join(entries).encode("utf-8")).hexdigest()


def _dump_frontmatter(payload: dict[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n\n{body.strip()}\n"


class SkillCompatibilityLayer:
    """Imports external Agent Skills repositories into pylon-native skill packages."""

    def __init__(
        self,
        *,
        import_root: Path | None = None,
        adapter_registry: CompatibilityAdapterRegistry | None = None,
    ) -> None:
        self._import_root = (import_root or default_import_root()).expanduser()
        self._adapter_registry = adapter_registry or get_default_adapter_registry()

    def source_checkout_dir(self, source_id: str) -> Path:
        return self._import_root / source_id / "checkout"

    def source_root_dir(self, source_id: str) -> Path:
        return self._import_root / source_id

    def source_normalized_dir(self, source_id: str) -> Path:
        return self._import_root / source_id / "normalized"

    def source_skills_dir(self, source_id: str) -> Path:
        return self.source_normalized_dir(source_id) / "skills"

    def source_staging_root(self, source_id: str) -> Path:
        return self.source_root_dir(source_id) / ".staging"

    def source_snapshots_dir(self, source_id: str) -> Path:
        return self.source_root_dir(source_id) / "snapshots"

    def source_tool_candidate_decisions_path(self, source_id: str) -> Path:
        return self.source_root_dir(source_id) / "tool-candidate-decisions.json"

    def normalize_source_payload(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        location = str(payload.get("location", "")).strip()
        if not location:
            raise ValueError("Skill source location is required")
        kind = str(payload.get("kind", "local-dir")).strip() or "local-dir"
        source_id = str(payload.get("id", "")).strip() or slugify(Path(location).name or location, prefix="skill-source")
        normalized = {
            "id": source_id,
            "tenant_id": tenant_id,
            "kind": kind,
            "location": location,
            "adapter_profile": str(payload.get("adapter_profile", "")).strip() or "",
            "trust_class": str(payload.get("trust_class", "internal")).strip() or "internal",
            "default_branch": str(payload.get("default_branch", "main")).strip() or "main",
            "status": "registered",
        }
        return normalized

    def sync_source(
        self,
        source_payload: dict[str, Any],
        *,
        tool_candidate_decisions: dict[str, ToolCandidateDecision] | None = None,
    ) -> dict[str, Any]:
        source_id = str(source_payload["id"])
        session = self._begin_import_session(source_payload)
        source_format, detected_profile = self._adapter_registry.classify(session.checkout_dir)
        profile = str(source_payload.get("adapter_profile", "")).strip() or detected_profile
        adapter = self._adapter_registry.get(profile)
        revision = self._detect_revision(
            session.checkout_dir,
            kind=str(source_payload.get("kind", "local-dir")),
        )
        snapshot_id = uuid.uuid4().hex
        manifest_skills: list[dict[str, Any]] = []
        imported: list[ImportedSkillRecord] = []
        if source_format == "agent-skills-spec":
            skill_root = session.checkout_dir / "skills"
            for skill_dir in sorted(skill_root.iterdir()):
                if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                    continue
                imported.append(
                    adapter.normalize_skill(
                        source_root=session.checkout_dir,
                        source_payload=source_payload,
                        source_revision=revision,
                        skill_dir=skill_dir,
                    )
                )
        resolved_tool_candidate_decisions = (
            dict(tool_candidate_decisions)
            if tool_candidate_decisions is not None
            else self._load_tool_candidate_decisions(source_id)
        )
        tool_candidate_reviews = self._build_tool_candidate_reviews(
            source_id=source_id,
            source_revision=revision,
            imported=imported,
            decisions=resolved_tool_candidate_decisions,
        )
        self._materialize_imported_skills(
            artifact_root=session.staging_dir,
            checkout_dir=session.checkout_dir,
            source_payload=source_payload,
            source_revision=revision,
            imported=imported,
            tool_candidate_reviews=tool_candidate_reviews,
        )
        for record in imported:
            manifest_skills.append(
                {
                    "id": record.canonical_id,
                    "alias": record.normalized_id,
                    "skill_key": record.skill_key,
                    "handle": SkillHandle(
                        source_id=record.source_id,
                        skill_key=record.skill_key,
                    ).to_payload(),
                    "version_ref": SkillVersionRef(
                        source_id=record.source_id,
                        skill_key=record.skill_key,
                        revision=record.source_revision,
                    ).to_payload(),
                    "name": record.normalized_name,
                    "description": record.description,
                    "version": record.version,
                    "source_skill_path": record.source_skill_path,
                    "references": [asdict(item) for item in record.references],
                    "context_contracts": [asdict(item) for item in record.context_contracts],
                    "tool_candidates": [
                        {
                            **asdict(item),
                            "review": tool_candidate_reviews[item.candidate_id].to_payload(),
                        }
                        for item in record.tool_candidates
                    ],
                    "inference_log": list(record.inference_log),
                }
            )
        manifest = {
            "snapshot": {
                "snapshot_id": snapshot_id,
                "created_at": utc_now_iso(),
            },
            "source": {
                **dict(source_payload),
                "adapter_profile": profile,
                "source_format": source_format,
                "source_revision": revision,
                "checkout_dir": str(session.checkout_dir.resolve()),
                "normalized_dir": str(self.source_normalized_dir(source_id).resolve()),
            },
            "skills": manifest_skills,
        }
        session.staging_dir.mkdir(parents=True, exist_ok=True)
        (session.staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        report = {
            "session_id": session.session_id,
            "snapshot_id": snapshot_id,
            "source_id": source_id,
            "source_revision": revision,
            "adapter_profile": profile,
            "source_format": source_format,
            "imported_skill_count": len(manifest_skills),
            "references_count": sum(len(item["references"]) for item in manifest_skills),
            "tool_candidate_count": sum(len(item["tool_candidates"]) for item in manifest_skills),
            "promoted_tool_count": sum(
                1
                for review in tool_candidate_reviews.values()
                if review.promoted
            ),
            "tool_candidate_states": self._tool_candidate_state_counts(tool_candidate_reviews),
            "context_contract_count": sum(len(item["context_contracts"]) for item in manifest_skills),
            "normalized_dir": str(self.source_normalized_dir(source_id).resolve()),
        }
        (session.staging_dir / "import-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        promoted_dir = self._promote_staged_snapshot(source_id, session.staging_dir)
        snapshot = ImportSnapshot(
            snapshot_id=snapshot_id,
            source_id=source_id,
            revision=revision,
            source_format=source_format,
            adapter_profile=profile,
            created_at=str(manifest["snapshot"]["created_at"]),
            manifest_path=str((promoted_dir / "manifest.json").resolve()),
            report_path=str((promoted_dir / "import-report.json").resolve()),
            promoted_path=str(promoted_dir.resolve()),
        )
        self._persist_snapshot_metadata(snapshot)
        persisted_report = dict(report)
        persisted_report["promoted_dir"] = snapshot.promoted_path
        persisted_report["snapshot"] = snapshot.to_payload()
        (promoted_dir / "import-report.json").write_text(
            json.dumps(persisted_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._cleanup_staging_root(source_id)
        return persisted_report

    def manifest_for_source(self, source_id: str) -> dict[str, Any] | None:
        manifest_path = self.source_normalized_dir(source_id) / "manifest.json"
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def skill_metadata(
        self,
        skill_id: str,
        *,
        source_id: str = "",
        skill_key: str = "",
    ) -> dict[str, Any] | None:
        requested_id = str(skill_id).strip()
        requested_source_id = str(source_id).strip()
        requested_skill_key = str(skill_key).strip()
        for manifest_path in sorted(self._import_root.glob("*/normalized/manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_source = manifest.get("source", {})
            manifest_source_id = str(manifest_source.get("id", "")).strip()
            for skill in manifest.get("skills", []):
                candidate_id = str(skill.get("id", "")).strip()
                candidate_alias = str(skill.get("alias", skill.get("skill_key", ""))).strip()
                candidate_skill_key = str(skill.get("skill_key", candidate_alias)).strip()
                if requested_source_id and manifest_source_id != requested_source_id:
                    continue
                if requested_skill_key and candidate_skill_key != requested_skill_key:
                    continue
                if requested_id and requested_id not in {
                    candidate_id,
                    candidate_alias,
                    candidate_skill_key,
                }:
                    continue
                enriched = dict(skill)
                enriched.setdefault("source_id", manifest_source_id)
                return enriched
        return None

    def list_tool_candidates(self, source_id: str) -> list[dict[str, Any]]:
        manifest = self.manifest_for_source(source_id) or {}
        candidates: list[dict[str, Any]] = []
        for skill in manifest.get("skills", []):
            for candidate in skill.get("tool_candidates", []):
                payload = dict(candidate)
                payload.setdefault("source_id", source_id)
                payload.setdefault("skill_alias", skill.get("alias", skill.get("skill_key", "")))
                payload.setdefault("skill_handle", skill.get("handle", {}))
                payload.setdefault("skill_version_ref", skill.get("version_ref", {}))
                candidates.append(payload)
        candidates.sort(
            key=lambda item: (
                str(item.get("skill_id", "")),
                str(item.get("proposed_tool_id", "")),
                str(item.get("candidate_id", "")),
            )
        )
        return candidates

    def set_tool_candidate_state(
        self,
        *,
        source_id: str,
        candidate_id: str,
        state: str,
        note: str = "",
    ) -> dict[str, Any]:
        normalized_state = str(state).strip().lower()
        if normalized_state not in {"pending", "approved", "rejected"}:
            raise ValueError("Tool candidate state must be one of ['pending', 'approved', 'rejected']")
        manifest = self.manifest_for_source(source_id) or {}
        target: dict[str, Any] | None = None
        for skill in manifest.get("skills", []):
            for candidate in skill.get("tool_candidates", []):
                if str(candidate.get("candidate_id", "")).strip() == str(candidate_id).strip():
                    target = dict(candidate)
                    break
            if target is not None:
                break
        if target is None:
            raise KeyError(candidate_id)
        fingerprint = str(target.get("review", {}).get("fingerprint", "")).strip()
        if not fingerprint:
            fingerprint = tool_candidate_fingerprint(
                ToolCandidate(
                    candidate_id=str(target.get("candidate_id", "")),
                    skill_id=str(target.get("skill_id", "")),
                    origin_path=str(target.get("origin_path", "")),
                    adapter_kind=str(target.get("adapter_kind", "")),
                    proposed_tool_id=str(target.get("proposed_tool_id", "")),
                    confidence=float(target.get("confidence", 0.0) or 0.0),
                    descriptor_payload=dict(target.get("descriptor_payload", {})),
                    review_required=bool(target.get("review_required", True)),
                )
            )
        decisions = self._load_tool_candidate_decisions(source_id)
        if normalized_state == "pending":
            decisions.pop(str(candidate_id), None)
        else:
            decisions[str(candidate_id)] = ToolCandidateDecision(
                candidate_id=str(candidate_id),
                fingerprint=fingerprint,
                state=normalized_state,
                note=str(note).strip(),
                decided_at=utc_now_iso(),
            )
        self._save_tool_candidate_decisions(source_id, decisions)
        return {
            "candidate_id": str(candidate_id),
            "state": normalized_state,
            "note": str(note).strip(),
            "fingerprint": fingerprint,
        }

    def _prepare_checkout(self, source_payload: dict[str, Any]) -> Path:
        source_id = str(source_payload["id"])
        kind = str(source_payload.get("kind", "local-dir"))
        location = Path(str(source_payload["location"]).strip()).expanduser()
        if kind == "local-dir":
            return location.resolve()
        checkout_dir = self.source_checkout_dir(source_id)
        if checkout_dir.exists():
            subprocess.run(
                ["git", "-C", str(checkout_dir), "fetch", "--all", "--tags"],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            checkout_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", str(source_payload["location"]), str(checkout_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        default_branch = str(source_payload.get("default_branch", "main"))
        subprocess.run(
            ["git", "-C", str(checkout_dir), "checkout", default_branch],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout_dir), "pull", "--ff-only"],
            check=True,
            capture_output=True,
            text=True,
        )
        return checkout_dir

    def _detect_revision(self, checkout_dir: Path, *, kind: str) -> str:
        if kind == "git":
            try:
                result = subprocess.run(
                    ["git", "-C", str(checkout_dir), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()
            except Exception:
                return _repo_digest(checkout_dir)
        return _repo_digest(checkout_dir)

    def _begin_import_session(self, source_payload: dict[str, Any]) -> ImportSession:
        source_id = str(source_payload["id"])
        checkout_dir = self._prepare_checkout(source_payload)
        session_id = uuid.uuid4().hex
        staging_dir = self.source_staging_root(source_id) / session_id
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        return ImportSession(
            session_id=session_id,
            source_id=source_id,
            source_payload=dict(source_payload),
            checkout_dir=checkout_dir,
            staging_dir=staging_dir,
        )

    def _persist_snapshot_metadata(self, snapshot: ImportSnapshot) -> None:
        snapshot_dir = self.source_snapshots_dir(snapshot.source_id)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / f"{snapshot.snapshot_id}.json").write_text(
            json.dumps(snapshot.to_payload(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _promote_staged_snapshot(self, source_id: str, staged_dir: Path) -> Path:
        source_root = self.source_root_dir(source_id)
        normalized_dir = self.source_normalized_dir(source_id)
        backup_dir = source_root / f"normalized.__backup__.{uuid.uuid4().hex}"
        source_root.mkdir(parents=True, exist_ok=True)
        try:
            if normalized_dir.exists():
                normalized_dir.replace(backup_dir)
            staged_dir.replace(normalized_dir)
        except Exception:
            if backup_dir.exists() and not normalized_dir.exists():
                backup_dir.replace(normalized_dir)
            raise
        finally:
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
        return normalized_dir

    def _cleanup_staging_root(self, source_id: str) -> None:
        staging_root = self.source_staging_root(source_id)
        if not staging_root.exists():
            return
        for child in staging_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    def _load_tool_candidate_decisions(
        self,
        source_id: str,
    ) -> dict[str, ToolCandidateDecision]:
        path = self.source_tool_candidate_decisions_path(source_id)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        decisions: dict[str, ToolCandidateDecision] = {}
        for key, item in dict(payload.get("candidates", {})).items():
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", key)).strip()
            fingerprint = str(item.get("fingerprint", "")).strip()
            if not candidate_id or not fingerprint:
                continue
            decisions[candidate_id] = ToolCandidateDecision(
                candidate_id=candidate_id,
                fingerprint=fingerprint,
                state=str(item.get("state", "pending")).strip() or "pending",
                note=str(item.get("note", "")).strip(),
                decided_at=str(item.get("decided_at", "")).strip(),
            )
        return decisions

    def _save_tool_candidate_decisions(
        self,
        source_id: str,
        decisions: dict[str, ToolCandidateDecision],
    ) -> None:
        path = self.source_tool_candidate_decisions_path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_id": source_id,
            "updated_at": utc_now_iso(),
            "candidates": {
                candidate_id: asdict(decision)
                for candidate_id, decision in sorted(decisions.items())
            },
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _build_tool_candidate_reviews(
        self,
        *,
        source_id: str,
        source_revision: str,
        imported: list[ImportedSkillRecord],
        decisions: dict[str, ToolCandidateDecision],
    ) -> dict[str, ToolCandidateReview]:
        reviews: dict[str, ToolCandidateReview] = {}
        for record in imported:
            for candidate in record.tool_candidates:
                reviews[candidate.candidate_id] = self._resolve_tool_candidate_review(
                    source_id=source_id,
                    source_revision=source_revision,
                    candidate=candidate,
                    decisions=decisions,
                )
        return reviews

    def _resolve_tool_candidate_review(
        self,
        *,
        source_id: str,
        source_revision: str,
        candidate: ToolCandidate,
        decisions: dict[str, ToolCandidateDecision],
    ) -> ToolCandidateReview:
        fingerprint = tool_candidate_fingerprint(candidate)
        descriptor_kind = str(candidate.descriptor_payload.get("kind", "")).strip() or "unknown"
        bindable = descriptor_kind in {"local-script", "platform-ref"}
        blocked_reason = ""
        if not bindable:
            blocked_reason = f"descriptor kind '{descriptor_kind}' is not executable"
        if not candidate.review_required:
            return ToolCandidateReview(
                candidate_id=candidate.candidate_id,
                source_id=source_id,
                skill_id=candidate.skill_id,
                proposed_tool_id=candidate.proposed_tool_id,
                adapter_kind=candidate.adapter_kind,
                origin_path=candidate.origin_path,
                descriptor_kind=descriptor_kind,
                fingerprint=fingerprint,
                review_required=False,
                source_revision=source_revision,
                state="auto-approved",
                promoted=bindable,
                bindable=bindable,
                decision_source="system",
                promotion_blocked_reason=blocked_reason,
            )
        decision = decisions.get(candidate.candidate_id)
        if decision is None:
            return ToolCandidateReview(
                candidate_id=candidate.candidate_id,
                source_id=source_id,
                skill_id=candidate.skill_id,
                proposed_tool_id=candidate.proposed_tool_id,
                adapter_kind=candidate.adapter_kind,
                origin_path=candidate.origin_path,
                descriptor_kind=descriptor_kind,
                fingerprint=fingerprint,
                review_required=True,
                source_revision=source_revision,
                state="pending",
                promoted=False,
                bindable=bindable,
                promotion_blocked_reason=blocked_reason,
            )
        if decision.fingerprint != fingerprint:
            return ToolCandidateReview(
                candidate_id=candidate.candidate_id,
                source_id=source_id,
                skill_id=candidate.skill_id,
                proposed_tool_id=candidate.proposed_tool_id,
                adapter_kind=candidate.adapter_kind,
                origin_path=candidate.origin_path,
                descriptor_kind=descriptor_kind,
                fingerprint=fingerprint,
                review_required=True,
                source_revision=source_revision,
                state="pending",
                promoted=False,
                bindable=bindable,
                decision_source="stale",
                note=decision.note,
                decided_at=decision.decided_at,
                stale_decision=True,
                promotion_blocked_reason=blocked_reason,
            )
        promoted = decision.state == "approved" and bindable
        return ToolCandidateReview(
            candidate_id=candidate.candidate_id,
            source_id=source_id,
            skill_id=candidate.skill_id,
            proposed_tool_id=candidate.proposed_tool_id,
            adapter_kind=candidate.adapter_kind,
            origin_path=candidate.origin_path,
            descriptor_kind=descriptor_kind,
            fingerprint=fingerprint,
            review_required=True,
            source_revision=source_revision,
            state=decision.state,
            promoted=promoted,
            bindable=bindable,
            decision_source="manual",
            note=decision.note,
            decided_at=decision.decided_at,
            promotion_blocked_reason=blocked_reason,
        )

    @staticmethod
    def _tool_candidate_state_counts(
        reviews: dict[str, ToolCandidateReview],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for review in reviews.values():
            counts[review.state] = counts.get(review.state, 0) + 1
        return counts

    def _materialize_imported_skills(
        self,
        *,
        artifact_root: Path,
        checkout_dir: Path,
        source_payload: dict[str, Any],
        source_revision: str,
        imported: list[ImportedSkillRecord],
        tool_candidate_reviews: dict[str, ToolCandidateReview],
    ) -> None:
        source_id = str(source_payload["id"])
        skills_dir = artifact_root / "skills"
        if skills_dir.exists():
            shutil.rmtree(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        for record in imported:
            skill_dir = skills_dir / record.normalized_id
            skill_dir.mkdir(parents=True, exist_ok=True)
            frontmatter = {
                "id": record.canonical_id,
                "alias": record.normalized_id,
                "skill_key": record.skill_key,
                "name": record.normalized_name,
                "version": record.version,
                "description": record.description,
                "source": str(source_payload.get("location", source_id)),
                "source_kind": "imported",
                "source_id": source_id,
                "source_revision": source_revision,
                "source_format": record.source_format,
                "trust_class": str(source_payload.get("trust_class", "internal")),
                "approval_class": "auto",
                "references": [item.path for item in record.references],
                "reference_assets": [asdict(item) for item in record.references],
                "default_reference_bundle": list(record.default_reference_bundle),
                "context_contracts": [asdict(item) for item in record.context_contracts],
                "import_inference_log": list(record.inference_log),
            }
            (skill_dir / "SKILL.md").write_text(
                _dump_frontmatter(frontmatter, record.content),
                encoding="utf-8",
            )
            if record.references:
                references_dir = skill_dir / "references"
                references_dir.mkdir(exist_ok=True)
                for reference in record.references:
                    source_path = Path(reference.absolute_path)
                    target_path = skill_dir / reference.path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, target_path)
            promoted_candidates = [
                candidate
                for candidate in record.tool_candidates
                if tool_candidate_reviews.get(candidate.candidate_id) is not None
                and tool_candidate_reviews[candidate.candidate_id].promoted
            ]
            if promoted_candidates:
                tools_dir = skill_dir / "tools"
                tools_dir.mkdir(exist_ok=True)
            for candidate in promoted_candidates:
                descriptor = dict(candidate.descriptor_payload)
                tool_id = str(descriptor.get("id", candidate.proposed_tool_id))
                origin_path = checkout_dir / candidate.origin_path
                if descriptor.get("kind") == "local-script" and origin_path.exists():
                    scripts_dir = skill_dir / "scripts"
                    scripts_dir.mkdir(exist_ok=True)
                    copied_name = f"{tool_id}{origin_path.suffix or '.bin'}"
                    copied_path = scripts_dir / copied_name
                    shutil.copy2(origin_path, copied_path)
                    descriptor["entrypoint"] = f"scripts/{copied_name}"
                elif candidate.origin_path:
                    descriptor.setdefault("resource_limits", {})
                    descriptor["resource_limits"]["origin_path"] = candidate.origin_path
                (skill_dir / "tools" / f"{tool_id}.yaml").write_text(
                    yaml.safe_dump(descriptor, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )


@lru_cache(maxsize=1)
def get_default_skill_compatibility_layer() -> SkillCompatibilityLayer:
    return SkillCompatibilityLayer()
