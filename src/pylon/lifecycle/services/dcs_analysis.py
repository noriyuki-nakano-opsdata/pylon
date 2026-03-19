"""DCS (Development Context Support) analysis services.

Provides edge-case analysis, rubber-duck PRD generation, impact analysis,
sequence diagram generation, and state transition analysis for lifecycle phases.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


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


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeCase:
    id: str
    scenario: str
    severity: str  # "critical" | "high" | "medium" | "low"
    mitigation: str = ""
    feature_id: str = ""


@dataclass(frozen=True)
class EdgeCaseAnalysis:
    edge_cases: tuple[EdgeCase, ...] = ()
    risk_matrix: dict[str, int] = field(default_factory=dict)  # severity -> count
    coverage_score: float = 0.0


@dataclass(frozen=True)
class ImpactLayer:
    layer: str  # "core" | "api" | "service" | "data" | "ui" | "test" | "config"
    impacts: tuple[dict[str, Any], ...] = ()  # [{component, severity, description}]


@dataclass(frozen=True)
class ImpactAnalysis:
    layers: tuple[ImpactLayer, ...] = ()
    blast_radius: int = 0
    critical_paths_affected: tuple[str, ...] = ()


@dataclass(frozen=True)
class SequenceDiagram:
    id: str
    title: str
    mermaid_code: str
    flow_type: str = "success"  # "success" | "error" | "exception"


@dataclass(frozen=True)
class SequenceDiagramResult:
    diagrams: tuple[SequenceDiagram, ...] = ()


@dataclass(frozen=True)
class StateTransition:
    from_state: str
    to_state: str
    trigger: str
    guard: str = ""
    risk_level: str = "low"


@dataclass(frozen=True)
class StateTransitionAnalysis:
    states: tuple[dict[str, Any], ...] = ()  # [{id, name, description}]
    transitions: tuple[StateTransition, ...] = ()
    risk_states: tuple[dict[str, Any], ...] = ()
    mermaid_code: str = ""


@dataclass(frozen=True)
class RubberDuckPRD:
    problem_statement: str = ""
    target_users: tuple[str, ...] = ()
    success_metrics: tuple[dict[str, Any], ...] = ()
    scope_boundaries: dict[str, tuple[str, ...]] = field(default_factory=dict)
    key_decisions: tuple[dict[str, Any], ...] = ()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = ("critical", "high", "medium", "low")

_AUTH_DATA_KEYWORDS = frozenset({
    "auth", "authentication", "authorization", "credential", "password",
    "token", "secret", "data loss", "data leak", "corruption", "delete",
    "permission", "access control", "encryption", "key management",
})

_UX_BLOCKING_KEYWORDS = frozenset({
    "login", "signup", "onboarding", "checkout", "payment", "navigation",
    "loading", "timeout", "crash", "freeze", "unresponsive",
})

_LAYER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "core": ("engine", "core", "domain", "model", "logic", "algorithm"),
    "api": ("api", "endpoint", "route", "rest", "graphql", "grpc"),
    "service": ("service", "handler", "controller", "middleware", "worker"),
    "data": ("database", "db", "storage", "migration", "schema", "query", "cache"),
    "ui": ("ui", "frontend", "component", "page", "view", "layout", "css", "style"),
    "test": ("test", "spec", "fixture", "mock", "assertion"),
    "config": ("config", "configuration", "env", "setting", "flag", "toggle"),
}


def _classify_severity(scenario: str, feature_name: str) -> str:
    combined = f"{scenario} {feature_name}".lower()
    if any(kw in combined for kw in _AUTH_DATA_KEYWORDS):
        return "critical"
    if any(kw in combined for kw in _UX_BLOCKING_KEYWORDS):
        return "high"
    if any(kw in combined for kw in ("validation", "format", "limit", "boundary")):
        return "medium"
    return "low"


def _generate_edge_cases_for_feature(
    feature: dict[str, Any],
    index: int,
) -> list[EdgeCase]:
    feature_id = str(feature.get("id") or f"feat-{index:03d}")
    name = _normalize_space(feature.get("name") or feature.get("title") or "")
    description = _normalize_space(
        feature.get("description") or feature.get("statement") or ""
    )
    combined = f"{name} {description}".lower()
    cases: list[EdgeCase] = []

    # Input boundary conditions
    input_scenario = f"Empty or null input provided to {name or 'feature'}"
    input_sev = _classify_severity(input_scenario, name)
    cases.append(EdgeCase(
        id=f"EC-{feature_id}-input-boundary",
        scenario=input_scenario,
        severity=input_sev,
        mitigation="Validate all inputs at system boundary; return clear error messages.",
        feature_id=feature_id,
    ))

    overflow_scenario = f"Overflow or special characters in input for {name or 'feature'}"
    overflow_sev = _classify_severity(overflow_scenario, name)
    cases.append(EdgeCase(
        id=f"EC-{feature_id}-input-overflow",
        scenario=overflow_scenario,
        severity=overflow_sev,
        mitigation="Enforce length limits and sanitize special characters.",
        feature_id=feature_id,
    ))

    # State transition edge cases
    if any(kw in combined for kw in ("state", "status", "workflow", "transition", "step", "phase")):
        state_scenario = f"Concurrent access or race condition during {name or 'feature'} state transition"
        state_sev = _classify_severity(state_scenario, name)
        cases.append(EdgeCase(
            id=f"EC-{feature_id}-state-race",
            scenario=state_scenario,
            severity=state_sev,
            mitigation="Use optimistic locking or serialized state transitions.",
            feature_id=feature_id,
        ))

    timeout_scenario = f"Timeout or partial failure during {name or 'feature'} processing"
    timeout_sev = _classify_severity(timeout_scenario, name)
    cases.append(EdgeCase(
        id=f"EC-{feature_id}-timeout",
        scenario=timeout_scenario,
        severity=timeout_sev,
        mitigation="Implement retry with exponential backoff and circuit breaker.",
        feature_id=feature_id,
    ))

    # Integration edge cases
    if any(kw in combined for kw in ("api", "service", "integration", "external", "third-party", "network")):
        integration_scenario = f"External service unavailable during {name or 'feature'} operation"
        integration_sev = _classify_severity(integration_scenario, name)
        cases.append(EdgeCase(
            id=f"EC-{feature_id}-service-unavailable",
            scenario=integration_scenario,
            severity=integration_sev,
            mitigation="Implement graceful degradation and fallback paths.",
            feature_id=feature_id,
        ))

    return cases


def _build_risk_matrix(cases: list[EdgeCase]) -> dict[str, int]:
    matrix: dict[str, int] = {}
    for case in cases:
        matrix[case.severity] = matrix.get(case.severity, 0) + 1
    return matrix


def _classify_feature_layers(feature: dict[str, Any]) -> list[str]:
    combined = " ".join([
        str(feature.get("name", "")),
        str(feature.get("title", "")),
        str(feature.get("description", "")),
        str(feature.get("statement", "")),
        str(feature.get("type", "")),
        str(feature.get("layer", "")),
    ]).lower()
    layers: list[str] = []
    for layer, keywords in _LAYER_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            layers.append(layer)
    if not layers:
        layers.append("service")
    return layers


def _sanitize_mermaid_label(text: str) -> str:
    return _normalize_space(text).replace('"', "'")[:60]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_edge_cases(
    features: list[dict[str, Any]],
    requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze features for edge cases and risk evaluation."""
    all_cases: list[EdgeCase] = []
    features_with_cases: set[str] = set()

    for idx, feature in enumerate(_as_list(features)):
        feat = _as_dict(feature)
        if not feat:
            continue
        cases = _generate_edge_cases_for_feature(feat, idx)
        if cases:
            features_with_cases.add(str(feat.get("id") or f"feat-{idx:03d}"))
        all_cases.extend(cases)

    # Incorporate requirements hints if provided
    for req in _as_list(requirements):
        req_data = _as_dict(req)
        statement = _normalize_space(req_data.get("statement") or "")
        if not statement:
            continue
        req_id = str(req_data.get("id") or "req-unknown")
        severity = _classify_severity(statement, "")
        all_cases.append(EdgeCase(
            id=f"EC-{req_id}-req-boundary",
            scenario=f"Requirement boundary violation: {statement[:80]}",
            severity=severity,
            mitigation="Verify requirement constraints through acceptance testing.",
            feature_id=req_id,
        ))

    risk_matrix = _build_risk_matrix(all_cases)
    total_features = len([f for f in _as_list(features) if _as_dict(f)])
    coverage = len(features_with_cases) / total_features if total_features > 0 else 0.0

    return {
        "edge_cases": [
            {
                "id": c.id,
                "scenario": c.scenario,
                "severity": c.severity,
                "mitigation": c.mitigation,
                "feature_id": c.feature_id,
            }
            for c in all_cases
        ],
        "risk_matrix": risk_matrix,
        "coverage_score": round(coverage, 2),
    }


def generate_rubber_duck_prd(
    spec: str,
    research: dict[str, Any] | None = None,
    features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a PRD-like summary from spec, research findings, and features."""
    spec_text = _normalize_space(spec)
    # Extract problem statement: first sentence or up to 300 chars
    if ". " in spec_text:
        problem_statement = spec_text[: spec_text.index(". ") + 1]
    elif spec_text:
        problem_statement = spec_text[:300]
    else:
        problem_statement = ""

    research_data = _as_dict(research)
    feature_list = _as_list(features)

    # Target users from research user_research or feature personas
    target_users: list[str] = []
    user_research = _as_dict(research_data.get("user_research"))
    segment = _normalize_space(user_research.get("segment"))
    if segment:
        target_users.append(segment)
    for signal in _as_list(user_research.get("signals")):
        text = _normalize_space(signal)
        if text and text not in target_users:
            target_users.append(text)
    for feat in feature_list:
        feat_data = _as_dict(feat)
        persona = _normalize_space(feat_data.get("persona") or feat_data.get("target_user") or "")
        if persona and persona not in target_users:
            target_users.append(persona)
    target_users = _dedupe_strings(target_users)[:5]

    # Success metrics from features
    success_metrics: list[dict[str, Any]] = []
    for feat in feature_list:
        feat_data = _as_dict(feat)
        for criterion in _as_list(feat_data.get("acceptance_criteria")):
            text = _normalize_space(criterion) if isinstance(criterion, str) else _normalize_space(
                _as_dict(criterion).get("text") or _as_dict(criterion).get("description") or ""
            )
            if text:
                success_metrics.append({
                    "feature": _normalize_space(feat_data.get("name") or feat_data.get("title") or ""),
                    "metric": text,
                })
        kpi = _normalize_space(feat_data.get("kpi") or feat_data.get("metric") or "")
        if kpi:
            success_metrics.append({
                "feature": _normalize_space(feat_data.get("name") or feat_data.get("title") or ""),
                "metric": kpi,
            })

    # Scope boundaries
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    for feat in feature_list:
        feat_data = _as_dict(feat)
        name = _normalize_space(feat_data.get("name") or feat_data.get("title") or "")
        if name:
            in_scope.append(name)
        for exclusion in _as_list(feat_data.get("exclusions") or feat_data.get("out_of_scope")):
            text = _normalize_space(exclusion)
            if text:
                out_of_scope.append(text)
    scope_boundaries: dict[str, tuple[str, ...]] = {
        "in_scope": tuple(_dedupe_strings(in_scope)),
        "out_of_scope": tuple(_dedupe_strings(out_of_scope)),
    }

    # Key decisions from research claims with high confidence
    key_decisions: list[dict[str, Any]] = []
    for claim in _as_list(research_data.get("claims")):
        claim_data = _as_dict(claim)
        confidence = float(claim_data.get("confidence", 0) or 0)
        if confidence >= 0.7:
            statement = _normalize_space(
                claim_data.get("statement") or claim_data.get("claim_statement") or ""
            )
            if statement:
                key_decisions.append({
                    "decision": statement,
                    "confidence": round(confidence, 2),
                    "source": str(claim_data.get("id") or claim_data.get("owner") or ""),
                })

    return {
        "problem_statement": problem_statement,
        "target_users": target_users,
        "success_metrics": success_metrics[:10],
        "scope_boundaries": {k: list(v) for k, v in scope_boundaries.items()},
        "key_decisions": key_decisions[:10],
    }


def analyze_impact(
    change_description: str,
    features: list[dict[str, Any]] | None = None,
    task_dag: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze impact of a change across system layers."""
    change_lower = _normalize_space(change_description).lower()
    feature_list = _as_list(features)
    dag = _as_dict(task_dag)

    layer_impacts: dict[str, list[dict[str, Any]]] = {
        layer: [] for layer in _LAYER_KEYWORDS
    }
    blast_radius = 0

    for feat in feature_list:
        feat_data = _as_dict(feat)
        if not feat_data:
            continue
        name = _normalize_space(feat_data.get("name") or feat_data.get("title") or "")
        feat_lower = f"{name} {_normalize_space(feat_data.get('description') or '')}".lower()

        # Check if the feature is potentially affected by the change
        change_tokens = [t for t in change_lower.split() if len(t) > 2]
        affected = any(token in feat_lower for token in change_tokens) if change_tokens else True

        if not affected:
            continue

        layers = _classify_feature_layers(feat_data)
        for layer in layers:
            severity = "high" if layer in ("core", "data") else "medium"
            layer_impacts[layer].append({
                "component": name or "unnamed feature",
                "severity": severity,
                "description": f"Change to '{change_description[:60]}' affects {name or 'feature'} at {layer} layer.",
            })
            blast_radius += 1

    # Build ImpactLayer tuples
    result_layers: list[dict[str, Any]] = []
    for layer_name in _LAYER_KEYWORDS:
        impacts = layer_impacts[layer_name]
        if impacts:
            result_layers.append({
                "layer": layer_name,
                "impacts": impacts,
            })

    # Critical paths from DAG
    critical_paths: list[str] = []
    for task_id, task_data in _as_dict(dag.get("tasks")).items() if dag.get("tasks") else []:
        task = _as_dict(task_data) if isinstance(task_data, Mapping) else {}
        task_name = _normalize_space(task.get("name") or task_id)
        deps = _as_list(task.get("dependencies") or task.get("depends_on"))
        if deps and any(
            _normalize_space(d).lower() in change_lower
            for d in deps
        ):
            critical_paths.append(task_name)
    # Also check DAG nodes list format
    for node in _as_list(dag.get("nodes")):
        node_data = _as_dict(node)
        node_id = _normalize_space(node_data.get("id") or node_data.get("name") or "")
        if node_id and node_id.lower() in change_lower:
            for dep_node in _as_list(dag.get("nodes")):
                dep_data = _as_dict(dep_node)
                deps = _as_list(dep_data.get("dependencies") or dep_data.get("depends_on"))
                if node_id in [str(d) for d in deps]:
                    critical_paths.append(
                        _normalize_space(dep_data.get("id") or dep_data.get("name") or "")
                    )

    return {
        "layers": result_layers,
        "blast_radius": blast_radius,
        "critical_paths_affected": _dedupe_strings(critical_paths),
    }


def generate_sequence_diagrams(
    features: list[dict[str, Any]],
    flows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate Mermaid sequence diagrams for feature flows."""
    diagrams: list[dict[str, Any]] = []
    flow_list = _as_list(flows)

    for idx, feature in enumerate(_as_list(features)):
        feat = _as_dict(feature)
        if not feat:
            continue
        feat_id = str(feat.get("id") or f"feat-{idx:03d}")
        feat_name = _normalize_space(feat.get("name") or feat.get("title") or f"Feature {idx + 1}")
        label = _sanitize_mermaid_label(feat_name)

        # Determine participants from feature characteristics
        combined = f"{feat_name} {_normalize_space(feat.get('description') or '')}".lower()
        participants = ["User", "Frontend"]
        if any(kw in combined for kw in ("api", "endpoint", "rest", "graphql")):
            participants.append("API")
        else:
            participants.append("API")
        if any(kw in combined for kw in ("service", "worker", "handler")):
            participants.append("Service")
        else:
            participants.append("Service")
        if any(kw in combined for kw in ("database", "db", "storage", "data", "cache")):
            participants.append("Database")

        # Check for matching flow definition
        matched_flow = None
        for flow in flow_list:
            flow_data = _as_dict(flow)
            if str(flow_data.get("feature_id", "")) == feat_id or _normalize_space(
                flow_data.get("name") or ""
            ).lower() == feat_name.lower():
                matched_flow = flow_data
                break

        # Build success diagram
        participant_lines = "\n".join(f"    participant {p}" for p in participants)

        if matched_flow:
            steps = _as_list(matched_flow.get("steps"))
            step_lines = []
            for step in steps:
                step_data = _as_dict(step)
                src = _normalize_space(step_data.get("from") or "User")
                dst = _normalize_space(step_data.get("to") or "Service")
                msg = _sanitize_mermaid_label(
                    step_data.get("message") or step_data.get("action") or "request"
                )
                step_lines.append(f"    {src}->>+{dst}: {msg}")
                reply = _normalize_space(step_data.get("reply") or "")
                if reply:
                    step_lines.append(f"    {dst}-->>-{src}: {_sanitize_mermaid_label(reply)}")
            interaction_lines = "\n".join(step_lines) if step_lines else (
                f"    User->>+Frontend: initiate {label}\n"
                f"    Frontend->>+API: request\n"
                f"    API->>+Service: process\n"
                f"    Service-->>-API: result\n"
                f"    API-->>-Frontend: response\n"
                f"    Frontend-->>-User: display result"
            )
        else:
            interaction_lines = (
                f"    User->>+Frontend: initiate {label}\n"
                f"    Frontend->>+API: request\n"
                f"    API->>+Service: process"
            )
            if "Database" in participants:
                interaction_lines += f"\n    Service->>+Database: query\n    Database-->>-Service: data"
            interaction_lines += (
                f"\n    Service-->>-API: result\n"
                f"    API-->>-Frontend: response\n"
                f"    Frontend-->>-User: display result"
            )

        success_mermaid = f"sequenceDiagram\n{participant_lines}\n{interaction_lines}"
        diagrams.append({
            "id": f"seq-{feat_id}-success",
            "title": f"{feat_name} - Success Flow",
            "mermaid_code": success_mermaid,
            "flow_type": "success",
        })

        # Build error diagram if error handling is implied
        has_error_hints = any(
            kw in combined
            for kw in ("error", "fail", "exception", "retry", "fallback", "timeout", "validation")
        )
        if has_error_hints or (matched_flow and matched_flow.get("error_steps")):
            error_interactions = (
                f"    User->>+Frontend: initiate {label}\n"
                f"    Frontend->>+API: request\n"
                f"    API->>+Service: process\n"
                f"    Service-->>-API: error response\n"
                f"    API-->>-Frontend: error 4xx/5xx\n"
                f"    Frontend-->>-User: display error message"
            )
            error_mermaid = f"sequenceDiagram\n{participant_lines}\n{error_interactions}"
            diagrams.append({
                "id": f"seq-{feat_id}-error",
                "title": f"{feat_name} - Error Flow",
                "mermaid_code": error_mermaid,
                "flow_type": "error",
            })

    return {
        "diagrams": diagrams,
    }


def analyze_state_transitions(
    features: list[dict[str, Any]],
    flows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze state transitions across features."""
    states: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    state_ids: set[str] = set()
    outgoing: dict[str, int] = {}
    incoming: dict[str, int] = {}

    def _ensure_state(state_id: str, name: str = "", description: str = "") -> None:
        if state_id not in state_ids:
            state_ids.add(state_id)
            states.append({
                "id": state_id,
                "name": name or state_id,
                "description": description,
            })

    # Extract from features
    for idx, feature in enumerate(_as_list(features)):
        feat = _as_dict(feature)
        if not feat:
            continue
        feat_name = _normalize_space(feat.get("name") or feat.get("title") or f"Feature {idx + 1}")

        # Check for explicit states/transitions in feature
        for st in _as_list(feat.get("states")):
            st_data = _as_dict(st)
            sid = _normalize_space(st_data.get("id") or st_data.get("name") or "")
            if sid:
                _ensure_state(sid, _normalize_space(st_data.get("name") or sid), _normalize_space(st_data.get("description") or ""))

        for tr in _as_list(feat.get("transitions")):
            tr_data = _as_dict(tr)
            from_s = _normalize_space(tr_data.get("from") or tr_data.get("from_state") or "")
            to_s = _normalize_space(tr_data.get("to") or tr_data.get("to_state") or "")
            trigger = _normalize_space(tr_data.get("trigger") or tr_data.get("event") or "action")
            if from_s and to_s:
                _ensure_state(from_s, from_s)
                _ensure_state(to_s, to_s)
                guard = _normalize_space(tr_data.get("guard") or "")
                risk = _normalize_space(tr_data.get("risk_level") or "low")
                transitions.append({
                    "from_state": from_s,
                    "to_state": to_s,
                    "trigger": trigger,
                    "guard": guard,
                    "risk_level": risk,
                })
                outgoing[from_s] = outgoing.get(from_s, 0) + 1
                incoming[to_s] = incoming.get(to_s, 0) + 1

        # If no explicit transitions, infer from feature lifecycle
        if not _as_list(feat.get("transitions")):
            init_state = f"{feat_name}_init"
            active_state = f"{feat_name}_active"
            complete_state = f"{feat_name}_complete"
            error_state = f"{feat_name}_error"

            _ensure_state(init_state, f"{feat_name} Init", f"Initial state for {feat_name}")
            _ensure_state(active_state, f"{feat_name} Active", f"Processing state for {feat_name}")
            _ensure_state(complete_state, f"{feat_name} Complete", f"Completed state for {feat_name}")
            _ensure_state(error_state, f"{feat_name} Error", f"Error state for {feat_name}")

            for from_s, to_s, trigger, risk in [
                (init_state, active_state, "start", "low"),
                (active_state, complete_state, "finish", "low"),
                (active_state, error_state, "failure", "high"),
                (error_state, init_state, "retry", "medium"),
            ]:
                transitions.append({
                    "from_state": from_s,
                    "to_state": to_s,
                    "trigger": trigger,
                    "guard": "",
                    "risk_level": risk,
                })
                outgoing[from_s] = outgoing.get(from_s, 0) + 1
                incoming[to_s] = incoming.get(to_s, 0) + 1

    # Process explicit flows
    for flow in _as_list(flows):
        flow_data = _as_dict(flow)
        for tr in _as_list(flow_data.get("transitions")):
            tr_data = _as_dict(tr)
            from_s = _normalize_space(tr_data.get("from") or tr_data.get("from_state") or "")
            to_s = _normalize_space(tr_data.get("to") or tr_data.get("to_state") or "")
            trigger = _normalize_space(tr_data.get("trigger") or "action")
            if from_s and to_s:
                _ensure_state(from_s, from_s)
                _ensure_state(to_s, to_s)
                transitions.append({
                    "from_state": from_s,
                    "to_state": to_s,
                    "trigger": trigger,
                    "guard": _normalize_space(tr_data.get("guard") or ""),
                    "risk_level": _normalize_space(tr_data.get("risk_level") or "low"),
                })
                outgoing[from_s] = outgoing.get(from_s, 0) + 1
                incoming[to_s] = incoming.get(to_s, 0) + 1

    # Identify risk states: terminal error states or states with no outgoing transitions
    risk_states: list[dict[str, Any]] = []
    for state in states:
        sid = state["id"]
        is_terminal = outgoing.get(sid, 0) == 0 and incoming.get(sid, 0) > 0
        is_error = any(kw in sid.lower() for kw in ("error", "fail", "dead", "timeout", "panic"))
        if is_terminal or is_error:
            reason = []
            if is_terminal:
                reason.append("terminal state (no outgoing transitions)")
            if is_error:
                reason.append("error/failure state")
            risk_states.append({
                "id": sid,
                "name": state.get("name", sid),
                "reason": "; ".join(reason),
            })

    # Generate Mermaid stateDiagram-v2
    mermaid_lines = ["stateDiagram-v2"]
    for tr in transitions:
        from_s = tr["from_state"].replace(" ", "_")
        to_s = tr["to_state"].replace(" ", "_")
        trigger = tr["trigger"]
        mermaid_lines.append(f"    {from_s} --> {to_s}: {trigger}")

    return {
        "states": states,
        "transitions": transitions,
        "risk_states": risk_states,
        "mermaid_code": "\n".join(mermaid_lines),
    }


def evaluate_dcs_quality(
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate quality of DCS analysis results."""
    gates: list[dict[str, Any]] = []

    # Gate 1: Edge case coverage
    edge_cases = _as_list(_as_dict(analysis.get("edge_case_analysis")).get("edge_cases"))
    coverage = float(_as_dict(analysis.get("edge_case_analysis")).get("coverage_score", 0))
    edge_passed = len(edge_cases) > 0 and coverage > 0
    gates.append({
        "id": "edge-case-coverage",
        "title": "Edge case analysis covers identified features",
        "passed": edge_passed,
        "reason": (
            f"Edge case analysis produced {len(edge_cases)} cases with {coverage:.0%} feature coverage"
            if edge_passed
            else "Edge case analysis is missing or has zero coverage"
        ),
    })

    # Gate 2: Behavior model coverage (sequence diagrams + state transitions)
    diagrams = _as_list(_as_dict(analysis.get("sequence_diagrams")).get("diagrams"))
    state_transitions = _as_list(_as_dict(analysis.get("state_transitions")).get("transitions"))
    behavior_passed = len(diagrams) > 0 or len(state_transitions) > 0
    gates.append({
        "id": "behavior-model-coverage",
        "title": "Behavior models (sequence diagrams or state transitions) are present",
        "passed": behavior_passed,
        "reason": (
            f"Behavior models include {len(diagrams)} sequence diagrams and {len(state_transitions)} state transitions"
            if behavior_passed
            else "No sequence diagrams or state transitions generated"
        ),
    })

    return gates
