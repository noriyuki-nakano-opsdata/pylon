"""Compile planning artifacts into downstream-enforceable value contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VALUE_CONTRACT_ID = "value-contract"
OUTCOME_TELEMETRY_CONTRACT_ID = "outcome-telemetry-contract"
REQUIRED_DELIVERY_CONTRACT_IDS: tuple[str, ...] = (
    "design-system-contract",
    "access-control-contract",
    "operability-contract",
    "development-standards",
    VALUE_CONTRACT_ID,
    OUTCOME_TELEMETRY_CONTRACT_ID,
)
VALUE_CONTRACT_WORKSPACE_ARTIFACTS: tuple[str, ...] = (
    "app/lib/value-contract.ts",
    "docs/spec/value-contract.md",
)
OUTCOME_TELEMETRY_WORKSPACE_ARTIFACTS: tuple[str, ...] = (
    "server/contracts/outcome-telemetry.ts",
    "docs/spec/outcome-telemetry.md",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _ns(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _slug(value: Any, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in _ns(value)).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:48] or prefix


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        text = _ns(item)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _decision_context_fingerprint(project_record: dict[str, Any]) -> str:
    decision_context = _as_dict(project_record.get("decision_context") or project_record.get("decisionContext"))
    return _ns(decision_context.get("fingerprint"))


def _selected_features(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [_as_dict(item) for item in _as_list(project_record.get("features")) if _as_dict(item)]
    selected = [item for item in rows if item.get("selected") is True]
    return selected or rows


def _selected_feature_name(item: dict[str, Any]) -> str:
    return _ns(item.get("name") or item.get("feature"))


def _metric_row(
    metric_id: str,
    *,
    name: str,
    signal: str,
    target: str,
    source: str,
    leading_indicator: str = "",
) -> dict[str, Any]:
    return {
        "id": metric_id,
        "name": _ns(name),
        "signal": _ns(signal),
        "target": _ns(target),
        "source": _ns(source),
        "leading_indicator": _ns(leading_indicator),
    }


def _kill_criterion_text(item: Any) -> str:
    record = _as_dict(item)
    if record:
        parts = [
            _ns(record.get("milestone_name") or record.get("milestoneName")),
            _ns(record.get("failure_mode") or record.get("failureMode")),
            _ns(record.get("condition")),
            _ns(record.get("trigger")),
        ]
        return " | ".join(part for part in parts if part)
    return _ns(item)


def build_value_contract(project_record: dict[str, Any]) -> dict[str, Any]:
    analysis = _as_dict(project_record.get("analysis"))
    if not analysis:
        return {}

    selected_features = _selected_features(project_record)
    feature_lookup = {
        _slug(_selected_feature_name(item), prefix=f"feature-{index + 1}"): item
        for index, item in enumerate(selected_features)
        if _selected_feature_name(item)
    }
    personas = [_as_dict(item) for item in _as_list(analysis.get("personas")) if _as_dict(item)]
    use_cases = [_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)]
    traceability = [_as_dict(item) for item in _as_list(analysis.get("traceability")) if _as_dict(item)]
    job_stories = [_as_dict(item) for item in _as_list(analysis.get("job_stories")) if _as_dict(item)]
    journeys = [_as_dict(item) for item in _as_list(analysis.get("user_journeys")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(project_record.get("milestones")) if _as_dict(item)]
    ia_analysis = _as_dict(analysis.get("ia_analysis"))
    kano_rows = [_as_dict(item) for item in _as_list(analysis.get("kano_features")) if _as_dict(item)]

    traceability_by_use_case: dict[str, list[dict[str, Any]]] = {}
    for row in traceability:
        use_case_id = _ns(row.get("use_case_id"))
        if not use_case_id:
            continue
        traceability_by_use_case.setdefault(use_case_id, []).append(row)

    required_use_cases: list[dict[str, Any]] = []
    for index, use_case in enumerate(use_cases[:8]):
        use_case_id = _ns(use_case.get("id")) or f"uc-{index + 1}"
        links = traceability_by_use_case.get(use_case_id, [])
        feature_names = _dedupe_strings(
            [
                _ns(link.get("feature_name"))
                for link in links
                if _ns(link.get("feature_name"))
            ]
            + [
                _selected_feature_name(feature)
                for feature in selected_features
                if _selected_feature_name(feature) and _selected_feature_name(feature) in _ns(use_case.get("title"))
            ]
        )
        milestone_names = _dedupe_strings(
            [
                _ns(link.get("milestone_name"))
                for link in links
                if _ns(link.get("milestone_name"))
            ]
        )
        required_use_cases.append(
            {
                "id": use_case_id,
                "title": _ns(use_case.get("title")) or f"Use case {index + 1}",
                "priority": _ns(use_case.get("priority")) or "should",
                "actor": _ns(use_case.get("actor")),
                "summary": _ns(use_case.get("summary")),
                "feature_names": feature_names,
                "milestone_names": milestone_names,
            }
        )

    compiled_job_stories: list[dict[str, Any]] = []
    for index, story in enumerate(job_stories[:8]):
        title = _ns(story.get("title")) or (
            f"When {_ns(story.get('situation'))}, I want to {_ns(story.get('motivation'))}"
        )
        compiled_job_stories.append(
            {
                "id": _slug(title, prefix=f"job-{index + 1}"),
                "title": title,
                "situation": _ns(story.get("situation")),
                "motivation": _ns(story.get("motivation")),
                "outcome": _ns(story.get("outcome")),
                "priority": _ns(story.get("priority")) or "supporting",
                "related_features": _dedupe_strings(_as_list(story.get("related_features"))),
            }
        )

    compiled_journeys: list[dict[str, Any]] = []
    for index, journey in enumerate(journeys[:5]):
        touchpoints = [_as_dict(item) for item in _as_list(journey.get("touchpoints")) if _as_dict(item)]
        critical_touchpoints = [
            {
                "phase": _ns(point.get("phase")) or "usage",
                "action": _ns(point.get("action")),
                "touchpoint": _ns(point.get("touchpoint")),
                "emotion": _ns(point.get("emotion")) or "neutral",
                "pain_point": _ns(point.get("pain_point")),
                "opportunity": _ns(point.get("opportunity")),
            }
            for point in touchpoints[:8]
        ]
        failure_moments = _dedupe_strings(
            [
                _ns(point.get("pain_point"))
                for point in touchpoints
                if _ns(point.get("pain_point"))
            ]
        )
        compiled_journeys.append(
            {
                "id": _slug(journey.get("persona_name") or f"journey-{index + 1}", prefix=f"journey-{index + 1}"),
                "persona_name": _ns(journey.get("persona_name")) or f"Persona {index + 1}",
                "critical_touchpoints": critical_touchpoints,
                "failure_moments": failure_moments[:5],
            }
        )

    site_map = [_as_dict(item) for item in _as_list(ia_analysis.get("site_map")) if _as_dict(item)]
    top_level_nodes = [
        {
            "id": _ns(item.get("id")) or f"node-{index + 1}",
            "label": _ns(item.get("label")) or f"Node {index + 1}",
            "priority": _ns(item.get("priority")) or "secondary",
            "description": _ns(item.get("description")),
        }
        for index, item in enumerate(site_map[:6])
    ]
    key_paths = [
        {
            "name": _ns(item.get("name")) or f"Path {index + 1}",
            "steps": _dedupe_strings(_as_list(item.get("steps"))),
        }
        for index, item in enumerate(_as_list(ia_analysis.get("key_paths"))[:6])
        if _as_dict(item)
    ]
    top_tasks = _dedupe_strings(
        [
            step
            for path in key_paths
            for step in _as_list(path.get("steps"))
            if _ns(step)
        ]
    )[:8]

    must_be = [
        _ns(item.get("feature"))
        for item in kano_rows
        if _ns(item.get("category")) == "must-be" and _ns(item.get("feature"))
    ]
    performance = [
        _ns(item.get("feature"))
        for item in kano_rows
        if _ns(item.get("category")) in {"one-dimensional", "performance"} and _ns(item.get("feature"))
    ]
    attractive = [
        _ns(item.get("feature"))
        for item in kano_rows
        if _ns(item.get("category")) == "attractive" and _ns(item.get("feature"))
    ]

    success_metrics: list[dict[str, Any]] = []
    for index, path in enumerate(key_paths[:3]):
        path_name = _ns(path.get("name")) or f"Key path {index + 1}"
        success_metrics.append(
            _metric_row(
                f"path-{_slug(path_name, prefix=f'path-{index + 1}')}",
                name=f"{path_name} completion rate",
                signal=f"Users complete the {path_name} path without dropping before the last step.",
                target="Improves versus prior iteration and remains explicitly observable.",
                source="journey_path_completion",
                leading_indicator="Path started vs completed events stay attributable per release.",
            )
        )
    for index, milestone in enumerate(milestones[:3]):
        milestone_name = _ns(milestone.get("name")) or f"Milestone {index + 1}"
        success_metrics.append(
            _metric_row(
                f"milestone-{_slug(milestone_name, prefix=f'ms-{index + 1}')}",
                name=f"{milestone_name} evidence signal",
                signal=_ns(milestone.get("criteria")) or f"Evidence exists that {milestone_name} is true in the shipped experience.",
                target="Release review can point to explicit evidence before promotion.",
                source="milestone_evidence",
            )
        )
    for index, feature in enumerate(selected_features[:3]):
        feature_name = _selected_feature_name(feature)
        if not feature_name:
            continue
        success_metrics.append(
            _metric_row(
                f"feature-{_slug(feature_name, prefix=f'feature-{index + 1}')}",
                name=f"{feature_name} adoption signal",
                signal=f"Operators or end users reach and use {feature_name} inside the key journey.",
                target="Feature usage is observable and explainable during iteration review.",
                source="feature_activation",
            )
        )
    success_metrics = success_metrics[:8]

    kill_criteria = _dedupe_strings(
        [_kill_criterion_text(item) for item in _as_list(analysis.get("kill_criteria")) if _kill_criterion_text(item)]
    )[:8]
    release_readiness_signals = _dedupe_strings(
        [
            "Primary persona, job story, and journey path stay traceable through development and deploy.",
            "Selected must-be capabilities remain present in the release candidate.",
            "Success metrics and kill criteria are observable before promotion.",
            "Navigation and IA key paths remain intact in the shipped experience.",
            *[
                _ns(item.get("criteria"))
                for item in milestones
                if _ns(item.get("criteria"))
            ],
        ]
    )[:8]

    primary_personas = [
        {
            "name": _ns(item.get("name")) or f"Persona {index + 1}",
            "role": _ns(item.get("role")),
            "context": _ns(item.get("context")),
            "goals": _dedupe_strings(_as_list(item.get("goals"))),
            "frustrations": _dedupe_strings(_as_list(item.get("frustrations"))),
        }
        for index, item in enumerate(personas[:4])
    ]
    selected_feature_payload = [
        {
            "id": feature_id,
            "name": _selected_feature_name(item),
            "priority": _ns(item.get("priority")) or "should",
            "category": _ns(item.get("category")) or "one-dimensional",
            "rationale": _ns(item.get("rationale")),
        }
        for feature_id, item in feature_lookup.items()
        if _selected_feature_name(item)
    ]

    summary_parts = [
        primary_personas[0]["name"] if primary_personas else "",
        compiled_job_stories[0]["title"] if compiled_job_stories else "",
        key_paths[0]["name"] if key_paths else "",
    ]
    return {
        "id": VALUE_CONTRACT_ID,
        "schema_version": 1,
        "summary": " | ".join(part for part in summary_parts if part)
        or "Planning analysis is compiled into a downstream value contract.",
        "primary_personas": primary_personas,
        "selected_features": selected_feature_payload,
        "required_use_cases": required_use_cases,
        "job_stories": compiled_job_stories,
        "user_journeys": compiled_journeys,
        "kano_focus": {
            "must_be": must_be,
            "performance": performance,
            "attractive": attractive,
        },
        "information_architecture": {
            "navigation_model": _ns(ia_analysis.get("navigation_model")) or "hierarchical",
            "top_level_nodes": top_level_nodes,
            "key_paths": key_paths,
            "top_tasks": top_tasks,
        },
        "success_metrics": success_metrics,
        "kill_criteria": kill_criteria,
        "release_readiness_signals": release_readiness_signals,
        "decision_context_fingerprint": _decision_context_fingerprint(project_record),
    }


def build_outcome_telemetry_contract(
    project_record: dict[str, Any],
    *,
    value_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compiled_value_contract = _as_dict(value_contract) or build_value_contract(project_record)
    if not compiled_value_contract:
        return {}

    key_paths = [_as_dict(item) for item in _as_list(_as_dict(compiled_value_contract.get("information_architecture")).get("key_paths")) if _as_dict(item)]
    selected_features = [_as_dict(item) for item in _as_list(compiled_value_contract.get("selected_features")) if _as_dict(item)]
    success_metrics = [_as_dict(item) for item in _as_list(compiled_value_contract.get("success_metrics")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(project_record.get("milestones")) if _as_dict(item)]

    telemetry_events: list[dict[str, Any]] = []
    for index, path in enumerate(key_paths[:4]):
        path_name = _ns(path.get("name")) or f"Path {index + 1}"
        path_slug = _slug(path_name, prefix=f"path-{index + 1}")
        related_metric_ids = [
            _ns(metric.get("id"))
            for metric in success_metrics
            if path_slug in _ns(metric.get("id"))
        ]
        telemetry_events.extend(
            [
                {
                    "id": f"{path_slug}-started",
                    "name": f"{path_slug}.started",
                    "purpose": f"Observe when users enter the {path_name} path.",
                    "properties": ["persona", "entrySurface", "releaseVersion"],
                    "success_metric_ids": related_metric_ids,
                },
                {
                    "id": f"{path_slug}-completed",
                    "name": f"{path_slug}.completed",
                    "purpose": f"Observe successful completion of the {path_name} path.",
                    "properties": ["persona", "exitSurface", "durationMs", "releaseVersion"],
                    "success_metric_ids": related_metric_ids,
                },
            ]
        )
    for index, feature in enumerate(selected_features[:6]):
        feature_name = _ns(feature.get("name"))
        if not feature_name:
            continue
        feature_slug = _slug(feature_name, prefix=f"feature-{index + 1}")
        telemetry_events.append(
            {
                "id": f"{feature_slug}-activated",
                "name": f"feature.{feature_slug}.activated",
                "purpose": f"Record usage of {feature_name} inside the user journey.",
                "properties": ["actor", "surface", "releaseVersion"],
                "success_metric_ids": [
                    _ns(metric.get("id"))
                    for metric in success_metrics
                    if feature_slug in _ns(metric.get("id"))
                ],
            }
        )
    for index, milestone in enumerate(milestones[:4]):
        milestone_name = _ns(milestone.get("name")) or f"Milestone {index + 1}"
        milestone_slug = _slug(milestone_name, prefix=f"ms-{index + 1}")
        telemetry_events.append(
            {
                "id": f"{milestone_slug}-evidence",
                "name": f"milestone.{milestone_slug}.evidence_recorded",
                "purpose": f"Attach explicit evidence that {milestone_name} is being met.",
                "properties": ["evidenceType", "owner", "releaseVersion"],
                "success_metric_ids": [
                    _ns(metric.get("id"))
                    for metric in success_metrics
                    if milestone_slug in _ns(metric.get("id"))
                ],
            }
        )
    telemetry_events = telemetry_events[:16]

    experiment_questions = _dedupe_strings(
        [
            _ns(item.get("reason") or item.get("title"))
            for item in _as_list(_as_dict(project_record.get("analysis")).get("assumptions"))
            if _as_dict(item)
        ]
        + [
            _ns(item)
            for item in _as_list(_as_dict(project_record.get("research")).get("open_questions"))
            if _ns(item)
        ]
    )[:6]

    release_checks = [
        {
            "id": VALUE_CONTRACT_ID,
            "title": "Value contract is attached to the release candidate",
            "detail": "Persona, JTBD, key path, and success metrics are visible at release time.",
        },
        {
            "id": OUTCOME_TELEMETRY_CONTRACT_ID,
            "title": "Outcome telemetry contract is attached to the release candidate",
            "detail": "Success metrics, kill criteria, and telemetry events remain explicit before promotion.",
        },
        {
            "id": "instrumentation-coverage",
            "title": "Instrumentation covers selected paths, features, and milestone evidence",
            "detail": "The release candidate can be observed along the primary journey and value hypotheses.",
        },
    ]

    return {
        "id": OUTCOME_TELEMETRY_CONTRACT_ID,
        "schema_version": 1,
        "summary": "Outcome telemetry is compiled from the planning value contract and carried into deploy/iterate.",
        "success_metrics": success_metrics,
        "kill_criteria": [
            _ns(item)
            for item in _as_list(compiled_value_contract.get("kill_criteria"))
            if _ns(item)
        ],
        "telemetry_events": telemetry_events,
        "workspace_artifacts": [
            *VALUE_CONTRACT_WORKSPACE_ARTIFACTS,
            *OUTCOME_TELEMETRY_WORKSPACE_ARTIFACTS,
        ],
        "release_checks": release_checks,
        "instrumentation_requirements": [
            "Primary key paths must emit started and completed signals.",
            "Selected features must emit activation signals with release provenance.",
            "Milestone evidence must be recordable before release promotion.",
            "Kill criteria must map to at least one observable signal or explicit operator review step.",
        ],
        "experiment_questions": experiment_questions,
        "decision_context_fingerprint": _decision_context_fingerprint(project_record),
    }


def value_contract_ready(contract: dict[str, Any] | None) -> bool:
    payload = _as_dict(contract)
    return bool(
        _as_list(payload.get("primary_personas"))
        and _as_list(payload.get("selected_features"))
        and _as_list(payload.get("success_metrics"))
        and _as_list(_as_dict(payload.get("information_architecture")).get("key_paths"))
    )


def outcome_telemetry_contract_ready(contract: dict[str, Any] | None) -> bool:
    payload = _as_dict(contract)
    return bool(
        _as_list(payload.get("success_metrics"))
        and _as_list(payload.get("telemetry_events"))
        and _as_list(payload.get("workspace_artifacts"))
        and _as_list(payload.get("release_checks"))
    )
