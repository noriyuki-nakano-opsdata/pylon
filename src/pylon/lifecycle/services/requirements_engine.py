"""EARS (Easy Approach to Requirements Syntax) requirements extraction and quality evaluation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EARSRequirement:
    id: str
    pattern: str
    statement: str
    confidence: float
    source_claim_ids: tuple[str, ...] = ()
    user_story_ids: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementsBundle:
    requirements: tuple[EARSRequirement, ...] = ()
    user_stories: tuple[dict[str, Any], ...] = ()
    acceptance_criteria: tuple[dict[str, Any], ...] = ()
    confidence_distribution: dict[str, int] = field(default_factory=dict)
    completeness_score: float = 0.0
    traceability_index: dict[str, tuple[str, ...]] = field(default_factory=dict)


EARS_PATTERNS = ("ubiquitous", "event-driven", "unwanted", "state-driven", "optional", "complex")

_VALID_REQUIREMENT_ID_RE = re.compile(r"^REQ-\d{4}$")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def classify_ears_pattern(statement: str) -> str:
    """Classify an EARS statement into its pattern type based on keywords."""
    upper = statement.upper().strip()
    has_when = bool(re.search(r"\bWHEN\b", upper))
    has_if_then = bool(re.search(r"\bIF\b.*\bTHEN\b", upper))
    has_while = bool(re.search(r"\bWHILE\b", upper))
    has_where = bool(re.search(r"\bWHERE\b", upper))
    has_shall = bool(re.search(r"\bSHALL\b", upper))
    if not has_shall:
        return "ubiquitous"
    keyword_count = sum([has_when, has_if_then, has_while, has_where])
    if keyword_count >= 2:
        return "complex"
    if has_if_then:
        return "unwanted"
    if has_when:
        return "event-driven"
    if has_while:
        return "state-driven"
    if has_where:
        return "optional"
    return "ubiquitous"


def confidence_to_level(confidence: float) -> str:
    """Map confidence float to human-readable level."""
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _build_user_story(
    claim: dict[str, Any],
    user_research: dict[str, Any] | None,
    req_id: str,
) -> dict[str, Any]:
    segment = _normalize_space(
        _as_dict(user_research).get("segment") if user_research else None
    ) or "a user"
    statement = _normalize_space(claim.get("statement") or claim.get("claim_statement") or "")
    pain_points = _as_list(_as_dict(user_research).get("pain_points")) if user_research else []
    motivation = _normalize_space(pain_points[0]) if pain_points else "achieve my goal"
    return {
        "id": f"US-{req_id.removeprefix('REQ-')}",
        "requirement_id": req_id,
        "persona": segment,
        "action": statement,
        "motivation": motivation,
        "text": f"As {segment}, I want to {statement.lower()} so that I can {motivation.lower()}.",
    }


def _build_acceptance_criteria(
    claim: dict[str, Any],
    req_id: str,
) -> dict[str, Any]:
    statement = _normalize_space(claim.get("statement") or claim.get("claim_statement") or "")
    condition = _normalize_space(claim.get("condition") or "the feature is active")
    return {
        "id": f"AC-{req_id.removeprefix('REQ-')}",
        "requirement_id": req_id,
        "given": f"Given {condition}",
        "when": f"When the system processes the request",
        "then": f"Then {statement.lower()}" if statement else "Then the expected outcome is achieved",
        "text": f"Given {condition}, when the system processes the request, then {statement.lower()}." if statement else f"Given {condition}, when the system processes the request, then the expected outcome is achieved.",
    }


def _compute_confidence_distribution(requirements: list[dict[str, Any]]) -> dict[str, int]:
    distribution: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for req in requirements:
        level = confidence_to_level(float(req.get("confidence", 0.0) or 0.0))
        distribution[level] = distribution.get(level, 0) + 1
    return distribution


def _compute_completeness_score(
    requirements: list[dict[str, Any]],
    user_stories: list[dict[str, Any]],
    acceptance_criteria: list[dict[str, Any]],
    confidence_distribution: dict[str, int],
) -> float:
    if not requirements:
        return 0.0
    total = len(requirements)
    has_stories = sum(1 for r in requirements if any(
        s.get("requirement_id") == r.get("id") for s in user_stories
    ))
    has_criteria = sum(1 for r in requirements if any(
        c.get("requirement_id") == r.get("id") for c in acceptance_criteria
    ))
    has_traceability = sum(1 for r in requirements if _as_list(r.get("source_claim_ids")))
    story_ratio = has_stories / total
    criteria_ratio = has_criteria / total
    traceability_ratio = has_traceability / total
    high_count = confidence_distribution.get("high", 0)
    confidence_ratio = high_count / total if total > 0 else 0.0
    score = (story_ratio * 0.25) + (criteria_ratio * 0.25) + (traceability_ratio * 0.3) + (confidence_ratio * 0.2)
    return round(min(1.0, max(0.0, score)), 2)


def _build_traceability_index(requirements: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = {}
    for req in requirements:
        req_id = str(req.get("id", ""))
        for claim_id in _as_list(req.get("source_claim_ids")):
            cid = str(claim_id).strip()
            if cid:
                if cid not in index:
                    index[cid] = []
                if req_id not in index[cid]:
                    index[cid].append(req_id)
    return {k: tuple(v) for k, v in index.items()}


def build_requirements_bundle(
    claims: list[dict[str, Any]],
    user_research: dict[str, Any] | None,
    spec: str,
    *,
    existing_requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a RequirementsBundle dict from research claims and user research.

    Extracts accepted claims, assigns REQ-XXXX IDs sequentially, classifies EARS
    patterns, builds user stories and acceptance criteria, calculates confidence
    distribution and completeness score, and builds a traceability index.
    """
    accepted = [
        _as_dict(item)
        for item in _as_list(claims)
        if str(_as_dict(item).get("status", "")).strip() == "accepted"
    ]
    start_index = len(_as_list(existing_requirements)) + 1
    requirements: list[dict[str, Any]] = []
    user_stories: list[dict[str, Any]] = []
    acceptance_criteria_list: list[dict[str, Any]] = []

    for offset, claim in enumerate(accepted):
        req_id = f"REQ-{start_index + offset:04d}"
        statement = _normalize_space(claim.get("statement") or claim.get("claim_statement") or spec)
        confidence = float(claim.get("confidence", 0.5) or 0.5)
        claim_id = str(claim.get("id", "")).strip()
        pattern = classify_ears_pattern(statement)
        req = {
            "id": req_id,
            "pattern": pattern,
            "statement": statement,
            "confidence": round(confidence, 2),
            "source_claim_ids": [claim_id] if claim_id else [],
            "user_story_ids": [f"US-{req_id.removeprefix('REQ-')}"],
            "acceptance_criteria": [f"AC-{req_id.removeprefix('REQ-')}"],
        }
        requirements.append(req)
        user_stories.append(_build_user_story(claim, user_research, req_id))
        acceptance_criteria_list.append(_build_acceptance_criteria(claim, req_id))

    confidence_distribution = _compute_confidence_distribution(requirements)
    completeness_score = _compute_completeness_score(
        requirements,
        user_stories,
        acceptance_criteria_list,
        confidence_distribution,
    )
    traceability_index = _build_traceability_index(requirements)

    return {
        "requirements": requirements,
        "user_stories": user_stories,
        "acceptance_criteria": acceptance_criteria_list,
        "confidence_distribution": confidence_distribution,
        "completeness_score": completeness_score,
        "traceability_index": {k: list(v) for k, v in traceability_index.items()},
    }


def evaluate_requirements_quality(
    bundle: dict[str, Any],
    *,
    spec: str = "",
) -> tuple[list[dict[str, Any]], float]:
    """Evaluate quality of a requirements bundle.

    Returns a tuple of (quality_issues, completeness_score). Checks requirement IDs,
    traceability, confidence distribution, acceptance criteria, and duplicates.
    """
    issues: list[dict[str, Any]] = []
    requirements = _as_list(bundle.get("requirements"))
    acceptance_criteria = _as_list(bundle.get("acceptance_criteria"))
    confidence_distribution = _as_dict(bundle.get("confidence_distribution"))

    seen_ids: set[str] = set()
    for req in requirements:
        req_data = _as_dict(req)
        req_id = str(req_data.get("id", "")).strip()

        if not _VALID_REQUIREMENT_ID_RE.match(req_id):
            issues.append({
                "id": req_id or "unknown",
                "severity": "error",
                "message": f"Invalid requirement ID format: '{req_id}'. Expected REQ-XXXX.",
            })

        if req_id in seen_ids:
            issues.append({
                "id": req_id,
                "severity": "error",
                "message": f"Duplicate requirement ID: {req_id}.",
            })
        if req_id:
            seen_ids.add(req_id)

        source_claim_ids = _as_list(req_data.get("source_claim_ids"))
        if not source_claim_ids:
            issues.append({
                "id": req_id or "unknown",
                "severity": "warning",
                "message": f"Requirement {req_id} has no source_claim_ids (traceability gap).",
            })

        has_ac = any(
            str(_as_dict(ac).get("requirement_id", "")).strip() == req_id
            for ac in acceptance_criteria
        )
        if not has_ac:
            issues.append({
                "id": req_id or "unknown",
                "severity": "warning",
                "message": f"Requirement {req_id} has no acceptance criteria.",
            })

    total = len(requirements)
    high_count = int(confidence_distribution.get("high", 0) or 0)
    if total > 0 and (high_count / total) < 0.5:
        issues.append({
            "id": "confidence-ratio",
            "severity": "warning",
            "message": f"High-confidence requirements are below 50% ({high_count}/{total}).",
        })

    completeness_score = float(bundle.get("completeness_score", 0.0) or 0.0)
    return issues, completeness_score


def _normalize_for_comparison(text: str) -> str:
    return " ".join(text.lower().strip().split())


def merge_requirements_with_reverse_engineering(
    forward_bundle: dict[str, Any],
    reverse_requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge forward-generated requirements with reverse-engineered ones.

    Deduplicates by statement similarity (normalized lowercase comparison).
    Reverse-engineered items get a confidence boost if they match forward items.
    """
    merged = dict(forward_bundle)
    existing_reqs = list(_as_list(merged.get("requirements")))
    existing_stories = list(_as_list(merged.get("user_stories")))
    existing_criteria = list(_as_list(merged.get("acceptance_criteria")))

    existing_statements: set[str] = {
        _normalize_for_comparison(str(_as_dict(r).get("statement", "")))
        for r in existing_reqs
    }
    next_index = len(existing_reqs) + 1

    for reverse_req in _as_list(reverse_requirements):
        rev = _as_dict(reverse_req)
        rev_statement = _normalize_for_comparison(str(rev.get("statement", "")))
        if not rev_statement:
            continue

        if rev_statement in existing_statements:
            for idx, existing in enumerate(existing_reqs):
                ex = _as_dict(existing)
                if _normalize_for_comparison(str(ex.get("statement", ""))) == rev_statement:
                    current_confidence = float(ex.get("confidence", 0.5) or 0.5)
                    boosted = round(min(1.0, current_confidence + 0.1), 2)
                    if isinstance(existing, dict):
                        existing["confidence"] = boosted
                    else:
                        patched = dict(ex)
                        patched["confidence"] = boosted
                        existing_reqs[idx] = patched
                    break
            continue

        req_id = f"REQ-{next_index:04d}"
        next_index += 1
        statement = _normalize_space(rev.get("statement") or "")
        confidence = round(float(rev.get("confidence", 0.5) or 0.5), 2)
        pattern = classify_ears_pattern(statement)
        claim_id = str(rev.get("source_claim_id") or rev.get("id") or "").strip()

        new_req = {
            "id": req_id,
            "pattern": pattern,
            "statement": statement,
            "confidence": confidence,
            "source_claim_ids": [claim_id] if claim_id else [],
            "user_story_ids": [f"US-{req_id.removeprefix('REQ-')}"],
            "acceptance_criteria": [f"AC-{req_id.removeprefix('REQ-')}"],
        }
        existing_reqs.append(new_req)
        existing_statements.add(rev_statement)

        existing_stories.append({
            "id": f"US-{req_id.removeprefix('REQ-')}",
            "requirement_id": req_id,
            "persona": "a user",
            "action": statement,
            "motivation": "achieve my goal",
            "text": f"As a user, I want to {statement.lower()} so that I can achieve my goal.",
        })
        existing_criteria.append({
            "id": f"AC-{req_id.removeprefix('REQ-')}",
            "requirement_id": req_id,
            "given": "Given the feature is active",
            "when": "When the system processes the request",
            "then": f"Then {statement.lower()}" if statement else "Then the expected outcome is achieved",
            "text": f"Given the feature is active, when the system processes the request, then {statement.lower()}." if statement else "Given the feature is active, when the system processes the request, then the expected outcome is achieved.",
        })

    confidence_distribution = _compute_confidence_distribution(existing_reqs)
    completeness_score = _compute_completeness_score(
        existing_reqs,
        existing_stories,
        existing_criteria,
        confidence_distribution,
    )
    traceability_index = _build_traceability_index(existing_reqs)

    merged["requirements"] = existing_reqs
    merged["user_stories"] = existing_stories
    merged["acceptance_criteria"] = existing_criteria
    merged["confidence_distribution"] = confidence_distribution
    merged["completeness_score"] = completeness_score
    merged["traceability_index"] = {k: list(v) for k, v in traceability_index.items()}
    return merged
