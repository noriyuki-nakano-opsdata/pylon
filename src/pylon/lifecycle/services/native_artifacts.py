"""Canonical lifecycle artifact integration for native Tsumiki services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pylon.lifecycle.services.dcs_analysis import (
    analyze_edge_cases,
    analyze_impact,
    analyze_state_transitions,
    evaluate_dcs_quality,
    generate_rubber_duck_prd,
    generate_sequence_diagrams,
)
from pylon.lifecycle.services.dcs_localization import localize_dcs_analysis
from pylon.lifecycle.services.requirements_engine import (
    build_requirements_bundle,
    merge_requirements_with_reverse_engineering,
)
from pylon.lifecycle.services.requirements_localization import (
    localize_requirements_bundle,
)
from pylon.lifecycle.services.reverse_engineering import (
    build_reverse_engineering_result,
    evaluate_reverse_engineering_quality,
)
from pylon.lifecycle.services.reverse_engineering_localization import (
    localize_reverse_engineering_result,
)
from pylon.lifecycle.services.task_decomposition import (
    decompose_features_to_tasks,
)
from pylon.lifecycle.services.technical_design import (
    build_technical_design_bundle,
    evaluate_technical_design_quality,
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


def _bool(value: Any, fallback: bool = False) -> bool:
    return value if isinstance(value, bool) else fallback


def _float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _selected_design_variant(project_record: dict[str, Any]) -> dict[str, Any]:
    selected_id = _ns(project_record.get("selectedDesignId"))
    variants = [_as_dict(item) for item in _as_list(project_record.get("designVariants")) if _as_dict(item)]
    if selected_id:
        for variant in variants:
            if _ns(variant.get("id")) == selected_id:
                return variant
    return variants[0] if variants else {}


def _selected_features(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    feature_rows = [_as_dict(item) for item in _as_list(project_record.get("features")) if _as_dict(item)]
    selected = [item for item in feature_rows if item.get("selected", True) is True]
    source = selected or feature_rows
    milestones = [_as_dict(item) for item in _as_list(project_record.get("milestones")) if _as_dict(item)]
    milestone_ids = [_ns(item.get("id") or item.get("name")) for item in milestones if _ns(item.get("id") or item.get("name"))]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(source, start=1):
        feature_name = _ns(item.get("name") or item.get("feature") or item.get("title") or f"Feature {index}")
        if not feature_name:
            continue
        milestone_id = _ns(item.get("milestone_id") or item.get("milestoneId"))
        if not milestone_id and milestone_ids:
            milestone_id = milestone_ids[min(index - 1, len(milestone_ids) - 1)]
        implementation_cost = _ns(item.get("implementation_cost") or item.get("implementationCost") or "medium").lower()
        effort_hours = {
            "low": 8.0,
            "medium": 16.0,
            "high": 24.0,
        }.get(implementation_cost, 16.0)
        normalized.append(
            {
                "id": _ns(item.get("id")) or f"feature-{index}",
                "name": feature_name,
                "title": feature_name,
                "feature": feature_name,
                "description": _ns(item.get("description") or item.get("rationale") or feature_name),
                "summary": _ns(item.get("summary") or item.get("rationale") or ""),
                "priority": _ns(item.get("priority") or "should").lower() or "should",
                "depends_on": [
                    _ns(dep)
                    for dep in _as_list(item.get("depends_on") or item.get("dependsOn"))
                    if _ns(dep)
                ],
                "milestone_id": milestone_id or None,
                "effort_hours": effort_hours,
                "acceptance_criteria": [
                    text
                    for text in (
                        _ns(criterion)
                        for criterion in _as_list(item.get("acceptance_criteria") or item.get("acceptanceCriteria"))
                    )
                    if text
                ]
                or [f"{feature_name} が主要導線で成立すること"],
                "fields": [
                    _as_dict(field)
                    for field in _as_list(item.get("fields") or item.get("properties"))
                    if _as_dict(field)
                ],
            }
        )
    return normalized


def _text_matches_feature(text: Any, feature: Any) -> bool:
    lhs = _ns(text).lower()
    rhs = _ns(feature).lower()
    if not lhs or not rhs:
        return False
    if rhs in lhs:
        return True
    feature_tokens = [token for token in rhs.replace("/", " ").replace("-", " ").split() if len(token) >= 3]
    if not feature_tokens:
        return False
    return sum(1 for token in feature_tokens if token in lhs) >= max(1, min(2, len(feature_tokens)))


def _slug(value: Any, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:48] or prefix


def _synthetic_requirement_claims(
    features: list[dict[str, Any]],
    *,
    accepted_claims: list[dict[str, Any]],
    spec: str,
) -> list[dict[str, Any]]:
    synthesized: list[dict[str, Any]] = []
    existing_text = [
        " ".join(
            part
            for part in (
                _ns(claim.get("statement") or claim.get("claim_statement")),
                _ns(claim.get("condition")),
            )
            if part
        )
        for claim in accepted_claims
    ]
    for index, feature in enumerate(features, start=1):
        feature_name = _ns(feature.get("name") or feature.get("feature") or feature.get("title"))
        if not feature_name:
            continue
        if any(_text_matches_feature(text, feature_name) for text in existing_text):
            continue
        description = _ns(feature.get("description") or feature.get("summary") or feature_name)
        acceptance_criteria = [
            _ns(item)
            for item in _as_list(feature.get("acceptance_criteria") or feature.get("acceptanceCriteria"))
            if _ns(item)
        ]
        lead_acceptance = acceptance_criteria[0] if acceptance_criteria else ""
        statement = (
            f"The system SHALL support {feature_name} and satisfy {lead_acceptance}."
            if lead_acceptance
            else f"The system SHALL support {feature_name} as part of {spec or 'the product specification'}."
        )
        synthesized.append(
            {
                "id": f"synthetic-{_slug(feature.get('id') or feature_name or index, prefix='claim')}",
                "statement": statement,
                "claim_statement": statement,
                "condition": f"the operator uses the {feature_name} workflow",
                "status": "accepted",
                "confidence": 0.72,
                "source": "selected_feature",
                "feature_id": _ns(feature.get("id")),
                "feature_name": feature_name,
                "acceptance_criteria": acceptance_criteria,
                "rationale": description,
            }
        )
        existing_text.append(statement)
    return synthesized


def _requirements_config(project_record: dict[str, Any]) -> dict[str, Any]:
    raw = _as_dict(project_record.get("requirementsConfig"))
    return {
        "earsEnabled": raw.get("earsEnabled", True) is not False,
        "interactiveClarification": raw.get("interactiveClarification", True) is not False,
        "confidenceFloor": round(_float(raw.get("confidenceFloor"), 0.6), 2),
    }


def _collect_snippet_inputs(project_record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str | None]:
    code_snippets: list[dict[str, Any]] = []
    test_snippets: list[dict[str, Any]] = []
    file_paths: list[str] = []

    def _push_snippet(target: list[dict[str, Any]], item: Any) -> None:
        record = _as_dict(item)
        path = _ns(record.get("file_path") or record.get("filePath") or record.get("path"))
        content = str(record.get("content") or "")
        language = _ns(record.get("language") or record.get("lang"))
        if not content.strip():
            return
        target.append(
            {
                "content": content,
                "file_path": path,
                "language": language,
            }
        )
        if path:
            file_paths.append(path)

    def _pull_from(container: dict[str, Any]) -> bool:
        found = False
        for item in _as_list(container.get("codeSnippets") or container.get("code_snippets")):
            _push_snippet(code_snippets, item)
            found = True
        for item in _as_list(container.get("testSnippets") or container.get("test_snippets")):
            _push_snippet(test_snippets, item)
            found = True
        for path in _as_list(container.get("filePaths") or container.get("file_paths")):
            normalized = _ns(path)
            if normalized:
                file_paths.append(normalized)
                found = True
        return found

    for candidate in (
        project_record,
        _as_dict(project_record.get("research")),
        _as_dict(project_record.get("analysis")),
        _as_dict(project_record.get("reverseEngineeringSource")),
    ):
        if _pull_from(candidate):
            return code_snippets, test_snippets, list(dict.fromkeys(file_paths)), "codebase"

    selected_design = _selected_design_variant(project_record)
    prototype_app = _as_dict(selected_design.get("prototype_app") or selected_design.get("prototypeApp"))
    for item in _as_list(prototype_app.get("files")):
        record = _as_dict(item)
        path = _ns(record.get("path"))
        content = str(record.get("content") or "")
        if not path or not content.strip():
            continue
        language = _ns(record.get("kind"))
        snippet = {"content": content, "file_path": path, "language": language}
        if any(marker in path.lower() for marker in ("test", ".spec.", ".test.")):
            test_snippets.append(snippet)
        else:
            code_snippets.append(snippet)
        file_paths.append(path)
    if code_snippets or test_snippets:
        return code_snippets, test_snippets, list(dict.fromkeys(file_paths)), "prototype_app"

    build_code = str(project_record.get("buildCode") or "")
    if build_code.strip():
        return (
            [{"content": build_code, "file_path": "generated/build.tsx", "language": "typescript"}],
            [],
            ["generated/build.tsx"],
            "build_code",
        )
    return [], [], [], None


def normalize_reverse_engineering_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _as_dict(result)
    if not source:
        return None
    endpoints = []
    for item in _as_list(source.get("api_endpoints") or source.get("apiEndpoints")):
        record = _as_dict(item)
        endpoints.append(
            {
                "method": _ns(record.get("method") or "GET"),
                "path": _ns(record.get("path") or "/"),
                "handler": _ns(record.get("handler")),
                "filePath": _ns(record.get("file_path") or record.get("filePath")),
            }
        )
    interfaces = []
    for item in _as_list(source.get("interfaces")):
        record = _as_dict(item)
        interfaces.append(
            {
                "name": _ns(record.get("name")),
                "kind": _ns(record.get("kind") or "interface"),
                "properties": [_as_dict(prop) for prop in _as_list(record.get("properties")) if _as_dict(prop)],
                "filePath": _ns(record.get("file_path") or record.get("filePath")),
            }
        )
    database_schema = []
    for item in _as_list(source.get("database_schema") or source.get("databaseSchema")):
        record = _as_dict(item)
        database_schema.append(
            {
                "name": _ns(record.get("name")),
                "columns": [_as_dict(column) for column in _as_list(record.get("columns")) if _as_dict(column)],
                "source": _ns(record.get("source")),
            }
        )
    extracted_requirements = []
    for item in _as_list(source.get("extracted_requirements") or source.get("extractedRequirements")):
        record = _as_dict(item)
        extracted_requirements.append(
            {
                "id": _ns(record.get("id")),
                "pattern": _ns(record.get("pattern")),
                "statement": _ns(record.get("statement")),
                "confidence": round(_float(record.get("confidence"), 0.0), 2),
                "sourceFile": _ns(record.get("source_file") or record.get("sourceFile")),
                "sourceType": _ns(record.get("source_type") or record.get("sourceType")),
            }
        )
    return {
        "extractedRequirements": extracted_requirements,
        "architectureDoc": _as_dict(source.get("architecture_doc") or source.get("architectureDoc")),
        "dataflowMermaid": _ns(source.get("dataflow_mermaid") or source.get("dataflowMermaid")),
        "apiEndpoints": endpoints,
        "databaseSchema": database_schema,
        "interfaces": interfaces,
        "taskStructure": [_as_dict(item) for item in _as_list(source.get("task_structure") or source.get("taskStructure")) if _as_dict(item)],
        "testSpecs": [_as_dict(item) for item in _as_list(source.get("test_specs") or source.get("testSpecs")) if _as_dict(item)],
        "coverageScore": round(_float(source.get("coverage_score") or source.get("coverageScore"), 0.0), 2),
        "languagesDetected": [_ns(item) for item in _as_list(source.get("languages_detected") or source.get("languagesDetected")) if _ns(item)],
        "sourceType": _ns(source.get("source_type") or source.get("sourceType")) or "unknown",
        "qualityGates": [_as_dict(item) for item in _as_list(source.get("quality_gates") or source.get("qualityGates")) if _as_dict(item)],
    }


def normalize_requirements_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _as_dict(bundle)
    if not source:
        return None
    normalized_acceptance: list[dict[str, Any]] = []
    acceptance_by_requirement: dict[str, list[str]] = {}
    for item in _as_list(source.get("acceptance_criteria") or source.get("acceptanceCriteria")):
        record = _as_dict(item)
        requirement_id = _ns(record.get("requirement_id") or record.get("requirementId"))
        criterion = _ns(record.get("text") or record.get("criterion"))
        if not criterion:
            given = _ns(record.get("given"))
            when = _ns(record.get("when"))
            then = _ns(record.get("then"))
            criterion = ", ".join(part for part in (given, when, then) if part)
        normalized_acceptance.append(
            {
                "id": _ns(record.get("id")),
                "requirementId": requirement_id,
                "criterion": criterion,
            }
        )
        if requirement_id and criterion:
            acceptance_by_requirement.setdefault(requirement_id, []).append(criterion)

    normalized_requirements: list[dict[str, Any]] = []
    for item in _as_list(source.get("requirements")):
        record = _as_dict(item)
        requirement_id = _ns(record.get("id"))
        criteria = acceptance_by_requirement.get(requirement_id, [])
        if not criteria:
            criteria = [
                _ns(value)
                for value in _as_list(record.get("acceptanceCriteria") or record.get("acceptance_criteria"))
                if _ns(value)
            ]
        normalized_requirements.append(
            {
                "id": requirement_id,
                "pattern": _ns(record.get("pattern")) or "ubiquitous",
                "statement": _ns(record.get("statement")),
                "confidence": round(_float(record.get("confidence"), 0.0), 2),
                "sourceClaimIds": [_ns(value) for value in _as_list(record.get("source_claim_ids") or record.get("sourceClaimIds")) if _ns(value)],
                "userStoryIds": [_ns(value) for value in _as_list(record.get("user_story_ids") or record.get("userStoryIds")) if _ns(value)],
                "acceptanceCriteria": criteria,
            }
        )

    user_stories: list[dict[str, Any]] = []
    for item in _as_list(source.get("user_stories") or source.get("userStories")):
        record = _as_dict(item)
        description = _ns(record.get("text") or record.get("description"))
        title = _ns(record.get("title"))
        if not title:
            persona = _ns(record.get("persona")) or "ユーザー"
            action = _ns(record.get("action")) or _ns(record.get("requirement_id") or record.get("requirementId"))
            title = f"{persona}: {action}" if action else persona
        user_stories.append(
            {
                "id": _ns(record.get("id")),
                "title": title,
                "description": description or title,
            }
        )

    confidence_distribution = _as_dict(source.get("confidence_distribution") or source.get("confidenceDistribution"))
    traceability_index = _as_dict(source.get("traceability_index") or source.get("traceabilityIndex"))
    return {
        "requirements": normalized_requirements,
        "userStories": user_stories,
        "acceptanceCriteria": normalized_acceptance,
        "confidenceDistribution": {
            "high": int(_float(confidence_distribution.get("high"), 0)),
            "medium": int(_float(confidence_distribution.get("medium"), 0)),
            "low": int(_float(confidence_distribution.get("low"), 0)),
        },
        "completenessScore": round(_float(source.get("completeness_score") or source.get("completenessScore"), 0.0), 2),
        "traceabilityIndex": {
            _ns(key): [_ns(value) for value in _as_list(values) if _ns(value)]
            for key, values in traceability_index.items()
            if _ns(key)
        },
    }


def normalize_task_decomposition(decomposition: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _as_dict(decomposition)
    if not source:
        return None
    tasks = []
    for item in _as_list(source.get("tasks")):
        record = _as_dict(item)
        tasks.append(
            {
                "id": _ns(record.get("id")),
                "title": _ns(record.get("title")),
                "description": _ns(record.get("description")),
                "phase": _ns(record.get("phase")),
                "milestoneId": _ns(record.get("milestone_id") or record.get("milestoneId")) or None,
                "dependsOn": [_ns(dep) for dep in _as_list(record.get("depends_on") or record.get("dependsOn")) if _ns(dep)],
                "effortHours": round(_float(record.get("effort_hours") or record.get("effortHours"), 0.0), 1),
                "priority": _ns(record.get("priority") or "should") or "should",
                "featureId": _ns(record.get("feature_id") or record.get("featureId")) or None,
                "requirementId": _ns(record.get("requirement_id") or record.get("requirementId")) or None,
            }
        )
    phase_milestones = []
    for item in _as_list(source.get("phase_milestones") or source.get("phaseMilestones")):
        record = _as_dict(item)
        phase_milestones.append(
            {
                "phase": _ns(record.get("phase")),
                "milestoneIds": [_ns(mid) for mid in _as_list(record.get("milestone_ids") or record.get("milestoneIds")) if _ns(mid)],
                "taskCount": int(_float(record.get("task_count") or record.get("taskCount"), 0)),
                "totalHours": round(_float(record.get("total_hours") or record.get("totalHours"), 0.0), 1),
                "durationDays": int(_float(record.get("duration_days") or record.get("durationDays"), 0)),
            }
        )
    return {
        "tasks": tasks,
        "dagEdges": [
            [_ns(edge[0]), _ns(edge[1])]
            for edge in _as_list(source.get("dag_edges") or source.get("dagEdges"))
            if isinstance(edge, (list, tuple)) and len(edge) >= 2 and _ns(edge[0]) and _ns(edge[1])
        ],
        "phaseMilestones": phase_milestones,
        "totalEffortHours": round(_float(source.get("total_effort_hours") or source.get("totalEffortHours"), 0.0), 1),
        "criticalPath": [_ns(item) for item in _as_list(source.get("critical_path") or source.get("criticalPath")) if _ns(item)],
        "effortByPhase": {
            _ns(key): round(_float(value, 0.0), 1)
            for key, value in _as_dict(source.get("effort_by_phase") or source.get("effortByPhase")).items()
            if _ns(key)
        },
        "hasCycles": _bool(source.get("has_cycles"), _bool(source.get("hasCycles"))),
    }


def normalize_dcs_analysis(analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _as_dict(analysis)
    if not source:
        return None
    rubber_duck = _as_dict(source.get("rubber_duck_prd") or source.get("rubberDuckPrd"))
    edge_cases = _as_dict(source.get("edge_case_analysis") or source.get("edgeCases"))
    impact_analysis = _as_dict(source.get("impact_analysis") or source.get("impactAnalysis"))
    sequence_diagrams = _as_dict(source.get("sequence_diagrams") or source.get("sequenceDiagrams"))
    state_transitions = _as_dict(source.get("state_transitions") or source.get("stateTransitions"))
    normalized = {
        "rubberDuckPrd": {
            "problemStatement": _ns(rubber_duck.get("problem_statement") or rubber_duck.get("problemStatement")),
            "targetUsers": [_ns(item) for item in _as_list(rubber_duck.get("target_users") or rubber_duck.get("targetUsers")) if _ns(item)],
            "successMetrics": [_as_dict(item) for item in _as_list(rubber_duck.get("success_metrics") or rubber_duck.get("successMetrics")) if _as_dict(item)],
            "scopeBoundaries": {
                "inScope": [_ns(item) for item in _as_list(_as_dict(rubber_duck.get("scope_boundaries") or rubber_duck.get("scopeBoundaries")).get("in_scope") or _as_dict(rubber_duck.get("scope_boundaries") or rubber_duck.get("scopeBoundaries")).get("inScope")) if _ns(item)],
                "outOfScope": [_ns(item) for item in _as_list(_as_dict(rubber_duck.get("scope_boundaries") or rubber_duck.get("scopeBoundaries")).get("out_of_scope") or _as_dict(rubber_duck.get("scope_boundaries") or rubber_duck.get("scopeBoundaries")).get("outOfScope")) if _ns(item)],
            },
            "keyDecisions": [_as_dict(item) for item in _as_list(rubber_duck.get("key_decisions") or rubber_duck.get("keyDecisions")) if _as_dict(item)],
        }
        if rubber_duck
        else None,
        "edgeCases": {
            "edgeCases": [
                {
                    "id": _ns(item.get("id")),
                    "scenario": _ns(item.get("scenario")),
                    "severity": _ns(item.get("severity")) or "low",
                    "mitigation": _ns(item.get("mitigation")),
                    "featureId": _ns(item.get("feature_id") or item.get("featureId")),
                }
                for item in (_as_dict(entry) for entry in _as_list(edge_cases.get("edge_cases") or edge_cases.get("edgeCases")))
                if item
            ],
            "riskMatrix": {
                _ns(key): int(_float(value, 0))
                for key, value in _as_dict(edge_cases.get("risk_matrix") or edge_cases.get("riskMatrix")).items()
                if _ns(key)
            },
            "coverageScore": round(_float(edge_cases.get("coverage_score") or edge_cases.get("coverageScore"), 0.0), 2),
        }
        if edge_cases
        else None,
        "impactAnalysis": {
            "layers": [
                {
                    "layer": _ns(item.get("layer")),
                    "impacts": [_as_dict(impact) for impact in _as_list(item.get("impacts")) if _as_dict(impact)],
                }
                for item in (_as_dict(entry) for entry in _as_list(impact_analysis.get("layers")))
                if item
            ],
            "blastRadius": int(_float(impact_analysis.get("blast_radius") or impact_analysis.get("blastRadius"), 0)),
            "criticalPathsAffected": [_ns(item) for item in _as_list(impact_analysis.get("critical_paths_affected") or impact_analysis.get("criticalPathsAffected")) if _ns(item)],
        }
        if impact_analysis
        else None,
        "sequenceDiagrams": {
            "diagrams": [
                {
                    "id": _ns(item.get("id")),
                    "title": _ns(item.get("title")),
                    "mermaidCode": _ns(item.get("mermaid_code") or item.get("mermaidCode")),
                    "flowType": _ns(item.get("flow_type") or item.get("flowType")),
                }
                for item in (_as_dict(entry) for entry in _as_list(sequence_diagrams.get("diagrams")))
                if item
            ]
        }
        if sequence_diagrams
        else None,
        "stateTransitions": {
            "states": [
                {
                    "id": _ns(item.get("id")),
                    "name": _ns(item.get("name")),
                    "description": _ns(item.get("description")),
                }
                for item in (_as_dict(entry) for entry in _as_list(state_transitions.get("states")))
                if item
            ],
            "transitions": [
                {
                    "fromState": _ns(item.get("from_state") or item.get("fromState")),
                    "toState": _ns(item.get("to_state") or item.get("toState")),
                    "trigger": _ns(item.get("trigger")),
                    "guard": _ns(item.get("guard")),
                    "riskLevel": _ns(item.get("risk_level") or item.get("riskLevel")) or "low",
                }
                for item in (_as_dict(entry) for entry in _as_list(state_transitions.get("transitions")))
                if item
            ],
            "riskStates": [_as_dict(item) for item in _as_list(state_transitions.get("risk_states") or state_transitions.get("riskStates")) if _as_dict(item)],
            "mermaidCode": _ns(state_transitions.get("mermaid_code") or state_transitions.get("mermaidCode")),
        }
        if state_transitions
        else None,
        "qualityGates": [_as_dict(item) for item in _as_list(source.get("quality_gates") or source.get("qualityGates")) if _as_dict(item)],
    }
    if not any(normalized.get(key) for key in ("rubberDuckPrd", "edgeCases", "impactAnalysis", "sequenceDiagrams", "stateTransitions")):
        return None
    return normalized


def normalize_technical_design_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    source = _as_dict(bundle)
    if not source:
        return None
    normalized = {
        "architecture": _as_dict(source.get("architecture")),
        "dataflowMermaid": _ns(source.get("dataflow_mermaid") or source.get("dataflowMermaid")),
        "apiSpecification": [
            {
                "method": _ns(item.get("method") or "GET"),
                "path": _ns(item.get("path") or "/"),
                "description": _ns(item.get("description")),
                "authRequired": _bool(item.get("auth_required"), _bool(item.get("authRequired"), True)),
            }
            for item in (_as_dict(entry) for entry in _as_list(source.get("api_specification") or source.get("apiSpecification")))
            if item
        ],
        "databaseSchema": [
            {
                "name": _ns(item.get("name")),
                "columns": [_as_dict(column) for column in _as_list(item.get("columns")) if _as_dict(column)],
                "indexes": [_ns(index) for index in _as_list(item.get("indexes")) if _ns(index)],
            }
            for item in (_as_dict(entry) for entry in _as_list(source.get("database_schema") or source.get("databaseSchema")))
            if item
        ],
        "interfaceDefinitions": [
            {
                "name": _ns(item.get("name")),
                "properties": [_as_dict(prop) for prop in _as_list(item.get("properties")) if _as_dict(prop)],
                "extends": [_ns(parent) for parent in _as_list(item.get("extends")) if _ns(parent)],
            }
            for item in (_as_dict(entry) for entry in _as_list(source.get("interface_definitions") or source.get("interfaceDefinitions")))
            if item
        ],
        "componentDependencyGraph": {
            _ns(key): [_ns(dep) for dep in _as_list(value) if _ns(dep)]
            for key, value in _as_dict(source.get("component_dependency_graph") or source.get("componentDependencyGraph")).items()
            if _ns(key)
        },
        "qualityGates": [_as_dict(item) for item in _as_list(source.get("quality_gates") or source.get("qualityGates")) if _as_dict(item)],
    }
    if not normalized["architecture"] and not normalized["apiSpecification"] and not normalized["databaseSchema"] and not normalized["interfaceDefinitions"]:
        return None
    return normalized


def _requirements_for_task_mapping(
    requirements: dict[str, Any] | None,
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    feature_names = {item["id"]: _ns(item.get("name") or item.get("feature")) for item in features if _ns(item.get("id"))}
    mapped: list[dict[str, Any]] = []
    for item in _as_list(_as_dict(requirements).get("requirements")):
        record = _as_dict(item)
        statement = _ns(record.get("statement")).lower()
        feature_ids = [
            feature_id
            for feature_id, feature_name in feature_names.items()
            if feature_name and feature_name.lower() in statement
        ]
        mapped.append(
            {
                "id": _ns(record.get("id")),
                "statement": _ns(record.get("statement")),
                "feature_ids": feature_ids,
            }
        )
    return mapped


def _impact_task_dag(task_decomposition: dict[str, Any] | None) -> dict[str, Any]:
    tasks = []
    for item in _as_list(_as_dict(task_decomposition).get("tasks")):
        record = _as_dict(item)
        tasks.append(
            {
                "id": _ns(record.get("id")),
                "name": _ns(record.get("title")),
                "depends_on": [_ns(dep) for dep in _as_list(record.get("dependsOn") or record.get("depends_on")) if _ns(dep)],
            }
        )
    return {"nodes": tasks}


def backfill_native_artifacts(
    project_record: dict[str, Any],
    *,
    target_language: str = "ja",
) -> dict[str, Any]:
    project = dict(project_record)
    project["requirementsConfig"] = _requirements_config(project)
    spec = _ns(project.get("spec"))
    if not spec:
        return project

    selected_features = _selected_features(project)
    research = _as_dict(project.get("research"))
    selected_design = _selected_design_variant(project)

    reverse_engineering = normalize_reverse_engineering_result(project.get("reverseEngineering"))
    if reverse_engineering is None:
        code_snippets, test_snippets, file_paths, source_type = _collect_snippet_inputs(project)
        if code_snippets or test_snippets:
            raw_reverse = build_reverse_engineering_result(
                code_snippets,
                test_snippets=test_snippets or None,
                file_paths=file_paths or None,
            )
            raw_reverse["source_type"] = source_type or "unknown"
            raw_reverse["quality_gates"] = evaluate_reverse_engineering_quality(raw_reverse)
            reverse_engineering = normalize_reverse_engineering_result(
                localize_reverse_engineering_result(raw_reverse, target_language=target_language)
            )
    if reverse_engineering is not None:
        project["reverseEngineering"] = reverse_engineering

    requirements = normalize_requirements_bundle(project.get("requirements"))
    config = _requirements_config(project)
    if config["earsEnabled"] and (
        requirements is None or not _as_list(_as_dict(requirements).get("requirements"))
    ):
        confidence_floor = _float(config.get("confidenceFloor"), 0.6)
        accepted_claims = [
            _as_dict(item)
            for item in _as_list(research.get("claims"))
            if _as_dict(item).get("status") == "accepted"
            and _float(_as_dict(item).get("confidence"), 0.0) >= confidence_floor
        ]
        claims = accepted_claims + _synthetic_requirement_claims(
            selected_features,
            accepted_claims=accepted_claims,
            spec=spec,
        )
        forward_bundle = build_requirements_bundle(
            claims,
            _as_dict(research.get("user_research") or research.get("userResearch")) or None,
            spec,
        )
        reverse_requirements = (
            _as_list(_as_dict(reverse_engineering).get("extractedRequirements"))
            if reverse_engineering is not None
            else []
        )
        if reverse_requirements:
            forward_bundle = merge_requirements_with_reverse_engineering(forward_bundle, reverse_requirements)
        requirements = normalize_requirements_bundle(
            localize_requirements_bundle(forward_bundle, target_language=target_language)
        )
    if requirements is not None:
        project["requirements"] = requirements
    elif config["earsEnabled"] is False:
        project["requirements"] = None

    task_decomposition = normalize_task_decomposition(project.get("taskDecomposition"))
    if task_decomposition is None and selected_features:
        task_decomposition = normalize_task_decomposition(
            decompose_features_to_tasks(
                selected_features,
                [_as_dict(item) for item in _as_list(project.get("milestones")) if _as_dict(item)],
                requirements=_requirements_for_task_mapping(requirements, selected_features),
            )
        )
    if task_decomposition is not None:
        project["taskDecomposition"] = task_decomposition

    dcs_analysis = normalize_dcs_analysis(project.get("dcsAnalysis"))
    if dcs_analysis is None and selected_features:
        flows = []
        prototype = _as_dict(selected_design.get("prototype"))
        for item in _as_list(prototype.get("flows")):
            record = _as_dict(item)
            flows.append(
                {
                    "id": _ns(record.get("id")),
                    "name": _ns(record.get("name")),
                    "steps": [_ns(step) for step in _as_list(record.get("steps")) if _ns(step)],
                    "goal": _ns(record.get("goal")),
                }
            )
        raw_dcs = {
            "rubber_duck_prd": generate_rubber_duck_prd(spec, research, selected_features),
            "edge_case_analysis": analyze_edge_cases(
                selected_features,
                requirements=_as_list(_as_dict(requirements).get("requirements")),
            ),
            "impact_analysis": analyze_impact(
                spec,
                selected_features,
                task_dag=_impact_task_dag(task_decomposition),
            ),
            "sequence_diagrams": generate_sequence_diagrams(selected_features, flows=flows or None),
            "state_transitions": analyze_state_transitions(selected_features, flows=flows or None),
        }
        raw_dcs["quality_gates"] = evaluate_dcs_quality(raw_dcs)
        dcs_analysis = normalize_dcs_analysis(
            localize_dcs_analysis(raw_dcs, target_language=target_language)
        )
    if dcs_analysis is not None:
        project["dcsAnalysis"] = dcs_analysis

    technical_design = normalize_technical_design_bundle(project.get("technicalDesign"))
    if technical_design is None and selected_features:
        raw_technical_design = build_technical_design_bundle(
            _as_dict(project.get("analysis")),
            selected_features,
            selected_design or None,
        )
        raw_technical_design["quality_gates"] = evaluate_technical_design_quality(raw_technical_design)
        technical_design = normalize_technical_design_bundle(raw_technical_design)
    if technical_design is not None:
        project["technicalDesign"] = technical_design

    return project
