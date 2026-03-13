"""Shared import-time types for the skills compatibility subsystem."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pylon.skills.models import SkillHandle, SkillVersionRef


def canonical_skill_id(source_id: str, skill_key: str) -> str:
    return SkillHandle(
        source_id=str(source_id).strip(),
        skill_key=str(skill_key).strip(),
    ).canonical_id


def canonical_version_ref(source_id: str, skill_key: str, revision: str) -> str:
    return SkillVersionRef(
        source_id=str(source_id).strip(),
        skill_key=str(skill_key).strip(),
        revision=str(revision).strip(),
    ).canonical_ref


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tool_candidate_fingerprint(candidate: "ToolCandidate") -> str:
    payload = {
        "candidate_id": candidate.candidate_id,
        "skill_id": candidate.skill_id,
        "origin_path": candidate.origin_path,
        "adapter_kind": candidate.adapter_kind,
        "proposed_tool_id": candidate.proposed_tool_id,
        "descriptor_payload": candidate.descriptor_payload,
        "review_required": candidate.review_required,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ImportedReference:
    skill_id: str
    path: str
    absolute_path: str
    kind: str = "reference-md"
    title: str = ""
    tags: tuple[str, ...] = ()
    digest: str = ""


@dataclass(frozen=True)
class ContextContract:
    contract_id: str
    skill_id: str
    path_patterns: tuple[str, ...]
    mode: str = "read"
    required: bool = False
    description: str = ""
    discovery_hint: str = ""
    max_chars: int = 4000


@dataclass(frozen=True)
class ToolCandidate:
    candidate_id: str
    skill_id: str
    origin_path: str
    adapter_kind: str
    proposed_tool_id: str
    confidence: float = 0.0
    descriptor_payload: dict[str, Any] = field(default_factory=dict)
    review_required: bool = True


@dataclass(frozen=True)
class ToolCandidateDecision:
    candidate_id: str
    fingerprint: str
    state: str = "pending"
    note: str = ""
    decided_at: str = ""


@dataclass(frozen=True)
class ToolCandidateReview:
    candidate_id: str
    source_id: str
    skill_id: str
    proposed_tool_id: str
    adapter_kind: str
    origin_path: str
    descriptor_kind: str
    fingerprint: str
    review_required: bool
    source_revision: str
    state: str = "pending"
    promoted: bool = False
    bindable: bool = False
    decision_source: str = "none"
    note: str = ""
    decided_at: str = ""
    stale_decision: bool = False
    promotion_blocked_reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportedSkillRecord:
    source_id: str
    source_revision: str
    source_skill_path: str
    source_format: str
    source_name: str
    normalized_id: str
    normalized_name: str
    description: str
    content: str
    version: str
    references: tuple[ImportedReference, ...] = ()
    default_reference_bundle: tuple[str, ...] = ()
    context_contracts: tuple[ContextContract, ...] = ()
    tool_candidates: tuple[ToolCandidate, ...] = ()
    inference_log: tuple[str, ...] = ()

    @property
    def skill_key(self) -> str:
        return self.normalized_id

    @property
    def canonical_id(self) -> str:
        return canonical_skill_id(self.source_id, self.skill_key)

    @property
    def canonical_version_ref(self) -> str:
        return canonical_version_ref(
            self.source_id,
            self.skill_key,
            self.source_revision,
        )


@dataclass(frozen=True)
class ImportSnapshot:
    snapshot_id: str
    source_id: str
    revision: str
    source_format: str
    adapter_profile: str
    created_at: str
    manifest_path: str
    report_path: str
    promoted_path: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportSession:
    session_id: str
    source_id: str
    source_payload: dict[str, Any]
    checkout_dir: Path
    staging_dir: Path
