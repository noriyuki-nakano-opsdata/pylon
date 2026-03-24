"""Product Lifecycle orchestration and grounded multi-agent lifecycle logic."""

from __future__ import annotations

import ast
import contextvars
import hashlib
import inspect
import json
import math
import os
import re
import time
import uuid
from datetime import UTC, datetime
from html import escape, unescape
from typing import Any, Callable, TypedDict
from urllib import request as urllib_request
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from pylon.agents.cognitive import ReActEngine
from pylon.autonomy.routing import ModelRouteRequest
from pylon.control_plane.scheduler.scheduler import (
    SchedulerDependencyError,
    WorkflowScheduler,
    WorkflowTask,
)
from pylon.lifecycle.services.research_localization import (
    merge_research_localization,
    research_localization_payload,
    with_research_operator_copy,
    translate_fixed_research_text,
)
from pylon.lifecycle.services.planning_localization import (
    merge_planning_localization,
    planning_localization_payload,
    with_planning_operator_copy,
)
from pylon.lifecycle.services.design_localization import (
    backfill_design_localization,
)
from pylon.lifecycle.services.development_workspace import (
    build_development_code_workspace,
    build_development_spec_audit,
    refine_development_code_workspace,
)
from pylon.lifecycle.services.value_contracts import (
    OUTCOME_TELEMETRY_CONTRACT_ID,
    REQUIRED_DELIVERY_CONTRACT_IDS,
    VALUE_CONTRACT_ID,
    build_outcome_telemetry_contract,
    build_value_contract,
    outcome_telemetry_contract_ready,
    value_contract_ready,
)
from pylon.lifecycle.services.development_repo_execution import (
    execute_development_code_workspace,
)
from pylon.lifecycle.services.native_artifacts import (
    normalize_dcs_analysis,
    normalize_requirements_bundle,
    normalize_reverse_engineering_result,
    normalize_task_decomposition,
    normalize_technical_design_bundle,
)
from pylon.prototyping import (
    build_nextjs_prototype_app,
    build_prototype_spec,
)
from pylon.lifecycle.services.research_quality import (
    collect_research_node_results,
    evaluate_research_quality,
    research_node_result,
)
from pylon.lifecycle.services.decision_context import (
    build_lifecycle_decision_context,
)
from pylon.lifecycle.services.research_sources import (
    pricing_hint_from_packet as _pricing_hint_from_packet,
    research_context as _research_context,
    source_observations as _source_observations,
)
from pylon.lifecycle.services.research_runtime import (
    claim_confidence_overrides as _claim_confidence_overrides,
    first_research_text as _first_research_text,
    normalize_space as _normalize_space,
    normalized_research_strings as _normalized_research_strings,
    parse_research_structured_value as _parse_research_structured_value,
    research_autonomous_remediation_state as _research_autonomous_remediation_state,
    research_judgement_artifact as _research_judgement_artifact,
    research_runtime_output as _research_runtime_output,
    research_text_fragments as _research_text_fragments,
    truncate_research_text as _truncate_research_text,
)
from pylon.lifecycle.services.research_view_model import build_research_view_model
from pylon.providers.base import Message, TokenUsage
from pylon.runtime.llm import LLMRuntime, ProviderRegistry, estimate_cost_from_usage, parse_model_ref
from pylon.skills.runtime import SkillRuntime, get_default_skill_runtime
from pylon.workflow.result import NodeResult

class EvidenceItem(TypedDict):
    """Structured evidence for deploy readiness."""
    category: str  # e.g. "work_package", "milestone", "critical_path", "execution", "contract", "file", "route", "package"
    label: str  # Human-readable description
    value: str | int | float  # The evidence value
    unit: str  # e.g. "count", "path", "id", "percentage"


class ChecklistItem(TypedDict):
    """Structured deploy checklist entry."""
    id: str  # Machine-readable identifier
    label: str  # Human-readable description
    category: str  # e.g. "integration", "security", "quality", "readiness"
    required: bool  # Whether this is a blocking requirement


class BlockingIssue(TypedDict):
    """Structured blocking issue."""
    id: str
    severity: str  # "critical" | "major"
    description: str
    source_phase: str  # Which phase raised it


class ReviewFocusItem(TypedDict):
    """Structured review focus area."""
    area: str  # e.g. "security", "performance", "integration"
    description: str
    priority: str  # "high" | "medium" | "low"


PHASE_ORDER: tuple[str, ...] = (
    "research",
    "planning",
    "design",
    "approval",
    "development",
    "deploy",
    "iterate",
)

_LifecycleAgentSkillLookup = Callable[[str], list[str] | tuple[str, ...]]
_LIFECYCLE_SKILL_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("pylon_lifecycle_skill_context", default=None)
)

_MUTABLE_PROJECT_FIELDS = frozenset(
    {
        "name",
        "description",
        "githubRepo",
        "productIdentity",
        "spec",
        "autonomyLevel",
        "researchConfig",
        "researchOperatorDecision",
        "research",
        "analysis",
        "features",
        "milestones",
        "designVariants",
        "selectedDesignId",
        "approvalStatus",
        "approvalComments",
        "approvalRequestId",
        "buildCode",
        "buildCost",
        "buildIteration",
        "buildDecisionFingerprint",
        "milestoneResults",
        "deliveryPlan",
        "developmentExecution",
        "developmentHandoff",
        "valueContract",
        "outcomeTelemetryContract",
        "planEstimates",
        "selectedPreset",
        "orchestrationMode",
        "governanceMode",
        "phaseStatuses",
        "deployChecks",
        "releases",
        "feedbackItems",
        "recommendations",
        "artifacts",
        "decisionLog",
        "skillInvocations",
        "delegations",
        "phaseRuns",
        "requirements",
        "requirementsConfig",
        "reverseEngineering",
        "taskDecomposition",
        "dcsAnalysis",
        "technicalDesign",
    }
)


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    if not cleaned:
        cleaned = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return cleaned[:48]


def _ns(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _keywords(spec: str) -> list[str]:
    lowered = str(spec).replace("・", " ").replace("/", " ").replace("_", " ").lower()
    tokens = [token.strip(".,:;!?()[]{}\"'") for token in lowered.split()]
    return [token for token in tokens if token]


def _contains_any(spec: str, *terms: str) -> bool:
    lowered = spec.lower()
    return any(term.lower() in lowered for term in terms)


_PRODUCT_KIND_SIGNALS: dict[str, tuple[tuple[str, int], ...]] = {
    "learning": (
        ("学習", 3),
        ("勉強", 3),
        ("lesson", 3),
        ("quiz", 3),
        ("education", 3),
        ("child", 3),
        ("kids", 3),
        ("family", 2),
        ("game", 2),
        ("ゲーム", 2),
    ),
    "operations": (
        ("workflow", 3),
        ("approval", 3),
        ("operator", 3),
        ("orchestration", 3),
        ("lifecycle", 3),
        ("phase", 2),
        ("planning", 2),
        ("design", 2),
        ("research", 2),
        ("multi-agent", 3),
        ("マルチエージェント", 3),
        ("自律", 3),
        ("基盤", 2),
        ("ライフサイクル", 3),
        ("フェーズ", 2),
        ("成果物", 2),
        ("系譜", 2),
        ("品質ゲート", 2),
        ("運用", 3),
        ("承認", 3),
        ("監査", 3),
        ("control plane", 3),
        ("platform", 1),
        ("agent", 1),
        ("ops", 1),
        ("studio", 1),
    ),
    "commerce": (
        ("checkout", 3),
        ("commerce", 3),
        ("e-commerce", 3),
        ("注文", 3),
        ("shop", 2),
        ("store", 2),
        ("cart", 2),
        ("order", 2),
        ("販売", 2),
    ),
}

_PRODUCT_KIND_PRIORITY = {
    "learning": 3,
    "commerce": 2,
    "operations": 1,
    "generic": 0,
}


def _weighted_keyword_score(spec: str, terms: tuple[tuple[str, int], ...]) -> int:
    lowered = spec.lower()
    prefix = lowered[:600]
    score = 0
    for term, weight in terms:
        normalized = term.lower()
        hits = lowered.count(normalized)
        if hits <= 0:
            continue
        score += hits * weight
        if normalized in prefix:
            score += weight
    return score


def _selected_feature_names(state: dict[str, Any]) -> list[str]:
    selected = []
    for item in state.get("features", []) or state.get("selected_features", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("selected", True):
            name = str(item.get("feature", "")).strip()
            if name:
                selected.append(name)
    return selected


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


def _current_lifecycle_skill_context() -> dict[str, Any]:
    return dict(_LIFECYCLE_SKILL_CONTEXT.get() or {})


def _resolve_lifecycle_assigned_skills(
    *,
    phase: str,
    node_id: str,
    assigned_skill_ids: list[str] | tuple[str, ...] = (),
    include_blueprint_defaults: bool = True,
    agent_skill_lookup: _LifecycleAgentSkillLookup | None = None,
) -> list[str]:
    resolved = [
        str(item)
        for item in assigned_skill_ids
        if str(item).strip()
    ]
    effective_lookup = (
        agent_skill_lookup
        or _current_lifecycle_skill_context().get("agent_skill_lookup")
    )
    if callable(effective_lookup) and node_id:
        try:
            resolved.extend(
                str(item)
                for item in effective_lookup(node_id)
                if str(item).strip()
            )
        except Exception:
            pass
    if include_blueprint_defaults and phase and node_id:
        try:
            blueprint_agent = _phase_blueprint_for_node(phase, node_id)
            resolved.extend(
                str(item)
                for item in _as_list(blueprint_agent.get("skills"))
                if str(item).strip()
            )
        except Exception:
            pass
    return _dedupe_strings(resolved)


def _infer_lifecycle_phase_and_node(purpose: str) -> tuple[str | None, str | None]:
    skill_plan_match = re.match(
        r"^lifecycle-skill-plan-(research|planning|design|development|deploy|iterate)-([a-z0-9-]+)$",
        purpose,
    )
    if skill_plan_match:
        return skill_plan_match.group(1), skill_plan_match.group(2)
    phase_match = re.match(
        r"^lifecycle-(research|planning|design|development|deploy|iterate)-",
        purpose,
    )
    if not phase_match:
        return None, None
    phase = phase_match.group(1)
    remainder = purpose[len(f"lifecycle-{phase}-"):]
    try:
        node_ids = sorted(
            build_lifecycle_phase_blueprints(phase).keys(),
            key=len,
            reverse=True,
        )
    except Exception:
        node_ids = []
    for candidate in node_ids:
        if remainder == candidate or remainder.startswith(f"{candidate}-"):
            return phase, candidate
    special_nodes = {
        "design": {
            "judge": "design-evaluator",
        },
        "development": {
            "plan": "planner",
            "frontend-plan": "frontend-builder",
            "backend-plan": "backend-builder",
            "integrate": "integrator",
            "review": "reviewer",
        },
    }
    return phase, _as_dict(special_nodes.get(phase)).get(remainder)


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _compact_lifecycle_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 2:
        if isinstance(value, str):
            return value[:280]
        if isinstance(value, list):
            return f"{len(value)} items"
        if isinstance(value, dict):
            return f"{len(value)} fields"
        return value
    if isinstance(value, str):
        return value[:280]
    if isinstance(value, list):
        return [_compact_lifecycle_value(item, depth=depth + 1) for item in value[:6]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 10:
                compacted["_truncated"] = True
                break
            compacted[str(key)] = _compact_lifecycle_value(item, depth=depth + 1)
        return compacted
    return value


def _contains_japanese(text: str) -> bool:
    return any(
        ("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")
        for ch in text
    )


def _looks_like_machine_token(text: str) -> bool:
    normalized = text.strip()
    return bool(
        normalized
        and (
            normalized.startswith(("http://", "https://", "project://"))
            or re.fullmatch(r"[a-z0-9_.:-]+", normalized)
        )
    )


_RESEARCH_RESULT_LIMITS = {
    "quick": 2,
    "standard": 3,
    "deep": 4,
}

_RESEARCH_NON_VENDOR_HOSTS = frozenset(
    {
        "bing.com",
        "capterra.com",
        "docs.google.com",
        "duckduckgo.com",
        "facebook.com",
        "g2.com",
        "getapp.com",
        "github.com",
        "linkedin.com",
        "medium.com",
        "reddit.com",
        "softwareadvice.com",
        "x.com",
        "youtube.com",
    }
)

_RESEARCH_POSITIVE_HINTS = (
    "adoption",
    "demand",
    "expanding",
    "growth",
    "opportunity",
    "roi",
    "scale",
    "需要",
    "成長",
    "拡大",
    "導入",
)

_RESEARCH_NEGATIVE_HINTS = (
    "barrier",
    "challenge",
    "compliance",
    "cost",
    "friction",
    "integration",
    "latency",
    "risk",
    "security",
    "課題",
    "懸念",
    "規制",
    "運用負荷",
)

_RESEARCH_LOCALIZATION_FIXED_JA = {
    "external url evidence is present": "外部 URL に grounded された evidence があります。",
    "external url evidence is missing": "外部 URL に grounded された evidence が不足しています。",
    "dissent coverage present": "主要仮説に対する反証が生成されています。",
    "dissent coverage missing": "主要仮説に対する反証が不足しています。",
    "confidence floor satisfied": "confidence floor は planning の閾値を満たしています。",
    "all critical nodes healthy": "critical node はすべて正常です。",
    "Address degraded nodes, strengthen source grounding, and re-evaluate blocked claims.": "degraded node を補修し、source grounding を補強したうえで、blocked claim を再評価します。",
    "Claims that survived dissent are passed to planning together with unresolved questions.": "反証を踏まえて残った仮説を、未解決の問いと一緒に planning に引き渡します。",
}

_RESEARCH_NON_PRODUCT_PATH_HINTS = (
    "article",
    "articles",
    "blog",
    "blogs",
    "comparison",
    "comparisons",
    "guide",
    "guides",
    "insights",
    "learn",
    "news",
    "post",
    "posts",
    "report",
    "reports",
    "research",
    "resources",
    "trends",
)

_RESEARCH_PRODUCT_PATH_HINTS = (
    "app",
    "features",
    "platform",
    "pricing",
    "product",
    "products",
    "software",
    "solution",
    "solutions",
)

_RESEARCH_PRODUCT_TEXT_HINTS = (
    "approval",
    "automation",
    "control plane",
    "feature",
    "governance",
    "operator workflow",
    "platform",
    "pricing",
    "product",
    "software",
    "traceability",
    "workflow",
)

_RESEARCH_ARTICLE_TEXT_HINTS = (
    "alternatives",
    "best ",
    "comparison",
    "industry outlook",
    "market size",
    "news",
    "report",
    "top ",
    "trends",
    "vs.",
    "vs ",
)

_RESEARCH_NETWORK_FAILURE_TTL_SECONDS = 120.0
_RESEARCH_NETWORK_BACKOFF: dict[str, float] = {}
_RESEARCH_SEARCH_HOST_KEY = "__research-search__"

def _research_retry_count(state: dict[str, Any], node_id: str) -> int:
    return int(
        _as_dict(state.get(_node_state_key(node_id, "result"))).get("retryCount", 0)
        or 0
    )


def _research_recovery_mode(state: dict[str, Any]) -> str:
    remediation_mode = str(_research_remediation_context(state).get("recoveryMode", "") or "").strip()
    if remediation_mode:
        return remediation_mode
    return str(state.get("recovery_mode", state.get("recoveryMode", "auto")) or "auto").strip()


def _research_effective_recovery_mode(
    state: dict[str, Any],
    *,
    node_id: str | None = None,
) -> str:
    configured = _research_recovery_mode(state)
    if configured != "auto":
        return configured
    research = _as_dict(state.get("research"))
    if not research:
        return "auto"
    prior_retry_count = 0
    if node_id:
        prior_retry_count = _research_retry_count(state, node_id)
    if prior_retry_count > 0 or any(
        int(_as_dict(item).get("retryCount", 0) or 0) > 0
        for item in _as_list(research.get("node_results"))
    ):
        return "reframe_research"
    return "deepen_evidence"


def _research_depth(state: dict[str, Any]) -> str:
    configured = str(state.get("depth", "standard") or "standard")
    recovery_mode = _research_effective_recovery_mode(state)
    if recovery_mode == "deepen_evidence":
        return "deep"
    return configured


def _research_source_limit(state: dict[str, Any]) -> int:
    return _RESEARCH_RESULT_LIMITS.get(_research_depth(state), 3)

def _normalize_identity_profile(value: Any) -> dict[str, Any]:
    profile = _as_dict(value)
    official_website = _normalize_external_url(str(profile.get("officialWebsite", "") or ""))
    official_domains = _dedupe_strings(
        [
            _source_host(str(item))
            for item in _as_list(profile.get("officialDomains"))
            if _source_host(str(item))
        ]
    )
    if official_website:
        host = _source_host(official_website)
        if host and host not in official_domains:
            official_domains.append(host)
    return {
        "companyName": _normalize_space(profile.get("companyName")),
        "productName": _normalize_space(profile.get("productName")),
        "officialWebsite": official_website,
        "officialDomains": official_domains,
        "aliases": _dedupe_strings(_normalize_space(item) for item in _as_list(profile.get("aliases"))),
        "excludedEntityNames": _dedupe_strings(
            _normalize_space(item) for item in _as_list(profile.get("excludedEntityNames"))
        ),
    }


def _research_identity_profile(state: dict[str, Any]) -> dict[str, Any]:
    return _normalize_identity_profile(
        _as_dict(state.get("identity_profile")) or _as_dict(state.get("productIdentity"))
    )


def _identity_anchor_exclusions(identity_profile: dict[str, Any]) -> list[str]:
    exclusions: list[str] = []
    for item in _as_list(identity_profile.get("excludedEntityNames"))[:3]:
        text = _normalize_space(item)
        if text:
            exclusions.append(f'-"{text[:48]}"')
    return exclusions


def _research_query_anchor(spec: str, identity_profile: dict[str, Any] | None = None) -> str:
    identity = _normalize_identity_profile(identity_profile)
    anchor_parts = _dedupe_strings(
        [
            _normalize_space(identity.get("productName")),
            _normalize_space(identity.get("companyName")),
            *[str(item) for item in _as_list(identity.get("aliases"))[:2]],
            *[str(item) for item in _as_list(identity.get("officialDomains"))[:1]],
        ]
    )
    if anchor_parts:
        return " ".join([*anchor_parts, *_identity_anchor_exclusions(identity)])[:180]
    title = _normalize_space(_preview_title(spec))
    if len(title) >= 18:
        return title[:120]
    keywords = _keywords(spec)
    if keywords:
        return " ".join(keywords[:8])[:120]
    return title[:120] or "product software"


def _research_remediation_context(state: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(state.get("remediation_context"))


def _research_remediation_targets(state: dict[str, Any]) -> set[str]:
    context = _research_remediation_context(state)
    return {
        str(item)
        for item in [
            *_as_list(context.get("retryNodeIds")),
            *_as_list(context.get("blockingNodeIds")),
        ]
        if str(item).strip()
    }


def _research_node_is_targeted_for_remediation(state: dict[str, Any], node_id: str) -> bool:
    targets = _research_remediation_targets(state)
    return not targets or node_id in targets


def _research_remediation_queries(
    state: dict[str, Any],
    *,
    node_id: str,
    queries: list[str],
) -> list[str]:
    context = _research_remediation_context(state)
    recovery_mode = _research_effective_recovery_mode(state, node_id=node_id)
    if (
        not context
        and recovery_mode in {"", "auto"}
    ):
        return list(dict.fromkeys(str(item) for item in queries if str(item).strip()))
    if context and not _research_node_is_targeted_for_remediation(state, node_id):
        return list(dict.fromkeys(str(item) for item in queries if str(item).strip()))
    anchor = _research_query_anchor(
        str(state.get("spec", "")),
        _research_identity_profile(state),
    )
    objective = _normalize_space(context.get("objective"))
    missing = {
        str(item)
        for item in _as_list(context.get("missingSourceClasses"))
        if str(item).strip()
    }
    extra: list[str] = []
    if node_id == "competitor-analyst":
        extra.extend(
            [
                f"{anchor} official product",
                f"{anchor} pricing",
                f"{anchor} integrations",
                f"{anchor} vendor platform",
            ]
        )
        if {"vendor_page", "pricing_page", "integration_doc"} & missing:
            extra.extend(
                [
                    f"{anchor} product overview",
                    f"{anchor} pricing page",
                    f"{anchor} integration documentation",
            ]
        )
    elif node_id == "market-researcher":
        extra.extend(
            [
                f"{anchor} market report",
                f"{anchor} industry report",
                f"{anchor} CAGR adoption",
            ]
        )
    elif node_id == "user-researcher":
        extra.extend(
            [
                f"{anchor} customer review",
                f"{anchor} forum discussion",
                f"{anchor} operator pain point",
            ]
        )
    elif node_id == "tech-evaluator":
        extra.extend(
            [
                f"{anchor} documentation api",
                f"{anchor} security compliance",
                f"{anchor} implementation guide",
            ]
        )
    if recovery_mode == "reframe_research":
        if node_id == "competitor-analyst":
            extra.extend(
                [
                    f"{anchor} enterprise use case",
                    f"{anchor} team workflow",
                    f"{anchor} governance requirement",
                    f"{anchor} implementation friction",
                ]
            )
        elif node_id == "market-researcher":
            extra.extend(
                [
                    f"{anchor} buyer segment",
                    f"{anchor} adoption barrier",
                    f"{anchor} implementation obstacle",
                    f"{anchor} change management",
                ]
            )
        elif node_id == "user-researcher":
            extra.extend(
                [
                    f"{anchor} jobs to be done",
                    f"{anchor} switching cost",
                    f"{anchor} manual workaround",
                    f"{anchor} budget owner",
                ]
            )
        elif node_id == "tech-evaluator":
            extra.extend(
                [
                    f"{anchor} audit trail",
                    f"{anchor} role based access",
                    f"{anchor} operational constraint",
                    f"{anchor} implementation risk",
                ]
            )
    if objective:
        extra.append(f"{anchor} {objective[:80]}")
    return list(
        dict.fromkeys(str(item).strip() for item in [*queries, *extra] if str(item).strip())
    )


def _source_host(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    return (parsed.hostname or "").lower().replace("www.", "")


def _source_label_from_host(host: str) -> str:
    primary = str(host or "").split(".", 1)[0].replace("-", " ").replace("_", " ").strip()
    if not primary:
        return "Source"
    return " ".join(part.capitalize() for part in primary.split())


def _normalize_external_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    if "://" not in raw and "." in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl()


def _is_external_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _research_network_enabled() -> bool:
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _research_network_host_available(host_key: str) -> bool:
    if not host_key:
        return True
    blocked_until = float(_RESEARCH_NETWORK_BACKOFF.get(host_key, 0.0) or 0.0)
    if blocked_until <= 0.0:
        return True
    if blocked_until <= time.monotonic():
        _RESEARCH_NETWORK_BACKOFF.pop(host_key, None)
        return True
    return False


def _mark_research_network_host_unavailable(host_key: str) -> None:
    if not host_key:
        return
    _RESEARCH_NETWORK_BACKOFF[host_key] = (
        time.monotonic() + _RESEARCH_NETWORK_FAILURE_TTL_SECONDS
    )


def _extract_html_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return _truncate_research_text(unescape(match.group(1)), limit=140) if match else ""


def _extract_html_meta_description(html: str) -> str:
    patterns = (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\'](.*?)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return _truncate_research_text(unescape(match.group(1)), limit=220)
    return ""


def _visible_text_from_html(html: str) -> str:
    stripped = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", html)
    stripped = re.sub(r"(?i)<br\s*/?>", "\n", stripped)
    stripped = re.sub(r"(?i)</(p|div|section|article|li|h1|h2|h3|h4|h5|h6)>", "\n", stripped)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return _normalize_space(unescape(stripped))


def _fetch_research_packet(url: str) -> dict[str, Any]:
    normalized = _normalize_external_url(url)
    if not normalized or not _research_network_enabled():
        return {}
    host_key = _source_host(normalized)
    if not _research_network_host_available(host_key):
        return {}
    request = urllib_request.Request(
        normalized,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            "User-Agent": "PylonLifecycleResearch/1.0 (+https://pylon.local)",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=3.0) as response:  # noqa: S310
            content_type = str(response.headers.get("Content-Type", ""))
            lowered_content_type = content_type.lower()
            if lowered_content_type and "text/html" not in lowered_content_type and "application/xhtml+xml" not in lowered_content_type:
                return {}
            raw = response.read(240_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception:
        _mark_research_network_host_unavailable(host_key)
        return {}
    html = raw.decode(charset, errors="replace")
    text_excerpt = _truncate_research_text(_visible_text_from_html(html), limit=1000)
    description = _extract_html_meta_description(html)
    title = _extract_html_title(html) or _source_label_from_host(_source_host(normalized))
    excerpt = _truncate_research_text(description or text_excerpt or title, limit=260)
    return {
        "source_ref": normalized,
        "source_type": "url",
        "url": normalized,
        "host": _source_host(normalized),
        "title": title,
        "description": description,
        "excerpt": excerpt,
        "text_excerpt": text_excerpt,
    }


def _html_attribute(attrs: str, name: str) -> str:
    match = re.search(rf'{name}=["\'](.*?)["\']', attrs, re.IGNORECASE | re.DOTALL)
    return unescape(match.group(1)).strip() if match else ""


def _unwrap_search_result_url(href: str) -> str:
    raw = unescape(str(href or "").strip())
    if raw.startswith("//"):
        raw = f"https:{raw}"
    parsed = urlparse(raw)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        redirected = parse_qs(parsed.query).get("uddg")
        if redirected:
            return _normalize_external_url(unquote(redirected[0]))
    return _normalize_external_url(raw)


def _extract_search_results(html: str, *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for match in re.finditer(r"<a(?P<attrs>[^>]*)>(?P<label>.*?)</a>", html, re.IGNORECASE | re.DOTALL):
        attrs = str(match.group("attrs") or "")
        href = _html_attribute(attrs, "href")
        class_name = _html_attribute(attrs, "class")
        if "uddg=" not in href and "result" not in class_name.lower():
            continue
        resolved = _unwrap_search_result_url(href)
        if not resolved or resolved in seen_urls:
            continue
        title = _truncate_research_text(_visible_text_from_html(match.group("label")), limit=140)
        if not title:
            continue
        seen_urls.add(resolved)
        results.append({"title": title, "url": resolved})
        if len(results) >= limit:
            break
    return results


def _search_web(query: str, *, limit: int) -> list[dict[str, str]]:
    if not _research_network_enabled():
        return []
    if not _research_network_host_available(_RESEARCH_SEARCH_HOST_KEY):
        return []
    endpoints = (
        "https://duckduckgo.com/html/?" + urlencode({"q": query}),
        "https://lite.duckduckgo.com/lite/?" + urlencode({"q": query}),
    )
    for endpoint in endpoints:
        request = urllib_request.Request(
            endpoint,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
                "User-Agent": "PylonLifecycleResearch/1.0 (+https://pylon.local)",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=2.0) as response:  # noqa: S310
                html = response.read(180_000).decode(
                    response.headers.get_content_charset() or "utf-8",
                    errors="replace",
                )
        except Exception:
            _mark_research_network_host_unavailable(_RESEARCH_SEARCH_HOST_KEY)
            break
        results = _extract_search_results(html, limit=limit)
        if results:
            return results
    return []


def _brief_research_packet(spec: str) -> dict[str, Any]:
    title = _preview_title(spec) or "Project brief"
    excerpt = _truncate_research_text(spec, limit=260) or "No brief provided."
    return {
        "source_ref": "project://brief",
        "source_type": "project-brief",
        "url": "",
        "host": "project-brief",
        "title": title,
        "description": excerpt,
        "excerpt": excerpt,
        "text_excerpt": _truncate_research_text(spec, limit=1000) or excerpt,
    }


def _looks_like_vendor_source(url: str) -> bool:
    host = _source_host(url)
    if not host:
        return False
    if host in _RESEARCH_NON_VENDOR_HOSTS:
        return False
    if any(host.endswith(f".{blocked}") for blocked in _RESEARCH_NON_VENDOR_HOSTS):
        return False
    return True


def _looks_like_vendor_product_packet(packet: dict[str, Any]) -> bool:
    url = str(packet.get("url") or packet.get("source_ref") or "")
    if not _looks_like_vendor_source(url):
        return False
    parsed = urlparse(url)
    path_segments = [
        segment.strip().lower()
        for segment in parsed.path.split("/")
        if segment.strip()
    ]
    text = " ".join(
        [
            str(packet.get("title", "") or ""),
            str(packet.get("description", "") or ""),
            str(packet.get("excerpt", "") or ""),
            str(packet.get("text_excerpt", "") or ""),
        ]
    ).lower()
    if any(segment in _RESEARCH_PRODUCT_PATH_HINTS for segment in path_segments):
        return True
    if any(hint in text for hint in _RESEARCH_PRODUCT_TEXT_HINTS):
        return True
    if any(segment in _RESEARCH_NON_PRODUCT_PATH_HINTS for segment in path_segments):
        return False
    if any(hint in text for hint in _RESEARCH_ARTICLE_TEXT_HINTS):
        return False
    return len(path_segments) <= 1


def _collect_research_source_packets(
    state: dict[str, Any],
    *,
    focus: str,
    queries: list[str],
    seed_urls: list[str] | None = None,
    include_brief_on_empty: bool = False,
    prefer_vendor_hosts: bool = False,
) -> list[dict[str, Any]]:
    limit = _research_source_limit(state)
    packets: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    def _append(packet: dict[str, Any]) -> None:
        source_ref = str(packet.get("source_ref", "")).strip()
        if not source_ref or source_ref in seen_refs:
            return
        seen_refs.add(source_ref)
        packets.append(packet)

    for raw_url in list(seed_urls or [])[:limit]:
        normalized_url = _normalize_external_url(str(raw_url))
        packet = _fetch_research_packet(str(raw_url))
        if not packet and normalized_url:
            host = _source_host(normalized_url)
            packet = {
                "source_ref": normalized_url,
                "source_type": "url",
                "url": normalized_url,
                "host": host,
                "title": _source_label_from_host(host),
                "description": "",
                "excerpt": "Public page fetch did not succeed for this supplied source URL.",
                "text_excerpt": "",
            }
        if packet:
            _append(packet)

    if len(packets) < limit:
        for query in queries:
            for result in _search_web(query, limit=max(limit * 2, 4)):
                candidate_url = str(result.get("url", "")).strip()
                if prefer_vendor_hosts and not _looks_like_vendor_source(candidate_url):
                    continue
                packet = _fetch_research_packet(candidate_url)
                if not packet:
                    continue
                if not packet.get("title"):
                    packet["title"] = result.get("title", "")
                if prefer_vendor_hosts and not _looks_like_vendor_product_packet(packet):
                    continue
                _append(packet)
                if len(packets) >= limit:
                    break
            if len(packets) >= limit:
                break

    if prefer_vendor_hosts and not packets and not seed_urls:
        return _collect_research_source_packets(
            state,
            focus=focus,
            queries=queries,
            seed_urls=seed_urls,
            include_brief_on_empty=include_brief_on_empty,
            prefer_vendor_hosts=False,
        )

    if not packets and include_brief_on_empty:
        _append(_brief_research_packet(str(state.get("spec", ""))))

    return packets


def _infer_product_kind(spec: str) -> str:
    tokens = set(_keywords(spec))
    if "ec" in tokens:
        return "commerce"
    scores = {
        kind: _weighted_keyword_score(spec, terms)
        for kind, terms in _PRODUCT_KIND_SIGNALS.items()
    }
    top_kind, top_score = max(
        scores.items(),
        key=lambda item: (item[1], _PRODUCT_KIND_PRIORITY[item[0]]),
    )
    if top_score > 0:
        return top_kind
    return "generic"


def _base_design_tokens(spec: str) -> dict[str, Any]:
    kind = _infer_product_kind(spec)
    if kind == "learning":
        return {
            "style": {
                "name": "Playful Learning",
                "keywords": ["friendly", "bright", "encouraging"],
                "best_for": "family learning journeys and short-session retention",
                "performance": "lightweight card-based UI with clear progress cues",
                "accessibility": "high-contrast labels and large tap targets",
            },
            "colors": {
                "primary": "#2563eb",
                "secondary": "#22c55e",
                "cta": "#f59e0b",
                "background": "#f8fafc",
                "text": "#1e293b",
                "notes": "Use warm reward accents sparingly to keep focus on the learning loop.",
            },
            "typography": {
                "heading": "Plus Jakarta Sans",
                "body": "Noto Sans JP",
                "mood": ["playful", "clear", "reassuring"],
            },
            "effects": ["gentle progress glow", "soft card lift", "streak celebration accents"],
            "anti_patterns": ["dense admin dashboards", "small caption-heavy controls", "low-contrast reward states"],
            "rationale": "The interface should motivate repeated short sessions while still feeling safe and legible for guardians.",
        }
    if kind == "commerce":
        return {
            "style": {
                "name": "Trust Commerce",
                "keywords": ["confident", "clean", "conversion-focused"],
                "best_for": "catalog browsing, checkout, and order confidence",
                "performance": "fast browsing with clear merchandising hierarchy",
                "accessibility": "strong contrast and explicit form states",
            },
            "colors": {
                "primary": "#0f172a",
                "secondary": "#0ea5e9",
                "cta": "#ef4444",
                "background": "#ffffff",
                "text": "#111827",
                "notes": "Keep CTA contrast high and reserve red for decisive commerce actions.",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["trustworthy", "direct", "efficient"],
            },
            "effects": ["sticky CTA emphasis", "hover elevation for product cards", "quiet checkout motion"],
            "anti_patterns": ["hidden fees", "ambiguous status colors", "over-decorated checkout forms"],
            "rationale": "Commerce flows need trust and speed more than novelty, so the visual system should reduce hesitation.",
        }
    if kind == "operations":
        return {
            "style": {
                "name": "Operational Clarity",
                "keywords": ["structured", "audit-ready", "high-density"],
                "best_for": "operator workflows and decision-heavy platform surfaces",
                "performance": "dense but scannable layouts with clear state changes",
                "accessibility": "semantic contrast and explicit status signaling",
            },
            "colors": {
                "primary": "#0f172a",
                "secondary": "#1d4ed8",
                "cta": "#f97316",
                "background": "#f8fafc",
                "text": "#0f172a",
                "notes": "Use amber as an operator action color and blue for system state.",
            },
            "typography": {
                "heading": "IBM Plex Sans",
                "body": "Noto Sans JP",
                "mood": ["precise", "technical", "controlled"],
            },
            "effects": ["status pulse for active runs", "subtle panel depth", "artifact lineage emphasis"],
            "anti_patterns": ["ornamental gradients", "ambiguous badges", "oversized marketing hero blocks"],
            "rationale": "Operator products need trustworthy density and fast scanability rather than decorative novelty.",
        }
    return {
        "style": {
            "name": "Balanced Product",
            "keywords": ["clear", "adaptive", "modern"],
            "best_for": "general-purpose digital products with mixed audiences",
            "performance": "progressive disclosure and responsive content grouping",
            "accessibility": "clear semantic hierarchy and keyboard-safe interactions",
        },
        "colors": {
            "primary": "#1d4ed8",
            "secondary": "#14b8a6",
            "cta": "#f97316",
            "background": "#f8fafc",
            "text": "#0f172a",
            "notes": "Keep the palette restrained so feature priority and content hierarchy carry the UI.",
        },
        "typography": {
            "heading": "IBM Plex Sans",
            "body": "Noto Sans JP",
            "mood": ["balanced", "practical", "modern"],
        },
        "effects": ["subtle entry fades", "hover elevation", "clear focus rings"],
        "anti_patterns": ["generic dashboard filler", "weak empty states", "low-information hero sections"],
        "rationale": "The product should stay adaptable while preserving clear task hierarchy and predictable interactions.",
    }


def _build_persona_bundle(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    context = _research_context(state, segment_from_spec=_segment_from_spec)
    signals = context["user_signals"] or ["価値をすばやく理解したい", "迷わず次の行動に進みたい"]
    pain_points = context["pain_points"] or ["文脈が失われやすい", "品質の見通しが持ちづらい"]
    segment = context["segment"]

    if kind == "learning":
        personas = [
            {
                "name": "Haruka",
                "role": "保護者",
                "age_range": "32-45",
                "goals": _dedupe_strings(["子どもが毎日無理なく続けられること", "学習の進み具合を短時間で把握すること", signals[0]]),
                "frustrations": _dedupe_strings(["続けにくい教材だと習慣化しない", "成果が見えないと課金継続を判断しづらい", pain_points[0]]),
                "tech_proficiency": "medium",
                "context": "忙しい生活の中で、短時間でも継続できる学習体験を求めている。",
            },
            {
                "name": "Sota",
                "role": "学習者",
                "age_range": "6-11",
                "goals": ["毎日少しずつ達成感を得ること", "ゲーム感覚で学び続けること"],
                "frustrations": ["難しすぎると離脱する", "単調だと飽きやすい"],
                "tech_proficiency": "medium",
                "context": "スマホやタブレットで短い学習セッションを繰り返す。",
            },
        ]
        stories = [
            {
                "role": "保護者",
                "action": "1日の学習量と継続状況を確認したい",
                "benefit": "無理のない学習習慣を支援できる",
                "acceptance_criteria": ["今日の達成状況が見える", "継続日数が一目で分かる", "次の推奨行動が提示される"],
                "priority": "must",
            },
            {
                "role": "学習者",
                "action": "短いチャレンジを遊ぶように完了したい",
                "benefit": "毎日続けるモチベーションが保てる",
                "acceptance_criteria": ["1回5分以内で完了できる", "達成時に報酬がある", "難易度が調整される"],
                "priority": "must",
            },
            {
                "role": "保護者",
                "action": "子どもに合わせて学習設定を変えたい",
                "benefit": "年齢や進度に合った学習体験を維持できる",
                "acceptance_criteria": ["目標を変更できる", "通知や時間帯を設定できる"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Haruka",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Haruka", "action": "子ども向け学習アプリを探す", "touchpoint": "App listing", "emotion": "neutral", "pain_point": "本当に続くか判断しづらい", "opportunity": "短時間で続く設計を明示する"},
                    {"phase": "consideration", "persona": "Haruka", "action": "無料体験を比較する", "touchpoint": "Onboarding preview", "emotion": "neutral", "opportunity": "保護者向けの進捗可視化を先に見せる"},
                    {"phase": "acquisition", "persona": "Haruka", "action": "初回設定を行う", "touchpoint": "Goal setup", "emotion": "positive", "opportunity": "年齢別おすすめ設定を提案する"},
                    {"phase": "usage", "persona": "Haruka", "action": "進捗と継続を確認する", "touchpoint": "Guardian dashboard", "emotion": "positive", "opportunity": "今日の一言サマリーを表示する"},
                    {"phase": "advocacy", "persona": "Haruka", "action": "他の保護者に共有する", "touchpoint": "Progress share", "emotion": "positive", "opportunity": "達成バッジを共有可能にする"},
                ],
            }
        ]
        return personas, stories, journeys

    if kind == "commerce":
        personas = [
            {
                "name": "Mina",
                "role": "購入者",
                "age_range": "24-40",
                "goals": _dedupe_strings(["欲しい商品を迷わず見つけること", "安心して購入を完了すること", signals[0]]),
                "frustrations": _dedupe_strings(["比較や在庫状況が見えにくい", "購入途中で不安になる", pain_points[0]]),
                "tech_proficiency": "medium",
                "context": "スマホ中心で比較検討から購入までを短時間で済ませたい。",
            },
            {
                "name": "Riku",
                "role": "店舗運営担当",
                "age_range": "28-42",
                "goals": ["売れ筋と離脱ポイントを把握すること", "在庫切れや問い合わせ負荷を減らすこと"],
                "frustrations": ["販促の効果測定が遅い", "顧客の迷いポイントが見えない"],
                "tech_proficiency": "high",
                "context": "商品運営とCVR改善を兼務している。",
            },
        ]
        stories = [
            {
                "role": "購入者",
                "action": "条件に合う商品をすぐに絞り込みたい",
                "benefit": "比較の負担を減らして購入判断を早められる",
                "acceptance_criteria": ["カテゴリ・価格・在庫で絞り込める", "比較観点が分かりやすい"],
                "priority": "must",
            },
            {
                "role": "購入者",
                "action": "配送や支払い条件を確認して安心して決済したい",
                "benefit": "購入途中の離脱を減らせる",
                "acceptance_criteria": ["送料や到着見込みが明示される", "チェックアウト状態が分かる"],
                "priority": "must",
            },
            {
                "role": "店舗運営担当",
                "action": "在庫と売れ筋を把握したい",
                "benefit": "欠品や機会損失を減らせる",
                "acceptance_criteria": ["在庫警告がある", "人気商品を一覧できる"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Mina",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Mina", "action": "商品を検索する", "touchpoint": "Search results", "emotion": "neutral", "opportunity": "比較軸をカード上で見せる"},
                    {"phase": "consideration", "persona": "Mina", "action": "候補を比較する", "touchpoint": "Product detail", "emotion": "neutral", "pain_point": "違いが分かりにくい", "opportunity": "仕様比較とレビュー要約を出す"},
                    {"phase": "acquisition", "persona": "Mina", "action": "購入する", "touchpoint": "Checkout", "emotion": "positive", "opportunity": "配送・支払情報を1画面で確信させる"},
                    {"phase": "usage", "persona": "Mina", "action": "配送状況を確認する", "touchpoint": "Order tracking", "emotion": "neutral", "opportunity": "通知と到着予測を提供する"},
                    {"phase": "advocacy", "persona": "Mina", "action": "レビューを書く", "touchpoint": "Review prompt", "emotion": "positive", "opportunity": "満足直後に投稿を促す"},
                ],
            }
        ]
        return personas, stories, journeys

    if kind == "operations":
        personas = [
            {
                "name": "Aiko",
                "role": f"{segment} Platform Lead",
                "age_range": "30-45",
                "goals": _dedupe_strings(["Keep context intact from decision to build", "Balance quality with autonomy", signals[0]]),
                "frustrations": _dedupe_strings(["Context is lost at each handoff", "Approval and audit evidence is scattered", pain_points[0]]),
                "tech_proficiency": "high",
                "context": "Owns cross-functional delivery decisions across research, planning, and release review.",
            },
            {
                "name": "Ken",
                "role": "Workflow Operator",
                "age_range": "28-40",
                "goals": ["See run state and blockers immediately", "Issue the next approval or rework decision without hesitation"],
                "frustrations": ["Artifacts and review decisions live in separate places", "Phase progress lacks durable evidence"],
                "tech_proficiency": "high",
                "context": "Handles daily workflow operations and release readiness decisions.",
            },
        ]
        stories = [
            {
                "role": "Platform Lead",
                "action": "preserve decision evidence from research through build",
                "benefit": "review and approval decisions stay explainable",
                "acceptance_criteria": ["artifacts remain attached to each phase", "rework reasons are traceable", "quality gates stay visible"],
                "priority": "must",
            },
            {
                "role": "Workflow Operator",
                "action": "understand multi-agent run status and the next decision",
                "benefit": "stalls can be resolved quickly",
                "acceptance_criteria": ["run state is visible", "agent handoffs are explicit", "the next action is shown"],
                "priority": "must",
            },
            {
                "role": "Platform Lead",
                "action": "carry the selected design and feature scope into build without drift",
                "benefit": "delivery churn stays low",
                "acceptance_criteria": ["the selected design is reflected in build", "feature scope and milestones stay linked"],
                "priority": "should",
            },
        ]
        journeys = [
            {
                "persona_name": "Aiko",
                "touchpoints": [
                    {"phase": "awareness", "persona": "Aiko", "action": "open a new product initiative", "touchpoint": "Research brief", "emotion": "neutral", "opportunity": "Put value hypotheses and competitor pressure side by side from the start"},
                    {"phase": "consideration", "persona": "Aiko", "action": "reshape scope", "touchpoint": "Planning review", "emotion": "neutral", "pain_point": "Priorities and evidence drift apart", "opportunity": "Present Must/Should/Could with rationale in the same view"},
                    {"phase": "acquisition", "persona": "Aiko", "action": "make a go or no-go decision", "touchpoint": "Approval gate", "emotion": "positive", "opportunity": "Link directly into the exact rework destination"},
                    {"phase": "usage", "persona": "Aiko", "action": "review build and quality state", "touchpoint": "Development review", "emotion": "positive", "opportunity": "Keep artifact lineage and milestone state visible together"},
                    {"phase": "advocacy", "persona": "Aiko", "action": "share the outcome with the operating team", "touchpoint": "Release summary", "emotion": "positive", "opportunity": "Spell out what makes the release operator-ready"},
                ],
            }
        ]
        return personas, stories, journeys

    personas = [
        {
            "name": "Naoki",
            "role": f"{segment} Product Owner",
            "age_range": "28-42",
            "goals": _dedupe_strings(["ユーザーに価値が伝わる初期体験を作ること", "仕様と実装のズレを減らすこと", signals[0]]),
            "frustrations": _dedupe_strings(["要求が広がりやすい", "優先順位が曖昧だと開発がぶれる", pain_points[0]]),
            "tech_proficiency": "high",
            "context": "企画と実装の橋渡しを担う。",
        },
        {
            "name": "Yuna",
            "role": "Primary User",
            "age_range": "24-38",
            "goals": ["迷わず主要タスクを完了すること", "途中で価値を実感すること"],
            "frustrations": ["最初の導線が複雑だと離脱する", "状態が分かりにくいと不安になる"],
            "tech_proficiency": "medium",
            "context": "モバイルとデスクトップを横断して利用する。",
        },
    ]
    stories = [
        {
            "role": "Product Owner",
            "action": "主要な利用シナリオを先に定義したい",
            "benefit": "scope を早く固定できる",
            "acceptance_criteria": ["主要導線が明文化される", "優先順位が示される"],
            "priority": "must",
        },
        {
            "role": "Primary User",
            "action": "最初のタスクを短時間で完了したい",
            "benefit": "継続利用する価値をすぐに理解できる",
            "acceptance_criteria": ["初回導線が短い", "状態と次アクションが明示される"],
            "priority": "must",
        },
    ]
    journeys = [
        {
            "persona_name": "Yuna",
            "touchpoints": [
                {"phase": "awareness", "persona": "Yuna", "action": "価値を知る", "touchpoint": "Landing / first view", "emotion": "neutral", "opportunity": "主要価値を1画面で伝える"},
                {"phase": "consideration", "persona": "Yuna", "action": "試すか判断する", "touchpoint": "Onboarding", "emotion": "neutral", "opportunity": "主要ユースケースだけ先に見せる"},
                {"phase": "acquisition", "persona": "Yuna", "action": "初回設定を完了する", "touchpoint": "Setup", "emotion": "positive", "opportunity": "progressive disclosure を使う"},
                {"phase": "usage", "persona": "Yuna", "action": "主要タスクを実行する", "touchpoint": "Primary workflow", "emotion": "positive", "opportunity": "空状態と次アクションを強くする"},
                {"phase": "advocacy", "persona": "Yuna", "action": "チームに共有する", "touchpoint": "Share / export", "emotion": "positive", "opportunity": "成果物を共有しやすくする"},
            ],
        }
    ]
    return personas, stories, journeys


def _build_story_architecture_bundle(state: dict[str, Any]) -> dict[str, Any]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    feature_names = _selected_feature_names(state)

    if kind == "learning":
        return {
            "job_stories": [
                {
                    "situation": "When a child opens the app for a short daily study session",
                    "motivation": "I want the next lesson to feel achievable and fun",
                    "outcome": "So I can keep the habit going without parental prompting",
                    "priority": "core",
                    "related_features": ["日次レッスン", "ごほうび", "進捗トラッキング"],
                },
                {
                    "situation": "When a learner returns after being interrupted",
                    "motivation": "I want to resume from the exact point I left off",
                    "outcome": "So I can finish the session without losing confidence",
                    "priority": "core",
                    "related_features": ["日次レッスン", "進捗トラッキング"],
                },
                {
                    "situation": "When a guardian checks progress after a busy day",
                    "motivation": "I want a quick summary of what was learned and what needs help",
                    "outcome": "So I can support the child without reading a long report",
                    "priority": "supporting",
                    "related_features": ["保護者ダッシュボード", "進捗トラッキング"],
                },
                {
                    "situation": "When a guardian wants the routine to fit family life",
                    "motivation": "I want to tune difficulty, reminders, and schedule quickly",
                    "outcome": "So the learning habit survives real-world interruptions",
                    "priority": "supporting",
                    "related_features": ["保護者コントロール", "通知", "難易度の自動調整"],
                },
            ],
            "actors": [
                {"name": "Guardian", "type": "primary", "description": "学習習慣を支援する保護者", "goals": ["継続率の把握", "安全な利用"], "interactions": ["progress review", "settings"]},
                {"name": "Learner", "type": "primary", "description": "短時間の学習を行う子ども", "goals": ["達成感", "楽しい学習"], "interactions": ["daily lesson", "rewards"]},
                {"name": "Recommendation Engine", "type": "external_system", "description": "難易度や次の課題を提案する外部ロジック", "goals": ["最適難易度提示"], "interactions": ["lesson personalization"]},
                {"name": "Content Admin", "type": "secondary", "description": "学習素材と到達度を管理する運営担当", "goals": ["教材品質の維持", "難所の把握"], "interactions": ["content review", "difficulty tuning"]},
            ],
            "roles": [
                {"name": "Guardian", "responsibilities": ["目標設定", "利用管理", "進捗確認"], "permissions": ["view_progress", "update_goals", "manage_notifications"], "related_actors": ["Guardian"]},
                {"name": "Learner", "responsibilities": ["日次課題の実行", "報酬の受け取り"], "permissions": ["start_lesson", "view_rewards"], "related_actors": ["Learner"]},
                {"name": "Content Admin", "responsibilities": ["問題セットの更新", "学習シナリオの管理"], "permissions": ["manage_content", "review_metrics"], "related_actors": ["Recommendation Engine"]},
                {"name": "Support Coach", "responsibilities": ["保護者の問い合わせ対応", "学習停滞時の支援"], "permissions": ["view_progress", "recommend_support_actions"], "related_actors": ["Guardian", "Content Admin"]},
            ],
            "use_cases": [
                {"id": "uc-learn-001", "title": "Start daily lesson", "actor": "Learner", "category": "学習体験", "sub_category": "実行", "preconditions": ["今日の課題が生成されている"], "main_flow": ["ホームを開く", "今日の課題を開始する", "問題に回答する", "結果と報酬を受け取る"], "postconditions": ["学習結果が保存される"], "priority": "must", "related_stories": ["日次レッスン"]},
                {"id": "uc-learn-002", "title": "Resume interrupted lesson", "actor": "Learner", "category": "学習体験", "sub_category": "再開", "preconditions": ["途中保存された学習履歴が存在する"], "main_flow": ["アプリを再度開く", "前回の途中状態を確認する", "続きから再開する", "残りの課題を完了する"], "postconditions": ["中断前後を含む学習履歴が統合される"], "priority": "must", "related_stories": ["進捗トラッキング", "日次レッスン"]},
                {"id": "uc-learn-003", "title": "Review guardian summary", "actor": "Guardian", "category": "保護者管理", "sub_category": "確認", "preconditions": ["学習履歴が存在する"], "main_flow": ["進捗画面を開く", "今日の達成と継続日数を確認する", "つまずきポイントと次の推奨行動を確認する"], "postconditions": ["支援内容を判断できる"], "priority": "must", "related_stories": ["進捗トラッキング", "保護者ダッシュボード"]},
                {"id": "uc-learn-004", "title": "Adjust learning plan", "actor": "Guardian", "category": "保護者管理", "sub_category": "設定", "preconditions": ["利用者プロフィールが存在する"], "main_flow": ["目標設定を開く", "難易度や時間帯を変更する", "通知設定を保存する"], "postconditions": ["次回提案に設定が反映される"], "priority": "should", "related_stories": ["保護者コントロール", "通知"]},
                {"id": "uc-learn-005", "title": "Claim reward and streak", "actor": "Learner", "category": "学習体験", "sub_category": "定着", "preconditions": ["その日の課題が完了している"], "main_flow": ["結果画面を開く", "獲得した報酬とストリークを確認する", "次回の目標を知る"], "postconditions": ["継続動機が強化される"], "priority": "should", "related_stories": ["ごほうび・ストリーク"]},
                {"id": "uc-learn-006", "title": "Review content performance", "actor": "Content Admin", "category": "運営管理", "sub_category": "品質改善", "preconditions": ["学習データが蓄積されている"], "main_flow": ["教材レポートを開く", "正答率と離脱率を確認する", "改善が必要なコンテンツを特定する"], "postconditions": ["教材改善の優先順位が決まる"], "priority": "could", "related_stories": ["難易度の自動調整", "進捗トラッキング"]},
            ],
            "ia_analysis": {
                "navigation_model": "hierarchical",
                "site_map": [
                    {"id": "home", "label": "ホーム", "description": "今日の課題と継続状況", "priority": "primary", "children": []},
                    {"id": "lessons", "label": "レッスン", "description": "学習コンテンツ一覧", "priority": "primary", "children": []},
                    {"id": "progress", "label": "進捗", "description": "習慣と理解度の確認", "priority": "primary", "children": []},
                    {"id": "guardian", "label": "保護者設定", "description": "目標・通知・制限の管理", "priority": "secondary", "children": []},
                    {"id": "rewards", "label": "ごほうび", "description": "達成と継続の確認", "priority": "secondary", "children": []},
                    {"id": "admin", "label": "教材管理", "description": "教材品質と到達度の確認", "priority": "utility", "children": []},
                    {"id": "support", "label": "ヘルプ", "description": "FAQ と問い合わせ", "priority": "utility", "children": []},
                ],
                "key_paths": [
                    {"name": "Daily lesson loop", "steps": ["ホーム", "今日の課題", "結果", "報酬"]},
                    {"name": "Resume learning", "steps": ["ホーム", "途中再開", "結果"]},
                    {"name": "Guardian review", "steps": ["進捗", "学習サマリー", "目標設定"]},
                    {"name": "Content quality loop", "steps": ["教材管理", "教材レポート", "改善判断"]},
                ],
            },
        }

    if kind == "commerce":
        return {
            "job_stories": [
                {"situation": "When a buyer is comparing multiple products on mobile", "motivation": "I want filters and trust signals to narrow my choices fast", "outcome": "So I can buy without second-guessing the decision", "priority": "core", "related_features": ["商品検索", "比較", "在庫表示"]},
                {"situation": "When a buyer has already shortlisted products", "motivation": "I want to compare the differences side by side", "outcome": "So I can commit to the right option without reopening every detail page", "priority": "core", "related_features": ["商品比較", "商品詳細"]},
                {"situation": "When an operator spots a low-stock item", "motivation": "I want to react before high-intent demand is lost", "outcome": "So I can protect conversion and reduce support load", "priority": "supporting", "related_features": ["在庫アラート", "注文管理"]},
                {"situation": "When a buyer is waiting after payment", "motivation": "I want proactive delivery visibility", "outcome": "So I can stay confident without contacting support", "priority": "supporting", "related_features": ["配送トラッキング", "通知"]},
            ],
            "actors": [
                {"name": "Buyer", "type": "primary", "description": "購入検討中のユーザー", "goals": ["比較の簡略化", "安心して決済"], "interactions": ["search", "checkout"]},
                {"name": "Store Operator", "type": "primary", "description": "商品と注文を管理する運営担当", "goals": ["在庫最適化", "CVR改善"], "interactions": ["inventory", "order review"]},
                {"name": "Payment Provider", "type": "external_system", "description": "決済を処理する外部サービス", "goals": ["安全な決済"], "interactions": ["checkout"]},
                {"name": "Carrier Service", "type": "external_system", "description": "配送状況を返す外部配送サービス", "goals": ["配送更新"], "interactions": ["shipment tracking"]},
            ],
            "roles": [
                {"name": "Buyer", "responsibilities": ["商品探索", "注文", "配送確認"], "permissions": ["browse_products", "checkout", "view_orders"], "related_actors": ["Buyer"]},
                {"name": "Merchandiser", "responsibilities": ["商品情報更新", "在庫管理"], "permissions": ["manage_catalog", "manage_inventory"], "related_actors": ["Store Operator"]},
                {"name": "Support Operator", "responsibilities": ["注文対応", "返品確認"], "permissions": ["view_orders", "update_order_status"], "related_actors": ["Store Operator"]},
                {"name": "Fulfillment Lead", "responsibilities": ["出荷状況確認", "配送障害対応"], "permissions": ["view_shipments", "update_delivery_status"], "related_actors": ["Carrier Service", "Store Operator"]},
            ],
            "use_cases": [
                {"id": "uc-commerce-001", "title": "Browse and filter products", "actor": "Buyer", "category": "商品探索", "sub_category": "検索・比較", "preconditions": ["商品データが存在する"], "main_flow": ["商品一覧を開く", "条件で絞り込む", "比較候補を選ぶ", "詳細を確認する"], "postconditions": ["比較候補が決まる"], "priority": "must", "related_stories": ["商品検索"]},
                {"id": "uc-commerce-002", "title": "Compare shortlisted products", "actor": "Buyer", "category": "商品探索", "sub_category": "比較", "preconditions": ["比較候補が2件以上ある"], "main_flow": ["比較画面を開く", "価格・仕様・レビューを見比べる", "購入候補を1つに絞る"], "postconditions": ["購入判断が固まる"], "priority": "must", "related_stories": ["商品比較"]},
                {"id": "uc-commerce-003", "title": "Complete checkout", "actor": "Buyer", "category": "購入", "sub_category": "決済", "preconditions": ["カートに商品が入っている"], "main_flow": ["配送先を入力する", "支払方法を選ぶ", "合計金額を確認する", "注文を確定する"], "postconditions": ["注文が作成される"], "priority": "must", "related_stories": ["チェックアウト"]},
                {"id": "uc-commerce-004", "title": "Track order and delivery", "actor": "Buyer", "category": "購入後体験", "sub_category": "配送確認", "preconditions": ["注文が確定している"], "main_flow": ["注文履歴を開く", "配送状況を確認する", "到着見込みを把握する"], "postconditions": ["問い合わせなしで状況を理解できる"], "priority": "should", "related_stories": ["配送トラッキング", "通知"]},
                {"id": "uc-commerce-005", "title": "Manage inventory risk", "actor": "Merchandiser", "category": "運営管理", "sub_category": "在庫", "preconditions": ["在庫データが連携されている"], "main_flow": ["在庫画面を開く", "欠品リスクを確認する", "補充アクションを決める"], "postconditions": ["在庫リスクが整理される"], "priority": "should", "related_stories": ["在庫アラート"]},
                {"id": "uc-commerce-006", "title": "Resolve return or support issue", "actor": "Support Operator", "category": "運営管理", "sub_category": "サポート", "preconditions": ["注文データが存在する"], "main_flow": ["対象注文を検索する", "配送・返品状況を確認する", "返金または再送を判断する"], "postconditions": ["顧客対応が完了する"], "priority": "could", "related_stories": ["注文管理", "配送トラッキング"]},
            ],
            "ia_analysis": {
                "navigation_model": "hierarchical",
                "site_map": [
                    {"id": "catalog", "label": "商品一覧", "description": "カテゴリ・検索・比較", "priority": "primary", "children": []},
                    {"id": "product", "label": "商品詳細", "description": "比較と購入判断", "priority": "primary", "children": []},
                    {"id": "compare", "label": "比較", "description": "候補商品の比較", "priority": "primary", "children": []},
                    {"id": "checkout", "label": "チェックアウト", "description": "配送と決済", "priority": "primary", "children": []},
                    {"id": "orders", "label": "注文管理", "description": "購入履歴と配送確認", "priority": "secondary", "children": []},
                    {"id": "ops", "label": "運営管理", "description": "在庫・販促・問い合わせ", "priority": "secondary", "children": []},
                ],
                "key_paths": [
                    {"name": "Browse to compare", "steps": ["商品一覧", "比較", "商品詳細"]},
                    {"name": "Browse to buy", "steps": ["商品一覧", "商品詳細", "チェックアウト", "注文確認"]},
                    {"name": "Order confidence", "steps": ["注文管理", "配送確認", "通知"]},
                    {"name": "Inventory mitigation", "steps": ["運営管理", "在庫一覧", "補充判断"]},
                ],
            },
        }

    if kind == "operations":
        return {
            "job_stories": [
                {"situation": "When a product team starts a new initiative", "motivation": "I want the system to turn evidence into a decision-ready plan", "outcome": "So I can move into delivery without losing context", "priority": "core", "related_features": ["research workspace", "planning synthesis", "approval gate"]},
                {"situation": "When a release is blocked by quality or governance concerns", "motivation": "I want the blocking artifacts and next action to be obvious", "outcome": "So I can resolve the issue quickly instead of chasing context", "priority": "core", "related_features": ["artifact lineage", "release gate", "operator console"]},
                {"situation": "When a research lane degrades or stalls", "motivation": "I want to recover only the weak lane instead of repeating the whole run", "outcome": "So I can keep momentum while preserving trustworthy evidence", "priority": "core", "related_features": ["research workspace", "operator console", "artifact lineage"]},
                {"situation": "When platform governance changes", "motivation": "I want approval rules and team routing to update without breaking active delivery", "outcome": "So I can adapt the operating model without losing auditability", "priority": "supporting", "related_features": ["approval gate", "operator console", "planning synthesis"]},
            ],
            "actors": [
                {"name": "Platform Lead", "type": "primary", "description": "Owns delivery governance across the product lifecycle", "goals": ["Decision velocity", "Explainable approvals"], "interactions": ["planning review", "approval gate"]},
                {"name": "Lifecycle Operator", "type": "primary", "description": "Runs phases, monitors blockers, and manages interventions", "goals": ["Run visibility", "Controlled handoffs"], "interactions": ["run monitor", "deploy review"]},
                {"name": "Audit Peer", "type": "external_system", "description": "Validates approvals, safety, and governance posture", "goals": ["Auditability"], "interactions": ["approval", "security review"]},
                {"name": "Delivery Engineer", "type": "secondary", "description": "Turns selected design and scope into an executable build plan", "goals": ["Less rework", "Build quality"], "interactions": ["development handoff", "release readiness"]},
            ],
            "roles": [
                {"name": "Platform Lead", "responsibilities": ["scope judgment", "approval", "release oversight"], "permissions": ["approve", "select_design", "view_costs"], "related_actors": ["Platform Lead"]},
                {"name": "Lifecycle Operator", "responsibilities": ["phase execution", "exception handling", "deploy checks"], "permissions": ["run_phase", "view_artifacts", "create_release"], "related_actors": ["Lifecycle Operator"]},
                {"name": "Reviewer", "responsibilities": ["quality and security review", "rework guidance"], "permissions": ["comment", "request_changes", "view_operator_console"], "related_actors": ["Audit Peer"]},
                {"name": "Delivery Engineer", "responsibilities": ["implementation planning", "build handoff", "release coordination"], "permissions": ["view_scope", "view_design", "prepare_release"], "related_actors": ["Delivery Engineer", "Lifecycle Operator"]},
            ],
            "use_cases": [
                {"id": "uc-ops-001", "title": "Run discovery-to-build workflow", "actor": "Lifecycle Operator", "category": "Workflow operations", "sub_category": "Execution", "preconditions": ["A project spec exists"], "main_flow": ["Start research", "Review planning", "Select a design", "Run development"], "postconditions": ["Build artifacts and phase history are recorded"], "priority": "must", "related_stories": ["research workspace"]},
                {"id": "uc-ops-002", "title": "Recover degraded research lane", "actor": "Lifecycle Operator", "category": "Workflow operations", "sub_category": "Recovery", "preconditions": ["A research node is degraded or failed"], "main_flow": ["Open the degraded lane", "Review missing evidence and blockers", "Choose a recovery strategy", "Re-run only the affected lane"], "postconditions": ["The recovery reason and delta are recorded"], "priority": "must", "related_stories": ["research workspace", "operator console"]},
                {"id": "uc-ops-003", "title": "Approve or rework a phase", "actor": "Platform Lead", "category": "Governance", "sub_category": "Approval", "preconditions": ["Phase artifacts are ready"], "main_flow": ["Open the approval gate", "Review the evidence", "Approve or request rework"], "postconditions": ["The decision history is recorded"], "priority": "must", "related_stories": ["approval gate"]},
                {"id": "uc-ops-004", "title": "Trace artifact lineage", "actor": "Reviewer", "category": "Quality control", "sub_category": "Investigation", "preconditions": ["A run has completed"], "main_flow": ["Open an artifact", "Inspect the linked decisions", "Trace which agent produced it"], "postconditions": ["The evidence chain is explainable"], "priority": "must", "related_stories": ["artifact lineage"]},
                {"id": "uc-ops-005", "title": "Configure policies and team routing", "actor": "Platform Lead", "category": "Platform configuration", "sub_category": "Governance", "preconditions": ["The user has workspace admin access"], "main_flow": ["Open settings", "Update approval rules and quality gates", "Save team routing"], "postconditions": ["The new operating policy applies to the next run"], "priority": "should", "related_stories": ["approval gate", "planning synthesis"]},
                {"id": "uc-ops-006", "title": "Monitor active runs and intervene", "actor": "Lifecycle Operator", "category": "Workflow operations", "sub_category": "Monitoring", "preconditions": ["An active run exists"], "main_flow": ["Open the run monitor", "Inspect phase state and blockers", "Choose the required intervention"], "postconditions": ["The blockage and response history are recorded"], "priority": "should", "related_stories": ["operator console", "artifact lineage"]},
                {"id": "uc-ops-007", "title": "Review release readiness and publish outcome", "actor": "Delivery Engineer", "category": "Release management", "sub_category": "Release decision", "preconditions": ["Build artifacts and quality reports are available"], "main_flow": ["Open release readiness", "Review the milestone report and quality gate", "Create the release record"], "postconditions": ["The shipping decision and release artifacts are recorded"], "priority": "could", "related_stories": ["release readiness", "operator console"]},
            ],
            "ia_analysis": {
                "navigation_model": "hub-and-spoke",
                "site_map": [
                    {"id": "workspace", "label": "Lifecycle Workspace", "description": "Primary work area for each phase", "priority": "primary", "children": []},
                    {"id": "runs", "label": "Runs", "description": "Review runs and checkpoints", "priority": "primary", "children": []},
                    {"id": "approvals", "label": "Approvals", "description": "Pending approvals and rework history", "priority": "primary", "children": []},
                    {"id": "artifacts", "label": "Artifacts", "description": "Phase artifacts and lineage", "priority": "secondary", "children": []},
                    {"id": "policies", "label": "Policies", "description": "Approval rules and quality gate settings", "priority": "secondary", "children": []},
                    {"id": "release", "label": "Release", "description": "Release readiness and shipment history", "priority": "secondary", "children": []},
                    {"id": "settings", "label": "Settings", "description": "Policy and environment settings", "priority": "utility", "children": []},
                ],
                "key_paths": [
                    {"name": "Idea to approval", "steps": ["Lifecycle Workspace", "Research", "Planning", "Approval"]},
                    {"name": "Lane recovery", "steps": ["Runs", "Degraded lane", "Recovery strategy", "Research"]},
                    {"name": "Policy update", "steps": ["Policies", "Approval rules", "Team routing"]},
                    {"name": "Build to release", "steps": ["Development", "Runs", "Deploy", "Release"]},
                ],
            },
        }

    return {
        "job_stories": [
            {"situation": "When a user first tries the product", "motivation": "I want the core path to be obvious", "outcome": "So I can reach value without reading a manual", "priority": "core", "related_features": feature_names[:3] or ["onboarding", "primary workflow"]},
            {"situation": "When a user is midway through the product's main task", "motivation": "I want the current state and next action to stay visible", "outcome": "So I can complete the workflow without second-guessing what happens next", "priority": "core", "related_features": feature_names[:3] or ["status visibility", "primary workflow"]},
            {"situation": "When a product team scopes the first release", "motivation": "I want a crisp definition of the MVP", "outcome": "So I can ship without uncontrolled scope growth", "priority": "supporting", "related_features": feature_names[:3] or ["MVP scope"]},
            {"situation": "When a returning user resumes the product", "motivation": "I want my previous context to be restored quickly", "outcome": "So I can continue instead of restarting from scratch", "priority": "supporting", "related_features": feature_names[:3] or ["history and recovery", "notifications"]},
        ],
        "actors": [
            {"name": "Primary User", "type": "primary", "description": "主要タスクを実行する利用者", "goals": ["価値到達", "迷わない操作"], "interactions": ["onboarding", "main workflow"]},
            {"name": "Product Owner", "type": "secondary", "description": "価値仮説と scope を管理する担当者", "goals": ["初期リリース成功"], "interactions": ["planning", "review"]},
            {"name": "Operator", "type": "secondary", "description": "状態確認や問い合わせ対応を担う運用者", "goals": ["状態把握", "問い合わせ削減"], "interactions": ["status review", "history lookup"]},
        ],
        "roles": [
            {"name": "Primary User", "responsibilities": ["主要タスク実行"], "permissions": ["use_core_flow"], "related_actors": ["Primary User"]},
            {"name": "Admin", "responsibilities": ["設定と品質管理"], "permissions": ["configure", "review_metrics"], "related_actors": ["Product Owner"]},
            {"name": "Support Operator", "responsibilities": ["状態確認", "復旧支援"], "permissions": ["view_status", "view_history"], "related_actors": ["Operator"]},
        ],
        "use_cases": [
            {"id": "uc-generic-001", "title": "Complete guided onboarding", "actor": "Primary User", "category": "初回導線", "sub_category": "立ち上げ", "preconditions": ["初回利用または新規セットアップである"], "main_flow": ["オンボーディングを開始する", "必要情報を入力する", "最初の成功条件を確認する"], "postconditions": ["主要導線へ迷わず入れる"], "priority": "must", "related_stories": ["guided onboarding"]},
            {"id": "uc-generic-002", "title": "Complete the primary workflow", "actor": "Primary User", "category": "主要体験", "sub_category": "実行", "preconditions": ["利用開始条件が満たされている"], "main_flow": ["ホームを開く", "主要タスクを開始する", "結果を確認する"], "postconditions": ["価値が伝わる"], "priority": "must", "related_stories": ["primary workflow"]},
            {"id": "uc-generic-003", "title": "Review status and next action", "actor": "Primary User", "category": "主要体験", "sub_category": "把握", "preconditions": ["進行中または完了したタスクが存在する"], "main_flow": ["ステータス画面を開く", "現在状態を確認する", "次の推奨アクションを把握する"], "postconditions": ["迷わず次の操作に進める"], "priority": "must", "related_stories": ["status visibility"]},
            {"id": "uc-generic-004", "title": "Recover previous work context", "actor": "Primary User", "category": "継続利用", "sub_category": "復旧", "preconditions": ["過去の履歴または中断状態が存在する"], "main_flow": ["履歴を開く", "前回の状態を選択する", "復旧して再開する"], "postconditions": ["作業が中断前の文脈で再開される"], "priority": "should", "related_stories": ["history and recovery"]},
            {"id": "uc-generic-005", "title": "Configure notifications and preferences", "actor": "Admin", "category": "設定管理", "sub_category": "構成", "preconditions": ["設定権限がある"], "main_flow": ["設定画面を開く", "通知と基本設定を変更する", "保存する"], "postconditions": ["次回利用に反映される"], "priority": "should", "related_stories": ["notifications"]},
            {"id": "uc-generic-006", "title": "Administer workspace settings", "actor": "Admin", "category": "設定管理", "sub_category": "運用", "preconditions": ["管理権限がある"], "main_flow": ["ワークスペース設定を開く", "利用ルールや表示設定を更新する", "反映状況を確認する"], "postconditions": ["運用条件が整う"], "priority": "could", "related_stories": feature_names[:2]},
        ],
        "ia_analysis": {
            "navigation_model": "hierarchical",
            "site_map": [
                {"id": "home", "label": "ホーム", "description": "主要情報の要約", "priority": "primary", "children": []},
                {"id": "workflow", "label": "主要導線", "description": "最も価値のある操作", "priority": "primary", "children": []},
                {"id": "status", "label": "状態", "description": "進行状況と次アクション", "priority": "primary", "children": []},
                {"id": "history", "label": "履歴", "description": "過去の操作と成果", "priority": "secondary", "children": []},
                {"id": "settings", "label": "設定", "description": "環境や通知の設定", "priority": "utility", "children": []},
            ],
            "key_paths": [
                {"name": "First-run success", "steps": ["オンボーディング", "ホーム", "主要導線", "結果"]},
                {"name": "In-product orientation", "steps": ["状態", "次アクション", "主要導線"]},
                {"name": "Configuration", "steps": ["設定", "保存"]},
                {"name": "Recovery", "steps": ["履歴", "復旧", "主要導線"]},
            ],
        },
    }


def _feature_catalog_for_spec(state: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    if kind == "learning":
        return [
            ("日次レッスン", "must-be", "medium", "短時間でも継続しやすい学習ループを作る"),
            ("進捗トラッキング", "must-be", "medium", "保護者が継続状況を把握できる"),
            ("ごほうび・ストリーク", "one-dimensional", "medium", "習慣化の動機を強める"),
            ("難易度の自動調整", "one-dimensional", "high", "年齢や理解度に合わせて体験を最適化する"),
            ("保護者コントロール", "must-be", "medium", "利用時間や通知を安全に管理できる"),
            ("音声ガイド", "attractive", "medium", "低年齢ユーザーの没入感を高める"),
        ]
    if kind == "commerce":
        return [
            ("商品検索と絞り込み", "must-be", "medium", "比較と発見を素早くする"),
            ("商品比較", "one-dimensional", "medium", "購買判断を短縮する"),
            ("チェックアウト", "must-be", "high", "購入完了までの離脱を減らす"),
            ("在庫アラート", "one-dimensional", "medium", "欠品による機会損失を抑える"),
            ("配送トラッキング", "one-dimensional", "medium", "購入後の不安を減らす"),
            ("レコメンド", "attractive", "high", "客単価と回遊を伸ばす"),
        ]
    if kind == "operations":
        return [
            ("research workspace", "must-be", "medium", "Concentrate hypotheses and evidence in one surface"),
            ("planning synthesis", "must-be", "medium", "Make priorities and execution scope explicit"),
            ("artifact lineage", "one-dimensional", "medium", "Trace each decision back to its evidence"),
            ("approval gate", "must-be", "medium", "Support explainable go or rework decisions"),
            ("operator console", "one-dimensional", "high", "Monitor run state and specialist handoffs"),
            ("release readiness", "attractive", "medium", "Control the path from build to deploy"),
        ]
    return [
        ("guided onboarding", "must-be", "low", "最初の価値到達を早める"),
        ("primary workflow", "must-be", "medium", "主要ユースケースを成立させる"),
        ("status visibility", "one-dimensional", "low", "利用中の不安を減らす"),
        ("notifications", "one-dimensional", "medium", "継続利用を促す"),
        ("history and recovery", "one-dimensional", "medium", "再訪時の文脈復元を容易にする"),
        ("personalization", "attractive", "high", "利用継続時の満足度を高める"),
    ]


def _default_kano_features_for_spec(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "feature": name,
            "category": category,
            "user_delight": 0.95 if category == "attractive" else 0.82 if category == "one-dimensional" else 0.72,
            "implementation_cost": cost,
            "rationale": rationale,
        }
        for name, category, cost, rationale in _feature_catalog_for_spec(state)
    ]


def _default_feature_selections_for_spec(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "feature": item["feature"],
            "category": item["category"],
            "selected": item["category"] != "attractive",
            "priority": "must" if item["category"] == "must-be" else "should" if item["category"] == "one-dimensional" else "could",
            "user_delight": item["user_delight"],
            "implementation_cost": item["implementation_cost"],
            "rationale": item["rationale"],
        }
        for item in _default_kano_features_for_spec(state)
    ]


def _solution_bundle(state: dict[str, Any]) -> dict[str, Any]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    selected_features = _selected_feature_names(state)
    prominent = selected_features[:3] or [item[0] for item in _feature_catalog_for_spec(state)[:3]]

    if kind == "learning":
        business_model = {
            "value_propositions": ["短時間でも続く学習体験", "保護者が安心して見守れる進捗可視化"],
            "customer_segments": ["保護者", "学習者", "教育事業者"],
            "channels": ["App Store", "教育コミュニティ", "口コミ"],
            "revenue_streams": ["Family subscription", "Education bundle", "Premium content packs"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Daily learning loop", "criteria": f"{prominent[0]} と {prominent[1]} が1日の学習導線で完結し、中断からも再開できる", "rationale": "最初に継続の核となる日次体験を成立させる", "phase": "alpha", "depends_on_use_cases": ["uc-learn-001", "uc-learn-002"]},
            {"id": "ms-beta", "name": "Guardian confidence", "criteria": "保護者が進捗、設定、つまずきポイントを1画面で確認できる", "rationale": "継続課金の判断材料を作る", "phase": "beta", "depends_on_use_cases": ["uc-learn-003", "uc-learn-004", "uc-learn-005"]},
            {"id": "ms-release", "name": "Habit-ready release", "criteria": "通知、教材品質レビュー、アクセシビリティが整い7日継続を支援できる", "rationale": "習慣化に必要な運用品質を満たす", "phase": "release", "depends_on_use_cases": ["uc-learn-001", "uc-learn-003", "uc-learn-005", "uc-learn-006"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    if kind == "commerce":
        business_model = {
            "value_propositions": ["比較しやすく安心して買える購入体験", "在庫と注文を見える化する運営支援"],
            "customer_segments": ["購入者", "D2C 運営チーム", "小売事業者"],
            "channels": ["Web storefront", "広告流入", "メール・CRM"],
            "revenue_streams": ["Product margin", "Subscription perks", "Merchant tooling upsell"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Browse to buy", "criteria": "検索・比較・チェックアウトまでの購入導線が成立する", "rationale": "最初にCVRを生むコアループを作る", "phase": "alpha", "depends_on_use_cases": ["uc-commerce-001", "uc-commerce-002", "uc-commerce-003"]},
            {"id": "ms-beta", "name": "Operational confidence", "criteria": "在庫リスク、配送状況、問い合わせ対応を運営者が確認できる", "rationale": "運営上のボトルネックを減らす", "phase": "beta", "depends_on_use_cases": ["uc-commerce-004", "uc-commerce-005", "uc-commerce-006"]},
            {"id": "ms-release", "name": "Trustworthy commerce release", "criteria": "レスポンシブ、アクセシビリティ、配送通知が整った購入体験を提供する", "rationale": "実運用での安心感を確保する", "phase": "release", "depends_on_use_cases": ["uc-commerce-001", "uc-commerce-003", "uc-commerce-004"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    if kind == "operations":
        business_model = {
            "value_propositions": ["Reduce context loss from decision to build", "Run autonomous delivery safely with governance"],
            "customer_segments": ["AI platform teams", "Product operations teams", "Internal developer platform teams"],
            "channels": ["Developer tooling", "Internal platform rollout", "Ops enablement"],
            "revenue_streams": ["Platform seat", "Usage-based orchestration", "Premium governance modules"],
        }
        milestones = [
            {"id": "ms-alpha", "name": "Evidence-to-build loop", "criteria": "Artifact lineage stays continuous from research through development, and degraded lanes can be recovered individually", "rationale": "Establish traceability and localized recovery before pursuing full autonomy", "phase": "alpha", "depends_on_use_cases": ["uc-ops-001", "uc-ops-002", "uc-ops-004"]},
            {"id": "ms-beta", "name": "Governed delivery", "criteria": "Approval, rework, and policy changes can be operated with phase-level deep links", "rationale": "Stabilize the control surface for multi-agent operations", "phase": "beta", "depends_on_use_cases": ["uc-ops-003", "uc-ops-005", "uc-ops-006"]},
            {"id": "ms-release", "name": "Operator-ready release", "criteria": "Run telemetry, release gating, and release records work together as one operating flow", "rationale": "Reach a delivery quality bar that is safe to hand off to operators", "phase": "release", "depends_on_use_cases": ["uc-ops-001", "uc-ops-003", "uc-ops-006", "uc-ops-007"]},
        ]
        return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}

    business_model = {
        "value_propositions": ["主要ユースケースを迷わず完了できる", "仕様と実装の整合を保ちやすい"],
        "customer_segments": ["Primary users", "Product teams"],
        "channels": ["Web", "Mobile", "Team sharing"],
        "revenue_streams": ["Subscription", "Team plan", "Premium capabilities"],
    }
    milestones = [
        {"id": "ms-alpha", "name": "Core workflow ready", "criteria": f"{prominent[0]} と {prominent[1]} を含む主要導線が成立し、初回成功が計測できる", "rationale": "最初に価値到達を成立させる", "phase": "alpha", "depends_on_use_cases": ["uc-generic-001", "uc-generic-002", "uc-generic-003"]},
        {"id": "ms-beta", "name": "Configuration and recovery", "criteria": "設定変更、通知、履歴復元が一貫して扱える", "rationale": "継続利用の土台を作る", "phase": "beta", "depends_on_use_cases": ["uc-generic-004", "uc-generic-005"]},
        {"id": "ms-release", "name": "Release quality", "criteria": "レスポンシブ・a11y・主要状態表示と運用設定が揃う", "rationale": "運用品質の下限を満たす", "phase": "release", "depends_on_use_cases": ["uc-generic-002", "uc-generic-003", "uc-generic-004", "uc-generic-006"]},
    ]
    return {"business_model": business_model, "recommended_milestones": milestones, "design_tokens": _base_design_tokens(spec)}


def _planning_recommendations(state: dict[str, Any]) -> list[str]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    context = _research_context(state, segment_from_spec=_segment_from_spec)
    technical = _as_dict(_as_dict(state.get("research")).get("tech_feasibility"))
    score = float(technical.get("score", 0.75) or 0.75)

    recommendations: list[str] = []
    if kind == "learning":
        recommendations.extend([
            "初回は保護者の安心感よりも、子どもが5分で達成感を得られる日次導線を優先する",
            "進捗可視化と通知設定を beta までに入れて継続判断の材料を作る",
        ])
    elif kind == "commerce":
        recommendations.extend([
            "比較と決済の迷いを減らす導線を優先し、checkout での不安要素を最小化する",
            "運営側には在庫と注文の可視化を先に渡して欠品・問い合わせコストを抑える",
        ])
    elif kind == "operations":
        recommendations.extend([
            "Treat phase-by-phase artifact lineage as a first-class surface so approval evidence never gets lost.",
            "Stabilize handoff and rework control before widening multi-agent parallelism.",
        ])
    else:
        recommendations.extend([
            "初回価値到達までの導線を最短化し、二次導線は progressive disclosure で後ろに送る",
            "主要状態と次アクションを常に明示して、利用中の迷いを減らす",
        ])
    if context["opportunities"]:
        if kind == "operations":
            recommendations.append("市場の追い風があっても、alpha は operator workflow の必須判断面に絞って優位性を検証する")
        elif kind == "commerce":
            recommendations.append("市場機会を広く追う前に、比較から決済までの不安除去を最短距離で検証する")
        elif kind == "learning":
            recommendations.append("市場機会の広がりより先に、短時間でも継続できる日次習慣の成立を検証する")
        else:
            recommendations.append("市場機会の広さよりも、最初の成功導線が成立するかを優先して検証する")
    if context["threats"]:
        recommendations.append("外部ノイズや競争圧があるため、初期計画は説明可能で検証しやすいコアループに集中する")
    if score < 0.78:
        recommendations.append("技術実現性スコアが相対的に低いため、alpha では scope を絞って検証可能性を優先する")
    return _dedupe_strings(recommendations)


def _artifacts(*items: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]


def _provider_backed_lifecycle_available(provider_registry: ProviderRegistry | None) -> bool:
    return provider_registry is not None and bool(provider_registry.provider_names())


def _clamp_score(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, round(numeric, 2)))


def _color_or(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) in {4, 7}:
        return text
    return fallback


def _hex_to_rgb(value: Any) -> tuple[int, int, int] | None:
    text = _color_or(value, "")
    if not text:
        return None
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    try:
        return (
            int(text[1:3], 16),
            int(text[3:5], 16),
            int(text[5:7], 16),
        )
    except ValueError:
        return None


def _relative_luminance(value: Any) -> float:
    rgb = _hex_to_rgb(value)
    if rgb is None:
        return 1.0

    def _channel(component: int) -> float:
        normalized = component / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = (_channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: Any, background: Any) -> float:
    fg = _relative_luminance(foreground)
    bg = _relative_luminance(background)
    lighter = max(fg, bg)
    darker = min(fg, bg)
    return (lighter + 0.05) / (darker + 0.05)


def _accessible_preview_text_color(
    *,
    preferred: Any,
    background: Any,
    light_fallback: str,
    dark_fallback: str,
) -> str:
    preferred_hex = _color_or(preferred, "")
    background_hex = _color_or(background, "")
    if preferred_hex and background_hex and _contrast_ratio(preferred_hex, background_hex) >= 4.5:
        return preferred_hex
    if background_hex and _relative_luminance(background_hex) <= 0.18:
        return light_fallback
    return dark_fallback


def _preview_title(spec: str) -> str:
    for line in str(spec or "").splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:64]
    return "Lifecycle Product"


def _normalize_override_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


_DESIGN_PREVIEW_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bComplete guided onboarding\b", "初回設定を完了する"),
    (r"\bComplete the primary workflow\b", "主要タスクを完了する"),
    (r"\bComplete the 主要 workflow\b", "主要タスクを完了する"),
    (r"\bReview status and next action\b", "状態と次の操作を確認する"),
    (r"\bRecover previous work context\b", "前回の続きから再開する"),
    (r"\bFirst-run success\b", "初回設定から最初の成果まで"),
    (r"\bIn-product orientation\b", "利用中の状況確認"),
    (r"\bConfiguration\b", "設定を更新する"),
    (r"\bhistory and recovery\b", "履歴と復帰"),
    (r"\bguided onboarding\b", "初回設定"),
    (r"\bprimary workflow\b", "主要タスク"),
    (r"\bstatus visibility\b", "状態の見える化"),
    (r"\bOpen\s+(.+)", r"\1を開く"),
    (r"\bLifecycle Workspace\b", "ライフサイクルワークスペース"),
    (r"\bResearch Workspace\b", "調査ワークスペース"),
    (r"\bApproval Gate\b", "承認ゲート"),
    (r"\bArtifact Lineage\b", "成果物系譜"),
    (r"\bLineage Explorer\b", "リネージ探索"),
    (r"\bDecision Review\b", "判断レビュー"),
    (r"\bRun Ledger\b", "ラン台帳"),
    (r"\bRelease Readiness\b", "リリース準備"),
    (r"\bPhase Workspace\b", "フェーズワークスペース"),
    (r"\bCommand Deck\b", "判断デッキ"),
    (r"\bResearch Recovery\b", "調査復旧"),
    (r"\bRuns\b", "実行レーン"),
    (r"\bApprovals\b", "承認レビュー"),
    (r"\bArtifacts\b", "成果物系譜"),
    (r"\bOperator Shell\b", "オペレーターシェル"),
    (r"\bActive Screen\b", "アクティブ画面"),
    (r"\bPrimary Flow\b", "主要フロー"),
    (r"\bLayout\b", "レイアウト"),
    (r"\bPrototype Screens\b", "画面ストーリーボード"),
    (r"\bInteraction Principles\b", "操作原則"),
    (r"\bPrimary Flows\b", "主要フロー"),
    (r"\bMilestone Readiness\b", "マイルストーン準備"),
    (r"\bSystem Signals\b", "システムシグナル"),
    (r"\bPrimary work area for each phase\b", "各フェーズの主要作業面"),
    (r"\bReview runs and checkpoints\b", "ランとチェックポイントを確認する"),
    (r"\bReview approvals and handoff readiness\b", "承認レビューと引き継ぎ準備を確認する"),
    (r"\bReview approvals and release readiness\b", "承認とリリース準備を確認する"),
    (r"\bTrace\s+artifact\s+lineage\b", "成果物の系譜を追跡する"),
    (r"\bRun discovery-to-build workflow\b", "調査から実装準備までを進める"),
    (r"\bRecover degraded research lane\b", "劣化した調査レーンを復旧する"),
    (r"\bReview planning\b", "企画内容を確認する"),
    (r"\bStart research\b", "調査を開始する"),
    (r"\bSelect a design\b", "デザイン案を選ぶ"),
    (r"\bRun development\b", "開発準備へ進める"),
    (r"\bOpen primary workspace\b", "主要ワークスペースを開く"),
    (r"\bOpen the approval gate\b", "承認ゲートを開く"),
    (r"\bReview missing evidence and blockers\b", "不足根拠とブロッカーを確認する"),
    (r"\bChoose a recovery strategy\b", "復旧方針を選ぶ"),
    (r"\bRe-run only the affected lane\b", "影響したレーンだけ再実行する"),
    (r"\bIdea to approval\b", "構想から承認まで"),
    (r"\bLane recovery\b", "レーン復旧"),
    (r"\bBuild artifacts and phase history are recorded\b", "成果物とフェーズ履歴が記録される"),
    (r"\bThe recovery reason and delta are recorded\b", "復旧理由と差分が記録される"),
    (r"\bSelected design was generated from an older decision context\b", "選択中の案は古い判断文脈で生成されています"),
    (r"\bReview queue\b", "レビューキュー"),
    (r"\bDecision checklist\b", "判断チェックリスト"),
    (r"\bGovernance context\b", "統治コンテキスト"),
    (r"\bRun monitor\b", "ラン監視"),
    (r"\bCheckpoint lane\b", "復旧レーン"),
    (r"\bOperator notes\b", "運用メモ"),
    (r"\bDecision snapshot\b", "判断サマリー"),
    (r"\bWorkflow lane\b", "進行レーン"),
    (r"\bOperator context\b", "運用コンテキスト"),
    (r"\bEvidence-to-build loop\b", "根拠から実装への連鎖"),
    (r"\bGoverned delivery\b", "統制されたデリバリー"),
    (r"\bOperator-ready release\b", "オペレーターが扱えるリリース"),
    (r"\bTrace View\b", "追跡ビュー"),
    (r"\bTrace\b", "追跡"),
    (r"\bcommand-center\b", "コマンドセンター"),
    (r"\bdecision-studio\b", "判断スタジオ"),
    (r"\bcontrol-center\b", "コントロールセンター"),
    (r"\bsplit-review\b", "比較レビュー"),
    (r"\bsidebar\b", "サイドバー"),
    (r"\btop-nav\b", "トップナビ"),
    (r"\bhigh\b", "高"),
    (r"\bmedium\b", "中"),
    (r"\bbalanced\b", "標準"),
    (r"\btwo-column: 60% evidence brief \| 40% decision panel; single column on mobile\b", "2カラム: 根拠ブリーフ / 判断パネル。モバイルでは1カラム"),
    (r"\bsingle centered column \(max-width 800px\) with vertical timeline spine; full-width on mobile\b", "中央1カラム: 縦タイムライン軸。モバイルでは全幅"),
    (r"\bEvidence\s+Review\b", "根拠レビュー"),
    (r"\bEvidence\b", "根拠"),
    (r"\bPrimary Shell\b", "主要シェル"),
    (r"\bqueue\b", "キュー"),
    (r"\bchecklist\b", "チェックリスト"),
    (r"\bpacket\b", "パケット"),
    (r"\bsummary\b", "サマリー"),
    (r"\btimeline\b", "タイムライン"),
    (r"\bpanel\b", "パネル"),
    (r"\bgraph\b", "グラフ"),
    (r"\bform\b", "フォーム"),
    (r"\bstructure\b", "構成"),
    (r"\bPolicy update\b", "ポリシー更新"),
    (r"\bThe decision history is recorded\b", "判断履歴が記録される"),
    (r"\bThe evidence chain is explainable\b", "根拠のつながりを説明できる"),
    (r"\bthree-column: 240px rail \| flex center \| 320px context panel\b", "3カラム: 左レール / 主作業面 / 右コンテキスト"),
    (r"\btwo-panel: 55% run log \| 45% evidence accumulator, stacked on mobile\b", "2パネル: 実行ログ / 根拠蓄積面。モバイルでは縦積み"),
    (r"\bhigh-fidelity application shell with task flows\b", "主要フローを含む高精度プロダクトワークスペース"),
    (r"\bhigh-fidelity application shell with five primary screens and one degraded-state recovery flow\b", "主要5画面と復旧フローを含む高精度プロダクトワークスペース"),
    (r"\bartifact lineage\b", "成果物系譜"),
    (r"\bdevelopment\b", "開発"),
    (r"\bprimary\b", "主要"),
    (r"\bsecondary\b", "補助"),
    (r"\butility\b", "ユーティリティ"),
    (r"\bvisible copy\b", "画面文言"),
    (r"\bproduct workspace\b", "プロダクトワークスペース"),
    (r"\bartifact contract\b", "成果物契約"),
    (r"\btechnical choices\b", "技術判断"),
    (r"\bhandoff\b", "引き継ぎ"),
    (r"\bProduct Platform Lead\b", "プロダクト基盤責任者"),
    (r"\bEvidence-to-build loop\b", "根拠から実装への連鎖"),
    (r"\bGoverned delivery\b", "統制されたデリバリー"),
    (r"\bOperator-ready release\b", "運用可能なリリース"),
    (r"\bplanning synthesis\b", "企画シンセシス"),
    (r"\bworkspace\b", "ワークスペース"),
    (r"\bvisible UI\b", "画面上"),
)


_DESIGN_TEMPLATE_PREVIEW_VERSION = 9

_PREVIEW_INTERNAL_COPY_PATTERN = re.compile(
    r"(?:"
    r"(?:\b\d{2,4}px\b)|"
    r"(?:#[0-9a-f]{3,8})|"
    r"(?:grid-template-columns)|"
    r"(?:12-column)|"
    r"(?:phase-anchored)|"
    r"(?:icon nav)|"
    r"(?:context drawer)|"
    r"(?:main canvas)|"
    r"(?:slide-in)|"
    r"(?:diff highlighting)|"
    r"(?:mandatory rationale textarea)|"
    r"(?:character count)|"
    r"(?:cta[s]?)|"
    r"(?:svg)|"
    r"(?:dag)|"
    r"(?:virtuali[sz]ed)|"
    r"(?:crossfade)|"
    r"(?:barlow)|"
    r"(?:jetbrains)|"
    r"(?:color system)|"
    r"(?:typography)|"
    r"(?:aria-live)|"
    r"(?:operator shell)|"
    r"(?:product workspace)|"
    r"(?:artifact contract)|"
    r"(?:technical choices)|"
    r"(?:visible copy)|"
    r"(?:approval action surface)|"
    r"(?:phase nodes)|"
    r"(?:flush-right)|"
    r"(?:full-bleed)"
    r")",
    re.IGNORECASE,
)

_OPERATIONS_SCREEN_BLUEPRINTS: tuple[dict[str, Any], ...] = (
    {
        "ids": ("workspace", "research", "overview"),
        "keywords": ("workspace", "research", "phase workspace", "調査", "ワークスペース"),
        "title": "調査ワークスペース",
        "headline": "調査から実装準備までを一気通貫で進める",
        "purpose": "調査・企画・承認候補を同じ作業面で照合し、次に進むべき判断をすぐ決める。",
        "supporting_text": "構想から承認まで",
        "actions": ["調査ワークスペースを開く", "ライフサイクルワークスペースを確認する"],
        "modules": [
            {"name": "判断サマリー", "type": "summary", "items": ["次の一手", "保留理由", "承認候補"]},
            {"name": "進行レーン", "type": "timeline", "items": ["調査", "企画", "デザイン", "承認"]},
            {"name": "運用コンテキスト", "type": "summary", "items": ["判断責任者", "根拠の更新状況", "リリース準備"]},
        ],
        "success_state": "調査の根拠と次の一手が同じ画面でそろう",
    },
    {
        "ids": ("runs", "planning", "queue"),
        "keywords": ("runs", "planning synthesis", "run ledger", "計画", "ラン", "実行"),
        "title": "計画合成",
        "headline": "止まったレーンの原因を見極めて復旧する",
        "purpose": "停止したレーンの原因、影響範囲、復旧手順を並べ、必要な介入だけで再実行できるようにする。",
        "supporting_text": "実装準備からリリースまで",
        "actions": ["計画合成を開く", "復旧手順を確認する"],
        "modules": [
            {"name": "停止要因", "type": "summary", "items": ["失敗した条件", "影響したレーン", "優先度"]},
            {"name": "復旧レーン", "type": "timeline", "items": ["原因を確認する", "介入を選ぶ", "再実行する"]},
            {"name": "判断メモ", "type": "summary", "items": ["再試行余力", "残る懸念", "次の確認項目"]},
        ],
        "success_state": "復旧に必要な介入だけを迷わず選べる",
    },
    {
        "ids": ("approvals", "approval", "review"),
        "keywords": ("approval", "review", "承認", "判断レビュー"),
        "title": "承認ゲート",
        "headline": "承認するか差し戻すかを根拠付きで決める",
        "purpose": "承認理由、差し戻し条件、直近の変更点を同時に見比べ、決裁をその場で完了する。",
        "supporting_text": "構想から承認まで",
        "actions": ["承認ゲートを開く", "判断理由を記録する"],
        "modules": [
            {"name": "承認パケット", "type": "summary", "items": ["採用理由", "主要リスク", "次の一手"]},
            {"name": "判断チェックリスト", "type": "checklist", "items": ["根拠を確認する", "差し戻し条件を見る", "決裁する"]},
            {"name": "統治コンテキスト", "type": "summary", "items": ["監査証跡", "判断責任者", "リリース条件"]},
        ],
        "success_state": "承認判断と差し戻し条件を同じ面で確定できる",
    },
    {
        "ids": ("artifacts", "lineage", "history"),
        "keywords": ("artifact", "lineage", "history", "成果物", "系譜"),
        "title": "成果物系譜",
        "headline": "根拠から成果物までのつながりを追跡する",
        "purpose": "どの判断がどの成果物に反映されたかを遡り、差し戻しや再検証の影響をすぐ把握する。",
        "supporting_text": "構想から承認まで",
        "actions": ["成果物系譜を開く", "関連する判断を確認する"],
        "modules": [
            {"name": "根拠ソース", "type": "summary", "items": ["調査メモ", "企画判断", "承認履歴"]},
            {"name": "追跡経路", "type": "timeline", "items": ["調査", "企画", "デザイン", "承認"]},
            {"name": "参照レール", "type": "summary", "items": ["作成者", "更新時刻", "関連成果物"]},
        ],
        "success_state": "成果物の来歴と影響範囲をその場で説明できる",
    },
)

_OPERATIONS_SCREEN_BLUEPRINTS_IVORY: tuple[dict[str, Any], ...] = (
    {
        "ids": ("workspace", "research", "overview"),
        "keywords": ("workspace", "research", "phase workspace", "調査", "ワークスペース"),
        "title": "フェーズワークスペース",
        "headline": "判断の前提を静かに束ね、次の決裁へ進める",
        "purpose": "調査、企画、承認候補を落ち着いた余白で比較し、判断理由を保ったまま次の一手へ進む。",
        "supporting_text": "判断前提と差分を同じ視界で保つ",
        "actions": ["フェーズワークスペースを開く", "判断の前提を確認する"],
        "modules": [
            {"name": "判断カード", "type": "summary", "items": ["次に決めること", "保留理由", "承認候補"]},
            {"name": "進行の温度", "type": "timeline", "items": ["調査", "企画", "デザイン", "承認"]},
            {"name": "合意コンテキスト", "type": "summary", "items": ["判断責任者", "更新差分", "公開準備"]},
        ],
        "success_state": "判断前提と次の一手が穏やかな密度で揃う",
    },
    {
        "ids": ("runs", "planning", "queue"),
        "keywords": ("runs", "planning synthesis", "run ledger", "計画", "ラン", "実行"),
        "title": "ラン台帳",
        "headline": "止まった流れの差分を並べ、復旧方針を整流する",
        "purpose": "停止理由、影響範囲、復旧案を文脈ごと比較し、必要な介入だけを選べるようにする。",
        "supporting_text": "復旧方針を比較しながら選ぶ",
        "actions": ["ラン台帳を開く", "復旧方針を比較する"],
        "modules": [
            {"name": "停止差分", "type": "summary", "items": ["止まった条件", "影響レーン", "判断優先度"]},
            {"name": "復旧プラン", "type": "timeline", "items": ["原因を読む", "介入を選ぶ", "再実行する"]},
            {"name": "レビュー余白", "type": "summary", "items": ["再試行余力", "残る懸念", "次の確認点"]},
        ],
        "success_state": "復旧方針の比較と介入選択を落ち着いて完了できる",
    },
    {
        "ids": ("approvals", "approval", "review"),
        "keywords": ("approval", "review", "承認", "判断レビュー"),
        "title": "判断レビュー",
        "headline": "根拠を読み比べながら、承認条件を静かに固める",
        "purpose": "承認理由、差し戻し条件、直近の変更点を整った順序で見比べ、合意形成をその場で完了する。",
        "supporting_text": "根拠から決裁までを一連で確認する",
        "actions": ["判断レビューを開く", "判断理由を記録する"],
        "modules": [
            {"name": "承認サマリー", "type": "summary", "items": ["採用理由", "主要リスク", "次の判断"]},
            {"name": "比較チェック", "type": "checklist", "items": ["根拠を照合する", "差し戻し条件を見る", "決裁する"]},
            {"name": "統治ノート", "type": "summary", "items": ["監査証跡", "判断責任者", "公開条件"]},
        ],
        "success_state": "承認判断と差し戻し条件を穏やかな読解リズムで確定できる",
    },
    {
        "ids": ("artifacts", "lineage", "history"),
        "keywords": ("artifact", "lineage", "history", "成果物", "系譜"),
        "title": "系譜タイムライン",
        "headline": "判断から成果物までの反映順を時系列で追う",
        "purpose": "どの判断がどの成果物に反映されたかを時系列でたどり、差し戻しや再検証の影響をすぐ把握する。",
        "supporting_text": "変更の前後関係を同じ線で読む",
        "actions": ["系譜タイムラインを開く", "関連する判断を確認する"],
        "modules": [
            {"name": "根拠の出所", "type": "summary", "items": ["調査メモ", "企画判断", "承認履歴"]},
            {"name": "反映ライン", "type": "timeline", "items": ["調査", "企画", "デザイン", "承認"]},
            {"name": "参照ノート", "type": "summary", "items": ["作成者", "更新時刻", "関連成果物"]},
        ],
        "success_state": "判断の来歴と影響範囲を一本のタイムラインで説明できる",
    },
)


def _design_preview_text(value: Any) -> str:
    text = _normalize_override_text(value)
    if not text:
        return ""
    for pattern, replacement in _DESIGN_PREVIEW_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return (
        text
        .replace("画面上 に", "画面上に")
        .replace(" 根拠 が", " 根拠が")
        .replace("成果物リネージ", "成果物系譜")
        .replace("追跡 成果物の系譜", "成果物の系譜を追跡する")
        .replace("追跡 成果物系譜", "成果物の系譜を追跡する")
        .replace(" preview ", " プレビュー ")
        .replace(" handoff ", " 引き継ぎ ")
        .replace(" operator ", " 運用者 ")
        .replace("product workspace", "プロダクトワークスペース")
    )


def _contains_japanese_preview_text(text: str) -> bool:
    return any((("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")) for ch in text)


def _looks_english_heavy_preview_text(text: str) -> bool:
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    japanese_letters = sum(1 for ch in text if ("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff"))
    return ascii_letters >= 24 and ascii_letters > japanese_letters * 2


def _preview_copy_needs_rewrite(
    value: Any,
    *,
    max_length: int = 180,
) -> bool:
    text = _design_preview_text(value)
    if not text:
        return True
    lowered = text.lower()
    if _looks_like_placeholder_preview_copy(text):
        return True
    if _looks_english_heavy_preview_text(text):
        return True
    if len(text) > max_length:
        return True
    if _PREVIEW_INTERNAL_COPY_PATTERN.search(text):
        return True
    if text.count(":") >= 3 or text.count("→") >= 2:
        return True
    if any(marker in lowered for marker in ("left rail", "right tray", "main canvas", "full-bleed", "operator shell", "phase-anchored")):
        return True
    if any(marker in lowered for marker in ("degraded", "trace ", " lane", "evidence review", "artifact lineage", "run ledger")):
        return True
    return False


def _preview_copy_or_fallback(
    value: Any,
    *,
    fallback: str = "",
    max_length: int = 180,
) -> str:
    text = _design_preview_text(value)
    if not text:
        return fallback
    if fallback and _preview_copy_needs_rewrite(text, max_length=max_length):
        return fallback[:max_length]
    lowered = text.lower()
    if fallback and lowered.startswith(("the ", "and ", "with ", "without ")):
        return fallback
    if fallback and any(marker in lowered for marker in (" and ", " the ", " with ", " without ", "built on ", "operator shell")):
        return fallback
    if _looks_english_heavy_preview_text(text):
        return fallback or text[:max_length]
    if len(text) > max_length and fallback:
        return fallback
    return text[:max_length]


def _operations_screen_blueprint(*, screen_id: str, label: str, variant_style: str = "") -> dict[str, Any] | None:
    normalized_id = _normalize_override_text(screen_id).lower()
    normalized_label = _normalize_override_text(label).lower()
    blueprints = (
        _OPERATIONS_SCREEN_BLUEPRINTS_IVORY
        if str(variant_style or "").strip().lower() == "ivory-signal"
        else _OPERATIONS_SCREEN_BLUEPRINTS
    )
    for blueprint in blueprints:
        ids = {str(item).lower() for item in blueprint.get("ids", ())}
        keywords = tuple(str(item).lower() for item in blueprint.get("keywords", ()))
        if normalized_id and normalized_id in ids:
            return blueprint
        if normalized_label and any(keyword in normalized_label for keyword in keywords):
            return blueprint
    return None


def _preferred_operations_screen_label(*, screen_id: str, label: str, variant_style: str = "") -> str:
    blueprint = _operations_screen_blueprint(screen_id=screen_id, label=label, variant_style=variant_style)
    if blueprint:
        return str(blueprint.get("title") or _design_preview_text(label) or "主要画面")
    return _design_preview_text(label)


def _preview_subtitle_fallback(
    *,
    screens: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    features: list[str],
    variant_style: str = "",
) -> str:
    screen_ids = {str(_as_dict(item).get("id") or "").strip().lower() for item in screens}
    if screen_ids & {"workspace", "runs", "approvals", "artifacts", "lineage"}:
        if variant_style == "ivory-signal":
            return "根拠、差分、承認条件を静かな余白で比較し、合意形成の流れを切らさない設計。"
        return "調査、復旧、承認、成果物系譜を同じ制御面で往復し、判断文脈を切らさない設計。"
    flow_names = [
        _design_preview_text(item.get("name") or "")
        for item in flows[:2]
        if str(item.get("name") or "").strip()
    ]
    feature_names = [
        _design_preview_text(item)
        for item in features[:3]
        if str(item).strip()
    ]
    focus = " / ".join(flow_names[:2]) or "承認・差し戻し・系譜確認"
    support = " / ".join(feature_names[:2]) or "主要判断"
    return (
        f"{max(len(screens), 1)}画面を切り替えながら {focus} を同じワークスペースで扱い、"
        f"{support} の判断文脈を失わない設計。"
    )[:180]


def _preview_screen_purpose(screen: dict[str, Any]) -> str:
    screen_id = str(screen.get("id") or "").strip().lower()
    title = _design_preview_text(screen.get("title") or "主要画面")
    variant_style = str(screen.get("variant_style") or "").strip().lower()
    blueprint = _operations_screen_blueprint(screen_id=screen_id, label=title, variant_style=variant_style) or _screen_blueprint_for_label(title)
    fallback_by_id = {
        "workspace": "各フェーズの主要作業面",
        "run": "各フェーズの主要作業面",
        "overview": "各フェーズの主要作業面",
        "research": "ランとチェックポイントを確認する",
        "queue": "ランとチェックポイントを確認する",
        "approval": "保留中の承認と差し戻し履歴を確認する",
        "review": "保留中の承認と差し戻し履歴を確認する",
        "lineage": "フェーズ成果物と系譜を確認する",
        "artifacts": "フェーズ成果物と系譜を確認する",
        "settings": "ポリシーと通知条件を調整する",
    }
    fallback = str(_as_dict(blueprint).get("purpose") or fallback_by_id.get(screen_id) or f"{title}で必要な判断を1画面で完了する")
    return _preview_copy_or_fallback(screen.get("purpose"), fallback=fallback, max_length=72)


def _preview_primary_action(action: Any, *, screen: dict[str, Any]) -> str:
    screen_id = str(screen.get("id") or "").strip().lower()
    title = _design_preview_text(screen.get("title") or "主要画面")
    variant_style = str(screen.get("variant_style") or "").strip().lower()
    blueprint = _operations_screen_blueprint(screen_id=screen_id, label=title, variant_style=variant_style) or _screen_blueprint_for_label(title)
    fallback_by_id = {
        "workspace": "実行台を開く",
        "run": "実行台を開く",
        "overview": "実行台を開く",
        "research": "劣化レーンを開く",
        "queue": "劣化レーンを開く",
        "approval": "承認ゲートを開く",
        "review": "承認ゲートを開く",
        "lineage": "成果物を開く",
        "artifacts": "成果物を開く",
        "settings": "設定を開く",
    }
    blueprint_actions = [str(item) for item in _as_list(_as_dict(blueprint).get("actions")) if str(item).strip()]
    fallback = blueprint_actions[0] if blueprint_actions else fallback_by_id.get(screen_id, f"{title}を開く")
    candidate = _preview_copy_or_fallback(action, fallback=fallback, max_length=48)
    if not candidate:
        return fallback
    if not re.search(r"(する|開く|確認|記録|選ぶ|進める|保存|更新|追加|作成|再実行|比較|戻る|承認|差し戻し|登録|送る)", candidate):
        return fallback
    return candidate


def _default_operations_interaction_principles() -> list[str]:
    return [
        "次の一手は主要作業面の近くに置き、判断と操作を行き来しやすくする。",
        "差し戻しや復旧の理由は、別画面に逃がさずその場で説明できるようにする。",
        "根拠、承認、成果物系譜を同じ流れで追え、担当者が迷わない状態を保つ。",
        "モバイルでは要約を先に見せ、詳細と操作は段階的に開けるようにする。",
    ]


def _interaction_principles_need_product_copy(values: list[str]) -> bool:
    if not values:
        return True
    generic_count = 0
    for item in values:
        text = _normalize_override_text(item)
        if (
            _preview_copy_needs_rewrite(text, max_length=96)
            or re.search(r"\d+ms|px\b|grid|drawer|overlay|clickable|crossfade|トレイ|ドロワー|クリッカブル|クロスフェード", text, re.IGNORECASE)
        ):
            generic_count += 1
    return generic_count >= max(1, math.ceil(len(values) / 2))


_GENERIC_PREVIEW_MARKERS = (
    "guided onboarding",
    "primary workflow",
    "status visibility",
    "history and recovery",
    "complete guided onboarding",
    "complete the primary workflow",
    "complete the 主要 workflow",
    "review status and next action",
    "recover previous work context",
    "first-run success",
    "in-product orientation",
    "configuration",
    "primary tasks",
    "task flow",
    "support context",
    "primary user",
)


_CONSUMER_SCREEN_BLUEPRINTS: tuple[dict[str, Any], ...] = (
    {
        "keywords": ("献立", "メニュー", "meal", "menu"),
        "headline": "3日分の献立を素早く決める",
        "purpose": "家族の好み、在庫、調理時間を踏まえて、今日から数日分の候補を迷わず確定する。",
        "supporting_text": "候補の比較、差し替え、買い物準備までをひとつの面で完了させる。",
        "actions": ["献立を生成する", "候補を差し替える", "買い物リストへ送る"],
        "modules": [
            {"name": "今日の候補", "type": "summary", "items": ["3日分のおすすめ", "時間と予算のバランス", "アレルギー配慮"]},
            {"name": "判断フロー", "type": "timeline", "items": ["候補を比較する", "夕食を確定する", "必要食材を確認する"]},
            {"name": "確認ポイント", "type": "summary", "items": ["家族の好み", "在庫の使い切り", "調理負荷"]},
        ],
        "success_state": "3日分の献立が迷わず決まる",
    },
    {
        "keywords": ("在庫", "冷蔵庫", "inventory", "stock"),
        "headline": "冷蔵庫の在庫をすばやく登録する",
        "purpose": "写真、音声、手入力を使い分けながら、食材の状態を最短で更新する。",
        "supporting_text": "入力の負担を抑えつつ、賞味期限と不足食材を次の提案に反映する。",
        "actions": ["写真で登録する", "手入力で補正する", "在庫を保存する"],
        "modules": [
            {"name": "登録対象", "type": "summary", "items": ["冷蔵庫の食材", "冷凍ストック", "賞味期限が近い食材"]},
            {"name": "入力モード", "type": "timeline", "items": ["写真で読み取る", "音声で追加する", "手入力で修正する"]},
            {"name": "精度チェック", "type": "summary", "items": ["認識漏れを確認", "数量を調整", "献立提案へ反映"]},
        ],
        "success_state": "在庫の状態が次の献立提案に反映される",
    },
    {
        "keywords": ("買い物", "shopping", "list"),
        "headline": "不足食材だけを買い物リストにまとめる",
        "purpose": "献立に必要な食材だけを抽出し、店内で迷わない順番で並べる。",
        "supporting_text": "在庫との差分、カテゴリ、チェック状況を一つの視点で確認できるようにする。",
        "actions": ["不足分を確認する", "カテゴリ順に並べる", "購入済みにする"],
        "modules": [
            {"name": "不足食材", "type": "summary", "items": ["今日の不足分", "まとめ買い候補", "特売活用"]},
            {"name": "買い回り順", "type": "timeline", "items": ["野菜", "肉・魚", "日配", "乾物"]},
            {"name": "再利用候補", "type": "summary", "items": ["在庫から代替する", "残り物を使う", "次回へ繰り越す"]},
        ],
        "success_state": "必要な食材だけを漏れなく買える",
    },
    {
        "keywords": ("家族", "プロフィール", "profile", "preference"),
        "headline": "家族の好みと制約を登録する",
        "purpose": "好き嫌い、アレルギー、量、辛さなどの条件を更新して提案精度を上げる。",
        "supporting_text": "家族ごとの差分を保ったまま、次回の献立提案にすぐ反映できるようにする。",
        "actions": ["家族を追加する", "制約を更新する", "提案条件を保存する"],
        "modules": [
            {"name": "家族プロフィール", "type": "summary", "items": ["好き嫌い", "アレルギー", "量の好み"]},
            {"name": "制約更新", "type": "timeline", "items": ["家族を選ぶ", "条件を編集する", "保存して反映する"]},
            {"name": "提案ルール", "type": "summary", "items": ["幼児向け可否", "辛さ", "栄養バランス"]},
        ],
        "success_state": "家族ごとの条件が提案に正しく反映される",
    },
    {
        "keywords": ("履歴", "history", "recovery"),
        "headline": "前回の献立と反応を振り返る",
        "purpose": "過去の献立、家族の反応、差し替え履歴を見返して次回の判断に活かす。",
        "supporting_text": "よく使う献立や好評だった組み合わせをすぐ再利用できるようにする。",
        "actions": ["前回の献立を見る", "反応を確認する", "再利用する"],
        "modules": [
            {"name": "最近の献立", "type": "summary", "items": ["先週の人気メニュー", "差し替え履歴", "作成メモ"]},
            {"name": "振り返り", "type": "timeline", "items": ["献立を開く", "家族評価を見る", "次回へ反映する"]},
            {"name": "再利用候補", "type": "summary", "items": ["時短献立", "食材使い切り", "よく作る組み合わせ"]},
        ],
        "success_state": "前回の文脈を引き継いで次の献立に進める",
    },
    {
        "keywords": ("設定", "notification", "settings", "preference"),
        "headline": "通知と基本設定を整える",
        "purpose": "献立の提案タイミングやリマインド、家族共有の基本ルールを調整する。",
        "supporting_text": "次の利用時に迷わないよう、通知と既定値を先に整えておく。",
        "actions": ["通知を切り替える", "基本設定を更新する", "変更を保存する"],
        "modules": [
            {"name": "通知設定", "type": "summary", "items": ["夕方の提案通知", "買い物前リマインド", "家族共有通知"]},
            {"name": "変更フロー", "type": "timeline", "items": ["設定を選ぶ", "値を更新する", "保存して反映する"]},
            {"name": "既定ルール", "type": "summary", "items": ["調理時間", "予算", "通知頻度"]},
        ],
        "success_state": "次回から同じ設定で迷わず使い始められる",
    },
    {
        "keywords": ("状態", "status", "progress"),
        "headline": "今の準備状況と次の一手を確認する",
        "purpose": "献立決定、買い物準備、在庫更新のどこまで進んだかをひと目で把握する。",
        "supporting_text": "止まっている箇所を見つけて、次に取るべき操作へすぐ戻れるようにする。",
        "actions": ["進行状況を見る", "次の操作へ進む", "未完了を確認する"],
        "modules": [
            {"name": "進行状況", "type": "summary", "items": ["献立決定", "買い物準備", "在庫更新"]},
            {"name": "次の一手", "type": "timeline", "items": ["未完了を確認する", "必要な操作を選ぶ", "続きから再開する"]},
            {"name": "気になる項目", "type": "summary", "items": ["不足食材", "家族制約", "賞味期限"]},
        ],
        "success_state": "今どこまで進んだかと次の操作がすぐ分かる",
    },
)


def _first_preview_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("title", "name", "label", "description", "text", "value"):
            candidate = _first_preview_text(value.get(key))
            if candidate:
                return candidate
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidate = _first_preview_text(item)
            if candidate:
                return candidate
        return ""
    return _normalize_override_text(value).strip("'\"")


def _looks_like_placeholder_preview_copy(value: Any) -> bool:
    text = _normalize_override_text(value).lower()
    if not text:
        return False
    return any(marker in text for marker in _GENERIC_PREVIEW_MARKERS)


def _looks_like_component_token(value: Any) -> bool:
    text = _normalize_override_text(value)
    if not text:
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{4,}", text))


def _normalize_preview_action(value: Any, *, fallback_label: str) -> str:
    text = _normalize_override_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("open "):
        target = text[5:].strip() or fallback_label
        return f"{target}を開く"
    return _design_preview_text(text)


def _screen_blueprint_for_label(label: str) -> dict[str, Any] | None:
    lowered = _normalize_override_text(label).lower()
    if not lowered:
        return None
    for blueprint in _CONSUMER_SCREEN_BLUEPRINTS:
        if any(keyword.lower() in lowered for keyword in blueprint["keywords"]):
            return blueprint
    return None


def _screen_modules_need_product_copy(modules: list[dict[str, Any]]) -> bool:
    if not modules:
        return True
    generic_count = 0
    for module in modules:
        payload = _as_dict(module)
        texts = [
            payload.get("name"),
            payload.get("type"),
            *_as_list(payload.get("items"))[:3],
        ]
        if any(
            _looks_like_placeholder_preview_copy(item)
            or _preview_copy_needs_rewrite(item, max_length=96)
            or _looks_like_component_token(item)
            for item in texts
        ):
            generic_count += 1
    return generic_count >= max(1, math.ceil(len(modules) / 2))


def _actions_need_product_copy(actions: list[str], *, label: str) -> bool:
    if not actions:
        return True
    label_open = f"{_design_preview_text(label) or label}を開く"
    generic_actions = {
        "ホーム",
        "ホームを開く",
        "主要導線",
        "主要タスクを開始する",
        "結果",
        "結果を確認する",
        "設定",
        "設定を開く",
        "履歴",
        "履歴を開く",
        "状態",
        "次アクション",
        "前回の続きから再開する",
        "状態と次の操作を確認する",
    }
    for action in actions:
        if not action:
            continue
        if action == label_open:
            continue
        if action in generic_actions:
            continue
        if _looks_like_placeholder_preview_copy(action):
            continue
        if _preview_copy_needs_rewrite(action, max_length=48):
            continue
        return False
    return True


def _default_generic_headline(label: str) -> str:
    normalized = _design_preview_text(label)
    if not normalized:
        return "主要タスクを進める"
    return f"{normalized}で主要タスクを進める"


def _default_generic_purpose(label: str, description: str) -> str:
    normalized_label = _design_preview_text(label)
    normalized_description = _design_preview_text(description)
    if normalized_description:
        return normalized_description
    if normalized_label:
        return f"{normalized_label}に必要な判断と操作をひとつの面で扱う。"
    return "主要タスクに必要な判断と操作をひとつの面で扱う。"


def _screen_copy_for_context(
    *,
    screen_id: str,
    label: str,
    variant_style: str,
    description: str,
    use_case: dict[str, Any],
    key_path: dict[str, Any],
    modules: list[dict[str, Any]],
    fallback_actions: list[str],
) -> dict[str, Any]:
    blueprint = _operations_screen_blueprint(screen_id=screen_id, label=label, variant_style=variant_style) or _screen_blueprint_for_label(label)
    use_case_payload = _as_dict(use_case)
    key_path_payload = _as_dict(key_path)

    headline = _first_preview_text(use_case_payload.get("title"))
    if not headline or _looks_like_placeholder_preview_copy(headline) or _preview_copy_needs_rewrite(headline, max_length=80):
        headline = str(blueprint.get("headline")) if blueprint else _default_generic_headline(label)

    purpose = _first_preview_text(description or use_case_payload.get("goal") or use_case_payload.get("category"))
    if not purpose or _looks_like_placeholder_preview_copy(purpose) or _preview_copy_needs_rewrite(purpose, max_length=120):
        purpose = str(blueprint.get("purpose")) if blueprint else _default_generic_purpose(label, description)

    supporting_text = _first_preview_text(key_path_payload.get("name") or use_case_payload.get("sub_category"))
    if not supporting_text or _looks_like_placeholder_preview_copy(supporting_text) or _preview_copy_needs_rewrite(supporting_text, max_length=64):
        supporting_text = str(blueprint.get("supporting_text")) if blueprint else (
            f"{_design_preview_text(label) or 'この画面'}から次の操作へ迷わず進めるようにする。"
        )

    primary_actions = [
        action
        for action in (
            _normalize_preview_action(item, fallback_label=label)
            for item in fallback_actions
        )
        if action
    ]
    if blueprint and _actions_need_product_copy(primary_actions, label=label):
        primary_actions = [str(item) for item in blueprint["actions"]]
    if not primary_actions:
        primary_actions = (
            [str(item) for item in blueprint["actions"]]
            if blueprint
            else [f"{_design_preview_text(label) or '画面'}を開く"]
        )

    success_state = _first_preview_text(
        use_case_payload.get("postconditions")
        or key_path_payload.get("goal")
    )
    if not success_state or _looks_like_placeholder_preview_copy(success_state) or _preview_copy_needs_rewrite(success_state, max_length=72):
        success_state = str(blueprint.get("success_state")) if blueprint else (
            f"{_design_preview_text(label) or 'この画面'}で次の操作が迷わず決まる"
        )

    resolved_modules = modules
    if blueprint and _screen_modules_need_product_copy(modules):
        resolved_modules = [dict(item) for item in blueprint["modules"]]

    return {
        "headline": headline,
        "purpose": purpose,
        "supporting_text": supporting_text,
        "primary_actions": primary_actions,
        "modules": resolved_modules,
        "success_state": success_state,
    }


def _flow_name_for_context(index: int, raw_name: Any, screens: list[dict[str, Any]]) -> str:
    name = _first_preview_text(raw_name)
    if name and not _looks_like_placeholder_preview_copy(name):
        return name
    screen = _as_dict(screens[min(index, len(screens) - 1)]) if screens else {}
    screen_title = _design_preview_text(screen.get("title") or "")
    if not screen_title:
        return f"主要フロー {index + 1}"
    if index == 0:
        return f"{screen_title}の初回導線"
    if index == 1:
        return f"{screen_title}の主要操作"
    return f"{screen_title}の更新フロー"


def _parse_loose_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    text = _normalize_override_text(value)
    if not text or text[0] not in "{[":
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            payload = parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def _normalize_enum_value(value: Any, *, exact: dict[str, str], keywords: list[tuple[str, str]]) -> str:
    text = _normalize_override_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in exact:
        return exact[lowered]
    for needle, normalized in keywords:
        if needle in lowered:
            return normalized
    return ""


def _normalize_prototype_kind(value: Any) -> str:
    return _normalize_enum_value(
        value,
        exact={
            "control-center": "control-center",
            "decision-studio": "decision-studio",
            "storefront": "storefront",
            "guided-product": "guided-product",
            "product-workspace": "product-workspace",
        },
        keywords=[
            ("control", "control-center"),
            ("operator", "control-center"),
            ("approval", "control-center"),
            ("decision", "decision-studio"),
            ("studio", "decision-studio"),
            ("gallery", "decision-studio"),
            ("store", "storefront"),
            ("catalog", "storefront"),
            ("checkout", "storefront"),
            ("lesson", "guided-product"),
            ("learning", "guided-product"),
            ("workspace", "product-workspace"),
            ("shell", "product-workspace"),
            ("application", "product-workspace"),
        ],
    )


def _normalize_navigation_style(value: Any) -> str:
    return _normalize_enum_value(
        value,
        exact={"sidebar": "sidebar", "top-nav": "top-nav"},
        keywords=[
            ("left rail", "sidebar"),
            ("sidebar", "sidebar"),
            ("side rail", "sidebar"),
            ("persistent left", "sidebar"),
            ("hub-and-spoke", "sidebar"),
            ("drawer", "sidebar"),
            ("top-nav", "top-nav"),
            ("top nav", "top-nav"),
            ("top bar", "top-nav"),
            ("horizontal nav", "top-nav"),
            ("horizontal", "top-nav"),
            ("masthead", "top-nav"),
        ],
    )


def _normalize_density(value: Any) -> str:
    text = _normalize_override_text(value).lower()
    if not text:
        return ""
    if "medium-high" in text or "high" in text or "dense" in text:
        return "high"
    if "medium" in text:
        return "medium"
    if "low" in text or "airy" in text or "spacious" in text:
        return "low"
    return ""


def _normalize_visual_style(value: Any) -> str:
    return _normalize_enum_value(
        value,
        exact={
            "obsidian-atelier": "obsidian-atelier",
            "ivory-signal": "ivory-signal",
            "balanced-product": "balanced-product",
        },
        keywords=[
            ("obsidian", "obsidian-atelier"),
            ("control room", "obsidian-atelier"),
            ("architectural dark", "obsidian-atelier"),
            ("dark shell", "obsidian-atelier"),
            ("ivory", "ivory-signal"),
            ("luminous", "ivory-signal"),
            ("gallery", "ivory-signal"),
            ("editorial", "ivory-signal"),
            ("balanced", "balanced-product"),
            ("neutral", "balanced-product"),
        ],
    )


def _normalize_font_choice(value: Any) -> str:
    text = _normalize_override_text(value).strip("'\"")
    if not text:
        return ""
    if len(text) > 48:
        head = text.split(",", 1)[0].strip()
        return head if 1 < len(head) <= 36 else ""
    if any(marker in text.lower() for marker in ("layout", "component", "background", "#", "button")):
        return ""
    return text


def _normalize_screen_label(value: Any) -> str:
    mapping = _parse_loose_mapping(value)
    if mapping:
        value = (
            mapping.get("label")
            or mapping.get("title")
            or mapping.get("name")
            or mapping.get("screen")
            or mapping.get("id")
            or ""
        )
    text = _normalize_override_text(value).strip("'\"")
    if not text or any(marker in text for marker in ("'description':", '"description":', "'components':", '"components":')):
        return ""
    if len(text) > 64:
        for separator in (" — ", ": ", " | ", ". "):
            head = text.split(separator, 1)[0].strip()
            if 3 <= len(head) <= 48:
                return head
        return text[:56].rstrip(" -:")
    return text


def _normalize_interaction_principle(value: Any) -> str:
    text = _normalize_override_text(value)
    if not text or len(text) > 180:
        return ""
    if any(marker in text for marker in ("'components':", '"components":', "'layout':", '"layout":')):
        return ""
    return text


def _prototype_overrides_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "prototype_kind": _normalize_prototype_kind(payload.get("prototype_kind") or payload.get("prototypeKind")),
        "navigation_style": _normalize_navigation_style(payload.get("navigation_style") or payload.get("navigationStyle")),
        "density": _normalize_density(payload.get("density")),
        "visual_style": _normalize_visual_style(payload.get("visual_style") or payload.get("visualStyle")),
        "display_font": _normalize_font_choice(payload.get("display_font") or payload.get("displayFont")),
        "body_font": _normalize_font_choice(payload.get("body_font") or payload.get("bodyFont")),
        "screen_labels": [
            label
            for item in _as_list(payload.get("screen_labels") or payload.get("screenLabels"))
            if (label := _normalize_screen_label(item))
        ],
        "interaction_principles": [
            principle
            for item in _as_list(payload.get("interaction_principles") or payload.get("interactionPrinciples"))
            if (principle := _normalize_interaction_principle(item))
        ],
    }


def _merge_prototype_overrides(
    base: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in _as_dict(incoming).items():
        if isinstance(value, list):
            if value:
                merged[key] = value
            continue
        if isinstance(value, str):
            if value.strip():
                merged[key] = value.strip()
            continue
        if value not in (None, "", {}):
            merged[key] = value
    return merged


def _default_site_map_for_context(kind: str, variant_style: str = "") -> list[dict[str, str]]:
    if kind == "learning":
        return [
            {"id": "home", "label": "ホーム", "priority": "primary"},
            {"id": "lessons", "label": "レッスン", "priority": "primary"},
            {"id": "progress", "label": "進捗", "priority": "primary"},
            {"id": "guardian", "label": "保護者設定", "priority": "secondary"},
        ]
    if kind == "commerce":
        return [
            {"id": "catalog", "label": "商品一覧", "priority": "primary"},
            {"id": "product", "label": "商品詳細", "priority": "primary"},
            {"id": "checkout", "label": "チェックアウト", "priority": "primary"},
            {"id": "ops", "label": "運営管理", "priority": "secondary"},
        ]
    if kind == "operations":
        if variant_style == "ivory-signal":
            return [
                {"id": "workspace", "label": "フェーズワークスペース", "priority": "primary"},
                {"id": "runs", "label": "ラン台帳", "priority": "primary"},
                {"id": "approvals", "label": "判断レビュー", "priority": "primary"},
                {"id": "artifacts", "label": "系譜タイムライン", "priority": "secondary"},
            ]
        return [
            {"id": "workspace", "label": "ライフサイクルワークスペース", "priority": "primary"},
            {"id": "runs", "label": "実行レーン", "priority": "primary"},
            {"id": "approvals", "label": "承認レビュー", "priority": "primary"},
            {"id": "artifacts", "label": "成果物系譜", "priority": "secondary"},
        ]
    return [
        {"id": "home", "label": "ホーム", "priority": "primary"},
        {"id": "workflow", "label": "主要導線", "priority": "primary"},
        {"id": "history", "label": "履歴", "priority": "secondary"},
        {"id": "settings", "label": "設定", "priority": "utility"},
    ]


def _default_key_paths_for_context(kind: str, variant_style: str = "") -> list[dict[str, Any]]:
    if kind == "learning":
        return [
            {"name": "Daily lesson loop", "steps": ["ホーム", "今日の課題", "結果", "報酬"]},
            {"name": "Guardian review", "steps": ["進捗", "学習サマリー", "目標設定"]},
        ]
    if kind == "commerce":
        return [
            {"name": "Browse to buy", "steps": ["商品一覧", "商品詳細", "チェックアウト", "注文確認"]},
            {"name": "Inventory mitigation", "steps": ["運営管理", "在庫一覧", "補充判断"]},
        ]
    if kind == "operations":
        if variant_style == "ivory-signal":
            return [
                {"name": "判断前提をそろえる", "steps": ["フェーズワークスペース", "ラン台帳", "判断レビュー", "決裁"]},
                {"name": "レビューから反映準備まで", "steps": ["判断レビュー", "系譜タイムライン", "公開準備", "反映"]},
            ]
        return [
            {"name": "構想から承認まで", "steps": ["ライフサイクルワークスペース", "調査", "企画", "承認"]},
            {"name": "実装準備からリリースまで", "steps": ["開発準備", "実行レーン", "リリース確認", "反映"]},
        ]
    return [
        {"name": "First-run success", "steps": ["ホーム", "主要導線", "結果"]},
        {"name": "Configuration", "steps": ["設定", "保存"]},
    ]


def _shell_layout_for_kind(kind: str) -> str:
    if kind == "commerce":
        return "top-nav"
    return "sidebar"


def _screen_layout_for_kind(kind: str, *, index: int) -> str:
    if kind == "operations":
        return "command-center" if index == 0 else "split-review"
    if kind == "commerce":
        return "catalog-grid" if index == 0 else "decision-panel"
    if kind == "learning":
        return "guided-lesson" if index == 0 else "progress-console"
    return "product-workspace" if index == 0 else "detail-canvas"


def _screen_modules_for_context(
    *,
    kind: str,
    screen_id: str,
    label: str,
    variant_style: str,
    features: list[str],
    use_case: dict[str, Any],
    key_path: dict[str, Any],
    personas: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lowered = label.lower()
    role = str((_as_dict(personas[0]).get("role") if personas else "") or (_as_dict(personas[0]).get("name") if personas else "") or "Primary user")
    flow_steps = [str(item) for item in _as_list(use_case.get("main_flow")) if str(item).strip()] or [
        str(item) for item in _as_list(key_path.get("steps")) if str(item).strip()
    ]
    related = [str(item) for item in _as_list(use_case.get("related_stories")) if str(item).strip()] or features[:3]
    milestone_names = [
        str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
        for item in milestones[:3]
        if str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
    ]
    operations_blueprint = _operations_screen_blueprint(screen_id=screen_id, label=label, variant_style=variant_style)
    if kind == "operations" and operations_blueprint:
        return [dict(item) for item in _as_list(operations_blueprint.get("modules")) if isinstance(item, dict)]

    if "approval" in lowered or "承認" in lowered:
        return [
            {"name": "レビューキュー", "type": "queue", "items": related[:3] or ["承認パケット", "差し戻し依頼", "判断メモ"]},
            {"name": "判断チェックリスト", "type": "checklist", "items": flow_steps[:4] or ["根拠を確認する", "リスクを確認する", "承認するか差し戻す"]},
            {"name": "統治コンテキスト", "type": "summary", "items": milestone_names[:3] or ["ポリシー充足", "監査証跡", "判断責任者"]},
        ]
    if "run" in lowered or "telemetry" in lowered or "実行" in lowered:
        return [
            {"name": "ラン監視", "type": "timeline", "items": related[:3] or ["稼働中ラン", "停止ノード", "次の一手"]},
            {"name": "復旧レーン", "type": "timeline", "items": flow_steps[:4] or ["待機中", "進行中", "レビュー", "反映済み"]},
            {"name": "運用メモ", "type": "summary", "items": milestone_names[:3] or ["要対応事項", "再試行余力", "引き継ぎ明快さ"]},
        ]
    if "artifact" in lowered or "履歴" in lowered or "lineage" in lowered:
        return [
            {"name": "リネージ探索", "type": "graph", "items": related[:3] or ["根拠ソース", "判断ログ", "ビルド成果物"]},
            {"name": "追跡経路", "type": "timeline", "items": flow_steps[:4] or ["調査", "企画", "デザイン", "開発準備"]},
            {"name": "参照レール", "type": "summary", "items": milestone_names[:3] or ["担当者", "記録時刻", "書き出し"]},
        ]
    if "setting" in lowered or "設定" in lowered:
        return [
            {"name": "Policy groups", "type": "form", "items": related[:3] or ["Notifications", "Permissions", "Automation"]},
            {"name": "Change flow", "type": "timeline", "items": flow_steps[:4] or ["Edit", "Review", "Apply"]},
            {"name": "Safety defaults", "type": "summary", "items": milestone_names[:3] or ["Fallback", "Rollback", "Retention"]},
        ]
    if kind == "commerce":
        return [
            {"name": "Decision shelf", "type": "cards", "items": related[:3] or ["Top picks", "Trust signals", "Saved items"]},
            {"name": "Purchase flow", "type": "timeline", "items": flow_steps[:4] or ["Compare", "Detail", "Checkout", "Confirm"]},
            {"name": "Operator insight", "type": "summary", "items": [role, *(milestone_names[:2] or ["Stock risk", "Order state"])]},
        ]
    if kind == "learning":
        return [
            {"name": "Progress snapshot", "type": "summary", "items": related[:3] or ["Today's lesson", "Streak", "Reward"]},
            {"name": "Learning loop", "type": "timeline", "items": flow_steps[:4] or ["Start", "Practice", "Result", "Celebrate"]},
            {"name": "Guardian support", "type": "summary", "items": [role, *(milestone_names[:2] or ["Goal check", "Next recommendation"])]},
        ]
    if kind == "operations":
        return [
            {"name": "判断サマリー", "type": "summary", "items": related[:3] or ["次の一手", "停止フェーズ", "承認状態"]},
            {"name": "進行レーン", "type": "timeline", "items": flow_steps[:4] or ["調査", "企画", "デザイン", "開発準備"]},
            {"name": "運用コンテキスト", "type": "summary", "items": [role, *(milestone_names[:2] or ["リスク台帳", "リリース判断シグナル"])]},
        ]
    return [
        {"name": "Primary tasks", "type": "summary", "items": related[:3] or ["Core workflow", "Status", "Recovery"]},
        {"name": "Task flow", "type": "timeline", "items": flow_steps[:4] or ["Open", "Act", "Review"]},
        {"name": "Support context", "type": "summary", "items": [role, *(milestone_names[:2] or ["Help", "Settings"])]},
    ]


def _build_design_prototype(
    *,
    spec: str,
    analysis: dict[str, Any],
    selected_features: list[str],
    pattern_name: str,
    description: str,
    prototype_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = _infer_product_kind(spec)
    overrides = _prototype_overrides_from_payload(prototype_overrides or {})
    visual_style = str(overrides.get("visual_style") or ("obsidian-atelier" if kind == "operations" else "balanced-product"))
    ia_analysis = _as_dict(analysis.get("ia_analysis"))
    personas = [dict(item) for item in _as_list(analysis.get("personas")) if isinstance(item, dict)]
    use_cases = [dict(item) for item in _as_list(analysis.get("use_cases")) if isinstance(item, dict)]
    key_paths = [dict(item) for item in _as_list(ia_analysis.get("key_paths")) if isinstance(item, dict)] or _default_key_paths_for_context(kind, visual_style)
    site_map = [dict(item) for item in _as_list(ia_analysis.get("site_map")) if isinstance(item, dict)] or _default_site_map_for_context(kind, visual_style)
    design_tokens = _as_dict(analysis.get("design_tokens")) or _base_design_tokens(spec)
    milestones = [dict(item) for item in _as_list(analysis.get("recommended_milestones")) if isinstance(item, dict)]
    if not milestones:
        milestones = [dict(item) for item in _as_list(analysis.get("milestones")) if isinstance(item, dict)]
    screen_labels = [label for label in overrides.get("screen_labels", []) if label]

    screens: list[dict[str, Any]] = []
    for index, raw in enumerate(site_map[:4]):
        node = _as_dict(raw)
        raw_label = screen_labels[index] if index < len(screen_labels) else str(node.get("label") or node.get("id") or f"Screen {index + 1}")
        screen_id = str(node.get("id") or _slug(raw_label, prefix="screen"))
        label = (
            _preferred_operations_screen_label(screen_id=screen_id, label=raw_label, variant_style=visual_style)
            if kind == "operations"
            else raw_label
        )
        use_case = use_cases[index] if index < len(use_cases) else (use_cases[0] if use_cases else {})
        key_path = key_paths[index] if index < len(key_paths) else (key_paths[0] if key_paths else {})
        modules = _screen_modules_for_context(
            kind=kind,
            screen_id=screen_id,
            label=label,
            variant_style=visual_style,
            features=selected_features,
            use_case=_as_dict(use_case),
            key_path=_as_dict(key_path),
            personas=personas,
            milestones=milestones,
        )
        fallback_actions = _dedupe_strings(
            [
                *(str(item) for item in _as_list(_as_dict(use_case).get("main_flow"))[:2]),
                f"Open {label}",
                *(str(item) for item in _as_list(_as_dict(key_path).get("steps"))[:1]),
            ]
        )[:3]
        screen_copy = _screen_copy_for_context(
            screen_id=screen_id,
            label=label,
            variant_style=visual_style,
            description=str(node.get("description") or description),
            use_case=_as_dict(use_case),
            key_path=_as_dict(key_path),
            modules=modules,
            fallback_actions=fallback_actions,
        )
        screens.append(
            {
                "id": screen_id,
                "title": label,
                "purpose": screen_copy["purpose"],
                "layout": _screen_layout_for_kind(kind, index=index),
                "headline": screen_copy["headline"],
                "supporting_text": screen_copy["supporting_text"],
                "primary_actions": screen_copy["primary_actions"],
                "modules": screen_copy["modules"],
                "success_state": screen_copy["success_state"],
                "variant_style": visual_style,
            }
        )

    flows = []
    for index, raw in enumerate(key_paths[:3]):
        path = _as_dict(raw)
        steps = [str(item) for item in _as_list(path.get("steps")) if str(item).strip()]
        if not steps:
            continue
        flows.append(
            {
                "id": f"flow-{index + 1}",
                "name": _flow_name_for_context(index, path.get("name"), screens),
                "steps": steps,
                "goal": _first_preview_text(path.get("goal")) or str(screens[min(index, len(screens) - 1)].get("success_state") or ""),
            }
        )

    interaction_principles = _dedupe_strings(
        list(overrides.get("interaction_principles", []))
        + [str(item) for item in _as_list(design_tokens.get("effects")) if str(item).strip()]
        + [
            "Show the next action close to the active work surface.",
            "Keep evidence, decision context, and execution status in the same viewport.",
            "Prefer dense but scannable panels over marketing copy blocks.",
        ]
    )[:5]

    primary_nav = [
        {
            "id": str(item.get("id") or _slug(str(item.get("label") or "nav"), prefix="nav")),
            "label": str(item.get("label") or item.get("id") or "Section"),
            "priority": str(item.get("priority") or "primary"),
        }
        for item in site_map[:5]
    ]
    prototype_kind = overrides.get("prototype_kind") or (
        "control-center" if kind == "operations"
        else "storefront" if kind == "commerce"
        else "guided-product" if kind == "learning"
        else "product-workspace"
    )
    density = overrides.get("density") or ("high" if kind == "operations" else "medium")
    display_font = str(overrides.get("display_font") or _as_dict(design_tokens.get("typography")).get("heading") or "IBM Plex Sans")
    body_font = str(overrides.get("body_font") or _as_dict(design_tokens.get("typography")).get("body") or "Noto Sans JP")

    prototype = {
        "kind": prototype_kind,
        "app_shell": {
            "layout": overrides.get("navigation_style") or _shell_layout_for_kind(kind),
            "density": density,
            "primary_navigation": primary_nav,
            "status_badges": _dedupe_strings(selected_features[:3] or [screen["title"] for screen in screens[:3]]),
        },
        "screens": screens,
        "flows": flows,
        "interaction_principles": interaction_principles,
        "design_anchor": {
            "pattern_name": pattern_name,
            "description": description,
            "style_name": str(_as_dict(design_tokens.get("style")).get("name") or ""),
        },
        "visual_direction": {
            "visual_style": visual_style,
            "display_font": display_font,
            "body_font": body_font,
        },
    }
    return _sanitize_design_prototype(prototype, kind=kind)


def _sanitize_design_prototype(
    prototype: dict[str, Any] | None,
    *,
    kind: str,
) -> dict[str, Any]:
    payload = _as_dict(prototype)
    app_shell = _as_dict(payload.get("app_shell"))
    screens = [dict(item) for item in _as_list(payload.get("screens")) if isinstance(item, dict)]
    variant_style = str(_as_dict(payload.get("visual_direction")).get("visual_style") or "").strip().lower()
    default_paths = [dict(item) for item in _default_key_paths_for_context(kind, variant_style)]
    sanitized_screens: list[dict[str, Any]] = []

    for index, raw in enumerate(screens):
        screen = dict(raw)
        screen_id = str(screen.get("id") or f"screen-{index + 1}")
        raw_title = str(screen.get("title") or screen_id)
        title = (
            _preferred_operations_screen_label(screen_id=screen_id, label=raw_title, variant_style=variant_style)
            if kind == "operations"
            else (_design_preview_text(raw_title) or raw_title)
        )
        blueprint = _operations_screen_blueprint(screen_id=screen_id, label=title, variant_style=variant_style) or _screen_blueprint_for_label(title)
        fallback_modules = [dict(item) for item in _as_list(_as_dict(blueprint).get("modules")) if isinstance(item, dict)]
        fallback_actions = [str(item) for item in _as_list(_as_dict(blueprint).get("actions")) if str(item).strip()]
        fallback_purpose = str(_as_dict(blueprint).get("purpose") or _default_generic_purpose(title, ""))
        fallback_headline = str(_as_dict(blueprint).get("headline") or _default_generic_headline(title))
        fallback_supporting = str(_as_dict(blueprint).get("supporting_text") or (default_paths[min(index, len(default_paths) - 1)].get("name") if default_paths else ""))
        fallback_success = str(_as_dict(blueprint).get("success_state") or f"{title}で次の操作が迷わず決まる")

        raw_modules = [dict(item) for item in _as_list(screen.get("modules")) if isinstance(item, dict)]
        use_fallback_modules = _screen_modules_need_product_copy(raw_modules)
        sanitized_modules: list[dict[str, Any]] = []
        for module_index, module in enumerate(raw_modules if not use_fallback_modules else fallback_modules):
            fallback_module = fallback_modules[min(module_index, len(fallback_modules) - 1)] if fallback_modules else {}
            module_name = _preview_copy_or_fallback(
                module.get("name"),
                fallback=str(fallback_module.get("name") or "情報カード"),
                max_length=48,
            )
            module_type = _preview_copy_or_fallback(
                module.get("type"),
                fallback=str(fallback_module.get("type") or "summary"),
                max_length=24,
            )
            fallback_items = [str(item) for item in _as_list(fallback_module.get("items")) if str(item).strip()]
            raw_items = [str(item) for item in _as_list(module.get("items")) if str(item).strip()]
            candidate_items = raw_items or fallback_items
            items = [
                _preview_copy_or_fallback(
                    item,
                    fallback=fallback_items[min(item_index, len(fallback_items) - 1)] if fallback_items else "",
                    max_length=56,
                )
                for item_index, item in enumerate(candidate_items[:4])
                if _preview_copy_or_fallback(
                    item,
                    fallback=fallback_items[min(item_index, len(fallback_items) - 1)] if fallback_items else "",
                    max_length=56,
                )
            ]
            if items:
                sanitized_modules.append({"name": module_name, "type": module_type, "items": items})
        if not sanitized_modules and fallback_modules:
            sanitized_modules = [dict(item) for item in fallback_modules]

        actions = [
            _preview_primary_action(
                item,
                screen={"id": screen_id},
            )
            for item in _as_list(screen.get("primary_actions"))[:3]
        ]
        actions = [item for item in actions if item]
        if _actions_need_product_copy(actions, label=title):
            actions = fallback_actions[:3] if fallback_actions else actions
        if not actions:
            actions = fallback_actions[:3] if fallback_actions else [f"{title}を開く"]

        sanitized_screens.append(
            {
                **screen,
                "id": screen_id,
                "title": title,
                "headline": _preview_copy_or_fallback(screen.get("headline"), fallback=fallback_headline, max_length=72),
                "purpose": _preview_copy_or_fallback(screen.get("purpose"), fallback=fallback_purpose, max_length=120),
                "supporting_text": _preview_copy_or_fallback(screen.get("supporting_text"), fallback=fallback_supporting, max_length=72),
                "layout": _design_preview_text(screen.get("layout") or _screen_layout_for_kind(kind, index=index)),
                "primary_actions": actions,
                "modules": sanitized_modules,
                "success_state": _preview_copy_or_fallback(screen.get("success_state"), fallback=fallback_success, max_length=88),
                "variant_style": variant_style,
            }
        )

    sanitized_flows: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(payload.get("flows"))):
        flow = _as_dict(raw)
        fallback_path = default_paths[min(index, len(default_paths) - 1)] if default_paths else {}
        fallback_name = _flow_name_for_context(index, "", sanitized_screens)
        fallback_steps = [str(item) for item in _as_list(fallback_path.get("steps")) if str(item).strip()]
        raw_steps = [str(item) for item in _as_list(flow.get("steps")) if str(item).strip()]
        steps = [
            _preview_copy_or_fallback(
                step,
                fallback=fallback_steps[min(step_index, len(fallback_steps) - 1)] if fallback_steps else "",
                max_length=48,
            )
            for step_index, step in enumerate((raw_steps or fallback_steps)[:5])
            if _preview_copy_or_fallback(
                step,
                fallback=fallback_steps[min(step_index, len(fallback_steps) - 1)] if fallback_steps else "",
                max_length=48,
            )
        ]
        if not steps:
            steps = fallback_steps[:4]
        sanitized_flows.append(
            {
                "id": str(flow.get("id") or f"flow-{index + 1}"),
                "name": _preview_copy_or_fallback(flow.get("name"), fallback=fallback_name, max_length=64),
                "steps": steps,
                "goal": _preview_copy_or_fallback(
                    flow.get("goal"),
                    fallback=str((sanitized_screens[min(index, len(sanitized_screens) - 1)] if sanitized_screens else {}).get("success_state") or "次の判断が明確になる"),
                    max_length=96,
                ),
            }
        )

    interaction_principles = [
        _preview_copy_or_fallback(item, fallback="", max_length=92)
        for item in _as_list(payload.get("interaction_principles"))
        if _preview_copy_or_fallback(item, fallback="", max_length=92)
    ]
    if kind == "operations" and _interaction_principles_need_product_copy(interaction_principles):
        interaction_principles = _default_operations_interaction_principles()

    if kind == "operations" and sanitized_screens:
        primary_navigation = [
            {
                "id": str(screen.get("id") or f"nav-{index + 1}"),
                "label": str(screen.get("title") or f"画面 {index + 1}"),
                "priority": "primary" if index < 3 else "secondary",
            }
            for index, screen in enumerate(sanitized_screens[:4])
        ]
        status_badges = [str(screen.get("title") or "") for screen in sanitized_screens[:3] if str(screen.get("title") or "").strip()]
    else:
        primary_navigation = [dict(item) for item in _as_list(app_shell.get("primary_navigation")) if isinstance(item, dict)]
        status_badges = [str(item) for item in _as_list(app_shell.get("status_badges")) if str(item).strip()]

    return {
        **payload,
        "app_shell": {
            **app_shell,
            "primary_navigation": primary_navigation,
            "status_badges": status_badges,
        },
        "screens": sanitized_screens,
        "flows": sanitized_flows,
        "interaction_principles": interaction_principles,
    }


def _infer_prototype_context_kind(prototype: dict[str, Any] | None) -> str:
    payload = _as_dict(prototype)
    screen_ids = {str(_as_dict(item).get("id") or "").strip().lower() for item in _as_list(payload.get("screens"))}
    if screen_ids & {"workspace", "runs", "approvals", "artifacts", "lineage", "review"}:
        return "operations"
    kind = str(payload.get("kind") or "").lower()
    if any(token in kind for token in ("store", "catalog", "checkout", "commerce")):
        return "commerce"
    if any(token in kind for token in ("learn", "lesson", "guided")):
        return "learning"
    return "generic"


def _looks_like_prototype_html(code: str) -> bool:
    lowered = str(code or "").lower()
    screen_count = lowered.count("data-screen-id=")
    has_navigation_shell = "<nav" in lowered and (
        "aria-label=\"primary navigation\"" in lowered
        or "aria-label=\"主要ナビゲーション\"" in lowered
        or "role=\"tablist\"" in lowered
    )
    return (
        "<html" in lowered
        and "<main" in lowered
        and screen_count >= 1
        and has_navigation_shell
        and "data-prototype-kind" in lowered
    )


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "```" in text:
        segments = text.split("```")
        candidates.extend(segment.strip() for segment in segments if segment.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


_HTML_DOCUMENT_JSON_KEYS = (
    "html",
    "html_document",
    "htmlDocument",
    "preview_html",
    "previewHtml",
    "prototype_html",
    "prototypeHtml",
    "document",
    "markup",
)


def _ensure_html_head_defaults(head_html: str) -> str:
    lower = head_html.lower()
    enriched = head_html
    if "<meta charset" not in lower:
        enriched = enriched.replace("<head>", '<head><meta charset="utf-8" />', 1)
    if "name=\"viewport\"" not in lower and "name='viewport'" not in lower:
        enriched = enriched.replace(
            "</head>",
            '<meta name="viewport" content="width=device-width, initial-scale=1" /></head>',
            1,
        )
    return enriched


def _wrap_html_fragment_as_document(fragment: str) -> str:
    text = str(fragment or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"<!doctype[^>]*>", "", text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"</?html\b[^>]*>", "", cleaned, flags=re.IGNORECASE).strip()
    head_match = re.search(r"<head\b[^>]*>.*?</head>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    body_match = re.search(r"<body\b[^>]*>.*?</body>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    head_html = (
        _ensure_html_head_defaults(head_match.group(0))
        if head_match
        else '<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>'
    )
    remainder = cleaned
    if head_match:
        remainder = remainder.replace(head_match.group(0), "", 1).strip()
    body_html = body_match.group(0) if body_match else ""
    if body_html:
        remainder = remainder.replace(body_html, "", 1).strip()
    if not body_html:
        if not any(
            marker in remainder.lower()
            for marker in ("<main", "<nav", "<section", "<style", "<script", "data-screen-id", "role=\"tablist\"")
        ):
            return ""
        body_html = f"<body>{remainder}</body>"
    return f'<!doctype html><html lang="ja">{head_html}{body_html}</html>'


def _extract_html_document(content: str) -> str:
    """Extract a self-contained HTML document from LLM output."""
    text = str(content or "").strip()
    if not text:
        return ""
    # Try fenced code blocks first.
    if "```" in text:
        for segment in text.split("```"):
            cleaned = segment.strip()
            if cleaned.lower().startswith("html"):
                cleaned = cleaned[4:].strip()
            if cleaned.lower().startswith("<!doctype") or cleaned.lower().startswith("<html"):
                return cleaned
            wrapped = _wrap_html_fragment_as_document(cleaned)
            if wrapped:
                return wrapped
    payload = _extract_json_object(text)
    if isinstance(payload, dict):
        for key in _HTML_DOCUMENT_JSON_KEYS:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            extracted = _extract_html_document(value)
            if extracted:
                return extracted
    # Fall back to raw <html> extraction.
    lower = text.lower()
    doctype_start = lower.find("<!doctype")
    html_start = lower.find("<html")
    start = doctype_start if doctype_start != -1 else html_start
    if start == -1:
        return _wrap_html_fragment_as_document(text)
    end = lower.rfind("</html>")
    if end == -1:
        html_fragment = text[start:].strip()
        if "</body>" in html_fragment.lower():
            return f"{html_fragment}</html>"
        return _wrap_html_fragment_as_document(html_fragment)
    return text[start : end + len("</html>")]


def _llm_event_payload(result: Any, *, purpose: str, raw_content: str) -> dict[str, Any]:
    usage = result.response.usage
    usage_payload = None
    if usage is not None:
        usage_payload = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "total_tokens": usage.total_tokens,
            "metered_tokens": usage.metered_tokens,
        }
    return {
        "purpose": purpose,
        "provider": result.route.provider_name,
        "model": result.response.model,
        "estimated_cost_usd": result.estimated_cost_usd,
        "usage": usage_payload,
        "route": result.route.to_dict(),
        "context": dict(result.context),
        "response_preview": raw_content[:400],
    }


async def _lifecycle_llm_json(
    *,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
    preferred_model: str,
    purpose: str,
    static_instruction: str,
    user_prompt: str,
    quality_sensitive: bool = True,
    tenant_id: str | None = None,
    phase: str | None = None,
    node_id: str | None = None,
    assigned_skill_ids: list[str] | tuple[str, ...] = (),
    explicit_skill_ids: list[str] | tuple[str, ...] = (),
    skill_runtime: SkillRuntime | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not _provider_backed_lifecycle_available(provider_registry):
        return None, [], ""
    runtime = llm_runtime or LLMRuntime()
    skill_context = _current_lifecycle_skill_context()
    effective_skill_runtime = (
        skill_runtime
        or skill_context.get("skill_runtime")
        or get_default_skill_runtime()
    )
    resolved_phase = phase
    resolved_node_id = node_id
    if not resolved_phase or not resolved_node_id:
        inferred_phase, inferred_node_id = _infer_lifecycle_phase_and_node(purpose)
        resolved_phase = resolved_phase or inferred_phase
        resolved_node_id = resolved_node_id or inferred_node_id
    resolved_tenant_id = str(
        tenant_id
        or skill_context.get("tenant_id")
        or "default"
    )
    inferred_assigned_skill_ids = list(assigned_skill_ids)
    if resolved_phase and resolved_node_id:
        inferred_assigned_skill_ids = _resolve_lifecycle_assigned_skills(
            phase=resolved_phase,
            node_id=resolved_node_id,
            assigned_skill_ids=assigned_skill_ids,
        )
    resolved_instruction, effective_skills = effective_skill_runtime.augment_instruction(
        static_instruction,
        tenant_id=resolved_tenant_id,
        assigned_skill_ids=inferred_assigned_skill_ids,
        explicit_skill_ids=explicit_skill_ids,
        control_plane_skills=skill_context.get("control_plane_skills"),
    )
    request = ModelRouteRequest(
        purpose=purpose,
        input_tokens_estimate=max(len(resolved_instruction + user_prompt) // 4, 256),
        requires_tools=bool(effective_skills.available_tools),
        latency_sensitive=not quality_sensitive,
        quality_sensitive=quality_sensitive,
        cacheable_prefix=True,
        batch_eligible=False,
    )
    llm_events: list[dict[str, Any]] = []
    try:
        available_tools = [tool.provider_tool() for tool in effective_skills.available_tools]
        tool_executors = {
            tool.name: tool.executor
            for tool in effective_skills.available_tools
            if tool.executor is not None
        }
        if available_tools and tool_executors:
            async def _chat_fn(messages: list[Message], **kwargs: Any):
                result = await runtime.chat(
                    registry=provider_registry,
                    request=request,
                    messages=messages,
                    preferred_model=preferred_model,
                    static_instruction=resolved_instruction,
                    tools=kwargs.get("tools"),
                )
                usage = result.response.usage
                llm_events.append(
                    {
                        "purpose": purpose,
                        "provider": result.route.provider_name,
                        "model": result.response.model,
                        "usage": (
                            {
                                "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens,
                                "cache_read_tokens": usage.cache_read_tokens,
                                "cache_write_tokens": usage.cache_write_tokens,
                                "reasoning_tokens": usage.reasoning_tokens,
                                "total_tokens": usage.total_tokens,
                                "metered_tokens": usage.metered_tokens,
                            }
                            if usage is not None
                            else None
                        ),
                        "estimated_cost_usd": result.estimated_cost_usd,
                        "context": dict(result.context),
                        "tool_loop": True,
                    }
                )
                return result.response

            async def _tool_executor(tool_name: str, tool_input: dict[str, Any]) -> str:
                executor = tool_executors.get(tool_name)
                if executor is None:
                    raise RuntimeError(f"Tool '{tool_name}' is not available")
                return await executor(tool_input)

            react_result = await ReActEngine().run(
                messages=[Message(role="user", content=user_prompt)],
                chat_fn=_chat_fn,
                tool_executor=_tool_executor,
                available_tools=available_tools,
            )
            raw_content = str(react_result.final_answer or "")
            payload = _extract_json_object(raw_content)
            return payload, llm_events, raw_content
        result = await runtime.chat(
            registry=provider_registry,
            request=request,
            messages=[Message(role="user", content=user_prompt)],
            preferred_model=preferred_model,
            static_instruction=resolved_instruction,
        )
    except Exception as exc:
        return None, [{"purpose": purpose, "error": str(exc)}], ""
    raw_content = str(result.response.content or "")
    payload = _extract_json_object(raw_content)
    return payload, [_llm_event_payload(result, purpose=purpose, raw_content=raw_content)], raw_content


async def _research_llm_json(
    *,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
    preferred_model: str,
    purpose: str,
    static_instruction: str,
    user_prompt: str,
    schema_name: str,
    required_keys: list[str] | None = None,
    phase: str | None = None,
    node_id: str | None = None,
    tenant_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    payload, llm_events, raw_content = await _lifecycle_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=preferred_model,
        purpose=purpose,
        static_instruction=static_instruction,
        user_prompt=user_prompt,
        phase=phase,
        node_id=node_id,
        tenant_id=tenant_id,
    )
    for item in llm_events:
        if isinstance(item, dict):
            item["stage"] = "strict"
    if isinstance(payload, dict):
        return payload, llm_events, {
            "parse_status": "strict",
            "raw_preview": raw_content[:400],
        }
    if not raw_content.strip():
        return None, llm_events, {
            "parse_status": "failed",
            "raw_preview": "",
            "degradation_reasons": ["empty_llm_response"],
        }
    repair_prompt = (
        "Repair the following model output into a strict JSON object.\n"
        f"Schema name: {schema_name}\n"
        f"Required keys: {required_keys or []}\n"
        "Return JSON only.\n"
        f"Raw response:\n{raw_content}"
    )
    repaired, repair_events, repair_raw = await _lifecycle_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=preferred_model,
        purpose=f"{purpose}-repair",
        static_instruction=(
            "You repair malformed model output into a strict JSON object. "
            "Do not explain anything. Return JSON only."
        ),
        user_prompt=repair_prompt,
        quality_sensitive=False,
        phase=phase,
        node_id=node_id,
        tenant_id=tenant_id,
    )
    for item in repair_events:
        if isinstance(item, dict):
            item["stage"] = "repair"
    llm_events.extend(repair_events)
    if isinstance(repaired, dict):
        return repaired, llm_events, {
            "parse_status": "repaired",
            "raw_preview": (repair_raw or raw_content)[:400],
            "degradation_reasons": ["llm_response_repaired"],
        }
    return None, llm_events, {
        "parse_status": "fallback",
        "raw_preview": raw_content[:400],
        "degradation_reasons": ["llm_json_parse_failed"],
    }


async def _localize_research_output(
    research: dict[str, Any],
    *,
    target_language: str,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    localized = with_research_operator_copy(dict(research), target_language="en")
    if target_language != "ja":
        localized = with_research_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "skipped"
        return localized, [], {"status": "skipped"}

    localized["judge_summary"] = translate_fixed_research_text(
        localized.get("judge_summary"),
        target_language=target_language,
    )
    localized["quality_gates"] = [
        {
            **_as_dict(item),
            "reason": translate_fixed_research_text(
                _as_dict(item).get("reason"),
                target_language=target_language,
            ),
        }
        for item in _as_list(localized.get("quality_gates"))
    ]
    remediation_plan = _as_dict(localized.get("remediation_plan"))
    if remediation_plan:
        localized["remediation_plan"] = {
            **remediation_plan,
            "objective": translate_fixed_research_text(
                remediation_plan.get("objective"),
                target_language=target_language,
            ),
        }
    localized["execution_trace"] = [
        {
            **_as_dict(item),
            "objective": translate_fixed_research_text(
                _as_dict(item).get("objective"),
                target_language=target_language,
            ),
        }
        for item in _as_list(localized.get("execution_trace"))
    ]

    payload = research_localization_payload(localized)
    if not payload:
        localized = with_research_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "noop"
        return localized, [], {"status": "noop"}
    if not _provider_backed_lifecycle_available(provider_registry):
        localized = with_research_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "skipped"
        return localized, [], {"status": "skipped"}

    translated, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model("research-localizer", provider_registry),
        purpose="lifecycle-research-localizer",
        static_instruction=(
            "Translate user-facing JSON string values into the target language. "
            "Return JSON only. Preserve keys, arrays, ids, URLs, numeric values, booleans, and machine tokens."
        ),
        user_prompt=(
            "Return JSON only.\n"
            f"Target language: {target_language}\n"
            "Translate natural-language values only. Keep product names and URLs unchanged when translation is unnatural.\n"
            f"JSON payload: {json.dumps(payload, ensure_ascii=False)}"
        ),
        schema_name="research-localization",
        required_keys=list(payload.keys()),
        phase="research",
    )
    if isinstance(translated, dict):
        localized = merge_research_localization(localized, translated)
        localized["localization_status"] = str(llm_meta.get("parse_status", "strict"))
    else:
        localized["localization_status"] = str(llm_meta.get("parse_status", "fallback"))
    localized = with_research_operator_copy(localized, target_language=target_language)
    localized["display_language"] = target_language
    return localized, llm_events, llm_meta


async def _localize_planning_output(
    analysis: dict[str, Any],
    *,
    target_language: str,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    localized = with_planning_operator_copy(dict(analysis), target_language="en")
    if target_language != "ja":
        localized = with_planning_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "skipped"
        return localized, [], {"status": "skipped"}

    payload = planning_localization_payload(localized)
    if not payload:
        localized = with_planning_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "noop"
        return localized, [], {"status": "noop"}
    if not _provider_backed_lifecycle_available(provider_registry):
        localized = with_planning_operator_copy(localized, target_language=target_language)
        localized["display_language"] = target_language
        localized["localization_status"] = "skipped"
        return localized, [], {"status": "skipped"}

    translated, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model("planning-localizer", provider_registry),
        purpose="lifecycle-planning-localizer",
        static_instruction=(
            "Translate user-facing JSON string values into the target language. "
            "Return JSON only. Preserve keys, arrays, ids, URLs, enum tokens, numeric values, booleans, and machine tokens."
        ),
        user_prompt=(
            "Return JSON only.\n"
            f"Target language: {target_language}\n"
            "Translate natural-language values only. Keep product names, IDs, URLs, enum values, and architecture tokens unchanged when translation is unnatural.\n"
            f"JSON payload: {json.dumps(payload, ensure_ascii=False)}"
        ),
        schema_name="planning-localization",
        required_keys=list(payload.keys()),
        phase="planning",
        node_id="planning-localizer",
    )
    if isinstance(translated, dict):
        localized = merge_planning_localization(localized, translated)
        localized["localization_status"] = str(llm_meta.get("parse_status", "strict"))
    else:
        localized["localization_status"] = str(llm_meta.get("parse_status", "fallback"))
    localized = with_planning_operator_copy(localized, target_language=target_language)
    localized["display_language"] = target_language
    return localized, llm_events, llm_meta


_LIFECYCLE_MODEL_STRATEGIES: dict[str, dict[str, Any]] = {
    "competitor-analyst": {
        "archetype": "long-context competitive comparator",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "anthropic/claude-sonnet-4-6"),
    },
    "market-researcher": {
        "archetype": "broad market synthesizer",
        "candidates": ("gemini/gemini-3-pro-preview", "moonshot/kimi-k2.5", "openai/gpt-5-mini"),
    },
    "user-researcher": {
        "archetype": "qualitative interviewer",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "openai/gpt-5-mini"),
    },
    "tech-evaluator": {
        "archetype": "system feasibility reasoner",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "research-synthesizer": {
        "archetype": "structured synthesis engine",
        "candidates": ("openai/gpt-5-mini", "moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6"),
    },
    "evidence-librarian": {
        "archetype": "source normalizer",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "openai/gpt-5-mini"),
    },
    "devils-advocate-researcher": {
        "archetype": "adversarial systems critic",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "cross-examiner": {
        "archetype": "structured contradiction detector",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "gemini/gemini-3-pro-preview"),
    },
    "research-judge": {
        "archetype": "decision calibrator",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
    "research-localizer": {
        "archetype": "low-cost output localizer",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "anthropic/claude-haiku-4-5-20251001"),
    },
    "persona-builder": {
        "archetype": "persona and motivation mapper",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview"),
    },
    "story-architect": {
        "archetype": "journey and IA composer",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "anthropic/claude-sonnet-4-6"),
    },
    "feature-analyst": {
        "archetype": "scope and prioritization reasoner",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "solution-architect": {
        "archetype": "delivery architecture planner",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "planning-synthesizer": {
        "archetype": "decision-table synthesizer",
        "candidates": ("openai/gpt-5-mini", "moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6"),
    },
    "scope-skeptic": {
        "archetype": "scope reduction critic",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "gemini/gemini-3-pro-preview"),
    },
    "assumption-auditor": {
        "archetype": "assumption auditor",
        "candidates": ("anthropic/claude-sonnet-4-6", "zhipu/glm-4-plus", "openai/gpt-5-mini"),
    },
    "negative-persona-challenger": {
        "archetype": "failure-mode generator",
        "candidates": ("gemini/gemini-3-pro-preview", "moonshot/kimi-k2.5", "zhipu/glm-4-plus"),
    },
    "milestone-falsifier": {
        "archetype": "verification gate critic",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "planning-judge": {
        "archetype": "portfolio and tradeoff judge",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
    "planning-localizer": {
        "archetype": "low-cost output localizer",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "anthropic/claude-haiku-4-5-20251001"),
    },
    "claude-designer": {
        "archetype": "premium interaction designer",
        "candidates": ("anthropic/claude-sonnet-4-6", "moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview"),
    },
    "openai-designer": {
        "archetype": "high-iteration UI concept generator",
        "candidates": ("moonshot/kimi-k2.5", "openai/gpt-5-mini", "gemini/gemini-3-pro-preview"),
    },
    "gemini-designer": {
        "archetype": "alternate premium product designer",
        "candidates": ("moonshot/kimi-k2.5", "gemini/gemini-3-pro-preview", "openai/gpt-5-mini"),
    },
    "design-evaluator": {
        "archetype": "design judge and rubric scorer",
        "candidates": ("zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "planner": {
        "archetype": "delivery planner",
        "candidates": ("openai/gpt-5-mini", "zhipu/glm-4-plus", "anthropic/claude-sonnet-4-6"),
    },
    "frontend-builder": {
        "archetype": "UI implementation specialist",
        "candidates": ("moonshot/kimi-k2.5", "anthropic/claude-sonnet-4-6", "openai/gpt-5-mini"),
    },
    "backend-builder": {
        "archetype": "backend systems implementer",
        "candidates": ("zhipu/glm-4-plus", "openai/gpt-5-mini", "anthropic/claude-sonnet-4-6"),
    },
    "integrator": {
        "archetype": "cross-artifact integrator",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "moonshot/kimi-k2.5"),
    },
    "reviewer": {
        "archetype": "final quality reviewer",
        "candidates": ("anthropic/claude-sonnet-4-6", "openai/gpt-5-mini", "zhipu/glm-4-plus"),
    },
}


def _preferred_lifecycle_model(
    node_id: str,
    provider_registry: ProviderRegistry | None = None,
) -> str:
    strategy = _as_dict(_LIFECYCLE_MODEL_STRATEGIES.get(node_id))
    raw_candidates = strategy.get("candidates")
    candidates = [
        str(item).strip()
        for item in (list(raw_candidates) if isinstance(raw_candidates, (list, tuple)) else [])
        if str(item).strip()
    ]
    if not candidates:
        return ""
    if provider_registry is None:
        return candidates[0]
    available = set(provider_registry.provider_names())
    for candidate in candidates:
        provider_name, _ = candidate.split("/", 1)
        if provider_name in available:
            return candidate
    return candidates[0]


def _design_variant_usage_estimate(
    *,
    selected_features: list[str],
    pattern_name: str,
    description: str,
    prototype_overrides: dict[str, Any] | None = None,
) -> TokenUsage:
    feature_count = max(len(selected_features), 1)
    descriptive_weight = max((len(pattern_name) + len(description)) // 12, 24)
    overrides = _as_dict(prototype_overrides)
    density = str(overrides.get("density") or "").strip().lower()
    navigation_style = str(overrides.get("navigation_style") or "").strip().lower()
    screen_count = len([item for item in _as_list(overrides.get("screen_labels")) if str(item).strip()])
    principle_count = len([item for item in _as_list(overrides.get("interaction_principles")) if str(item).strip()])
    density_in = 60 if density == "high" else 35 if density == "medium" else 15
    density_out = 180 if density == "high" else 95 if density == "medium" else 40
    nav_in = 25 if navigation_style == "top-nav" else 40 if navigation_style == "sidebar" else 20
    nav_out = 30 if navigation_style == "top-nav" else 65 if navigation_style == "sidebar" else 18
    return TokenUsage(
        input_tokens=620 + feature_count * 130 + descriptive_weight + density_in + nav_in + screen_count * 8 + principle_count * 10,
        output_tokens=960 + feature_count * 120 + descriptive_weight // 2 + density_out + nav_out + screen_count * 36 + principle_count * 42,
    )


def _design_model_ref_from_display(model_name: str) -> str:
    lowered = str(model_name or "").strip().lower()
    if "/" in lowered and lowered.count("/") == 1:
        return str(model_name).strip()
    if "claude sonnet 4.6" in lowered:
        return "anthropic/claude-sonnet-4-6"
    if "claude sonnet 4.5" in lowered:
        return "anthropic/claude-sonnet-4-5"
    if "gemini 3 pro" in lowered:
        return "google/gemini-3-pro-preview"
    if "kimi" in lowered:
        return "moonshot/kimi-k2.5"
    if "glm-4-plus" in lowered:
        return "zhipu/glm-4-plus"
    if "gpt-5-mini" in lowered:
        return "openai/gpt-5-mini"
    return ""


def _aggregate_llm_event_metrics(events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[TokenUsage, float]:
    aggregated = TokenUsage()
    estimated_cost = 0.0
    for event in events:
        payload = _as_dict(event)
        usage_payload = _as_dict(payload.get("usage"))
        usage = TokenUsage(
            input_tokens=int(usage_payload.get("input_tokens", 0) or 0),
            output_tokens=int(usage_payload.get("output_tokens", 0) or 0),
            cache_read_tokens=int(usage_payload.get("cache_read_tokens", 0) or 0),
            cache_write_tokens=int(usage_payload.get("cache_write_tokens", 0) or 0),
            reasoning_tokens=int(usage_payload.get("reasoning_tokens", 0) or 0),
        )
        aggregated.input_tokens += usage.input_tokens
        aggregated.output_tokens += usage.output_tokens
        aggregated.cache_read_tokens += usage.cache_read_tokens
        aggregated.cache_write_tokens += usage.cache_write_tokens
        aggregated.reasoning_tokens += usage.reasoning_tokens
        event_cost = float(payload.get("estimated_cost_usd", payload.get("cost_usd", 0.0)) or 0.0)
        if event_cost <= 0.0 and usage.total_tokens > 0:
            event_cost = estimate_cost_from_usage(
                str(payload.get("provider", "") or ""),
                str(payload.get("model", "") or ""),
                usage,
            )
        estimated_cost += event_cost
    return aggregated, round(estimated_cost, 3)


def _estimate_design_variant_cost(
    *,
    model_name: str,
    usage: TokenUsage,
    model_ref: str = "",
    cost_override: float | None = None,
) -> float:
    if cost_override is not None and cost_override > 0.0:
        return round(cost_override, 3)
    resolved_ref = model_ref or _design_model_ref_from_display(model_name)
    provider_name, model_id = parse_model_ref(resolved_ref)
    if provider_name and model_id:
        return round(estimate_cost_from_usage(provider_name, model_id, usage), 3)
    return round(((usage.input_tokens * 1.0) + (usage.output_tokens * 4.0)) / 1_000_000, 3)


def _design_variant_voice(
    *,
    variant_id: str = "",
    visual_style: str = "",
    kind: str = "",
) -> dict[str, str]:
    normalized_variant = str(variant_id or "").strip().lower()
    normalized_style = str(visual_style or "").strip().lower()
    if normalized_variant == "gemini-designer" or normalized_style == "ivory-signal":
        return {
            "experience_thesis": "根拠、差分、承認条件を静かな余白で並べ、合意形成の負荷を下げる。",
            "operational_bet": "圧迫感を抑えた判断室レイアウトで、レビュー前の読解コストを下げながら、決裁の瞬間だけ強いシグナルを出す。",
            "handoff_note": "採用時は、余白を保った比較面、落ち着いた判断順序、決裁時だけ立ち上がるシグナルを実装条件として固定する。",
            "selection_summary": "根拠確認と合意形成を穏やかな密度で進めやすく、レビュー負荷を下げられる。",
            "operator_promise": "根拠を読み比べながら承認条件を固め、合意形成を急がせずに完了できる。",
        }
    if kind == "operations":
        return {
            "experience_thesis": "重要判断、停止要因、承認条件をひとつの操作盤で裁き、迷いを次の一手に変える。",
            "operational_bet": "情報を減らすより、判断に必要な根拠と操作を同じ視野に重ね、復旧まで最短距離で回す。",
            "handoff_note": "採用時は、高密度でも迷わない情報優先順位、強い状態コントラスト、承認理由の即読性を実装条件として固定する。",
            "selection_summary": "重要判断と停止要因を同じ視野で扱え、承認前の運用判断が最も速い。",
            "operator_promise": "停止理由、承認条件、成果物の系譜が横断で見え、次の介入を迷わず選べる。",
        }
    return {
        "experience_thesis": "主要判断と次の一手が離れず、画面をまたいでも文脈が切れない体験を保つ。",
        "operational_bet": "根拠確認から承認準備までを同じ導線で回し、判断コストを減らす。",
        "handoff_note": "採用時は、主要画面、判断理由、守るべき体験をひとつの承認パケットにまとめる。",
        "selection_summary": "主要判断、根拠、引き継ぎの整合が高い。",
        "operator_promise": "主要判断と根拠を同じ文脈で確認しながら、次の操作へ移れる。",
    }


def _build_design_narrative(
    *,
    description: str,
    selected_features: list[str],
    decision_scope: dict[str, Any] | None = None,
    prototype: dict[str, Any] | None = None,
    provider_note: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope = _as_dict(decision_scope)
    prototype_payload = _as_dict(prototype)
    visual_style = str(_as_dict(prototype_payload.get("visual_direction")).get("visual_style") or "").strip().lower()
    variant_id = str(_as_dict(prototype_payload.get("design_anchor")).get("variant_id") or "").strip().lower()
    voice = _design_variant_voice(variant_id=variant_id, visual_style=visual_style, kind=_infer_prototype_context_kind(prototype_payload))
    screens = [dict(item) for item in _as_list(prototype_payload.get("screens")) if isinstance(item, dict)]
    override_payload = _as_dict(overrides)
    signature_defaults = _dedupe_strings(
        [
            str(screen.get("headline") or screen.get("title") or "").strip()
            for screen in screens[:3]
            if str(screen.get("headline") or screen.get("title") or "").strip()
        ]
    )
    feature_summary = ", ".join(selected_features[:3])
    lead_thesis = (
        str(override_payload.get("experience_thesis") or "").strip()
        or voice["experience_thesis"]
    )
    operational_bet = (
        str(override_payload.get("operational_bet") or "").strip()
        or (
            f"{feature_summary} を同じ運用文脈で行き来し、判断理由が次の操作から離れないようにする。"
            if feature_summary
            else voice["operational_bet"]
        )
    )
    handoff_note = (
        str(override_payload.get("handoff_note") or "").strip()
        or provider_note
        or voice["handoff_note"]
    )
    signature_moments = _dedupe_strings(
        [str(item).strip() for item in _as_list(override_payload.get("signature_moments")) if str(item).strip()]
        + signature_defaults
    )[:4]
    if not signature_moments:
        signature_moments = _dedupe_strings([str(item).strip() for item in selected_features if str(item).strip()])[:3]
    return {
        "experience_thesis": lead_thesis[:240],
        "operational_bet": operational_bet[:220],
        "signature_moments": signature_moments,
        "handoff_note": handoff_note[:220],
    }


def _build_design_implementation_brief(
    *,
    spec: str,
    analysis: dict[str, Any] | None = None,
    selected_features: list[str] | None = None,
    prototype: dict[str, Any] | None = None,
    decision_scope: dict[str, Any] | None = None,
    plan_estimates: list[dict[str, Any]] | None = None,
    selected_preset: str = "",
    quality_focus: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _brief_strings(value: Any, *, limit: int, max_length: int = 120) -> list[str]:
        return _dedupe_strings(
            [
                text[:max_length]
                for item in _as_list(value)
                if (text := str(item).strip())
            ]
        )[:limit]

    def _brief_choice_records(value: Any) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in _as_list(value):
            payload = _as_dict(item)
            area = str(payload.get("area") or "").strip()
            decision = str(payload.get("decision") or "").strip()
            rationale = str(payload.get("rationale") or "").strip()
            if not area or not decision:
                continue
            normalized.append(
                {
                    "area": area[:48],
                    "decision": decision[:140],
                    "rationale": rationale[:180],
                }
            )
            if len(normalized) >= 4:
                break
        return normalized

    def _brief_agent_lanes(value: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in _as_list(value):
            payload = _as_dict(item)
            role = str(payload.get("role") or "").strip()
            remit = str(payload.get("remit") or "").strip()
            skills = _brief_strings(payload.get("skills"), limit=4, max_length=48)
            if not role or not remit:
                continue
            normalized.append(
                {
                    "role": role[:64],
                    "remit": remit[:180],
                    "skills": skills,
                }
            )
            if len(normalized) >= 3:
                break
        return normalized

    kind = _infer_product_kind(spec)
    analysis_payload = _as_dict(analysis)
    scope = _as_dict(decision_scope)
    prototype_payload = _as_dict(prototype)
    override_payload = _as_dict(overrides)
    selected = [str(item).strip() for item in (selected_features or []) if str(item).strip()]
    screens = [dict(item) for item in _as_list(prototype_payload.get("screens")) if isinstance(item, dict)]
    screen_titles = [
        str(item.get("title") or item.get("headline") or "").strip()
        for item in screens[:4]
        if str(item.get("title") or item.get("headline") or "").strip()
    ]
    flow_names = [
        str(item.get("name") or "").strip()
        for item in _as_list(prototype_payload.get("flows"))[:3]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    estimate_candidates = [dict(item) for item in _as_list(plan_estimates) if isinstance(item, dict)]
    selected_estimate = next(
        (
            item for item in estimate_candidates
            if str(item.get("preset") or "").strip() == selected_preset
        ),
        next(
            (
                item for item in estimate_candidates
                if str(item.get("preset") or "").strip() == "standard"
            ),
            estimate_candidates[0] if estimate_candidates else {},
        ),
    )
    agents_used = [
        str(item).strip()
        for item in _as_list(_as_dict(selected_estimate).get("agents_used"))
        if str(item).strip()
    ]
    skills_used = [
        str(item).strip()
        for item in _as_list(_as_dict(selected_estimate).get("skills_used"))
        if str(item).strip()
    ]
    milestones = [
        str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
        for item in _as_list(analysis_payload.get("recommended_milestones"))
        if str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
    ] or [
        str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
        for item in _as_list(analysis_payload.get("milestones"))
        if str(_as_dict(item).get("name") or _as_dict(item).get("criteria") or "").strip()
    ]
    if kind == "operations":
        architecture_thesis = (
            "判断根拠、承認、成果物の系譜を同じ状態遷移で扱い、各工程を独立に再開できる運用基盤として実装する。"
        )
        system_shape = [
            "ライフサイクルワークスペースと工程別の主作業面を分ける",
            "実行状態はストリーム更新とチェックポイント保存の二層で同期する",
            "承認判断は変更履歴を残す判断パケットとして保存する",
            "成果物の系譜を横断参照できる来歴ストアを持つ",
        ]
        technical_choices = [
            {
                "area": "画面構成",
                "decision": "画面遷移よりワークスペース継続性を優先した状態保持型シェルにする",
                "rationale": "調査、企画、承認を跨いでも判断文脈を失わず、差し戻し時の認知負荷を増やさないため。",
            },
            {
                "area": "実行同期",
                "decision": "工程状態とエージェント実行はストリーム更新と永続チェックポイントの二層で扱う",
                "rationale": "長時間 run と再読込をまたいでも現在地を復元し、運用介入を安全にするため。",
            },
            {
                "area": "承認と監査",
                "decision": "承認パケット、コメント、判断履歴を同一の判断台帳に束ねる",
                "rationale": "承認理由と差し戻し理由が UI と監査証跡で分断しないようにするため。",
            },
            {
                "area": "成果物リネージ",
                "decision": "調査からデザインまでの成果物を工程単位で参照可能にする",
                "rationale": "なぜこの画面になったかを説明できる状態を、実装 handoff まで保つため。",
            },
        ]
    else:
        architecture_thesis = (
            "主要ワークフローと判断根拠を同じ面で扱い、段階的に詳細を開く product workspace として構成する。"
        )
        system_shape = [
            "主要タスクを起点にした workspace shell を置く",
            "状態更新は履歴と現在値を同時に見せる",
            "重要判断だけを approval surface で明示的に止める",
            "モバイルでは要約先行、詳細後出しの構成にする",
        ]
        technical_choices = [
            {
                "area": "フロントエンド構成",
                "decision": "情報密度を保ちながら折りたためる responsive workspace にする",
                "rationale": "desktop と mobile で同じ中核フローを崩さずに見せるため。",
            },
            {
                "area": "状態モデル",
                "decision": "作業中の状態、レビュー状態、完了状態を phase contract で分ける",
                "rationale": "空状態や差し戻し状態でも次の一手を明快にするため。",
            },
            {
                "area": "実装同期",
                "decision": "主要成果物は typed payload、可変 UI は derived preview として生成する",
                "rationale": "表示の自由度を保ちながら、保存と handoff の整合性を守るため。",
            },
        ]

    skill_summary = skills_used[:6] or [
        "workflow-design",
        "solution-architecture",
        "accessibility",
        "implementation-planning",
    ]
    base_agent_lanes = [
        {
            "role": "プロダクト設計レーン",
            "remit": "勝ち筋を主要フロー、判断順、空状態まで落とし込む",
            "skills": [item for item in skill_summary if item in {"workflow-design", "journey-mapping", "ux-research"}][:2] or ["workflow-design", "ux-research"],
        },
        {
            "role": "アーキテクチャ設計レーン",
            "remit": "phase contract、状態同期、approval 境界を定義する",
            "skills": [item for item in skill_summary if item in {"solution-architecture", "risk-analysis", "system-design"}][:2] or ["solution-architecture", "risk-analysis"],
        },
        {
            "role": "実装計画レーン",
            "remit": "画面分割、コンポーネント責務、段階的 delivery を決める",
            "skills": [item for item in skill_summary if item in {"frontend-implementation", "performance", "accessibility"}][:3] or ["frontend-implementation", "accessibility"],
        },
    ]
    if agents_used:
        base_agent_lanes[0]["role"] = f"{agents_used[0]} レーン"
        if len(agents_used) > 1:
            base_agent_lanes[1]["role"] = f"{agents_used[1]} レーン"
        if len(agents_used) > 2:
            base_agent_lanes[2]["role"] = f"{agents_used[2]} レーン"

    delivery_slices = _dedupe_strings(
        [
            *screen_titles,
            *flow_names,
            *selected[:2],
            *milestones[:2],
            *[str(item) for item in (quality_focus or []) if str(item).strip()],
            str(scope.get("lead_thesis") or "").strip(),
        ]
    )[:5]
    if not delivery_slices:
        delivery_slices = [
            "主要ワークスペース",
            "承認レビュー",
            "成果物リネージ",
        ]
    brief = {
        "architecture_thesis": architecture_thesis,
        "system_shape": system_shape,
        "technical_choices": technical_choices,
        "agent_lanes": base_agent_lanes,
        "delivery_slices": delivery_slices,
    }
    architecture_override = str(
        override_payload.get("architecture_thesis")
        or override_payload.get("architectureThesis")
        or ""
    ).strip()
    if architecture_override:
        brief["architecture_thesis"] = architecture_override[:240]
    system_shape_override = _brief_strings(
        override_payload.get("system_shape") or override_payload.get("systemShape"),
        limit=5,
    )
    if system_shape_override:
        brief["system_shape"] = system_shape_override
    technical_override = _brief_choice_records(
        override_payload.get("technical_choices") or override_payload.get("technicalChoices")
    )
    if technical_override:
        brief["technical_choices"] = technical_override
    lane_override = _brief_agent_lanes(
        override_payload.get("agent_lanes") or override_payload.get("agentLanes")
    )
    if lane_override:
        brief["agent_lanes"] = lane_override
    slices_override = _brief_strings(
        override_payload.get("delivery_slices") or override_payload.get("deliverySlices"),
        limit=5,
    )
    if slices_override:
        brief["delivery_slices"] = slices_override
    return brief


_PREVIEW_EXTERNAL_ASSET_PATTERN = re.compile(
    r"""<(?:script|link|img|source|iframe)[^>]+(?:src|href)=["']https?://""",
    re.IGNORECASE,
)

_PREVIEW_MARKETING_TERM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pricing", re.compile(r"\bpricing\b", re.IGNORECASE)),
    ("waitlist", re.compile(r"\bwaitlist\b", re.IGNORECASE)),
    ("testimonial", re.compile(r"\btestimonial(?:s)?\b", re.IGNORECASE)),
    ("request_demo", re.compile(r"\brequest a demo\b", re.IGNORECASE)),
    ("book_demo", re.compile(r"\bbook a demo\b", re.IGNORECASE)),
    ("free_trial", re.compile(r"\bfree trial\b", re.IGNORECASE)),
    ("start_free", re.compile(r"\bstart for free\b", re.IGNORECASE)),
    ("sign_up", re.compile(r"\bsign[\s-]?up\b", re.IGNORECASE)),
)

_PREVIEW_COPY_ISSUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("placeholder_copy", re.compile(r"\b(?:lorem ipsum|placeholder|todo|tbd|sample data)\b", re.IGNORECASE)),
    ("internal_jargon_visible", re.compile(r"\b(?:prototype spec|prototype app|tailwind|next\.?js|app router|css grid|grid-template-columns|css custom properties|dag)\b", re.IGNORECASE)),
    ("internal_milestone_id", re.compile(r"\b(?:ms|uc|risk|assumption|claim)-[a-z0-9-]+\b", re.IGNORECASE)),
)

_PREVIEW_ENGLISH_UI_TOKEN_PATTERN = re.compile(
    r"\b(?:dashboard|settings|planning|approval|review queue|review|release|workspace|artifact lineage|lineage|run monitor|active run|queue|packet|policies|evidence review)\b",
    re.IGNORECASE,
)


def _design_preview_visible_text(html: str) -> str:
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(html or ""), flags=re.IGNORECASE | re.DOTALL)
    attribute_text = re.findall(
        r"""(?:aria-label|title|placeholder)\s*=\s*["']([^"']+)["']""",
        cleaned,
        flags=re.IGNORECASE,
    )
    text_only = re.sub(r"<[^>]+>", " ", cleaned)
    return _normalize_space(" ".join([unescape(text_only), *[unescape(item) for item in attribute_text]]))


def _design_preview_copy_assessment(
    html: str,
    *,
    marketing_terms_detected: list[str],
) -> dict[str, Any]:
    visible_text = _design_preview_visible_text(html)
    issues: list[str] = []
    samples: list[str] = []
    for issue_id, pattern in _PREVIEW_COPY_ISSUE_PATTERNS:
        match = pattern.search(visible_text)
        if match:
            issues.append(issue_id)
            samples.append(match.group(0))
    english_tokens = sorted(
        {
            _normalize_space(match.group(0)).lower()
            for match in _PREVIEW_ENGLISH_UI_TOKEN_PATTERN.finditer(visible_text)
            if _normalize_space(match.group(0))
        }
    )
    if len(english_tokens) >= 3 and re.search(r"[\u3040-\u30ff\u3400-\u9fff]", visible_text):
        issues.append("english_ui_drift")
        samples.extend(english_tokens[:2])
    score = 1.0
    penalties = {
        "placeholder_copy": 0.26,
        "internal_jargon_visible": 0.22,
        "internal_milestone_id": 0.2,
        "english_ui_drift": 0.14,
    }
    for issue in issues:
        score -= penalties.get(issue, 0.12)
    if marketing_terms_detected:
        score -= 0.08
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", visible_text):
        score += 0.05
    if len(visible_text) >= 220:
        score += 0.04
    return {
        "copy_issues": _dedupe_strings(issues),
        "copy_issue_examples": _dedupe_strings(samples)[:4],
        "copy_quality_score": round(max(0.0, min(score, 1.0)), 2),
        "visible_text_sample": visible_text[:280],
    }


def _design_preview_interactive_features(html: str) -> list[str]:
    lower = str(html or "").lower()
    features: list[str] = []
    if any(token in lower for token in ("tablist", "tabpanel", "aria-selected", "data-tab")):
        features.append("tabs")
    if "accordion" in lower or "aria-expanded" in lower:
        features.append("accordion")
    if ":hover" in lower or "mouseenter" in lower or "mouseover" in lower:
        features.append("hover")
    if "transition" in lower or "animation" in lower:
        features.append("transitions")
    if "addeventlistener(" in lower or "onclick=" in lower:
        features.append("js-actions")
    if "<form" in lower:
        features.append("forms")
    return features


def _design_preview_screen_count_estimate(
    html: str,
    *,
    prototype: dict[str, Any] | None = None,
) -> int:
    lower = str(html or "").lower()
    prototype_count = len(_as_list(_as_dict(prototype).get("screens")))
    explicit_count = len(re.findall(r"data-screen-id\s*=", lower))
    aria_panel_count = len(re.findall(r"tabpanel", lower))
    return max(prototype_count, explicit_count, aria_panel_count)


def _design_preview_surface_signals(html: str) -> list[str]:
    lower = str(html or "").lower()
    signals: list[str] = []
    if "<table" in lower or 'aria-label="判断テーブル"' in lower or 'aria-label="data table"' in lower:
        signals.append("table")
    if "<form" in lower or "textbox" in lower or "textarea" in lower or "combobox" in lower:
        signals.append("form")
    if any(token in lower for token in ("metric", "kpi", "stat", "指標", "集計", "summary-card")):
        signals.append("metrics")
    if any(token in lower for token in ("status", "badge", "state", "進行中", "要確認", "完了", "blocked")):
        signals.append("status")
    return signals


def _design_preview_workflow_signals(html: str) -> list[str]:
    lower = str(html or "").lower()
    signals: list[str] = []
    if any(token in lower for token in ("approval", "承認")):
        signals.append("approval")
    if any(token in lower for token in ("evidence", "根拠")):
        signals.append("evidence")
    if any(token in lower for token in ("lineage", "系譜", "provenance")):
        signals.append("lineage")
    if any(token in lower for token in ("recover", "recovery", "復旧", "劣化", "degraded")):
        signals.append("recovery")
    if any(token in lower for token in ("operator", "運用", "workspace", "ワークスペース")):
        signals.append("operator-workspace")
    return signals


def _design_preview_marketing_terms(html: str) -> list[str]:
    lower = str(html or "").lower()
    detected: list[str] = []
    for label, pattern in _PREVIEW_MARKETING_TERM_PATTERNS:
        if pattern.search(lower):
            detected.append(label)
    return detected


def _design_preview_quality_score(
    *,
    html: str,
    screen_count_estimate: int,
    interactive_features: list[str],
    surface_signals: list[str],
    workflow_signals: list[str],
    marketing_terms_detected: list[str],
) -> float:
    lower = str(html or "").lower()
    score = 0.0
    if "<html" in lower and "</html>" in lower:
        score += 0.1
    if "<style" in lower:
        score += 0.08
    if "<script" in lower:
        score += 0.08
    if not _PREVIEW_EXTERNAL_ASSET_PATTERN.search(html):
        score += 0.06
    if "viewport" in lower:
        score += 0.06
    if "@media" in lower:
        score += 0.08
    score += min(max(screen_count_estimate, 0), 4) * 0.03
    score += min(len(interactive_features), 4) * 0.03
    score += min(len(surface_signals), 4) * 0.04
    score += min(len(workflow_signals), 5) * 0.04
    if "<nav" in lower or "sidebar" in lower or "top-nav" in lower or "top nav" in lower:
        score += 0.08
    if "aria-" in lower:
        score += 0.07
    if marketing_terms_detected:
        score -= 0.18
    return round(max(0.0, min(score, 1.0)), 2)


def _design_preview_meta(
    preview_html: str,
    *,
    source: str,
    extraction_ok: bool = False,
    fallback_reason: str = "",
    prototype: dict[str, Any] | None = None,
) -> dict[str, Any]:
    html = str(preview_html or "")
    lower = html.lower()
    screen_count_estimate = _design_preview_screen_count_estimate(html, prototype=prototype)
    interactive_features = _design_preview_interactive_features(html)
    surface_signals = _design_preview_surface_signals(html)
    workflow_signals = _design_preview_workflow_signals(html)
    marketing_terms_detected = _design_preview_marketing_terms(html)
    copy_assessment = _design_preview_copy_assessment(
        html,
        marketing_terms_detected=marketing_terms_detected,
    )
    validation_issues: list[str] = []
    if "<html" not in lower or "</html>" not in lower:
        validation_issues.append("missing_html_document")
    if "<style" not in lower:
        validation_issues.append("missing_inline_style")
    if "<script" not in lower:
        validation_issues.append("missing_inline_script")
    if _PREVIEW_EXTERNAL_ASSET_PATTERN.search(html):
        validation_issues.append("external_assets_detected")
    if "viewport" not in lower:
        validation_issues.append("missing_viewport")
    if "@media" not in lower:
        validation_issues.append("missing_responsive_breakpoint")
    if screen_count_estimate < 4:
        validation_issues.append("insufficient_screen_count")
    if len(interactive_features) < 1:
        validation_issues.append("limited_interactivity")
    if not ("<nav" in lower or "sidebar" in lower or "top-nav" in lower or "top nav" in lower):
        validation_issues.append("missing_navigation_shell")
    if "aria-" not in lower:
        validation_issues.append("missing_accessibility_annotations")
    if marketing_terms_detected:
        validation_issues.append("marketing_surface_detected")
    return {
        "source": source,
        "template_version": _DESIGN_TEMPLATE_PREVIEW_VERSION if source == "template" else None,
        "extraction_ok": extraction_ok,
        "validation_ok": len(validation_issues) == 0,
        "fallback_reason": fallback_reason,
        "html_size": len(html),
        "screen_count_estimate": screen_count_estimate,
        "interactive_features": interactive_features,
        "surface_signals": surface_signals,
        "workflow_signals": workflow_signals,
        "marketing_terms_detected": marketing_terms_detected,
        "copy_issues": list(_as_list(copy_assessment.get("copy_issues"))),
        "copy_issue_examples": list(_as_list(copy_assessment.get("copy_issue_examples"))),
        "copy_quality_score": float(copy_assessment.get("copy_quality_score", 0.0) or 0.0),
        "quality_score": _design_preview_quality_score(
            html=html,
            screen_count_estimate=screen_count_estimate,
            interactive_features=interactive_features,
            surface_signals=surface_signals,
            workflow_signals=workflow_signals,
            marketing_terms_detected=marketing_terms_detected,
        ),
        "validation_issues": validation_issues,
    }


def _design_primary_workflows(prototype: dict[str, Any] | None) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(_as_dict(prototype).get("flows"))):
        payload = _as_dict(item)
        name = str(payload.get("name") or "").strip()
        if not name:
            continue
        workflows.append(
            {
                "id": str(payload.get("id") or f"workflow-{index + 1}"),
                "name": name[:120],
                "goal": str(payload.get("goal") or "").strip()[:180],
                "steps": [
                    str(step).strip()[:120]
                    for step in _as_list(payload.get("steps"))
                    if str(step).strip()
                ][:5],
            }
        )
    return workflows


def _design_screen_specs(
    prototype: dict[str, Any] | None,
    prototype_spec: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    route_by_screen: dict[str, str] = {}
    for item in _as_list(_as_dict(prototype_spec).get("routes")):
        route = _as_dict(item)
        screen_id = str(route.get("screen_id") or "").strip()
        path = str(route.get("path") or "").strip()
        if screen_id and path and screen_id not in route_by_screen:
            route_by_screen[screen_id] = path
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(_as_dict(prototype).get("screens"))):
        screen = _as_dict(item)
        title = str(screen.get("title") or "").strip()
        if not title:
            continue
        screen_id = str(screen.get("id") or f"screen-{index + 1}")
        specs.append(
            {
                "id": screen_id,
                "title": title[:120],
                "purpose": str(screen.get("purpose") or "").strip()[:180],
                "layout": str(screen.get("layout") or "").strip()[:64],
                "primary_actions": [
                    str(action).strip()[:80]
                    for action in _as_list(screen.get("primary_actions"))
                    if str(action).strip()
                ][:4],
                "module_count": len(_as_list(screen.get("modules"))),
                "route_path": route_by_screen.get(screen_id),
            }
        )
    return specs


def _design_artifact_completeness(variant: dict[str, Any]) -> dict[str, Any]:
    prototype = _as_dict(variant.get("prototype"))
    prototype_spec = _as_dict(variant.get("prototype_spec"))
    prototype_app = _as_dict(variant.get("prototype_app"))
    implementation_brief = _as_dict(variant.get("implementation_brief"))
    primary_workflows = _as_list(variant.get("primary_workflows"))
    screen_specs = _as_list(variant.get("screen_specs"))
    checks = {
        "preview_html": bool(str(variant.get("preview_html") or "").strip()),
        "prototype": bool(prototype),
        "prototype_spec": bool(prototype_spec),
        "prototype_app": bool(prototype_app),
        "implementation_brief": bool(implementation_brief),
        "decision_scope": bool(_as_dict(variant.get("decision_scope"))),
        "decision_context_fingerprint": bool(str(variant.get("decision_context_fingerprint") or "").strip()),
        "scorecard": bool(_as_dict(variant.get("scorecard"))),
        "selection_rationale": bool(_as_dict(variant.get("selection_rationale"))),
        "approval_packet": bool(_as_dict(variant.get("approval_packet"))),
        "primary_workflows": bool(primary_workflows),
        "screen_specs": bool(screen_specs),
    }
    present = [name for name, ok in checks.items() if ok]
    missing = [name for name, ok in checks.items() if not ok]
    completeness_score = round(len(present) / max(len(checks), 1), 2)
    status = "complete" if not missing else "partial" if completeness_score >= 0.6 else "incomplete"
    return {
        "score": completeness_score,
        "status": status,
        "present": present,
        "missing": missing,
        "screen_count": len(_as_list(prototype.get("screens"))),
        "workflow_count": len(primary_workflows),
        "route_count": len(_as_list(prototype_spec.get("routes"))),
    }


def _design_preview_source_label(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized == "llm":
        return "LLMプレビュー"
    if normalized == "repaired":
        return "再構成プレビュー"
    return "テンプレートプレビュー"


def _design_variant_freshness(
    *,
    current_fingerprint: str,
    variant_fingerprint: str,
    artifact_completeness: dict[str, Any],
    preview_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = str(current_fingerprint or "").strip()
    variant = str(variant_fingerprint or "").strip()
    completeness_status = str(_as_dict(artifact_completeness).get("status") or "unknown")
    preview_payload = _as_dict(preview_meta)
    reasons: list[str] = []
    if current and variant and current != variant:
        status = "stale"
        reasons.append("planning/research decision context changed after this design was generated")
    elif current and variant:
        status = "fresh"
    else:
        status = "unknown"
        reasons.append("decision context fingerprint is incomplete")
    if completeness_status != "complete":
        reasons.append("design artifact contract is incomplete")
    if preview_payload.get("validation_ok") is False:
        reasons.append("design preview does not satisfy the preview contract")
    return {
        "status": status,
        "can_handoff": (
            status == "fresh"
            and completeness_status == "complete"
            and preview_payload.get("validation_ok") is True
        ),
        "current_fingerprint": current or None,
        "variant_fingerprint": variant or None,
        "reasons": reasons,
    }


def _design_scorecard_dimension(scorecard: dict[str, Any] | None, dimension_id: str) -> float:
    for item in _as_list(_as_dict(scorecard).get("dimensions")):
        payload = _as_dict(item)
        if str(payload.get("id") or "") == dimension_id:
            return float(payload.get("score", 0.0) or 0.0)
    return 0.0


def _design_selection_reasons(
    *,
    variant: dict[str, Any],
    scorecard: dict[str, Any],
    preview_meta: dict[str, Any],
) -> list[str]:
    prototype = _as_dict(variant.get("prototype"))
    voice = _design_variant_voice(
        variant_id=str(variant.get("id") or ""),
        visual_style=str(_as_dict(prototype.get("visual_direction")).get("visual_style") or ""),
        kind=_infer_prototype_context_kind(prototype),
    )
    reasons: list[str] = [voice["selection_summary"]]
    if _design_scorecard_dimension(scorecard, "operator_clarity") >= 0.85:
        reasons.append("主要判断、次の一手、状態変化を同じ視野で捉えられる。")
    if _design_scorecard_dimension(scorecard, "evidence_traceability") >= 0.8:
        reasons.append("根拠、承認、成果物の系譜が一貫した成果物としてつながっている。")
    if preview_meta.get("validation_ok") is True:
        reasons.append("プレビューが自己完結したプロダクト画面として成立している。")
    if len(_as_list(_as_dict(variant.get("implementation_brief")).get("technical_choices"))) >= 2:
        reasons.append("技術判断が具体化されており、開発への引き継ぎが曖昧になりにくい。")
    if float(preview_meta.get("copy_quality_score", 0.0) or 0.0) >= 0.9:
        reasons.append("画面文言がオペレーター向けの実製品トーンに揃っている。")
    return _dedupe_strings(reasons)[:4]


def _design_selection_tradeoffs(
    *,
    variant: dict[str, Any],
    preview_meta: dict[str, Any],
) -> list[str]:
    app_shell = _as_dict(_as_dict(variant.get("prototype")).get("app_shell"))
    density = str(app_shell.get("density") or "").lower()
    tradeoffs: list[str] = []
    if str(variant.get("id") or "").strip().lower() == "gemini-designer":
        tradeoffs.append("余白を活かした比較面なので、同時に監視できる状態数は制御室型より少ない。")
    elif density == "high":
        tradeoffs.append("情報密度が高いため、初見ユーザー向けには視線誘導と状態強調を維持する必要がある。")
    else:
        tradeoffs.append("余白を優先しているため、同時監視できる情報量は制御室型より少ない。")
    if _as_list(preview_meta.get("copy_issues")):
        tradeoffs.append("画面文言に内部用語や混在表現が残らないよう、承認前の文言監修が必要。")
    return _dedupe_strings(tradeoffs)[:4]


def _design_approval_packet(
    variant: dict[str, Any],
    *,
    selected: bool = False,
    guardrails_override: list[str] | None = None,
) -> dict[str, Any]:
    payload = _as_dict(variant)
    prototype = _as_dict(payload.get("prototype"))
    voice = _design_variant_voice(
        variant_id=str(payload.get("id") or ""),
        visual_style=str(_as_dict(prototype.get("visual_direction")).get("visual_style") or ""),
        kind=_infer_prototype_context_kind(prototype),
    )
    narrative = _as_dict(payload.get("narrative"))
    preview_meta = _as_dict(payload.get("preview_meta"))
    workflows = [str(item.get("name") or "").strip() for item in _as_list(payload.get("primary_workflows")) if isinstance(item, dict)]
    screen_titles = [str(item.get("title") or "").strip() for item in _as_list(payload.get("screen_specs")) if isinstance(item, dict)]
    must_keep = _dedupe_strings(
        [
            f"主要フロー「{workflows[0]}」と承認判断を同じ文脈で往復できること。" if workflows else "",
            f"「{screen_titles[0]}」で次の一手と保留理由がひと目で分かること。" if screen_titles else "",
            "根拠、承認、成果物の系譜を別々の導線に分断しないこと。",
            "モバイルでも主要状態と差し戻し理由が追えること。",
        ]
    )[:4]
    normalized_guardrails = [
        _design_preview_text(item)
        for item in _as_list(guardrails_override)
        if str(item).strip()
    ]
    guardrails = _dedupe_strings(
        normalized_guardrails
        + [
            "画面上に内部ID、実装用語、英語の混在コピーを出さないこと。",
            "主要操作のコントラストとフォーカス状態を下げないこと。",
            "承認理由、差し戻し理由、次の一手をファーストビューに残すこと。",
            "プレビュー契約を壊す外部アセット依存を追加しないこと。",
        ]
    )[:4]
    review_checklist = _dedupe_strings(
        [
            "主要 4 画面以上でテーブル / 指標 / 状態 / フォームが揃っている。",
            "承認または差し戻しの理由を、その場で根拠と照合できる。",
            "成果物の系譜と復旧導線が運用者目線で読める。",
            "日本語コピーが製品画面として自然で、内部メモ語が見えない。",
        ]
    )[:4]
    preview_source_label = _design_preview_source_label(str(preview_meta.get("source") or ""))
    handoff_summary = (
        f"{voice['selection_summary']} 主要 {len(screen_titles)} 画面と {len(workflows)} 本の運用フローを束ね、{preview_source_label}まで含めて承認レビューに渡せる。"
        if screen_titles or workflows
        else "主要画面、主要フロー、プレビュー品質までそろえた設計基準。"
    )
    operator_fallback = voice["operator_promise"] if selected else voice["selection_summary"]
    operator_promise = (
        _preview_copy_or_fallback(
            _design_preview_text(str(narrative.get("experience_thesis") or "").strip()),
            fallback=operator_fallback,
            max_length=220,
        )
        or operator_fallback
    )
    return {
        "operator_promise": operator_promise[:220],
        "must_keep": must_keep,
        "guardrails": guardrails,
        "review_checklist": review_checklist,
        "handoff_summary": handoff_summary[:220],
    }


def _design_selection_rationale(
    variant: dict[str, Any],
    *,
    selected: bool = False,
    summary_override: str = "",
    reasons_override: list[str] | None = None,
    tradeoffs_override: list[str] | None = None,
    approval_focus_override: list[str] | None = None,
) -> dict[str, Any]:
    payload = _as_dict(variant)
    prototype = _as_dict(payload.get("prototype"))
    voice = _design_variant_voice(
        variant_id=str(payload.get("id") or ""),
        visual_style=str(_as_dict(prototype.get("visual_direction")).get("visual_style") or ""),
        kind=_infer_prototype_context_kind(prototype),
    )
    scorecard = _as_dict(payload.get("scorecard"))
    preview_meta = _as_dict(payload.get("preview_meta"))
    normalized_reason_overrides = [
        _design_preview_text(item)
        for item in _as_list(reasons_override)
        if str(item).strip() and not _preview_copy_needs_rewrite(item, max_length=120)
    ]
    normalized_tradeoff_overrides = [
        _design_preview_text(item)
        for item in _as_list(tradeoffs_override)
        if str(item).strip() and not _preview_copy_needs_rewrite(item, max_length=120)
    ]
    normalized_focus_overrides = [
        _design_preview_text(item)
        for item in _as_list(approval_focus_override)
        if str(item).strip() and not _preview_copy_needs_rewrite(item, max_length=96)
    ]
    reasons = _dedupe_strings(normalized_reason_overrides + _design_selection_reasons(variant=payload, scorecard=scorecard, preview_meta=preview_meta))[:4]
    tradeoffs = _dedupe_strings(normalized_tradeoff_overrides + _design_selection_tradeoffs(variant=payload, preview_meta=preview_meta))[:4]
    approval_focus = _dedupe_strings(
        normalized_focus_overrides
        + [
            "承認理由と根拠リンクを同じ面に残す。",
            "差し戻し時の復旧導線をプレビューと引き継ぎの両方で守る。",
            "画面文言を運用者向けの日本語プロダクト文脈に揃える。",
        ]
    )[:4]
    summary = (
        _preview_copy_or_fallback(summary_override.strip(), fallback="", max_length=160)
        or voice["selection_summary"]
        or (reasons[0] if reasons else "")
        or "主要フロー、根拠追跡、承認への引き継ぎの整合が最も高い案。"
    )
    confidence = round(
        max(
            float(payload.get("selection_score", 0.0) or 0.0),
            float(scorecard.get("overall_score", 0.0) or 0.0),
        ),
        2,
    )
    return {
        "summary": summary[:220],
        "reasons": reasons,
        "tradeoffs": tradeoffs,
        "approval_focus": approval_focus,
        "confidence": confidence,
        "verdict": "selected" if selected else "candidate",
    }


def _design_scorecard(
    *,
    scores: dict[str, Any] | None,
    primary_workflows: list[dict[str, Any]],
    screen_specs: list[dict[str, Any]],
    implementation_brief: dict[str, Any] | None,
    preview_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    score_payload = _as_dict(scores)
    preview_payload = _as_dict(preview_meta)
    brief = _as_dict(implementation_brief)
    preview_quality = float(preview_payload.get("quality_score", 0.0) or 0.0)
    copy_quality = float(preview_payload.get("copy_quality_score", 0.0) or 0.0)
    preview_source = _design_preview_source_label(str(preview_payload.get("source") or ""))
    interaction_count = len(_as_list(preview_payload.get("interactive_features")))
    workflow_signal_count = len(_as_list(preview_payload.get("workflow_signals")))
    workflow_signals = {str(item) for item in _as_list(preview_payload.get("workflow_signals")) if str(item)}
    validation_issues = {str(item) for item in _as_list(preview_payload.get("validation_issues")) if str(item)}
    technical_choices = _as_list(brief.get("technical_choices"))
    system_shape = " ".join(str(item) for item in _as_list(brief.get("system_shape")) if str(item))
    lead_screens = " / ".join(
        str(_as_dict(item).get("title") or "").strip()
        for item in screen_specs[:2]
        if str(_as_dict(item).get("title") or "").strip()
    )
    lead_flows = " / ".join(
        str(_as_dict(item).get("name") or "").strip()
        for item in primary_workflows[:2]
        if str(_as_dict(item).get("name") or "").strip()
    )
    evidence_traceability = min(
        1.0,
        0.25 * min(len(screen_specs) / 4.0, 1.0)
        + 0.2 * min(len(primary_workflows) / 2.0, 1.0)
        + (0.2 if "evidence" in workflow_signals else 0.0)
        + (0.2 if "lineage" in workflow_signals else 0.0)
        + (0.15 if brief else 0.0),
    )
    rework_resilience = min(
        1.0,
        (0.28 if "recovery" in workflow_signals else 0.0)
        + (0.22 if "approval" in workflow_signals else 0.0)
        + (0.2 if re.search(r"checkpoint|復旧|差し戻し|rework|recover", system_shape, re.IGNORECASE) else 0.0)
        + 0.15 * min(len(technical_choices) / 3.0, 1.0)
        + (0.15 if preview_payload.get("validation_ok") is True else 0.0),
    )
    mobile_fidelity = min(
        1.0,
        (0.3 if "missing_responsive_breakpoint" not in validation_issues else 0.0)
        + 0.2 * min(len(screen_specs) / 4.0, 1.0)
        + 0.2 * min(interaction_count / 4.0, 1.0)
        + 0.15 * preview_quality
        + 0.15 * copy_quality,
    )
    implementation_stability = min(
        1.0,
        0.72 * float(score_payload.get("code_quality", 0.0) or 0.0)
        + 0.18 * min(len(technical_choices) / 4.0, 1.0)
        + 0.1 * min(len(_as_list(brief.get("delivery_slices"))) / 4.0, 1.0),
    )
    accessibility_score = min(
        1.0,
        0.8 * float(score_payload.get("accessibility", 0.0) or 0.0)
        + (0.12 if "missing_accessibility_annotations" not in validation_issues else 0.0)
        + 0.08 * copy_quality,
    )
    dimensions = [
        {
            "id": "operator_clarity",
            "label": "運用明快さ",
            "score": round(float(score_payload.get("ux_quality", 0.0) or 0.0), 2),
            "evidence": (
                f"{lead_screens or f'{len(screen_specs)} 画面'}で主要判断、次の一手、状態変化を同じ視界で追える。"
                if screen_specs
                else "主要判断と次の一手の関係を運用者目線で整理している。"
            ),
        },
        {
            "id": "evidence_traceability",
            "label": "根拠追跡",
            "score": round(evidence_traceability, 2),
            "evidence": (
                f"{lead_flows or f'{len(primary_workflows)} フロー'}と {len(screen_specs)} 画面に根拠・承認・系譜の接点を保持。"
            ),
        },
        {
            "id": "rework_resilience",
            "label": "差し戻し耐性",
            "score": round(rework_resilience, 2),
            "evidence": (
                "差し戻し・復旧・承認の導線が同じ成果物と技術判断に乗っている。"
                if "recovery" in workflow_signals or "approval" in workflow_signals
                else "差し戻しや復旧の導線は追加確認が必要。"
            ),
        },
        {
            "id": "mobile_fidelity",
            "label": "モバイル忠実度",
            "score": round(mobile_fidelity, 2),
            "evidence": (
                f"{preview_source} / {preview_payload.get('screen_count_estimate') or len(screen_specs)} 画面 / "
                f"{interaction_count} 種の操作要素 / 文言品質 {int(copy_quality * 100)}。"
            ),
        },
        {
            "id": "implementation_stability",
            "label": "実装安定性",
            "score": round(implementation_stability, 2),
            "evidence": (
                f"{len(technical_choices)} 件の技術判断と {len(_as_list(brief.get('agent_lanes')))} 本の実装レーンを保持。"
            ),
        },
        {
            "id": "accessibility",
            "label": "アクセシビリティ",
            "score": round(accessibility_score, 2),
            "evidence": (
                "ARIA 注記と状態ラベルが確認できる。"
                if "missing_accessibility_annotations" not in validation_issues
                else "アクセシビリティ注記と状態ラベルの追加確認が必要。"
            ),
        },
    ]
    overall = round(
        sum(float(item.get("score", 0.0) or 0.0) for item in dimensions) / max(len(dimensions), 1),
        2,
    )
    return {
        "overall_score": overall,
        "summary": (
            f"{lead_screens or f'{len(screen_specs)} 画面'}を基準面に、"
            f"{lead_flows or f'{len(primary_workflows)} フロー'}を回し、{preview_source}で整合を確認。"
        ),
        "dimensions": dimensions,
    }


def _design_variant_selection_score(variant: dict[str, Any]) -> float:
    payload = _as_dict(variant)
    scores = _as_dict(payload.get("scores"))
    preview = _as_dict(payload.get("preview_meta"))
    completeness = _as_dict(payload.get("artifact_completeness"))
    scorecard = _as_dict(payload.get("scorecard"))
    brief = _as_dict(payload.get("implementation_brief"))
    preview_quality = float(preview.get("quality_score", 0.0) or 0.0)
    copy_quality = float(preview.get("copy_quality_score", 0.0) or 0.0)
    source = str(preview.get("source") or "")
    validation_ok = bool(preview.get("validation_ok"))
    copy_issue_count = len(_as_list(preview.get("copy_issues")))
    source_bonus = (
        0.05
        if source == "llm" and validation_ok
        else 0.03
        if source == "repaired" and validation_ok
        else 0.01
        if validation_ok
        else -0.08
    )
    marketing_penalty = 0.08 if _as_list(preview.get("marketing_terms_detected")) else 0.0
    copy_penalty = min(copy_issue_count, 3) * 0.03
    operator_clarity = _design_scorecard_dimension(scorecard, "operator_clarity")
    evidence_traceability = _design_scorecard_dimension(scorecard, "evidence_traceability")
    rework_resilience = _design_scorecard_dimension(scorecard, "rework_resilience")
    mobile_fidelity = _design_scorecard_dimension(scorecard, "mobile_fidelity")
    implementation_stability = _design_scorecard_dimension(scorecard, "implementation_stability")
    accessibility_score = _design_scorecard_dimension(scorecard, "accessibility")
    composite = (
        0.18 * operator_clarity
        + 0.17 * evidence_traceability
        + 0.14 * rework_resilience
        + 0.12 * mobile_fidelity
        + 0.14 * implementation_stability
        + 0.12 * accessibility_score
        + 0.05 * preview_quality
        + 0.04 * copy_quality
        + 0.04 * float(completeness.get("score", 0.0) or 0.0)
        + 0.02 * float(scorecard.get("overall_score", 0.0) or 0.0)
        + source_bonus
        - marketing_penalty
        - copy_penalty
    )
    return round(max(0.0, min(composite, 1.0)), 4)


def _rank_design_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for variant in variants:
        enriched = dict(variant)
        enriched["selection_score"] = _design_variant_selection_score(enriched)
        ranked.append(enriched)
    return sorted(
        ranked,
        key=lambda item: (
            -float(item.get("selection_score", 0.0) or 0.0),
            -float(_as_dict(item.get("scores")).get("ux_quality", 0.0) or 0.0),
            str(item.get("model", "")),
        ),
    )


def _resolve_selected_design_id(
    variants: list[dict[str, Any]],
    judge_selected_id: str,
) -> str:
    if not variants:
        return ""
    judge_selected = str(judge_selected_id or "").strip()
    if not judge_selected:
        return str(variants[0].get("id") or "")
    preferred = next((item for item in variants if str(item.get("id") or "") == judge_selected), None)
    if preferred is None:
        return str(variants[0].get("id") or "")
    top_score = float(variants[0].get("selection_score", 0.0) or 0.0)
    preferred_score = float(preferred.get("selection_score", 0.0) or 0.0)
    return judge_selected if top_score - preferred_score <= 0.02 else str(variants[0].get("id") or "")


def _apply_design_judge_enrichment(
    variants: list[dict[str, Any]],
    *,
    selected_design_id: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    judge_payload = _as_dict(payload)
    winner_summary = str(judge_payload.get("winner_summary") or judge_payload.get("winnerSummary") or "").strip()
    winner_reasons = [str(item) for item in _as_list(judge_payload.get("winner_reasons") or judge_payload.get("winnerReasons")) if str(item).strip()]
    winner_tradeoffs = [str(item) for item in _as_list(judge_payload.get("winner_tradeoffs") or judge_payload.get("winnerTradeoffs")) if str(item).strip()]
    approval_guardrails = [str(item) for item in _as_list(judge_payload.get("approval_guardrails") or judge_payload.get("approvalGuardrails")) if str(item).strip()]
    enriched_variants: list[dict[str, Any]] = []
    for variant in variants:
        variant_payload = dict(variant)
        is_selected = str(variant_payload.get("id") or "") == selected_design_id
        variant_payload["selection_rationale"] = _design_selection_rationale(
            variant_payload,
            selected=is_selected,
            summary_override=winner_summary if is_selected else "",
            reasons_override=winner_reasons if is_selected else None,
            tradeoffs_override=winner_tradeoffs if is_selected else None,
            approval_focus_override=approval_guardrails if is_selected else None,
        )
        variant_payload["approval_packet"] = _design_approval_packet(
            variant_payload,
            selected=is_selected,
            guardrails_override=approval_guardrails if is_selected else None,
        )
        enriched_variants.append(variant_payload)
    return enriched_variants


def _enrich_design_variant_contract(
    variant: dict[str, Any],
    *,
    current_decision_context_fingerprint: str = "",
) -> dict[str, Any]:
    enriched = dict(variant)
    prototype_kind = _infer_prototype_context_kind(enriched.get("prototype"))
    prototype = _sanitize_design_prototype(_as_dict(enriched.get("prototype")), kind=prototype_kind)
    enriched["prototype"] = prototype
    prototype_spec = _as_dict(enriched.get("prototype_spec"))
    preview_html = str(enriched.get("preview_html") or "")
    preview_seed = _as_dict(enriched.get("preview_meta"))
    preview_meta = _design_preview_meta(
        preview_html,
        source=str(preview_seed.get("source") or "template"),
        extraction_ok=bool(preview_seed.get("extraction_ok")),
        fallback_reason=str(preview_seed.get("fallback_reason") or ""),
        prototype=prototype,
    )
    preview_passthrough_keys = {
        "template_version",
        "repaired_from_source",
        "repair_actions",
        "candidate_validation_ok",
        "candidate_validation_issues",
    }
    for key in preview_passthrough_keys:
        if key in preview_seed:
            preview_meta[key] = preview_seed.get(key)
    primary_workflows = _design_primary_workflows(prototype)
    screen_specs = _design_screen_specs(prototype, prototype_spec)
    enriched["preview_meta"] = preview_meta
    enriched["primary_workflows"] = primary_workflows
    enriched["screen_specs"] = screen_specs
    enriched["scorecard"] = _design_scorecard(
        scores=_as_dict(enriched.get("scores")),
        primary_workflows=primary_workflows,
        screen_specs=screen_specs,
        implementation_brief=_as_dict(enriched.get("implementation_brief")),
        preview_meta=preview_meta,
    )
    enriched["selection_rationale"] = _design_selection_rationale(enriched)
    enriched["approval_packet"] = _design_approval_packet(enriched)
    enriched["artifact_completeness"] = _design_artifact_completeness(enriched)
    enriched["freshness"] = _design_variant_freshness(
        current_fingerprint=current_decision_context_fingerprint or str(_as_dict(enriched.get("decision_scope")).get("fingerprint") or ""),
        variant_fingerprint=str(enriched.get("decision_context_fingerprint") or ""),
        artifact_completeness=_as_dict(enriched.get("artifact_completeness")),
        preview_meta=preview_meta,
    )
    return enriched


def _compile_design_preview_html(
    variant: dict[str, Any],
    state: dict[str, Any],
) -> str:
    payload = _as_dict(variant)
    analysis = _as_dict(state.get("analysis"))
    spec = str(state.get("spec") or payload.get("pattern_name") or "Product workspace")
    selected_features = _selected_feature_names(state)
    title = _preview_title(spec)
    subtitle = str(payload.get("description") or payload.get("rationale") or payload.get("pattern_name") or title)
    return _build_preview_html(
        title=title,
        subtitle=subtitle,
        primary=str(payload.get("primary_color") or "#2563eb"),
        accent=str(payload.get("accent_color") or "#f59e0b"),
        features=selected_features or ["Autonomous workflow", "Approval gates", "Quality review"],
        prototype=_as_dict(payload.get("prototype")),
        design_tokens=_as_dict(analysis.get("design_tokens")),
        milestones=[dict(item) for item in _as_list(state.get("milestones")) if isinstance(item, dict)],
    )


def _repair_design_variant_preview(
    variant: dict[str, Any],
    *,
    state: dict[str, Any],
    repair_reason: str,
) -> dict[str, Any]:
    payload = dict(variant)
    prior_preview_meta = _as_dict(payload.get("preview_meta"))
    candidate_html = str(payload.get("preview_html") or "")
    candidate_meta = dict(prior_preview_meta)
    payload["preview_candidate_html"] = candidate_html
    payload["preview_candidate_meta"] = candidate_meta
    payload["preview_html"] = _compile_design_preview_html(payload, state)
    payload["preview_meta"] = {
        "source": "repaired",
        "template_version": _DESIGN_TEMPLATE_PREVIEW_VERSION,
        "extraction_ok": bool(candidate_meta.get("extraction_ok")),
        "fallback_reason": repair_reason,
        "repaired_from_source": str(candidate_meta.get("source") or "unknown"),
        "repair_actions": ["recompiled_from_canonical_spec"],
        "candidate_validation_ok": bool(candidate_meta.get("validation_ok")),
        "candidate_validation_issues": list(_as_list(candidate_meta.get("validation_issues"))),
    }
    return _enrich_design_variant_contract(
        payload,
        current_decision_context_fingerprint=(
            str(_decision_context_from_state(state, compact=True).get("fingerprint") or "")
            or str(_as_dict(payload.get("decision_scope")).get("fingerprint") or "")
        ),
    )


def _design_preview_validator_handler(source_variant_id: str):
    def handler(node_id: str, state: dict[str, Any]) -> NodeResult:
        variant_key = f"{source_variant_id}_variant"
        raw_variant = _as_dict(state.get(variant_key))
        if not raw_variant:
            return NodeResult(
                state_patch={_node_state_key(node_id, "preview_validation"): {"status": "missing", "source_variant_id": source_variant_id}},
                artifacts=[],
                metrics={"validation_mode": "missing-variant"},
            )
        current_fingerprint = str(_decision_context_from_state(state, compact=True).get("fingerprint") or "")
        enriched_variant = _enrich_design_variant_contract(
            raw_variant,
            current_decision_context_fingerprint=current_fingerprint,
        )
        preview_meta = _as_dict(enriched_variant.get("preview_meta"))
        validation_issues = [str(item) for item in _as_list(preview_meta.get("validation_issues")) if str(item).strip()]
        repaired = preview_meta.get("validation_ok") is not True
        if repaired:
            enriched_variant = _repair_design_variant_preview(
                enriched_variant,
                state=state,
                repair_reason="preview_contract_repaired",
            )
        final_preview_meta = _as_dict(enriched_variant.get("preview_meta"))
        validation_summary = {
            "status": "repaired" if repaired else "passed",
            "source_variant_id": source_variant_id,
            "preview_source": final_preview_meta.get("source"),
            "candidate_source": preview_meta.get("source"),
            "repaired": repaired,
            "validation_ok": bool(final_preview_meta.get("validation_ok")),
            "issues": validation_issues,
            "fallback_reason": final_preview_meta.get("fallback_reason"),
        }
        return NodeResult(
            state_patch={
                variant_key: enriched_variant,
                _node_state_key(node_id, "preview_validation"): validation_summary,
            },
            artifacts=_artifacts(
                {
                    "name": f"{source_variant_id}-preview-validation",
                    "kind": "design",
                    **validation_summary,
                }
            ),
            metrics={
                "validation_mode": "deterministic-repair",
                "repaired": repaired,
            },
        )

    return handler


def _design_variant_payload(
    *,
    node_id: str,
    model_name: str,
    pattern_name: str,
    description: str,
    primary: str,
    accent: str,
    selected_features: list[str],
    spec: str,
    analysis: dict[str, Any] | None = None,
    rationale: str = "",
    quality_focus: list[str] | None = None,
    score_overrides: dict[str, Any] | None = None,
    provider_note: str = "",
    prototype_overrides: dict[str, Any] | None = None,
    decision_context_fingerprint: str = "",
    decision_scope: dict[str, Any] | None = None,
    token_usage: TokenUsage | None = None,
    cost_override: float | None = None,
    model_ref: str = "",
    narrative_overrides: dict[str, Any] | None = None,
    plan_estimates: list[dict[str, Any]] | None = None,
    selected_preset: str = "",
    target_language: str = "ja",
    implementation_brief_overrides: dict[str, Any] | None = None,
    preview_html_override: str = "",
    preview_meta_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scores = {
        "ux_quality": round(0.78 + (0.02 if "Minimal" in pattern_name else 0.0), 2),
        "code_quality": 0.82,
        "performance": round(0.86 - (0.03 if "Dashboard" in pattern_name else 0.0), 2),
        "accessibility": round(0.84 + (0.04 if "Minimal" in pattern_name else 0.0), 2),
    }
    for score_name, default in tuple(scores.items()):
        if score_overrides is None:
            continue
        scores[score_name] = _clamp_score(score_overrides.get(score_name), default=default)
    preview_features = selected_features or ["Autonomous workflow", "Approval gates", "Quality review"]
    usage = token_usage or _design_variant_usage_estimate(
        selected_features=preview_features,
        pattern_name=pattern_name,
        description=description,
        prototype_overrides=prototype_overrides,
    )
    analysis_payload = _as_dict(analysis)
    prototype = _build_design_prototype(
        spec=spec,
        analysis=analysis_payload,
        selected_features=preview_features,
        pattern_name=pattern_name,
        description=description,
        prototype_overrides=prototype_overrides,
    )
    prototype.setdefault("design_anchor", {})
    prototype["design_anchor"]["variant_id"] = node_id
    design_tokens = _as_dict(analysis_payload.get("design_tokens"))
    narrative = _build_design_narrative(
        description=description,
        selected_features=preview_features,
        decision_scope=decision_scope,
        prototype=prototype,
        provider_note=provider_note,
        overrides=narrative_overrides,
    )
    implementation_brief = _build_design_implementation_brief(
        spec=spec,
        analysis=analysis_payload,
        selected_features=preview_features,
        prototype=prototype,
        decision_scope=decision_scope,
        plan_estimates=plan_estimates,
        selected_preset=selected_preset,
        quality_focus=quality_focus,
        overrides=implementation_brief_overrides,
    )
    preview_title = _preview_title(spec)
    canonical_quality_focus = list(quality_focus or [])
    prototype_spec = build_prototype_spec(
        title=preview_title,
        subtitle=description,
        primary=primary,
        accent=accent,
        features=preview_features,
        prototype=prototype,
        design_tokens=design_tokens,
        decision_scope=decision_scope,
        quality_focus=canonical_quality_focus,
    )
    prototype_app = build_nextjs_prototype_app(
        title=preview_title,
        subtitle=description,
        primary=primary,
        accent=accent,
        prototype_spec=prototype_spec,
    )
    preview_source = "llm" if preview_html_override else "template"
    variant = {
        "id": node_id,
        "model": model_name,
        "pattern_name": pattern_name,
        "description": description,
        "preview_html": preview_html_override or _build_preview_html(
            title=preview_title,
            subtitle=description,
            primary=primary,
            accent=accent,
            features=preview_features,
            prototype=prototype,
            design_tokens=design_tokens,
        ),
        "prototype_spec": prototype_spec,
        "prototype_app": prototype_app,
        "prototype": prototype,
        "primary_color": primary,
        "accent_color": accent,
        "tokens": {"in": usage.input_tokens, "out": usage.output_tokens},
        "cost_usd": _estimate_design_variant_cost(
            model_name=model_name,
            usage=usage,
            model_ref=model_ref,
            cost_override=cost_override,
        ),
        "scores": scores,
        "rationale": rationale or description,
        "quality_focus": list(quality_focus or []),
        "narrative": narrative,
        "implementation_brief": implementation_brief,
        "preview_meta": {
            "source": preview_source,
            "template_version": _DESIGN_TEMPLATE_PREVIEW_VERSION if preview_source == "template" else None,
            "extraction_ok": bool(preview_html_override),
            "fallback_reason": "",
        },
    }
    if preview_meta_overrides:
        variant["preview_meta"] = {
            **_as_dict(variant.get("preview_meta")),
            **_as_dict(preview_meta_overrides),
        }
    if decision_context_fingerprint:
        variant["decision_context_fingerprint"] = decision_context_fingerprint
    if decision_scope:
        variant["decision_scope"] = decision_scope
    if provider_note:
        variant["provider_note"] = provider_note
    localized_variant = backfill_design_localization(variant, target_language=target_language)
    localized_quality_focus = [
        str(item)
        for item in _as_list(localized_variant.get("quality_focus"))
        if str(item).strip()
    ] or canonical_quality_focus
    localized_prototype = _as_dict(localized_variant.get("prototype")) or prototype
    localized_prototype_spec = build_prototype_spec(
        title=preview_title,
        subtitle=str(localized_variant.get("description") or description),
        primary=primary,
        accent=accent,
        features=preview_features,
        prototype=localized_prototype,
        design_tokens=design_tokens,
        decision_scope=decision_scope,
        quality_focus=localized_quality_focus,
    )
    localized_variant["prototype_spec"] = localized_prototype_spec
    localized_variant["prototype_app"] = build_nextjs_prototype_app(
        title=preview_title,
        subtitle=str(localized_variant.get("description") or description),
        primary=primary,
        accent=accent,
        prototype_spec=localized_prototype_spec,
    )
    if preview_html_override:
        localized_variant["preview_html"] = preview_html_override
    else:
        localized_variant["preview_html"] = _build_preview_html(
            title=preview_title,
            subtitle=str(localized_variant.get("description") or description),
            primary=primary,
            accent=accent,
            features=preview_features,
            prototype=localized_prototype,
            design_tokens=design_tokens,
        )
    localized_variant["preview_meta"] = dict(_as_dict(variant.get("preview_meta")))
    return _enrich_design_variant_contract(
        localized_variant,
        current_decision_context_fingerprint=decision_context_fingerprint,
    )


def _development_quality_snapshot(
    state: dict[str, Any],
    *,
    code: str,
) -> dict[str, Any]:
    milestones = []
    for raw in state.get("milestones", []) or []:
        if not isinstance(raw, dict):
            continue
        criteria = str(raw.get("criteria", ""))
        score = _milestone_score(criteria, code)
        milestones.append(
            {
                "id": str(raw.get("id", "")),
                "name": str(raw.get("name", "")),
                "status": "satisfied" if score >= 0.6 else "not_satisfied",
                "reason": (
                    "Build contains the required structural signals."
                    if score >= 0.6
                    else "Criteria is only partially represented in the current build artifact."
                ),
                "score": round(score, 2),
            }
        )
    if not milestones:
        milestones.append(
            {
                "id": "alpha-default",
                "name": "Alpha readiness",
                "status": "satisfied" if "<html" in code.lower() else "not_satisfied",
                "reason": (
                    "Generated build is previewable and structurally complete."
                    if "<html" in code.lower()
                    else "No previewable build artifact was generated."
                ),
                "score": 1.0 if "<html" in code.lower() else 0.0,
            }
        )
    findings = []
    if "eval(" in code:
        findings.append("Avoid eval() in generated artifacts.")
    if "innerHTML =" in code:
        findings.append("Prefer DOM-safe rendering over innerHTML assignment.")
    if "<main" not in code.lower():
        findings.append("Include a semantic <main> landmark.")
    if "aria-" not in code.lower():
        findings.append("Add ARIA labels to actionable controls.")
    if "viewport" not in code.lower():
        findings.append("Include responsive viewport metadata for mobile quality.")
    delivery_plan = _as_dict(state.get("delivery_plan"))
    code_workspace = _as_dict(delivery_plan.get("code_workspace"))
    repo_execution = _as_dict(state.get("repo_execution")) or _as_dict(delivery_plan.get("repo_execution"))
    work_unit_results = []
    for raw_unit in _as_list(delivery_plan.get("work_unit_contracts")):
        unit = _as_dict(raw_unit)
        checks = [
            str(item).strip()
            for item in _as_list(unit.get("acceptance_criteria"))
            if str(item).strip()
        ] or [
            str(item).strip()
            for item in _as_list(unit.get("qa_checks"))
            if str(item).strip()
        ]
        scores = [_milestone_score(check, code) for check in checks[:3]]
        score = max(scores) if scores else (1.0 if "<html" in code.lower() else 0.0)
        work_unit_results.append(
            {
                "id": str(unit.get("work_package_id") or unit.get("id") or "").strip(),
                "wave_index": int(unit.get("wave_index", 0) or 0),
                "status": "satisfied" if score >= 0.55 else "not_satisfied",
            }
        )
    repo_findings: list[str] = []
    if code_workspace:
        if not repo_execution:
            repo_findings.append("Real repo execution has not completed.")
        elif repo_execution.get("ready") is not True:
            repo_findings.extend(
                [
                    str(item)
                    for item in _as_list(repo_execution.get("errors"))
                    if str(item).strip()
                ]
            )
            if not repo_findings:
                repo_findings.append("Real repo execution did not reach a build-ready state.")
    security_status = "pass" if not findings else "warning"
    satisfied = sum(1 for item in milestones if _as_dict(item).get("status") == "satisfied")
    blockers = [
        f"Milestone not satisfied: {item['name']}"
        for item in milestones
        if _as_dict(item).get("status") != "satisfied"
    ]
    blockers.extend(
        f"Work unit not satisfied: {item['id']}"
        for item in work_unit_results
        if _as_dict(item).get("status") != "satisfied"
    )
    blockers.extend(findings)
    blockers.extend(repo_findings)
    return {
        "milestone_results": milestones,
        "work_unit_results": work_unit_results,
        "security_report": {
            "status": security_status,
            "findings": findings or ["No obvious unsafe DOM execution pattern was detected."],
        },
        "repo_execution_report": repo_execution,
        "milestones_satisfied": satisfied,
        "milestones_total": len(milestones),
        "blockers": blockers,
    }


def _skill_plan_state_key(node_id: str) -> str:
    return f"{node_id}_skill_plan"


def _delegation_state_key(node_id: str) -> str:
    return f"{node_id}_delegations"


def _peer_feedback_state_key(node_id: str) -> str:
    return f"{node_id}_peer_feedback"


def _is_non_blocking_review_finding(text: Any) -> bool:
    message = str(text or "").strip().lower()
    if not message:
        return False
    return message.startswith("no obvious ") or message.startswith("no blocking ")


def _phase_blueprint_for_node(phase: str, node_id: str) -> dict[str, Any]:
    phase_blueprint = build_lifecycle_phase_blueprints("catalog").get(phase, {})
    for agent in _as_list(phase_blueprint.get("team")):
        if isinstance(agent, dict) and str(agent.get("id", "")) == node_id:
            return dict(agent)
    return {}


def _phase_quality_targets(phase: str) -> list[str]:
    phase_blueprint = build_lifecycle_phase_blueprints("catalog").get(phase, {})
    return [
        str(item.get("title", ""))
        for item in _as_list(phase_blueprint.get("quality_gates"))
        if isinstance(item, dict) and str(item.get("title", "")).strip()
    ]


def _phase_support_skills(phase: str) -> list[str]:
    if phase == "research":
        return [
            "market-research",
            "competitive-intelligence",
            "evidence-audit",
            "counterexample-generation",
            "cross-examination",
            "decision-calibration",
        ]
    if phase == "planning":
        return [
            "persona-design",
            "use-case-design",
            "feature-prioritization",
            "scope-challenge",
            "assumption-audit",
            "decision-calibration",
        ]
    if phase == "design":
        return ["design-critique", "accessibility-review", "performance-review"]
    if phase == "development":
        return [
            "code-review",
            "delivery-review",
            "security-review",
            "safety-review",
            "quality-assurance",
            "acceptance-testing",
        ]
    return []


def _peer_recommendation_payload(
    *,
    peer_name: str,
    skill_name: str,
    phase: str,
    artifact_payload: dict[str, Any],
    quality_targets: list[str],
) -> dict[str, Any]:
    code = str(artifact_payload.get("code", "") or artifact_payload.get("preview_html", "") or "")
    recommendations: list[str] = []
    strengths: list[str] = []
    blockers: list[str] = []
    summary = f"{peer_name} reviewed {skill_name} for {phase}."

    if peer_name == "research-fabric":
        sources = [_as_dict(item) for item in _as_list(artifact_payload.get("sources")) if _as_dict(item)]
        summary = f"{peer_name} reviewed {len(sources)} grounded sources for {phase}."
        strengths.extend(
            [
                "The research artifact keeps claim context attached to concrete source packets.",
                "The review can distinguish grounded evidence from missing evidence.",
            ]
        )
        recommendations.extend(
            [
                "Mix vendor pages with neutral analyst or practitioner sources before finalizing claims.",
                "Call out where the result is based on public web evidence versus the project brief.",
                "Prefer source diversity over adding more snippets from the same domain.",
            ]
        )
        if len({str(item.get("host", "")) for item in sources if str(item.get("host", "")).strip()}) < 2:
            blockers.append("Research should rely on at least two distinct grounded domains before planning.")
    elif peer_name == "design-critic":
        pattern_name = str(artifact_payload.get("pattern_name", "Design concept") or "Design concept")
        summary = f"{peer_name} validated the {pattern_name} concept for clarity and accessibility."
        strengths.extend(
            [
                "Concept presents a differentiated visual direction.",
                "The baseline is legible enough for operator workflows.",
            ]
        )
        recommendations.extend(
            [
                "Strengthen mobile density control with clearer section hierarchy.",
                "Raise contrast around primary operator actions and status labels.",
                "Make approval and readiness signals visible above the fold.",
            ]
        )
        if "viewport" not in code.lower():
            blockers.append("Design preview should explicitly represent responsive viewport behavior.")
    elif peer_name == "safety-guardian":
        summary = f"{peer_name} audited security and safety posture for {phase}."
        if "eval(" in code:
            blockers.append("Remove eval() from the generated artifact.")
        if "innerHTML =" in code:
            blockers.append("Avoid direct innerHTML assignment in preview code.")
        recommendations.extend(
            [
                "Prefer semantic landmarks and explicit ARIA labels for operator controls.",
                "Keep release actions distinct from navigation actions.",
            ]
        )
        if not blockers:
            strengths.append("No high-risk DOM execution pattern was detected.")
    elif peer_name == "build-craft":
        summary = f"{peer_name} reviewed build execution quality for {phase}."
        recommendations.extend(
            [
                "Promote the main task flow into a stronger hero-to-detail narrative.",
                "Reduce visual noise and make milestone state transitions easier to scan.",
                "Ensure mobile layout keeps action clusters within one thumb zone.",
            ]
        )
        if "<main" not in code.lower():
            blockers.append("Integrated build should include a semantic <main> landmark.")
        if "aria-" not in code.lower():
            blockers.append("Integrated build should label actionable controls with ARIA.")
    elif peer_name == "quality-lab":
        summary = f"{peer_name} validated delivery readiness for {phase}."
        recommendations.extend(
            [
                "Represent each milestone with explicit pass/fail evidence in the UI.",
                "Surface next action, blocker count, and release confidence in one panel.",
            ]
        )
        if "viewport" not in code.lower():
            blockers.append("Build should include responsive viewport metadata.")
    else:
        recommendations.extend(quality_targets[:2] or [f"Preserve quality gate coverage for {phase}."])

    return {
        "summary": summary,
        "strengths": strengths,
        "recommendations": recommendations,
        "blockers": blockers,
        "quality_targets": quality_targets,
    }


async def _delegate_to_lifecycle_peer(
    *,
    phase: str,
    node_id: str,
    peer_name: str,
    skill_name: str,
    artifact_payload: dict[str, Any],
    reason: str,
    quality_targets: list[str],
) -> dict[str, Any] | None:
    from pylon.lifecycle.operator_console import build_lifecycle_peer_registry
    from pylon.protocols.a2a.client import A2AClient
    from pylon.protocols.a2a.server import A2AServer
    from pylon.protocols.a2a.types import (
        A2AMessage,
        A2ATask,
        Part,
        TaskState,
    )
    from pylon.protocols.a2a.types import (
        Artifact as A2AArtifact,
    )

    peer_registry = build_lifecycle_peer_registry()
    peer_card = peer_registry.get(peer_name)
    if peer_card is None:
        return None

    sender = f"lifecycle:{phase}:{node_id}"
    server = A2AServer(allowed_peers={sender})

    @server.on_task
    async def _handle_peer_task(task: A2ATask) -> A2ATask:
        recommendation = _peer_recommendation_payload(
            peer_name=peer_name,
            skill_name=skill_name,
            phase=phase,
            artifact_payload=artifact_payload,
            quality_targets=quality_targets,
        )
        task.add_message(
            A2AMessage(
                role="agent",
                parts=[Part(type="text", content=recommendation["summary"])],
            )
        )
        task.add_artifact(
            A2AArtifact(
                name=f"{peer_name}-{skill_name}-review",
                description=recommendation["summary"],
                parts=[Part(type="data", content=recommendation)],
                metadata={
                    "peer": peer_name,
                    "skill": skill_name,
                    "phase": phase,
                    "sender": node_id,
                },
            )
        )
        task.transition_to(TaskState.COMPLETED)
        return task

    client = A2AClient(server, sender=sender)
    submitted = A2ATask(
        id=f"{phase}:{node_id}:{peer_name}:{skill_name}:{uuid.uuid4().hex[:8]}",
        messages=[
            A2AMessage(
                role="agent",
                parts=[
                    Part(
                        type="text",
                        content=f"Delegate {skill_name} to {peer_name} for {phase}/{node_id}: {reason}",
                    )
                ],
            )
        ],
        artifacts=[
            A2AArtifact(
                name=f"{node_id}-context",
                description=f"Lifecycle context for {phase}/{node_id}",
                parts=[Part(type="data", content=_compact_lifecycle_value(artifact_payload))],
                metadata={"phase": phase, "node_id": node_id},
            )
        ],
        metadata={
            "phase": phase,
            "node_id": node_id,
            "peer": peer_name,
            "skill": skill_name,
            "reason": reason,
        },
    )
    completed = await client.send_task(submitted)
    task_payload = completed.to_dict()
    review_payload = _as_dict(_as_list(task_payload.get("artifacts"))[-1]) if _as_list(task_payload.get("artifacts")) else {}
    review_data = _as_dict(_as_list(review_payload.get("parts"))[0].get("content")) if _as_list(review_payload.get("parts")) else {}
    return {
        "peer": peer_name,
        "skill": skill_name,
        "status": str(task_payload.get("state", TaskState.COMPLETED.value)),
        "reason": reason,
        "peerCard": peer_card.to_dict(),
        "task": task_payload,
        "feedback": review_data,
    }


async def _plan_node_collaboration(
    *,
    phase: str,
    node_id: str,
    state: dict[str, Any],
    objective: str,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from pylon.lifecycle.operator_console import (
        build_lifecycle_peer_registry,
        build_lifecycle_skill_catalog,
    )

    agent = _phase_blueprint_for_node(phase, node_id)
    skill_catalog = build_lifecycle_skill_catalog()
    peer_registry = build_lifecycle_peer_registry()
    own_skills = _resolve_lifecycle_assigned_skills(
        phase=phase,
        node_id=node_id,
        include_blueprint_defaults=True,
    )
    candidate_skills = _dedupe_strings(own_skills + _phase_support_skills(phase))
    peer_candidates: list[dict[str, Any]] = []
    for skill_name in candidate_skills:
        peers = peer_registry.find_by_skill(skill_name)
        for peer in peers:
            peer_candidates.append(
                {
                    "peer": peer.name,
                    "skill": skill_name,
                    "description": str(next((item.description for item in peer.skills if item.name == skill_name), "")),
                }
            )
    quality_targets = _phase_quality_targets(phase)
    fallback_delegations = [
        {
            "peer": item["peer"],
            "skill": item["skill"],
            "reason": f"Use {item['peer']} to raise the quality bar on {item['skill']}.",
        }
        for item in peer_candidates[:2]
    ]
    fallback_plan = {
        "phase": phase,
        "node_id": node_id,
        "agent_label": str(agent.get("label", node_id) or node_id),
        "objective": objective,
        "candidate_skills": candidate_skills,
        "selected_skills": own_skills[:2] or candidate_skills[:2],
        "quality_targets": quality_targets,
        "delegations": fallback_delegations,
        "mode": "deterministic-reference",
        "execution_note": f"Start with {', '.join((own_skills[:2] or candidate_skills[:2])[:2])} and escalate quality via peer review when available.",
        "skill_details": {
            skill_name: _as_dict(skill_catalog.get(skill_name))
            for skill_name in candidate_skills
        },
    }
    if not _provider_backed_lifecycle_available(provider_registry):
        return fallback_plan, []

    payload, llm_events, _ = await _lifecycle_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-skill-plan-{phase}-{node_id}",
        static_instruction=(
            "You are a multi-agent skill planner. Return JSON only. "
            "Choose the smallest high-leverage skill set and delegate only when a peer materially raises quality."
        ),
        user_prompt=(
            "Return JSON with keys selected_skills, quality_targets, delegations, execution_note.\n"
            f"Phase: {phase}\n"
            f"Node: {node_id}\n"
            f"Objective: {objective}\n"
            f"Spec: {state.get('spec')}\n"
            f"Candidate skills: {candidate_skills}\n"
            f"Peer candidates: {peer_candidates}\n"
            f"Quality targets: {quality_targets}\n"
        ),
        phase=phase,
        node_id=node_id,
    )
    if not isinstance(payload, dict):
        return {**fallback_plan, "mode": "provider-backed-fallback"}, llm_events

    selected_skills = [
        skill_name
        for skill_name in [str(item) for item in _as_list(payload.get("selected_skills")) if str(item).strip()]
        if skill_name in candidate_skills
    ] or fallback_plan["selected_skills"]
    allowed_peers = {(item["peer"], item["skill"]) for item in peer_candidates}
    delegations = []
    for raw in _as_list(payload.get("delegations")):
        item = _as_dict(raw)
        peer = str(item.get("peer", "")).strip()
        skill_name = str(item.get("skill", "")).strip()
        if (peer, skill_name) not in allowed_peers:
            continue
        delegations.append(
            {
                "peer": peer,
                "skill": skill_name,
                "reason": str(item.get("reason") or f"Delegate {skill_name} to {peer}."),
            }
        )
    plan = {
        **fallback_plan,
        "selected_skills": selected_skills,
        "quality_targets": [
            str(item)
            for item in _as_list(payload.get("quality_targets"))
            if str(item).strip()
        ] or quality_targets,
        "delegations": delegations or fallback_delegations,
        "mode": "provider-backed-autonomous",
        "execution_note": str(payload.get("execution_note") or fallback_plan["execution_note"]),
    }
    return plan, llm_events

def _phase_statuses() -> list[dict[str, Any]]:
    return [
        {
            "phase": phase,
            "status": "available" if index == 0 else "locked",
            "version": 1,
        }
        for index, phase in enumerate(PHASE_ORDER)
    ]


def default_lifecycle_project_record(
    project_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "id": str(project_id),
        "projectId": str(project_id),
        "tenant_id": tenant_id,
        "name": str(project_id),
        "description": "",
        "githubRepo": None,
        "productIdentity": {
            "companyName": "",
            "productName": "",
            "officialWebsite": "",
            "officialDomains": [],
            "aliases": [],
            "excludedEntityNames": [],
        },
        "spec": "",
        "autonomyLevel": "A3",
        "researchConfig": {
            "competitorUrls": [],
            "depth": "standard",
            "outputLanguage": "ja",
            "recoveryMode": "auto",
        },
        "researchOperatorDecision": None,
        "research": None,
        "analysis": None,
        "features": [],
        "milestones": [],
        "designVariants": [],
        "selectedDesignId": None,
        "approvalStatus": "pending",
        "approvalComments": [],
        "approvalRequestId": None,
        "buildCode": None,
        "buildCost": 0.0,
        "buildIteration": 0,
        "buildDecisionFingerprint": None,
        "milestoneResults": [],
        "deliveryPlan": None,
        "developmentExecution": None,
        "developmentHandoff": None,
        "valueContract": None,
        "outcomeTelemetryContract": None,
        "planEstimates": [],
        "selectedPreset": "standard",
        "orchestrationMode": "workflow",
        "governanceMode": "governed",
        "phaseStatuses": _phase_statuses(),
        "deployChecks": [],
        "releases": [],
        "feedbackItems": [],
        "recommendations": [],
        "artifacts": [],
        "decisionLog": [],
        "skillInvocations": [],
        "delegations": [],
        "phaseRuns": [],
        "requirements": None,
        "requirementsConfig": {
            "earsEnabled": True,
            "interactiveClarification": True,
            "confidenceFloor": 0.6,
        },
        "reverseEngineering": None,
        "taskDecomposition": None,
        "dcsAnalysis": None,
        "technicalDesign": None,
        "createdAt": now,
        "updatedAt": now,
        "savedAt": now,
    }


def merge_lifecycle_project_record(
    existing: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)
    for field_name in _MUTABLE_PROJECT_FIELDS:
        if field_name in patch:
            merged[field_name] = patch[field_name]
    now = _utc_now_iso()
    merged["updatedAt"] = now
    merged["savedAt"] = now
    return merged


def build_lifecycle_phase_blueprints(project_id: str) -> dict[str, Any]:
    return {
        "research": {
            "phase": "research",
            "title": "Research Swarm",
            "summary": "市場、競合、ユーザー、技術を並列に調べて証拠ベースの仮説を作る。",
            "team": [
                _agent_blueprint(
                    "competitor-analyst",
                    "Competitor Scout",
                    "競合比較と差別化ポイント抽出",
                    tools=["http", "browser"],
                    skills=["market-research", "competitive-intelligence"],
                ),
                _agent_blueprint(
                    "market-researcher",
                    "Market Researcher",
                    "市場規模、トレンド、需要シグナルの整理",
                    tools=["http", "browser"],
                    skills=["market-sizing", "trend-analysis"],
                ),
                _agent_blueprint(
                    "user-researcher",
                    "User Researcher",
                    "想定ユーザーと課題仮説の生成",
                    skills=["jtbd-analysis", "persona-research"],
                ),
                _agent_blueprint(
                    "tech-evaluator",
                    "Tech Evaluator",
                    "技術実現性と導入リスクの査定",
                    tools=["http"],
                    skills=["architecture-review", "risk-analysis"],
                ),
                _agent_blueprint(
                    "research-synthesizer",
                    "Research Synthesizer",
                    "調査結果を claim ledger に統合し、反証前の thesis pack を作る",
                    skills=["synthesis", "decision-support"],
                ),
                _agent_blueprint(
                    "evidence-librarian",
                    "Evidence Librarian",
                    "根拠と source link を正規化し、採択に使える証拠台帳を作る",
                    tools=["http", "browser"],
                    skills=["evidence-audit", "source-normalization"],
                ),
                _agent_blueprint(
                    "devils-advocate-researcher",
                    "Devil's Advocate",
                    "市場仮説、競合優位、ユーザー課題の反証を生成する",
                    skills=["counterexample-generation", "risk-analysis"],
                ),
                _agent_blueprint(
                    "cross-examiner",
                    "Cross Examiner",
                    "claim ごとに矛盾、弱い根拠、未解決の問いを洗い出す",
                    skills=["cross-examination", "fact-checking"],
                ),
                _agent_blueprint(
                    "research-judge",
                    "Research Judge",
                    "反証を踏まえて surviving thesis と confidence を確定する",
                    skills=["decision-calibration", "portfolio-review"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("market-research", "research", "市場機会レポート"),
                _artifact_descriptor("competitor-map", "research", "競合比較マップ"),
                _artifact_descriptor("risk-register", "research", "初期リスク登録簿"),
                _artifact_descriptor("claim-ledger", "research", "claim / evidence / dissent ledger"),
            ],
            "quality_gates": [
                _quality_gate("source-grounding", "採択主張が source と evidence に接地している"),
                _quality_gate("counterclaim-coverage", "主要仮説に対する反証が生成されている"),
                _quality_gate("critical-dissent-resolved", "重大な dissent が未解決のまま残っていない"),
                _quality_gate("confidence-floor", "採択 thesis が planning に渡せる信頼度を満たしている"),
            ],
        },
        "planning": {
            "phase": "planning",
            "title": "Planning Council",
            "summary": "課題定義から feature 優先度、WBS、マイルストーンまでを設計する。",
            "team": [
                _agent_blueprint(
                    "persona-builder",
                    "Persona Builder",
                    "ペルソナ、ユーザーストーリー、感情動線を定義",
                    skills=["persona-design", "story-mapping"],
                ),
                _agent_blueprint(
                    "story-architect",
                    "Story Architect",
                    "JTBD、ユースケース、役割モデルを整理",
                    skills=["jtbd-analysis", "use-case-design"],
                ),
                _agent_blueprint(
                    "feature-analyst",
                    "Feature Analyst",
                    "KANO と実装コストから feature を優先付けする",
                    skills=["feature-prioritization", "kano-analysis"],
                ),
                _agent_blueprint(
                    "solution-architect",
                    "Solution Architect",
                    "マイルストーン、WBS、実装方針を作る",
                    skills=["wbs-planning", "solution-architecture"],
                ),
                _agent_blueprint(
                    "planning-synthesizer",
                    "Planning Synthesizer",
                    "企画 artifact を暫定プランへ統合し、反証可能な decision table を作る",
                    skills=["roadmapping", "program-planning"],
                ),
                _agent_blueprint(
                    "scope-skeptic",
                    "Scope Skeptic",
                    "feature scope を削る側から攻撃し、不要な実装を落とす",
                    skills=["scope-challenge", "feature-pruning"],
                ),
                _agent_blueprint(
                    "assumption-auditor",
                    "Assumption Auditor",
                    "persona、JTBD、市場仮説の弱い前提を監査する",
                    skills=["assumption-audit", "risk-analysis"],
                ),
                _agent_blueprint(
                    "negative-persona-challenger",
                    "Negative Persona Challenger",
                    "導入失敗や誤用を招くユーザー像を明示して穴を洗い出す",
                    skills=["negative-scenario-design", "persona-research"],
                ),
                _agent_blueprint(
                    "milestone-falsifier",
                    "Milestone Falsifier",
                    "milestone の曖昧さと検証不能な完了条件を攻撃する",
                    skills=["milestone-testing", "delivery-risk-analysis"],
                ),
                _agent_blueprint(
                    "planning-judge",
                    "Planning Judge",
                    "scope、assumption、milestone の surviving plan を確定する",
                    skills=["decision-calibration", "roadmapping"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("product-brief", "planning", "課題定義と価値仮説"),
                _artifact_descriptor("delivery-plan", "planning", "WBS と見積"),
                _artifact_descriptor("milestone-plan", "planning", "検証可能なマイルストーン"),
                _artifact_descriptor("decision-table", "planning", "採択 / 却下 / 保留の decision ledger"),
            ],
            "quality_gates": [
                _quality_gate("feature-traceability", "主要 feature が research claim と use case に接続されている"),
                _quality_gate("assumption-audit", "主要前提に対する監査結果が残っている"),
                _quality_gate("negative-persona-coverage", "失敗しやすい利用文脈が明示されている"),
                _quality_gate("milestone-falsifiability", "milestone が検証条件と失敗条件を持っている"),
            ],
        },
        "design": {
            "phase": "design",
            "title": "Design Jury",
            "summary": "強く差別化された 2 つの product prototype を生成し、判断しやすい最終候補に絞る。",
            "team": [
                _agent_blueprint(
                    "claude-designer",
                    "Concept Designer A",
                    "濃色で精密な control-room 案を生成",
                    skills=["ui-concepting", "visual-hierarchy"],
                ),
                _agent_blueprint(
                    "gemini-designer",
                    "Concept Designer B (KIMI)",
                    "KIMI K2.5 による明るく建築的な decision-studio 案を生成",
                    skills=["responsive-design", "component-patterns", "visual-systems"],
                ),
                _agent_blueprint(
                    "claude-preview-validator",
                    "Preview Validator A",
                    "Direction A の preview contract を検証し、必要なら canonical preview へ修復する",
                    skills=["artifact-validation", "design-contract-repair"],
                ),
                _agent_blueprint(
                    "gemini-preview-validator",
                    "Preview Validator B",
                    "Direction B の preview contract を検証し、必要なら canonical preview へ修復する",
                    skills=["artifact-validation", "design-contract-repair"],
                ),
                _agent_blueprint(
                    "design-evaluator",
                    "Design Judge",
                    "UX / code quality / performance / accessibility の観点で採点",
                    skills=["accessibility-review", "performance-review", "design-critique"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("design-candidates", "design", "複数の設計候補"),
                _artifact_descriptor("design-scorecard", "design", "採点結果と比較表"),
            ],
            "quality_gates": [
                _quality_gate("variant-diversity", "少なくとも 2 種類の設計アプローチが提示されている"),
                _quality_gate("a11y-floor", "全候補に基本的なアクセシビリティ考慮がある"),
                _quality_gate("preview-contract", "selected design の preview が contract を満たしている"),
            ],
        },
        "approval": {
            "phase": "approval",
            "title": "Approval Gate",
            "summary": "構想から設計までの artifact をレビューし、Go / Rework を決定する。",
            "team": [
                _agent_blueprint(
                    "approval-chair",
                    "Approval Chair",
                    "レビュー論点を整理して決裁情報をまとめる",
                    skills=["review-facilitation", "risk-summary"],
                )
            ],
            "artifacts": [
                _artifact_descriptor("approval-thread", "approval", "承認コメントと決定履歴"),
            ],
            "quality_gates": [
                _quality_gate("review-complete", "仕様、優先度、設計、マイルストーンが確認済み"),
            ],
        },
        "development": {
            "phase": "development",
            "title": "Autonomous Delivery Mesh",
            "summary": "承認済み context を dependency-aware delivery graph に展開し、衝突なく build から deploy handoff までを担う。",
            "team": [
                _agent_blueprint(
                    "planner",
                    "Build Planner",
                    "作業分解、依存順、merge 順、handoff 条件を定義",
                    skills=["task-routing", "implementation-planning"],
                ),
                _agent_blueprint(
                    "frontend-builder",
                    "Frontend Builder",
                    "画面構造と UI 実装を担当",
                    tools=["code-edit", "file-write"],
                    skills=["frontend-implementation", "responsive-ui"],
                ),
                _agent_blueprint(
                    "backend-builder",
                    "Backend Builder",
                    "データモデルと連携仕様を整理",
                    skills=["api-design", "domain-modeling"],
                ),
                _agent_blueprint(
                    "integrator",
                    "Integrator",
                    "成果物を単一の build artifact に統合",
                    tools=["code-edit", "file-write"],
                    skills=["integration", "artifact-assembly"],
                ),
                _agent_blueprint(
                    "qa-engineer",
                    "QA Engineer",
                    "受け入れ条件と milestone を検証",
                    skills=["acceptance-testing", "quality-assurance"],
                ),
                _agent_blueprint(
                    "security-reviewer",
                    "Security Reviewer",
                    "安全性と運用リスクを確認",
                    skills=["security-review", "safety-review"],
                ),
                _agent_blueprint(
                    "reviewer",
                    "Release Reviewer",
                    "最終レビューと build quality 判定",
                    skills=["code-review", "delivery-review"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("implementation-plan", "development", "実装方針と作業分解"),
                _artifact_descriptor("goal-spec", "development", "実装ゴールと contract 注入仕様"),
                _artifact_descriptor("delivery-plan", "development", "dependency-aware delivery graph"),
                _artifact_descriptor("delivery-waves", "development", "dependency-based execution waves"),
                _artifact_descriptor("work-unit-contracts", "development", "WU 単位の acceptance / QA / security contract"),
                _artifact_descriptor("build-artifact", "development", "プレビュー可能な build"),
                _artifact_descriptor("milestone-report", "development", "達成判定レポート"),
                _artifact_descriptor("deploy-handoff", "development", "deploy phase に渡す handoff packet"),
            ],
            "quality_gates": [
                _quality_gate("goal-spec", "承認済み context が goal spec と contract injection plan に分解されている"),
                _quality_gate("delivery-graph", "依存順と merge 順が定義された delivery graph がある"),
                _quality_gate("delivery-waves", "依存 DAG に基づく execution wave が定義されている"),
                _quality_gate("work-unit-contracts", "各 WU が acceptance / QA / security / repair policy を持っている"),
                _quality_gate("feature-coverage", "選択した主要機能が build に反映されている"),
                _quality_gate("milestone-readiness", "少なくとも alpha 相当のマイルストーンが満たされている"),
                _quality_gate("deploy-handoff", "deploy phase に渡せる handoff packet が揃っている"),
            ],
        },
        "deploy": {
            "phase": "deploy",
            "title": "Release Gate",
            "summary": "build artifact を品質ゲートに通し、配布可能な release として記録する。",
            "team": [
                _agent_blueprint(
                    "release-manager",
                    "Release Manager",
                    "品質ゲートと release 記録を管理",
                    skills=["release-management", "quality-gating"],
                )
            ],
            "artifacts": [
                _artifact_descriptor("deploy-checks", "deploy", "デプロイ前品質チェック"),
                _artifact_descriptor("release-record", "deploy", "公開可能な release 記録"),
            ],
            "quality_gates": [
                _quality_gate("release-ready", "HTML / responsive / a11y / security / performance が許容水準"),
            ],
        },
        "iterate": {
            "phase": "iterate",
            "title": "Iteration Engine",
            "summary": "実利用フィードバックを集約し、次の改善計画へ反映する。",
            "team": [
                _agent_blueprint(
                    "feedback-triager",
                    "Feedback Triager",
                    "フィードバックの分類と影響度評価",
                    skills=["feedback-analysis", "backlog-triage"],
                ),
                _agent_blueprint(
                    "roadmap-optimizer",
                    "Roadmap Optimizer",
                    "改善優先度と次の iteration 推奨を生成",
                    skills=["roadmap-optimization", "product-ops"],
                ),
            ],
            "artifacts": [
                _artifact_descriptor("feedback-backlog", "iterate", "投票付き改善バックログ"),
                _artifact_descriptor("iteration-recommendations", "iterate", "次アクション提案"),
            ],
            "quality_gates": [
                _quality_gate("feedback-closed-loop", "フィードバックが次の意思決定へ反映されている"),
            ],
        },
    }


def _agent_blueprint(
    agent_id: str,
    label: str,
    role: str,
    *,
    autonomy: str = "A2",
    tools: list[str] | None = None,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "label": label,
        "role": role,
        "autonomy": autonomy,
        "tools": list(tools or []),
        "skills": list(skills or []),
    }


def _artifact_descriptor(artifact_id: str, phase: str, title: str) -> dict[str, Any]:
    return {"id": artifact_id, "phase": phase, "title": title}


def _quality_gate(gate_id: str, title: str) -> dict[str, Any]:
    return {"id": gate_id, "title": title}


def build_lifecycle_workflow_definition(
    project_id: str,
    phase: str,
    *,
    project_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_id = f"lifecycle-{phase}-{project_id}"
    if phase == "research":
        project = {
            "version": "1",
            "name": "lifecycle-research",
            "description": "Research swarm with synthesis of competition, market, user, and technical signals.",
            "agents": {
                "competitor-analyst": _agent_def("competitive-intelligence", tools=["http", "browser"]),
                "market-researcher": _agent_def("market-sizing", tools=["http", "browser"]),
                "user-researcher": _agent_def("persona-research"),
                "tech-evaluator": _agent_def("technical-feasibility", tools=["http"]),
                "research-synthesizer": _agent_def("evidence-synthesis"),
                "evidence-librarian": _agent_def("evidence-audit", tools=["http", "browser"]),
                "devils-advocate-researcher": _agent_def("counterexample-generation"),
                "cross-examiner": _agent_def("cross-examination"),
                "research-judge": _agent_def("decision-calibration"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "competitor-analyst": {"agent": "competitor-analyst", "next": ["research-synthesizer"]},
                    "market-researcher": {"agent": "market-researcher", "next": ["research-synthesizer"]},
                    "user-researcher": {"agent": "user-researcher", "next": ["research-synthesizer"]},
                    "tech-evaluator": {"agent": "tech-evaluator", "next": ["research-synthesizer"]},
                    "research-synthesizer": {"agent": "research-synthesizer", "join_policy": "all_resolved", "next": ["evidence-librarian", "devils-advocate-researcher"]},
                    "evidence-librarian": {"agent": "evidence-librarian", "next": ["cross-examiner"]},
                    "devils-advocate-researcher": {"agent": "devils-advocate-researcher", "next": ["cross-examiner"]},
                    "cross-examiner": {
                        "agent": "cross-examiner",
                        "join_policy": "all_resolved",
                        "next": ["research-judge"],
                    },
                    "research-judge": {
                        "agent": "research-judge",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 0.8, "max_duration": "5m"},
        }
    elif phase == "planning":
        project = {
            "version": "1",
            "name": "lifecycle-planning",
            "description": "Planning council that turns research into personas, prioritized scope, and milestones.",
            "agents": {
                "persona-builder": _agent_def("persona-design"),
                "story-architect": _agent_def("story-mapping"),
                "feature-analyst": _agent_def("feature-prioritization"),
                "solution-architect": _agent_def("solution-architecture"),
                "planning-synthesizer": _agent_def("delivery-planning"),
                "scope-skeptic": _agent_def("scope-challenge"),
                "assumption-auditor": _agent_def("assumption-audit"),
                "negative-persona-challenger": _agent_def("negative-persona-challenge"),
                "milestone-falsifier": _agent_def("milestone-falsification"),
                "planning-judge": _agent_def("decision-calibration"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "persona-builder": {"agent": "persona-builder", "next": ["planning-synthesizer"]},
                    "story-architect": {"agent": "story-architect", "next": ["planning-synthesizer"]},
                    "feature-analyst": {"agent": "feature-analyst", "next": ["planning-synthesizer"]},
                    "solution-architect": {"agent": "solution-architect", "next": ["planning-synthesizer"]},
                    "planning-synthesizer": {"agent": "planning-synthesizer", "join_policy": "all_resolved", "next": ["scope-skeptic", "assumption-auditor", "negative-persona-challenger", "milestone-falsifier"]},
                    "scope-skeptic": {"agent": "scope-skeptic", "next": ["planning-judge"]},
                    "assumption-auditor": {"agent": "assumption-auditor", "next": ["planning-judge"]},
                    "negative-persona-challenger": {"agent": "negative-persona-challenger", "next": ["planning-judge"]},
                    "milestone-falsifier": {"agent": "milestone-falsifier", "next": ["planning-judge"]},
                    "planning-judge": {
                        "agent": "planning-judge",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 0.7, "max_duration": "6m"},
        }
    elif phase == "design":
        project = {
            "version": "1",
            "name": "lifecycle-design",
            "description": "Design jury that compares two elevated product directions and judges them on quality gates.",
            "agents": {
                "claude-designer": _agent_def("design-concept-a"),
                "gemini-designer": _agent_def("design-concept-b"),
                "claude-preview-validator": _agent_def("preview-contract-validator-a"),
                "gemini-preview-validator": _agent_def("preview-contract-validator-b"),
                "design-evaluator": _agent_def("design-judge"),
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "claude-designer": {"agent": "claude-designer", "next": ["claude-preview-validator"]},
                    "gemini-designer": {"agent": "gemini-designer", "next": ["gemini-preview-validator"]},
                    "claude-preview-validator": {"agent": "claude-preview-validator", "next": ["design-evaluator"]},
                    "gemini-preview-validator": {"agent": "gemini-preview-validator", "next": ["design-evaluator"]},
                    "design-evaluator": {
                        "agent": "design-evaluator",
                        "join_policy": "all_resolved",
                        "next": "END",
                    },
                },
            },
            "policy": {"max_cost_usd": 1.1, "max_duration": "8m", "require_approval_above": "A3"},
        }
    elif phase == "development":
        development_nodes = (
            _build_development_runtime_workflow_nodes(project_record)
            if isinstance(project_record, dict)
            else None
        )
        project = {
            "version": "1",
            "name": "lifecycle-development",
            "description": "Autonomous delivery mesh with dependency planning, conflict-safe implementation, real repo execution, QA, security, and deploy handoff review.",
            "agents": {
                "planner": _agent_def("build-planning"),
                "frontend-builder": _agent_def("frontend-implementation", tools=["code-edit", "file-write"]),
                "backend-builder": _agent_def("backend-implementation"),
                "integrator": _agent_def("artifact-integration", tools=["code-edit", "file-write"]),
                "repo-executor": _agent_def("repo-execution"),
                "qa-engineer": _agent_def("qa-review"),
                "security-reviewer": _agent_def("security-review"),
                "reviewer": _agent_def("release-review"),
            },
            "workflow": {
                "type": "graph",
                "nodes": development_nodes or {
                    "planner": {"agent": "planner", "next": ["frontend-builder", "backend-builder"]},
                    "frontend-builder": {"agent": "frontend-builder", "next": ["integrator"]},
                    "backend-builder": {"agent": "backend-builder", "next": ["integrator"]},
                    "integrator": {"agent": "integrator", "join_policy": "all_resolved", "next": ["repo-executor"]},
                    "repo-executor": {"agent": "repo-executor", "next": ["qa-engineer", "security-reviewer"]},
                    "qa-engineer": {"agent": "qa-engineer", "next": ["reviewer"]},
                    "security-reviewer": {"agent": "security-reviewer", "next": ["reviewer"]},
                    "reviewer": {"agent": "reviewer", "join_policy": "all_resolved", "next": "END"},
                },
            },
            "policy": {"max_cost_usd": 4.2, "max_duration": "24m", "require_approval_above": "A3"},
        }
    else:
        raise ValueError(f"Unsupported lifecycle phase: {phase}")
    return {"id": workflow_id, "project": project}


def _agent_def(role: str, *, tools: list[str] | None = None) -> dict[str, Any]:
    return {
        "role": role,
        "autonomy": "A2",
        "sandbox": "gvisor",
        "tools": list(tools or []),
    }


def build_lifecycle_workflow_handlers(
    phase: str,
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
    skill_runtime: SkillRuntime | None = None,
    tenant_id: str = "default",
    agent_skill_lookup: _LifecycleAgentSkillLookup | None = None,
    control_plane_skills: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def _wrap_handlers(handlers: dict[str, Any]) -> dict[str, Any]:
        wrapped: dict[str, Any] = {}

        def _wrap(handler: Any):
            async def invoke(node_id: str, state: dict[str, Any]):
                token = _LIFECYCLE_SKILL_CONTEXT.set(
                    {
                        "phase": phase,
                        "tenant_id": tenant_id,
                        "skill_runtime": skill_runtime,
                        "agent_skill_lookup": agent_skill_lookup,
                        "control_plane_skills": dict(control_plane_skills or {}),
                    }
                )
                try:
                    result = handler(node_id, state)
                    if inspect.isawaitable(result):
                        return await result
                    return result
                finally:
                    _LIFECYCLE_SKILL_CONTEXT.reset(token)

            return invoke

        for node_id, handler in handlers.items():
            wrapped[node_id] = _wrap(handler)
        return wrapped

    if phase == "research":
        return _wrap_handlers({
            "competitor-analyst": (
                lambda node_id, state: _research_competitor_autonomous_handler(
                    node_id,
                    state,
                    provider_registry=provider_registry,
                    llm_runtime=llm_runtime,
                )
                if _provider_backed_lifecycle_available(provider_registry)
                else _research_competitor_handler(node_id, state)
            ),
            "market-researcher": (
                lambda node_id, state: _research_market_autonomous_handler(
                    node_id,
                    state,
                    provider_registry=provider_registry,
                    llm_runtime=llm_runtime,
                )
                if _provider_backed_lifecycle_available(provider_registry)
                else _research_market_handler(node_id, state)
            ),
            "user-researcher": (
                lambda node_id, state: _research_user_autonomous_handler(
                    node_id,
                    state,
                    provider_registry=provider_registry,
                    llm_runtime=llm_runtime,
                )
                if _provider_backed_lifecycle_available(provider_registry)
                else _research_user_handler(node_id, state)
            ),
            "tech-evaluator": (
                lambda node_id, state: _research_tech_autonomous_handler(
                    node_id,
                    state,
                    provider_registry=provider_registry,
                    llm_runtime=llm_runtime,
                )
                if _provider_backed_lifecycle_available(provider_registry)
                else _research_tech_handler(node_id, state)
            ),
            "research-synthesizer": _research_synthesizer_handler,
            "evidence-librarian": _research_evidence_librarian_handler,
            "devils-advocate-researcher": lambda node_id, state: _research_devils_advocate_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "cross-examiner": lambda node_id, state: _research_cross_examiner_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "research-judge": lambda node_id, state: _research_judge_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        })
    if phase == "planning":
        return _wrap_handlers({
            "persona-builder": _planning_persona_handler,
            "story-architect": _planning_story_handler,
            "feature-analyst": _planning_feature_handler,
            "solution-architect": _planning_solution_handler,
            "planning-synthesizer": _planning_synthesizer_handler,
            "scope-skeptic": lambda node_id, state: _planning_scope_skeptic_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "assumption-auditor": lambda node_id, state: _planning_assumption_auditor_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "negative-persona-challenger": lambda node_id, state: _planning_negative_persona_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "milestone-falsifier": lambda node_id, state: _planning_milestone_falsifier_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "planning-judge": lambda node_id, state: _planning_judge_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        })
    if phase == "design":
        return _wrap_handlers({
            "claude-designer": _design_variant_handler(
                "Claude Sonnet 4.6",
                "Obsidian Control Atelier",
                "A premium dark product shell with editorial hierarchy, deliberate density, and crisp operator trust cues.",
                "#e7edf7",
                "#f59e0b",
                creative_brief=(
                    "Direction A should feel like a luxury control room for product operators: dark, precise, "
                    "architectural, and unmistakably not a generic dashboard."
                ),
                prototype_seed_overrides={
                    "prototype_kind": "control-center",
                    "navigation_style": "sidebar",
                    "density": "high",
                    "visual_style": "obsidian-atelier",
                    "display_font": "IBM Plex Sans",
                    "body_font": "IBM Plex Sans",
                    "screen_labels": ["判断デッキ", "調査復旧", "承認ゲート", "リネージ探索"],
                    "interaction_principles": [
                        "Keep evidence and the next action in one scan path.",
                        "Use contrast and calm spacing to create trust without dead space.",
                        "Make operator interventions feel deliberate and high-signal.",
                    ],
                },
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "gemini-designer": _design_variant_handler(
                "KIMI K2.5 / Direction B",
                "Ivory Signal Gallery",
                "A luminous product workspace with architectural pacing, bold navigation, and refined decision-focused surfaces.",
                "#14213d",
                "#2563eb",
                creative_brief=(
                    "Direction B should feel like an art-directed operations suite: brighter, more open, and more gallery-like, "
                    "but still dense enough for real operator work. Do not drift into a marketing hero, LP, or concept landing surface."
                ),
                prototype_seed_overrides={
                    "prototype_kind": "decision-studio",
                    "navigation_style": "top-nav",
                    "density": "medium",
                    "visual_style": "ivory-signal",
                    "display_font": "Avenir Next",
                    "body_font": "Hiragino Sans",
                    "screen_labels": ["フェーズワークスペース", "ラン台帳", "判断レビュー", "リリース準備"],
                    "interaction_principles": [
                        "Use asymmetry and generous framing to make dense information feel breathable.",
                        "Let navigation and review states read like a designed editorial system.",
                        "Keep mobile collapse graceful without losing the primary work surface.",
                    ],
                },
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "claude-preview-validator": _design_preview_validator_handler("claude-designer"),
            "gemini-preview-validator": _design_preview_validator_handler("gemini-designer"),
            "design-evaluator": lambda node_id, state: _design_evaluator_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        })
    if phase == "development":
        return _wrap_handlers({
            "planner": lambda node_id, state: _development_planner_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "frontend-builder": lambda node_id, state: _development_frontend_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "backend-builder": lambda node_id, state: _development_backend_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "integrator": lambda node_id, state: _development_integrator_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "repo-executor": _development_repo_executor_handler,
            "qa-engineer": _development_qa_handler,
            "security-reviewer": lambda node_id, state: _development_security_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
            "reviewer": lambda node_id, state: _development_reviewer_handler(
                node_id,
                state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            ),
        })
    raise ValueError(f"Unsupported lifecycle phase: {phase}")


def build_deploy_checks(project_record: dict[str, Any]) -> dict[str, Any]:
    build_code = str(project_record.get("buildCode") or "")
    feature_count = len(project_record.get("features") or [])
    selected_features = sum(
        1
        for item in project_record.get("features") or []
        if isinstance(item, dict) and item.get("selected") is True
    )
    delivery_plan = _as_dict(project_record.get("deliveryPlan"))
    code_workspace = _as_dict(delivery_plan.get("code_workspace"))
    workspace_paths = {
        str(_as_dict(item).get("path") or "").strip()
        for item in _as_list(code_workspace.get("files"))
        if str(_as_dict(item).get("path") or "").strip()
    }
    value_contract = _as_dict(project_record.get("valueContract"))
    outcome_telemetry_contract = _as_dict(project_record.get("outcomeTelemetryContract"))
    required_workspace_artifacts = {
        str(item).strip()
        for item in _as_list(outcome_telemetry_contract.get("workspace_artifacts"))
        if str(item).strip()
    }
    instrumentation_ready = bool(required_workspace_artifacts) and required_workspace_artifacts.issubset(workspace_paths)

    checks = [
        _deploy_check(
            "html-structure",
            "HTML structure",
            "pass" if "<html" in build_code.lower() and "<body" in build_code.lower() else "fail",
            "HTML document contains root structure.",
        ),
        _deploy_check(
            "responsive",
            "Responsive readiness",
            "pass"
            if "viewport" in build_code.lower() or "@media" in build_code.lower()
            else "warning",
            "Responsive viewport or media-query support is present.",
        ),
        _deploy_check(
            "a11y",
            "Accessibility floor",
            "pass"
            if any(token in build_code.lower() for token in ("aria-", "<main", "<nav", "<button"))
            else "warning",
            "Semantic landmarks and accessible controls are present.",
        ),
        _deploy_check(
            "security",
            "Security posture",
            "fail" if "eval(" in build_code or "innerHTML =" in build_code else "pass",
            "Avoids obvious unsafe DOM execution patterns.",
        ),
        _deploy_check(
            "performance",
            "Payload size",
            "pass" if len(build_code.encode("utf-8")) < 60_000 else "warning",
            "Generated payload stays within the local preview performance budget.",
        ),
        _deploy_check(
            "feature-coverage",
            "Feature coverage",
            "pass" if selected_features > 0 and feature_count > 0 else "warning",
            "Selected feature set is reflected in the generated artifact.",
        ),
        _deploy_check(
            VALUE_CONTRACT_ID,
            "Value contract readiness",
            "pass" if value_contract_ready(value_contract) else "fail",
            "Release should stay tied to personas, JTBD, IA key paths, and explicit success metrics.",
        ),
        _deploy_check(
            OUTCOME_TELEMETRY_CONTRACT_ID,
            "Outcome telemetry readiness",
            "pass" if outcome_telemetry_contract_ready(outcome_telemetry_contract) else "fail",
            "Release should carry success metrics, kill criteria, and telemetry events into iteration.",
        ),
        _deploy_check(
            "instrumentation-coverage",
            "Instrumentation coverage",
            "pass" if instrumentation_ready else "warning",
            "Workspace artifacts should materialize value and telemetry contracts so release evidence is replayable.",
        ),
    ]
    score_map = {"pass": 100, "warning": 70, "fail": 30}
    overall_score = round(sum(score_map[item["status"]] for item in checks) / len(checks))
    release_ready = all(item["status"] != "fail" for item in checks)
    return {
        "checks": checks,
        "summary": {
            "overallScore": overall_score,
            "releaseReady": release_ready,
            "passed": sum(1 for item in checks if item["status"] == "pass"),
            "warnings": sum(1 for item in checks if item["status"] == "warning"),
            "failed": sum(1 for item in checks if item["status"] == "fail"),
        },
    }


def build_release_record(project_record: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    checks_payload = build_deploy_checks(project_record)
    if not checks_payload["summary"]["releaseReady"]:
        raise ValueError("Lifecycle project is not release-ready")
    build_code = str(project_record.get("buildCode") or "")
    selected_design = str(project_record.get("selectedDesignId") or "")
    release_id = f"release-{uuid.uuid4().hex[:10]}"
    timestamp = _utc_now_iso()
    return {
        "id": release_id,
        "createdAt": timestamp,
        "version": f"v{max(_completed_phase_count(project_record), 1)}.0",
        "note": note.strip(),
        "selectedDesignId": selected_design,
        "artifactBytes": len(build_code.encode("utf-8")),
        "qualitySummary": checks_payload["summary"],
    }


def refresh_lifecycle_recommendations(project_record: dict[str, Any]) -> list[dict[str, Any]]:
    feedbacks = [
        item for item in project_record.get("feedbackItems", [])
        if isinstance(item, dict)
    ]
    recommendations: list[dict[str, Any]] = []
    if feedbacks:
        ordered = sorted(
            feedbacks,
            key=lambda item: (
                -int(item.get("votes", 0)),
                {"high": 0, "medium": 1, "low": 2}.get(str(item.get("impact", "medium")), 1),
            ),
        )
        top = ordered[0]
        recommendations.append(
            {
                "id": "top-feedback",
                "title": "Close the highest-signal feedback loop",
                "reason": str(top.get("text", "Most-voted feedback should be addressed first.")),
                "priority": "high",
            }
        )
    deploy_checks = [
        item for item in project_record.get("deployChecks", [])
        if isinstance(item, dict)
    ]
    failing_checks = [item for item in deploy_checks if item.get("status") == "fail"]
    if failing_checks:
        recommendations.append(
            {
                "id": "release-blocker",
                "title": "Resolve release blockers before the next deploy",
                "reason": ", ".join(str(item.get("label", item.get("id", ""))) for item in failing_checks),
                "priority": "critical",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "id": "expand-scope-carefully",
                "title": "Promote one Should feature into the next iteration",
                "reason": "The current lifecycle record has no blocking release or feedback issue, so the next value step is controlled scope expansion.",
                "priority": "medium",
            }
        )
    return recommendations


def _deploy_check(check_id: str, label: str, status: str, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
    }


def _completed_phase_count(project_record: dict[str, Any]) -> int:
    return sum(
        1
        for item in project_record.get("phaseStatuses", [])
        if isinstance(item, dict) and item.get("status") == "completed"
    )


_RESEARCH_PROPOSAL_NODES: tuple[str, ...] = (
    "competitor-analyst",
    "market-researcher",
    "user-researcher",
    "tech-evaluator",
)
_RESEARCH_REVIEW_NODES: tuple[str, ...] = (
    "evidence-librarian",
    "devils-advocate-researcher",
    "cross-examiner",
    "research-judge",
)
_PLANNING_PROPOSAL_NODES: tuple[str, ...] = (
    "persona-builder",
    "story-architect",
    "feature-analyst",
    "solution-architect",
)
_PLANNING_REVIEW_NODES: tuple[str, ...] = (
    "scope-skeptic",
    "assumption-auditor",
    "negative-persona-challenger",
    "milestone-falsifier",
    "planning-judge",
)
_SEVERITY_WEIGHT = {"critical": 0.22, "high": 0.14, "medium": 0.08, "low": 0.04}


def _node_state_key(node_id: str, suffix: str) -> str:
    return f"{node_id}_{suffix}"


def _provider_family(model_name: str) -> str:
    text = str(model_name or "").strip()
    return text.split("/", 1)[0] if "/" in text else (text or "deterministic")


def _phase_model_assignments(node_ids: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {node_id: (_preferred_lifecycle_model(node_id) or "deterministic-reference") for node_id in node_ids}


def _phase_low_diversity_mode(node_ids: list[str] | tuple[str, ...]) -> bool:
    families = {
        _provider_family(model_name)
        for model_name in _phase_model_assignments(node_ids).values()
        if model_name != "deterministic-reference"
    }
    return len(families) < 2


def _claim_entry(
    claim_id: str,
    *,
    statement: str,
    owner: str,
    category: str,
    evidence_ids: list[str],
    confidence: float = 0.7,
    status: str = "provisional",
    counterevidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": claim_id,
        "statement": statement,
        "owner": owner,
        "category": category,
        "evidence_ids": _dedupe_strings(evidence_ids),
        "counterevidence_ids": _dedupe_strings(list(counterevidence_ids or [])),
        "confidence": _clamp_score(confidence, default=0.7),
        "status": status,
    }


def _evidence_entry(
    evidence_id: str,
    *,
    source_ref: str,
    source_type: str,
    snippet: str,
    relevance: str,
    recency: str = "current cycle",
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "source_ref": source_ref,
        "source_type": source_type,
        "snippet": snippet,
        "recency": recency,
        "relevance": relevance,
    }


def _dissent_entry(
    dissent_id: str,
    *,
    claim_id: str,
    challenger: str,
    argument: str,
    severity: str,
    resolved: bool = False,
    recommended_test: str = "",
    resolution: str = "",
) -> dict[str, Any]:
    return {
        "id": dissent_id,
        "claim_id": claim_id,
        "challenger": challenger,
        "argument": argument,
        "severity": severity,
        "resolved": resolved,
        "recommended_test": recommended_test,
        "resolution": resolution,
    }


def _finding_entry(
    finding_id: str,
    *,
    title: str,
    challenger: str,
    severity: str,
    impact: str,
    recommendation: str,
    related_feature: str = "",
) -> dict[str, Any]:
    payload = {
        "id": finding_id,
        "title": title,
        "challenger": challenger,
        "severity": severity,
        "impact": impact,
        "recommendation": recommendation,
    }
    if related_feature:
        payload["related_feature"] = related_feature
    return payload


def _negative_persona_entry(
    persona_id: str,
    *,
    name: str,
    scenario: str,
    risk: str,
    mitigation: str,
) -> dict[str, Any]:
    return {
        "id": persona_id,
        "name": name,
        "scenario": scenario,
        "risk": risk,
        "mitigation": mitigation,
    }


def _collect_state_lists(
    state: dict[str, Any],
    *,
    node_ids: list[str] | tuple[str, ...],
    suffix: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node_id in node_ids:
        for raw in _as_list(state.get(_node_state_key(node_id, suffix))):
            record = _as_dict(raw)
            if record:
                items.append(record)
    return items


def _claim_confidence(
    *,
    evidence_count: int,
    unresolved_dissent: list[dict[str, Any]],
    default: float = 0.72,
) -> float:
    penalty = sum(_SEVERITY_WEIGHT.get(str(item.get("severity", "medium")), 0.08) for item in unresolved_dissent)
    return _clamp_score(default + min(evidence_count * 0.06, 0.18) - penalty, default=default)


def _claim_status(confidence: float, unresolved_dissent: list[dict[str, Any]]) -> str:
    severities = {str(item.get("severity", "")) for item in unresolved_dissent}
    if "critical" in severities or confidence < 0.58:
        return "blocked"
    if "high" in severities or confidence < 0.72:
        return "contested"
    return "accepted"


def _winning_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        claims,
        key=lambda item: (
            0 if str(item.get("status")) == "accepted" else 1,
            -float(item.get("confidence", 0.0) or 0.0),
            str(item.get("statement", "")),
        ),
    )
    winners = [item for item in ordered if str(item.get("status")) == "accepted"][:3]
    return winners or ordered[:2]


def _claim_statement_lookup(claims: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in claims:
        claim = _as_dict(item)
        claim_id = _normalize_space(claim.get("id"))
        statement = _first_research_text(claim.get("statement"), char_limit=220)
        if claim_id and statement:
            lookup[claim_id] = statement
    return lookup


def _resolved_winning_thesis_strings(
    values: Any,
    *,
    claims: list[dict[str, Any]],
    limit: int = 3,
    char_limit: int = 220,
) -> list[str]:
    claim_lookup = _claim_statement_lookup(claims)
    resolved: list[str] = []
    items = _as_list(values) if isinstance(values, list) else ([values] if values else [])
    for item in items:
        record = _as_dict(_parse_research_structured_value(item))
        claim_id = _normalize_space(record.get("claim_id") or record.get("id"))
        candidate = _first_research_text(item, char_limit=char_limit)
        if claim_id and claim_id in claim_lookup and (
            not candidate or _looks_like_machine_token(candidate) or candidate == claim_id
        ):
            candidate = claim_lookup[claim_id]
        elif candidate in claim_lookup:
            candidate = claim_lookup[candidate]
        candidate = _truncate_research_text(candidate, limit=char_limit)
        if not candidate or _looks_like_machine_token(candidate) or candidate in resolved:
            continue
        resolved.append(candidate)
        if len(resolved) >= limit:
            break
    return resolved


def _feature_supporting_claim_ids(state: dict[str, Any], *, limit: int = 2) -> list[str]:
    research = _as_dict(state.get("research"))
    winning = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item).get("status") == "accepted"]
    if not winning:
        winning = [_as_dict(item) for item in _as_list(research.get("claims"))]
    return [
        str(item.get("id"))
        for item in winning[:limit]
        if str(item.get("id", "")).strip()
    ]


def _build_feature_decisions(state: dict[str, Any], features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    supporting_claim_ids = _feature_supporting_claim_ids(state)
    decisions: list[dict[str, Any]] = []
    for item in features:
        feature = str(item.get("feature", "")).strip()
        if not feature:
            continue
        selected = item.get("selected") is True
        cost = str(item.get("implementation_cost", "medium"))
        decisions.append(
            {
                "feature": feature,
                "selected": selected,
                "supporting_claim_ids": supporting_claim_ids,
                "counterarguments": [],
                "rejection_reason": (
                    ""
                    if selected
                    else "Deliberately held for later to keep the first release scope falsifiable."
                ),
                "uncertainty": round(0.42 if cost == "high" else 0.24 if selected else 0.33, 2),
            }
        )
    return decisions


def _planning_selected_or_default_features(state: dict[str, Any]) -> list[dict[str, Any]]:
    features = [
        _as_dict(item)
        for item in (_as_list(state.get("feature_selections")) or _as_list(state.get("features")))
        if _as_dict(item)
    ]
    return features or _default_feature_selections_for_spec(state)


def _planning_use_cases_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = _as_dict(state.get("analysis"))
    use_cases = [_as_dict(item) for item in _as_list(state.get("use_cases")) if _as_dict(item)]
    if use_cases:
        return use_cases
    return [_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)]


def _planning_milestones_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = _as_dict(state.get("analysis"))
    milestones = [_as_dict(item) for item in _as_list(state.get("recommended_milestones")) if _as_dict(item)]
    if milestones:
        return milestones
    milestones = [_as_dict(item) for item in _as_list(analysis.get("recommended_milestones")) if _as_dict(item)]
    if milestones:
        return milestones
    return [_as_dict(item) for item in _as_list(_solution_bundle(state).get("recommended_milestones")) if _as_dict(item)]


def _planning_context_payload(
    state: dict[str, Any],
    *,
    features: list[dict[str, Any]] | None = None,
    personas: list[dict[str, Any]] | None = None,
    use_cases: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    design_tokens: dict[str, Any] | None = None,
    business_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = str(state.get("spec", ""))
    kind = _infer_product_kind(spec)
    research = _research_context(state, segment_from_spec=_segment_from_spec)
    selected_features = [
        str(item.get("feature", "")).strip()
        for item in (features or _planning_selected_or_default_features(state))
        if item.get("selected") is True and str(item.get("feature", "")).strip()
    ]
    persona_records = personas or _build_persona_bundle(state)[0]
    use_case_records = use_cases or _build_story_architecture_bundle(state).get("use_cases", [])
    milestone_records = milestones or _planning_milestones_from_state(state)
    style = _as_dict(_as_dict(design_tokens or _solution_bundle(state).get("design_tokens")).get("style"))
    business = _as_dict(business_model or _solution_bundle(state).get("business_model"))
    if kind == "operations":
        core_loop = "Turn grounded evidence into a governed plan, then carry the same decision context into design and build."
        north_star = "Operator trust: every phase decision should remain explainable, reviewable, and recoverable."
        experience_principles = [
            "Keep artifact lineage visible before automation breadth.",
            "Prefer lane-level recovery over full reruns.",
            "Make approval and rework states explicit in the primary workspace.",
        ]
        delivery_principles = [
            "Prove traceability and governance before expanding autonomous breadth.",
            "Treat degraded lanes as local recovery problems with explicit evidence gaps.",
            "Attach milestones to observable operator decisions, not narrative momentum.",
        ]
        market_notes = {
            "opportunities": (
                ["Enterprise and platform teams are actively evaluating governed multi-agent orchestration."]
                if research.get("opportunities")
                else []
            ),
            "threats": (
                ["Category noise is high, so differentiation must come from lineage, approvals, and recovery quality."]
                if research.get("threats")
                else []
            ),
        }
    elif kind == "commerce":
        core_loop = "Help buyers compare confidently and finish checkout without hesitation."
        north_star = "Purchase confidence: users should understand what to buy and why before checkout."
        experience_principles = [
            "Reduce ambiguity in comparison, pricing, and delivery.",
            "Keep conversion-critical states visible on mobile.",
            "Support operators with inventory and fulfillment clarity.",
        ]
        delivery_principles = [
            "Protect browse-to-buy completion before merchandising breadth.",
            "Measure hesitation around comparison and checkout states.",
            "Keep operational readiness tied to real order-handling flows.",
        ]
        market_notes = {
            "opportunities": (
                ["Demand exists, but it should be converted through faster comparison and clearer purchase confidence."]
                if research.get("opportunities")
                else []
            ),
            "threats": (
                ["Crowded commerce surfaces make hesitation and trust failures especially expensive."]
                if research.get("threats")
                else []
            ),
        }
    elif kind == "learning":
        core_loop = "Get the learner into a short, rewarding study loop that is easy to repeat."
        north_star = "Habit confidence: the product should help the learner return tomorrow."
        experience_principles = [
            "Show the next achievable step immediately.",
            "Keep guardian clarity high without overwhelming the learner.",
            "Favor short-session confidence over feature breadth.",
        ]
        delivery_principles = [
            "Ship the daily habit loop before enrichment systems.",
            "Keep interruption recovery tightly scoped.",
            "Tie milestones to repeatable learning behavior, not just surface completion.",
        ]
        market_notes = {
            "opportunities": (
                ["The opportunity is real only if the product proves short-session retention and repeatability."]
                if research.get("opportunities")
                else []
            ),
            "threats": (
                ["Users will churn quickly if the first routine feels too long or too hard."]
                if research.get("threats")
                else []
            ),
        }
    else:
        core_loop = "Move the user through the primary value path with minimal confusion."
        north_star = "Clarity first: users should understand the next action at every step."
        experience_principles = [
            "Shorten time-to-value before adding convenience layers.",
            "Keep current status and next action visible.",
            "Prefer progressive disclosure over breadth-first scope.",
        ]
        delivery_principles = [
            "Validate the first successful workflow before expanding scope.",
            "Keep milestones falsifiable and tightly scoped.",
            "Treat unresolved assumptions as explicit delivery constraints.",
        ]
        market_notes = {
            "opportunities": (
                ["The opportunity should be validated through a crisp first-use success path before scope expands."]
                if research.get("opportunities")
                else []
            ),
            "threats": (
                ["Category noise increases the penalty for ambiguous onboarding and unclear state."]
                if research.get("threats")
                else []
            ),
        }
    return {
        "product_kind": kind,
        "segment": research.get("segment"),
        "north_star": north_star,
        "core_loop": core_loop,
        "experience_principles": experience_principles,
        "delivery_principles": delivery_principles,
        "selected_feature_names": selected_features[:6],
        "primary_personas": [
            {
                "name": str(_as_dict(item).get("name", "")),
                "role": str(_as_dict(item).get("role", "")),
            }
            for item in persona_records[:2]
            if _as_dict(item)
        ],
        "primary_use_cases": [
            {
                "id": str(_as_dict(item).get("id", "")),
                "title": str(_as_dict(item).get("title", "")),
                "priority": str(_as_dict(item).get("priority", "")),
            }
            for item in use_case_records[:4]
            if _as_dict(item)
        ],
        "milestone_names": [
            str(_as_dict(item).get("name", ""))
            for item in milestone_records[:3]
            if str(_as_dict(item).get("name", "")).strip()
        ],
        "research_pressures": {
            "signals": list(research.get("user_signals", []))[:3],
            "pain_points": list(research.get("pain_points", []))[:3],
            "opportunities": market_notes["opportunities"],
            "threats": market_notes["threats"],
        },
        "design_anchor": {
            "style_name": str(style.get("name", "")),
            "keywords": [str(item) for item in _as_list(style.get("keywords")) if str(item).strip()][:4],
        },
        "business_model_anchor": {
            "customer_segments": [str(item) for item in _as_list(business.get("customer_segments")) if str(item).strip()][:4],
            "value_propositions": [str(item) for item in _as_list(business.get("value_propositions")) if str(item).strip()][:3],
        },
    }


def _planning_rejected_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "feature": str(item.get("feature", "")),
            "reason": "Held for later to preserve falsifiable scope and delivery confidence.",
            "counterarguments": ["This feature increases complexity before the first evidence loop is validated."],
        }
        for item in features
        if item.get("selected") is not True and str(item.get("feature", "")).strip()
    ]


def _planning_scope_findings(node_id: str, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = [
        _finding_entry(
            f"scope-{index + 1}",
            title=f"Scope pressure around {item.get('feature')}",
            challenger=node_id,
            severity="high" if str(item.get("implementation_cost")) == "high" else "medium",
            impact="If this remains in the first cut, the team may lose falsifiability and review speed.",
            recommendation="Keep this out of the first release unless a research claim explicitly requires it.",
            related_feature=str(item.get("feature", "")),
        )
        for index, item in enumerate(features)
        if item.get("selected") is True and str(item.get("implementation_cost")) == "high"
    ]
    return findings or [
        _finding_entry(
            "scope-guardrail",
            title="Protect first-release scope",
            challenger=node_id,
            severity="medium",
            impact="Adding convenience features early would blur whether the core workflow is actually working.",
            recommendation="Keep the first milestone focused on a single evidence-to-decision loop.",
        )
    ]


def _planning_assumption_records(state: dict[str, Any], personas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = _research_context(state, segment_from_spec=_segment_from_spec)
    assumptions = _dedupe_strings(
        [
            f"{str(personas[0].get('name', 'Primary user')) if personas else 'Primary user'} will trade setup breadth for stronger control and traceability.",
            "The first milestone can be validated before full-scale automation breadth is delivered.",
            *(f"Research assumption: {item}" for item in research["user_signals"][:1]),
        ]
    )
    return [
        {"id": f"assumption-{index + 1}", "statement": text, "severity": "medium"}
        for index, text in enumerate(assumptions)
    ]


def _planning_assumption_findings(node_id: str) -> list[dict[str, Any]]:
    return [
        _finding_entry(
            "assumption-gap",
            title="Planning relies on a narrow trust assumption",
            challenger=node_id,
            severity="medium",
            impact="If users actually value speed over governance, the proposed scope may be too heavy.",
            recommendation="Validate control-plane depth against onboarding friction in the first user loop.",
        )
    ]


def _planning_negative_personas_for_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    kind = _infer_product_kind(str(state.get("spec", "")))
    if kind == "operations":
        return [
            _negative_persona_entry(
                "negative-ops-1",
                name="Shadow Automator",
                scenario="Runs autonomous flows without reviewing evidence or approval states.",
                risk="Can create silent drift between plan, approval, and build.",
                mitigation="Keep approval status and lineage visible in every primary workflow.",
            ),
            _negative_persona_entry(
                "negative-ops-2",
                name="Audit Skeptic",
                scenario="Needs traceability to trust the system but only sees generated output.",
                risk="Rejects autonomous adoption if artifact lineage is not first-class.",
                mitigation="Surface claim-to-feature traceability and unresolved dissent above the fold.",
            ),
        ]
    return [
        _negative_persona_entry(
            "negative-generic-1",
            name="Impatient Evaluator",
            scenario="Judges the product after one incomplete run.",
            risk="Leaves before the core loop demonstrates value.",
            mitigation="Make the first successful workflow obvious and measurable.",
        )
    ]


def _planning_negative_persona_findings(node_id: str) -> list[dict[str, Any]]:
    return [
        _finding_entry(
            "negative-persona-risk",
            title="The plan does not naturally protect against the hardest-to-serve user",
            challenger=node_id,
            severity="medium",
            impact="Without explicit handling, failure modes stay hidden until rollout.",
            recommendation="Turn these negative personas into acceptance and instrumentation checks.",
        )
    ]


def _planning_kill_criteria_for_milestones(milestones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"kill-{index + 1}",
            "milestone_id": str(item.get("id", "")),
            "condition": f"If {str(item.get('name', 'the milestone')).strip()} cannot show observable completion evidence, stop scope expansion and re-open planning.",
            "rationale": "Milestones must be falsifiable instead of narrative.",
        }
        for index, item in enumerate(milestones[:3])
    ]


def _planning_milestone_findings(node_id: str, milestones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _finding_entry(
            f"milestone-{index + 1}",
            title=f"Milestone {str(item.get('name', 'Milestone'))} needs a failure condition",
            challenger=node_id,
            severity="medium",
            impact="A milestone without a stop condition will let the team ship momentum instead of evidence.",
            recommendation="Add the observable failure signal next to the success criteria.",
        )
        for index, item in enumerate(milestones[:2])
    ]


def _dedupe_findings_by_title(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in findings:
        record = _as_dict(item)
        key = (str(record.get("title", "")).strip(), str(record.get("recommendation", "")).strip())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _planning_review_defaults(
    state: dict[str, Any],
    *,
    features: list[dict[str, Any]] | None = None,
    personas: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    feature_records = features or _planning_selected_or_default_features(state)
    persona_records = personas or [
        _as_dict(item)
        for item in _as_list(state.get("persona_report"))
        if _as_dict(item)
    ]
    milestone_records = milestones or _planning_milestones_from_state(state)
    rejected_features = _planning_rejected_features(feature_records)
    assumptions = _planning_assumption_records(state, persona_records)
    negative_personas = _planning_negative_personas_for_state(state)
    kill_criteria = _planning_kill_criteria_for_milestones(milestone_records)
    red_team_findings = _dedupe_findings_by_title(
        [
            *_planning_scope_findings("scope-skeptic", feature_records),
            *_planning_assumption_findings("assumption-auditor"),
            *_planning_negative_persona_findings("negative-persona-challenger"),
            *_planning_milestone_findings("milestone-falsifier", milestone_records),
        ]
    )
    return {
        "rejected_features": rejected_features,
        "assumptions": assumptions,
        "negative_personas": negative_personas,
        "kill_criteria": kill_criteria,
        "red_team_findings": red_team_findings,
    }


def _planning_fallback_judge_summary(
    recommendations: list[str],
    review_defaults: dict[str, Any],
) -> str:
    top_finding = _as_dict(_as_list(review_defaults.get("red_team_findings"))[0])
    finding_title = str(top_finding.get("title", "")).strip()
    top_recommendation = next((str(item).strip() for item in recommendations if str(item).strip()), "")
    if finding_title and top_recommendation:
        return f"{finding_title}. {top_recommendation}"
    return finding_title or top_recommendation or "Keep planning tightly scoped, traceable, and falsifiable before moving into design."


def _feature_use_case_match_score(feature_name: str, use_case: dict[str, Any]) -> int:
    normalized_feature = feature_name.casefold()
    feature_keywords = set(_keywords(feature_name))
    score = 0
    for related in _as_list(use_case.get("related_stories")):
        related_text = str(related or "")
        related_normalized = related_text.casefold()
        if not related_normalized:
            continue
        if normalized_feature == related_normalized:
            score += 8
        elif normalized_feature in related_normalized or related_normalized in normalized_feature:
            score += 5
        overlap = feature_keywords & set(_keywords(related_text))
        score += min(len(overlap), 3)
    combined_text = " ".join(
        [
            str(use_case.get("title", "")),
            str(use_case.get("actor", "")),
            str(use_case.get("category", "")),
            str(use_case.get("sub_category", "")),
            *(str(step) for step in _as_list(use_case.get("main_flow"))),
        ]
    )
    combined_normalized = combined_text.casefold()
    if normalized_feature and normalized_feature in combined_normalized:
        score += 4
    score += min(len(feature_keywords & set(_keywords(combined_text))), 3)
    return score


def _traceability_use_case_for_feature(
    feature_name: str,
    use_cases: list[dict[str, Any]],
    *,
    fallback_index: int,
) -> dict[str, Any]:
    if not use_cases:
        return {}
    ranked = sorted(
        enumerate(use_cases),
        key=lambda item: (_feature_use_case_match_score(feature_name, item[1]), -item[0]),
        reverse=True,
    )
    best_index, best_use_case = ranked[0]
    if _feature_use_case_match_score(feature_name, best_use_case) > 0:
        return best_use_case
    return use_cases[min(fallback_index, len(use_cases) - 1)]


def _traceability_milestone_for_use_case(
    use_case: dict[str, Any],
    milestones: list[dict[str, Any]],
    *,
    fallback_index: int,
) -> dict[str, Any]:
    if not milestones:
        return {}
    use_case_id = str(use_case.get("id", "")).strip()
    for milestone in milestones:
        if use_case_id and use_case_id in {str(item) for item in _as_list(milestone.get("depends_on_use_cases"))}:
            return milestone
    priority = str(use_case.get("priority", "should") or "should")
    phase_hint = "alpha" if priority == "must" else "beta" if priority == "should" else "release"
    for milestone in milestones:
        if str(milestone.get("phase", "")) == phase_hint:
            return milestone
    return milestones[min(fallback_index, len(milestones) - 1)]


def _planning_required_traceability_use_cases(
    use_cases: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    milestone_use_case_ids = {
        str(use_case_id).strip()
        for milestone in milestones
        for use_case_id in _as_list(milestone.get("depends_on_use_cases"))
        if str(use_case_id).strip()
    }
    required: list[dict[str, Any]] = []
    seen: set[str] = set()
    for use_case in use_cases:
        record = _as_dict(use_case)
        use_case_id = str(record.get("id", "")).strip()
        priority = str(record.get("priority", "should") or "should")
        if not use_case_id or use_case_id in seen:
            continue
        if priority in {"must", "should"} or use_case_id in milestone_use_case_ids:
            seen.add(use_case_id)
            required.append(record)
    return required


def _build_traceability(state: dict[str, Any], features: list[dict[str, Any]], milestones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    use_cases = _planning_use_cases_from_state(state)
    selected_features = [
        item
        for item in features
        if _as_dict(item).get("selected") is True and str(_as_dict(item).get("feature", "")).strip()
    ]
    traces: list[dict[str, Any]] = []
    for index, item in enumerate(selected_features):
        feature_name = str(item.get("feature", "")).strip()
        claim = claims[min(index, len(claims) - 1)] if claims else {}
        use_case = _traceability_use_case_for_feature(feature_name, use_cases, fallback_index=index)
        milestone = _traceability_milestone_for_use_case(use_case, milestones, fallback_index=index)
        traces.append(
            {
                "claim_id": str(claim.get("id", "")),
                "claim": str(claim.get("statement", "")),
                "use_case_id": str(use_case.get("id", "")),
                "use_case": str(use_case.get("title", "")),
                "feature": feature_name,
                "milestone_id": str(milestone.get("id", "")),
                "milestone": str(milestone.get("name", "")),
                "confidence": float(claim.get("confidence", 0.72) or 0.72),
            }
        )
    traced_use_case_ids = {
        str(item.get("use_case_id", "")).strip()
        for item in traces
        if str(item.get("use_case_id", "")).strip()
    }
    required_use_cases = _planning_required_traceability_use_cases(use_cases, milestones)
    for index, use_case in enumerate(required_use_cases):
        use_case_id = str(use_case.get("id", "")).strip()
        if not use_case_id or use_case_id in traced_use_case_ids:
            continue
        related_features = _use_case_related_features(use_case, selected_features) if selected_features else []
        feature = _as_dict(related_features[0]) if related_features else (_as_dict(selected_features[0]) if selected_features else {})
        feature_name = str(feature.get("feature", "")).strip()
        feature_index = next(
            (
                feature_position
                for feature_position, item in enumerate(selected_features)
                if str(item.get("feature", "")).strip() == feature_name
            ),
            index,
        )
        claim = claims[min(feature_index, len(claims) - 1)] if claims else {}
        milestone = _traceability_milestone_for_use_case(use_case, milestones, fallback_index=index)
        traces.append(
            {
                "claim_id": str(claim.get("id", "")),
                "claim": str(claim.get("statement", "")),
                "use_case_id": use_case_id,
                "use_case": str(use_case.get("title", "")),
                "feature": feature_name,
                "milestone_id": str(milestone.get("id", "")),
                "milestone": str(milestone.get("name", "")),
                "confidence": float(claim.get("confidence", 0.72) or 0.72),
            }
        )
    return traces


def _planning_priority_rank(value: str) -> int:
    return {"must": 0, "should": 1, "could": 2}.get(str(value or "should"), 1)


def _plan_estimate_use_cases(use_cases: list[dict[str, Any]], preset: str) -> list[dict[str, Any]]:
    allowed = {
        "minimal": {"must"},
        "standard": {"must", "should"},
        "full": {"must", "should", "could"},
    }.get(preset, {"must", "should"})
    selected = [
        use_case
        for use_case in use_cases
        if str(use_case.get("priority", "should") or "should") in allowed
    ]
    return selected or use_cases[:1]


def _use_case_related_features(use_case: dict[str, Any], features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feature_index = {
        str(item.get("feature", "")).casefold(): item
        for item in features
        if str(item.get("feature", "")).strip()
    }
    related: list[dict[str, Any]] = []
    for story in _as_list(use_case.get("related_stories")):
        key = str(story or "").casefold()
        if key in feature_index:
            related.append(feature_index[key])
    if related:
        return related
    title = str(use_case.get("title", ""))
    ranked = sorted(
        features,
        key=lambda item: _feature_use_case_match_score(str(item.get("feature", "")), use_case),
        reverse=True,
    )
    if ranked and _feature_use_case_match_score(str(ranked[0].get("feature", "")), use_case) > 0:
        return ranked[:2]
    if title and features:
        return features[:1]
    return []

def _research_packets_to_evidence(
    node_id: str,
    packets: list[dict[str, Any]],
    *,
    prefix: str,
    relevance: str,
) -> list[dict[str, Any]]:
    return [
        _evidence_entry(
            f"ev-{prefix}-{index + 1}",
            source_ref=str(packet.get("source_ref", "")),
            source_type=str(packet.get("source_type", "url") or "url"),
            snippet=_truncate_research_text(
                packet.get("excerpt") or packet.get("description") or packet.get("text_excerpt") or packet.get("title"),
                limit=240,
            ),
            relevance=relevance,
        )
        for index, packet in enumerate(packets[: _research_source_limit({"depth": "deep"})])
        if str(packet.get("source_ref", "")).strip()
    ]


def _market_size_signal_from_packets(packets: list[dict[str, Any]]) -> str:
    for packet in packets:
        text = " ".join(
            [
                str(packet.get("description", "") or ""),
                str(packet.get("excerpt", "") or ""),
                str(packet.get("text_excerpt", "") or ""),
            ]
        )
        match = re.search(
            r"([^.!?]{0,60}(?:market size|market growth|cagr|billion|million|市場規模|成長率|%)[^.!?]{0,120})",
            text,
            re.IGNORECASE,
        )
        if match:
            return _truncate_research_text(match.group(1), limit=180)
    return "公開ソースでは定量的な市場規模の記述を確認できませんでした。"


def _competitor_weaknesses_from_packet(packet: dict[str, Any], spec: str) -> list[str]:
    text = " ".join(
        [
            str(packet.get("description", "") or ""),
            str(packet.get("excerpt", "") or ""),
            str(packet.get("text_excerpt", "") or ""),
        ]
    ).lower()
    weaknesses: list[str] = []
    pricing = _pricing_hint_from_packet(packet)
    if pricing == "Not publicly listed":
        weaknesses.append("公開ページでは料金体系を確認できませんでした。")
    if _infer_product_kind(spec) == "operations" and not any(
        term in text
        for term in ("governance", "audit", "approval", "traceability", "lineage", "compliance")
    ):
        weaknesses.append("公開情報ではガバナンスや監査性の説明が限定的でした。")
    if len(_normalize_space(packet.get("text_excerpt"))) < 180:
        weaknesses.append("公開情報だけでは詳細比較に十分な情報量を確保できませんでした。")
    return weaknesses[:2]


def _research_competitor_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    anchor = _research_query_anchor(spec, _research_identity_profile(state))
    queries = _research_remediation_queries(
        state,
        node_id=node_id,
        queries=[
            f"{anchor} software",
            f"{anchor} platform",
            f"{anchor} alternatives",
        ],
    )
    packets = _collect_research_source_packets(
        state,
        focus="competition",
        queries=queries,
        seed_urls=[str(item) for item in _as_list(state.get("competitor_urls")) if str(item).strip()],
        include_brief_on_empty=True,
        prefer_vendor_hosts=True,
    )
    source_packets = [packet for packet in packets if str(packet.get("source_type")) == "url"]
    evidence_packets = source_packets or packets[:1]
    evidence = _research_packets_to_evidence(
        node_id,
        evidence_packets,
        prefix="competitor",
        relevance="Competitive positioning reference",
    )
    competitors: list[dict[str, Any]] = []
    for packet in source_packets[: _research_source_limit(state)]:
        host = str(packet.get("host", "") or "")
        name = str(packet.get("title", "") or "").split("|", 1)[0].split(" - ", 1)[0].strip()
        competitors.append(
            {
                "name": _truncate_research_text(name or _source_label_from_host(host), limit=64),
                "url": str(packet.get("url", "")),
                "strengths": _source_observations([packet], limit=2),
                "weaknesses": _competitor_weaknesses_from_packet(packet, spec),
                "pricing": _pricing_hint_from_packet(packet),
                "target": _segment_from_spec(spec),
            }
        )
    claim_statement = (
        "公開ソースから直接参照できる競合候補がまだ不足しており、差別化仮説は追加調査前提です。"
        if not competitors
        else (
            f"公開ソースでは {competitors[0]['name']} を含む隣接プロダクトが確認でき、"
            "差別化は feature breadth ではなく運用品質・説明責任・導入後の制御性で評価されやすい可能性があります。"
        )
    )
    claims = [
        _claim_entry(
            "claim-competitive-gap",
            statement=claim_statement,
            owner=node_id,
            category="competition",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.7 if not competitors else min(0.82, 0.66 + len(evidence) * 0.04),
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if competitors and source_packets else "degraded",
        parse_status="strict",
        artifact={"competitors": competitors, "claim_statement": claim_statement},
        source_packets=evidence_packets,
        degradation_reasons=(
            []
            if competitors and source_packets
            else ["competitor_grounding_insufficient"]
        ),
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            "competitor_report": competitors,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            _node_state_key(node_id, "sources"): evidence_packets,
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts(
            {"name": "competitor-map", "kind": "research", "items": competitors, "sources": evidence_packets},
            {"name": "competitor-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
        metrics={"competitor_count": len(competitors), "grounded_sources": len(evidence_packets)},
    )


def _research_market_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    anchor = _research_query_anchor(spec, _research_identity_profile(state))
    queries = _research_remediation_queries(
        state,
        node_id=node_id,
        queries=[
            f"{anchor} market trends",
            f"{anchor} adoption",
            f"{anchor} market size",
        ],
    )
    packets = _collect_research_source_packets(
        state,
        focus="market",
        queries=queries,
        include_brief_on_empty=True,
    )
    external_packets = [packet for packet in packets if str(packet.get("source_type")) == "url"]
    evidence = _research_packets_to_evidence(
        node_id,
        external_packets or packets,
        prefix="market",
        relevance="Market research reference",
    )
    observations = _source_observations(external_packets or packets, limit=4)
    opportunities = [
        item
        for item in observations
        if any(hint in item.lower() for hint in _RESEARCH_POSITIVE_HINTS)
    ][:2] or observations[:2]
    threats = [
        item
        for item in observations
        if any(hint in item.lower() for hint in _RESEARCH_NEGATIVE_HINTS)
    ][:2]
    if not threats and observations:
        threats = observations[-2:]
    payload = {
        "market_size": _market_size_signal_from_packets(external_packets),
        "trends": observations[:3],
        "opportunities": opportunities,
        "threats": threats,
    }
    claim_statement = (
        "公開市場ソースの量がまだ少なく、需要仮説は brief ベースの仮説に留まっています。"
        if not external_packets
        else "公開ソースでは導入拡大と運用上の制約が併存しており、需要自体はある一方で差別化には具体的な運用品質の説明が必要です。"
    )
    claims = [
        _claim_entry(
            "claim-market-demand",
            statement=claim_statement,
            owner=node_id,
            category="market",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.65 if not external_packets else min(0.83, 0.67 + len(evidence) * 0.04),
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if external_packets else "degraded",
        parse_status="strict",
        artifact={**payload, "claim_statement": claim_statement},
        source_packets=external_packets or packets,
        degradation_reasons=[] if external_packets else ["market_grounding_insufficient"],
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            "market_report": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            _node_state_key(node_id, "sources"): external_packets or packets,
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts(
            {"name": "market-research", "kind": "research", **payload},
            {"name": "market-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
        metrics={"trend_count": len(payload["trends"]), "grounded_sources": len(external_packets)},
    )


def _research_user_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    anchor = _research_query_anchor(spec, _research_identity_profile(state))
    queries = _research_remediation_queries(
        state,
        node_id=node_id,
        queries=[
            f"{anchor} user pain points",
            f"{anchor} workflow challenges",
            f"{anchor} customer frustrations",
        ],
    )
    packets = _collect_research_source_packets(
        state,
        focus="user",
        queries=queries,
        include_brief_on_empty=True,
    )
    external_packets = [packet for packet in packets if str(packet.get("source_type")) == "url"]
    evidence = _research_packets_to_evidence(
        node_id,
        external_packets or packets,
        prefix="user",
        relevance="User demand or friction reference",
    )
    observations = _source_observations(external_packets or packets, limit=4)
    pain_points = [
        item
        for item in observations
        if any(hint in item.lower() for hint in _RESEARCH_NEGATIVE_HINTS)
    ][:2] or observations[1:3] or observations[:2]
    payload = {
        "signals": observations[:3] or [_truncate_research_text(spec, limit=180)],
        "pain_points": pain_points or [_truncate_research_text(spec, limit=180)],
        "segment": _segment_from_spec(spec),
    }
    claim_statement = (
        "外部ユーザー調査ソースがまだ薄く、現在の課題理解は brief と公開記事に依存しています。"
        if not external_packets
        else "公開ソースでは導入判断時の不安、運用負荷、既存手順との統合摩擦が繰り返し現れており、信頼形成が主要な UX 論点になります。"
    )
    claims = [
        _claim_entry(
            "claim-user-trust",
            statement=claim_statement,
            owner=node_id,
            category="user",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.67 if not external_packets else min(0.84, 0.69 + len(evidence) * 0.04),
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if external_packets else "degraded",
        parse_status="strict",
        artifact={**payload, "claim_statement": claim_statement},
        source_packets=external_packets or packets,
        degradation_reasons=[] if external_packets else ["user_grounding_insufficient"],
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            "user_research": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            _node_state_key(node_id, "sources"): external_packets or packets,
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts(
            {"name": "user-signals", "kind": "research", **payload},
            {"name": "user-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
    )


def _research_tech_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    spec = str(state.get("spec", ""))
    anchor = _research_query_anchor(spec, _research_identity_profile(state))
    queries = _research_remediation_queries(
        state,
        node_id=node_id,
        queries=[
            f"{anchor} implementation challenges",
            f"{anchor} architecture",
            f"{anchor} security integration",
        ],
    )
    packets = _collect_research_source_packets(
        state,
        focus="technical",
        queries=queries,
        include_brief_on_empty=True,
    )
    external_packets = [packet for packet in packets if str(packet.get("source_type")) == "url"]
    evidence = _research_packets_to_evidence(
        node_id,
        external_packets or packets,
        prefix="tech",
        relevance="Technical feasibility reference",
    )
    source_text = " ".join(
        str(packet.get("text_excerpt", "") or packet.get("excerpt", "") or "")
        for packet in external_packets
    ).lower()
    penalty = 0.0
    if any(term in source_text for term in ("security", "privacy", "compliance", "regulation", "規制")):
        penalty += 0.05
    if any(term in source_text for term in ("integration", "migration", "legacy", "latency", "cost", "運用負荷")):
        penalty += 0.06
    base_score = 0.78 if _contains_any(spec, "workflow", "agent", "dashboard", "app", "platform") else 0.7
    score = _clamp_score(base_score + min(len(external_packets) * 0.03, 0.09) - penalty, default=base_score)
    observations = _source_observations(external_packets or packets, limit=3)
    notes = (
        "公開技術ソースを十分に取得できず、技術評価は brief ベースの初期推定です。"
        if not external_packets
        else " / ".join(observations[:2]) or "公開ソースでは統合・運用品質・安全性が主要な実装論点として現れています。"
    )
    payload = {
        "score": round(score, 2),
        "notes": _truncate_research_text(notes, limit=280),
    }
    claim_statement = (
        "プロトタイプ実装は可能でも、本番品質は統合、運用監視、安全性の設計次第で大きく上下します。"
        if external_packets
        else "現時点では実装難易度を裏づける外部技術ソースが不足しており、技術リスクの多くは未検証です。"
    )
    claims = [
        _claim_entry(
            "claim-technical-feasibility",
            statement=claim_statement,
            owner=node_id,
            category="technical",
            evidence_ids=[item["id"] for item in evidence],
            confidence=0.7 if not external_packets else min(0.84, 0.68 + len(evidence) * 0.04),
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if external_packets else "degraded",
        parse_status="strict",
        artifact={**payload, "claim_statement": claim_statement},
        source_packets=external_packets or packets,
        degradation_reasons=[] if external_packets else ["technical_grounding_insufficient"],
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            "technical_report": payload,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            _node_state_key(node_id, "sources"): external_packets or packets,
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts(
            {"name": "risk-register", "kind": "research", "tech_feasibility": payload},
            {"name": "tech-claims", "kind": "research", "claims": claims, "evidence": evidence},
        ),
    )

async def _research_peer_delegations(
    *,
    node_id: str,
    plan: dict[str, Any],
    artifact_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    peer_feedback: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    for delegation in _as_list(plan.get("delegations"))[:2]:
        delegation_payload = _as_dict(delegation)
        delegated = await _delegate_to_lifecycle_peer(
            phase="research",
            node_id=node_id,
            peer_name=str(delegation_payload.get("peer", "")),
            skill_name=str(delegation_payload.get("skill", "")),
            artifact_payload=artifact_payload,
            reason=str(delegation_payload.get("reason", "")),
            quality_targets=[str(item) for item in _as_list(plan.get("quality_targets")) if str(item).strip()],
        )
        if delegated is None:
            continue
        delegations.append(delegated)
        feedback = _as_dict(delegated.get("feedback"))
        if feedback:
            peer_feedback.append(feedback)
    return delegations, peer_feedback


def _research_autonomous_node_result(
    *,
    base: NodeResult,
    node_id: str,
    state_overrides: dict[str, Any],
    plan: dict[str, Any],
    delegations: list[dict[str, Any]],
    peer_feedback: list[dict[str, Any]],
    llm_events: list[dict[str, Any]],
) -> NodeResult:
    return NodeResult(
        state_patch={
            **base.state_patch,
            **state_overrides,
            _skill_plan_state_key(node_id): plan,
            _delegation_state_key(node_id): delegations,
            _peer_feedback_state_key(node_id): peer_feedback,
        },
        artifacts=_artifacts(
            *[dict(item) for item in base.artifacts],
            {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
            *[
                {
                    "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                    "kind": "peer-review",
                    **_as_dict(item.get("feedback")),
                }
                for item in delegations
                if _as_dict(item.get("feedback"))
            ],
        ),
        llm_events=llm_events,
        metrics={**base.metrics, "research_mode": "provider-backed-autonomous"},
    )


async def _research_competitor_autonomous_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    base = _research_competitor_handler(node_id, state)
    source_packets = [_as_dict(item) for item in _as_list(base.state_patch.get(_node_state_key(node_id, "sources"))) if _as_dict(item)]
    if not _provider_backed_lifecycle_available(provider_registry) or not source_packets:
        return base
    plan, plan_events = await _plan_node_collaboration(
        phase="research",
        node_id=node_id,
        state=state,
        objective="Ground the competitive landscape in real web sources and avoid invented competitors or claims.",
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
    )
    payload, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-research-{node_id}",
        static_instruction=(
            "You are a competitive intelligence analyst. Return JSON only. "
            "Use only the provided source packets. Do not invent companies, URLs, pricing, strengths, or weaknesses."
        ),
        user_prompt=(
            "Return JSON with keys competitors, claim_statement, confidence.\n"
            "Each competitor must include name, url, strengths, weaknesses, pricing, target.\n"
            "Use empty arrays when evidence is insufficient.\n"
            f"Product spec: {state.get('spec')}\n"
            f"Source packets: {_compact_lifecycle_value(source_packets)}\n"
            f"Baseline competitors: {_compact_lifecycle_value(base.state_patch.get('competitor_report'))}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
            f"Delegation plan: {plan.get('delegations')}\n"
        ),
        schema_name="research-competitor",
        required_keys=["competitors", "claim_statement", "confidence"],
        phase="research",
        node_id=node_id,
    )
    competitors = [_as_dict(item) for item in _as_list(base.state_patch.get("competitor_report")) if _as_dict(item)]
    if isinstance(payload, dict):
        packet_by_url = {
            str(packet.get("source_ref", "")): packet
            for packet in source_packets
            if str(packet.get("source_ref", "")).strip()
        }
        refined: list[dict[str, Any]] = []
        for raw in _as_list(payload.get("competitors"))[: _research_source_limit(state)]:
            item = _as_dict(raw)
            if not item:
                continue
            url = _normalize_external_url(str(item.get("url", "") or ""))
            packet = packet_by_url.get(url)
            if packet is None:
                continue
            refined.append(
                {
                    "name": _truncate_research_text(
                        _first_research_text(
                            item.get("name"),
                            default=str(packet.get("title") or _source_label_from_host(str(packet.get("host", "")))),
                            char_limit=64,
                        ),
                        limit=64,
                    ),
                    "url": url,
                    "strengths": _normalized_research_strings(item.get("strengths"), limit=2, char_limit=150) or _source_observations([packet], limit=2),
                    "weaknesses": _normalized_research_strings(item.get("weaknesses"), limit=2, char_limit=150) or _competitor_weaknesses_from_packet(packet, str(state.get("spec", ""))),
                    "pricing": _truncate_research_text(
                        _first_research_text(item.get("pricing"), default=_pricing_hint_from_packet(packet), char_limit=80),
                        limit=80,
                    ),
                    "target": _truncate_research_text(
                        _first_research_text(item.get("target"), default=_segment_from_spec(str(state.get("spec", ""))), char_limit=80),
                        limit=80,
                    ),
                }
            )
        if refined:
            competitors = refined
    claim_statement = (
        _first_research_text(_as_dict(payload).get("claim_statement"))
        or str(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("statement", ""))
    )
    confidence = _clamp_score(
        _as_dict(payload).get("confidence"),
        default=float(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("confidence", 0.7) or 0.7),
    )
    claims = [
        _claim_entry(
            "claim-competitive-gap",
            statement=claim_statement,
            owner=node_id,
            category="competition",
            evidence_ids=[item["id"] for item in _as_list(base.state_patch.get(_node_state_key(node_id, "evidence")))],
            confidence=confidence,
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if competitors and source_packets and llm_meta.get("parse_status") != "failed" else "degraded",
        parse_status=str(llm_meta.get("parse_status", "strict")),
        artifact={"competitors": competitors, "claim_statement": claim_statement},
        source_packets=source_packets,
        degradation_reasons=list(llm_meta.get("degradation_reasons", [])),
        raw_preview=str(llm_meta.get("raw_preview", "")),
        llm_events=llm_events,
        retry_count=_research_retry_count(state, node_id),
    )
    delegations, peer_feedback = await _research_peer_delegations(
        node_id=node_id,
        plan=plan,
        artifact_payload={
            "focus": "competition",
            "sources": source_packets,
            "competitors": competitors,
            "claim": claims[0],
        },
    )
    return _research_autonomous_node_result(
        base=base,
        node_id=node_id,
        state_overrides={
            "competitor_report": competitors,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "result"): node_result,
        },
        plan=plan,
        delegations=delegations,
        peer_feedback=peer_feedback,
        llm_events=[*plan_events, *llm_events],
    )


async def _research_market_autonomous_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    base = _research_market_handler(node_id, state)
    source_packets = [_as_dict(item) for item in _as_list(base.state_patch.get(_node_state_key(node_id, "sources"))) if _as_dict(item)]
    if not _provider_backed_lifecycle_available(provider_registry) or not source_packets:
        return base
    plan, plan_events = await _plan_node_collaboration(
        phase="research",
        node_id=node_id,
        state=state,
        objective="Synthesize market signals from grounded public sources and separate opportunity from risk.",
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
    )
    payload, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-research-{node_id}",
        static_instruction=(
            "You are a market researcher. Return JSON only. "
            "Use only the provided source packets. If quantitative market sizing is missing, say so explicitly."
        ),
        user_prompt=(
            "Return JSON with keys market_size, trends, opportunities, threats, claim_statement, confidence.\n"
            f"Product spec: {state.get('spec')}\n"
            f"Source packets: {_compact_lifecycle_value(source_packets)}\n"
            f"Baseline market report: {_compact_lifecycle_value(base.state_patch.get('market_report'))}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
        ),
        schema_name="research-market",
        required_keys=["market_size", "trends", "opportunities", "threats", "claim_statement", "confidence"],
        phase="research",
        node_id=node_id,
    )
    market_report = _as_dict(base.state_patch.get("market_report"))
    if isinstance(payload, dict):
        market_report = {
            "market_size": _truncate_research_text(
                _first_research_text(
                    payload.get("market_size"),
                    default=str(market_report.get("market_size", "")),
                    char_limit=180,
                ),
                limit=180,
            ),
            "trends": _normalized_research_strings(payload.get("trends"), limit=3) or _normalized_research_strings(market_report.get("trends"), limit=3),
            "opportunities": _normalized_research_strings(payload.get("opportunities"), limit=3) or _normalized_research_strings(market_report.get("opportunities"), limit=3),
            "threats": _normalized_research_strings(payload.get("threats"), limit=3) or _normalized_research_strings(market_report.get("threats"), limit=3),
        }
    claim_statement = (
        _first_research_text(_as_dict(payload).get("claim_statement"))
        or str(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("statement", ""))
    )
    confidence = _clamp_score(
        _as_dict(payload).get("confidence"),
        default=float(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("confidence", 0.7) or 0.7),
    )
    claims = [
        _claim_entry(
            "claim-market-demand",
            statement=claim_statement,
            owner=node_id,
            category="market",
            evidence_ids=[item["id"] for item in _as_list(base.state_patch.get(_node_state_key(node_id, "evidence")))],
            confidence=confidence,
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if source_packets and llm_meta.get("parse_status") != "failed" else "degraded",
        parse_status=str(llm_meta.get("parse_status", "strict")),
        artifact={**market_report, "claim_statement": claim_statement},
        source_packets=source_packets,
        degradation_reasons=list(llm_meta.get("degradation_reasons", [])),
        raw_preview=str(llm_meta.get("raw_preview", "")),
        llm_events=llm_events,
        retry_count=_research_retry_count(state, node_id),
    )
    delegations, peer_feedback = await _research_peer_delegations(
        node_id=node_id,
        plan=plan,
        artifact_payload={"focus": "market", "sources": source_packets, "market_report": market_report, "claim": claims[0]},
    )
    return _research_autonomous_node_result(
        base=base,
        node_id=node_id,
        state_overrides={
            "market_report": market_report,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "result"): node_result,
        },
        plan=plan,
        delegations=delegations,
        peer_feedback=peer_feedback,
        llm_events=[*plan_events, *llm_events],
    )


async def _research_user_autonomous_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    base = _research_user_handler(node_id, state)
    source_packets = [_as_dict(item) for item in _as_list(base.state_patch.get(_node_state_key(node_id, "sources"))) if _as_dict(item)]
    if not _provider_backed_lifecycle_available(provider_registry) or not source_packets:
        return base
    plan, plan_events = await _plan_node_collaboration(
        phase="research",
        node_id=node_id,
        state=state,
        objective="Extract grounded user signals and pain points from public evidence without inventing interview data.",
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
    )
    payload, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-research-{node_id}",
        static_instruction=(
            "You are a user researcher. Return JSON only. "
            "Use only the provided public source packets and clearly grounded observations."
        ),
        user_prompt=(
            "Return JSON with keys signals, pain_points, segment, claim_statement, confidence.\n"
            f"Product spec: {state.get('spec')}\n"
            f"Source packets: {_compact_lifecycle_value(source_packets)}\n"
            f"Baseline user research: {_compact_lifecycle_value(base.state_patch.get('user_research'))}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
        ),
        schema_name="research-user",
        required_keys=["signals", "pain_points", "segment", "claim_statement", "confidence"],
        phase="research",
        node_id=node_id,
    )
    user_research = _as_dict(base.state_patch.get("user_research"))
    if isinstance(payload, dict):
        user_research = {
            "signals": _normalized_research_strings(payload.get("signals"), limit=3) or _normalized_research_strings(user_research.get("signals"), limit=3),
            "pain_points": _normalized_research_strings(payload.get("pain_points"), limit=3) or _normalized_research_strings(user_research.get("pain_points"), limit=3),
            "segment": _truncate_research_text(
                _first_research_text(
                    payload.get("segment") or user_research.get("segment"),
                    default=_segment_from_spec(str(state.get("spec", ""))),
                    char_limit=80,
                ),
                limit=80,
            ),
        }
    claim_statement = (
        _first_research_text(_as_dict(payload).get("claim_statement"))
        or str(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("statement", ""))
    )
    confidence = _clamp_score(
        _as_dict(payload).get("confidence"),
        default=float(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("confidence", 0.7) or 0.7),
    )
    claims = [
        _claim_entry(
            "claim-user-trust",
            statement=claim_statement,
            owner=node_id,
            category="user",
            evidence_ids=[item["id"] for item in _as_list(base.state_patch.get(_node_state_key(node_id, "evidence")))],
            confidence=confidence,
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if source_packets and llm_meta.get("parse_status") != "failed" else "degraded",
        parse_status=str(llm_meta.get("parse_status", "strict")),
        artifact={**user_research, "claim_statement": claim_statement},
        source_packets=source_packets,
        degradation_reasons=list(llm_meta.get("degradation_reasons", [])),
        raw_preview=str(llm_meta.get("raw_preview", "")),
        llm_events=llm_events,
        retry_count=_research_retry_count(state, node_id),
    )
    delegations, peer_feedback = await _research_peer_delegations(
        node_id=node_id,
        plan=plan,
        artifact_payload={"focus": "user", "sources": source_packets, "user_research": user_research, "claim": claims[0]},
    )
    return _research_autonomous_node_result(
        base=base,
        node_id=node_id,
        state_overrides={
            "user_research": user_research,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "result"): node_result,
        },
        plan=plan,
        delegations=delegations,
        peer_feedback=peer_feedback,
        llm_events=[*plan_events, *llm_events],
    )


async def _research_tech_autonomous_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    base = _research_tech_handler(node_id, state)
    source_packets = [_as_dict(item) for item in _as_list(base.state_patch.get(_node_state_key(node_id, "sources"))) if _as_dict(item)]
    if not _provider_backed_lifecycle_available(provider_registry) or not source_packets:
        return base
    plan, plan_events = await _plan_node_collaboration(
        phase="research",
        node_id=node_id,
        state=state,
        objective="Calibrate technical feasibility against grounded implementation, integration, and security signals.",
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
    )
    payload, llm_events, llm_meta = await _research_llm_json(
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
        preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
        purpose=f"lifecycle-research-{node_id}",
        static_instruction=(
            "You are a technical evaluator. Return JSON only. "
            "Ground the score and notes in the provided source packets and do not invent benchmarks."
        ),
        user_prompt=(
            "Return JSON with keys score, notes, claim_statement, confidence.\n"
            f"Product spec: {state.get('spec')}\n"
            f"Source packets: {_compact_lifecycle_value(source_packets)}\n"
            f"Baseline technical report: {_compact_lifecycle_value(base.state_patch.get('technical_report'))}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
        ),
        schema_name="research-technical",
        required_keys=["score", "notes", "claim_statement", "confidence"],
        phase="research",
        node_id=node_id,
    )
    technical_report = _as_dict(base.state_patch.get("technical_report"))
    if isinstance(payload, dict):
        technical_report = {
            "score": _clamp_score(payload.get("score"), default=float(technical_report.get("score", 0.7) or 0.7)),
            "notes": _truncate_research_text(
                _first_research_text(payload.get("notes"), default=str(technical_report.get("notes", "")), char_limit=280),
                limit=280,
            ),
        }
    claim_statement = (
        _first_research_text(_as_dict(payload).get("claim_statement"))
        or str(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("statement", ""))
    )
    confidence = _clamp_score(
        _as_dict(payload).get("confidence"),
        default=float(_as_list(base.state_patch.get(_node_state_key(node_id, "claims")))[0].get("confidence", 0.7) or 0.7),
    )
    claims = [
        _claim_entry(
            "claim-technical-feasibility",
            statement=claim_statement,
            owner=node_id,
            category="technical",
            evidence_ids=[item["id"] for item in _as_list(base.state_patch.get(_node_state_key(node_id, "evidence")))],
            confidence=confidence,
        ),
    ]
    node_result = research_node_result(
        node_id,
        status="success" if source_packets and llm_meta.get("parse_status") != "failed" else "degraded",
        parse_status=str(llm_meta.get("parse_status", "strict")),
        artifact={**technical_report, "claim_statement": claim_statement},
        source_packets=source_packets,
        degradation_reasons=list(llm_meta.get("degradation_reasons", [])),
        raw_preview=str(llm_meta.get("raw_preview", "")),
        llm_events=llm_events,
        retry_count=_research_retry_count(state, node_id),
    )
    delegations, peer_feedback = await _research_peer_delegations(
        node_id=node_id,
        plan=plan,
        artifact_payload={"focus": "technical", "sources": source_packets, "technical_report": technical_report, "claim": claims[0]},
    )
    return _research_autonomous_node_result(
        base=base,
        node_id=node_id,
        state_overrides={
            "technical_report": technical_report,
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "result"): node_result,
        },
        plan=plan,
        delegations=delegations,
        peer_feedback=peer_feedback,
        llm_events=[*plan_events, *llm_events],
    )


def _research_synthesizer_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    market = _as_dict(state.get("market_report"))
    technical = _as_dict(state.get("technical_report"))
    user_research = _as_dict(state.get("user_research"))
    claims = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES, suffix="claims")
    evidence = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES, suffix="evidence")
    winning = _winning_claims(claims)
    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in claims]
    research = {
        "competitors": list(state.get("competitor_report", [])),
        "market_size": market.get("market_size", "Early but expanding operational market"),
        "trends": _normalized_research_strings(market.get("trends"), limit=3),
        "opportunities": _normalized_research_strings(market.get("opportunities"), limit=3),
        "threats": _normalized_research_strings(market.get("threats"), limit=3),
        "user_research": {
            "signals": _normalized_research_strings(user_research.get("signals"), limit=3),
            "pain_points": _normalized_research_strings(user_research.get("pain_points"), limit=3),
            "segment": _first_research_text(
                user_research.get("segment"),
                default=_segment_from_spec(str(state.get("spec", ""))),
                char_limit=80,
            ),
        },
        "tech_feasibility": {
            "score": technical.get("score", 0.75),
            "notes": technical.get("notes", ""),
        },
        "claims": claims,
        "evidence": evidence,
        "dissent": [],
        "open_questions": [],
        "winning_theses": _normalized_research_strings(
            [item.get("statement") for item in winning],
            limit=3,
            char_limit=220,
        ),
        "confidence_summary": {
            "average": round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0,
            "floor": round(min(confidence_values), 2) if confidence_values else 0.0,
        },
        "model_assignments": _phase_model_assignments(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)),
    }
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "claims"): claims,
            _node_state_key(node_id, "evidence"): evidence,
            "research": research,
            "output": research,
        },
        artifacts=_artifacts({"name": "research-report", "kind": "research", **research}),
    )


def _research_evidence_librarian_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    research = _as_dict(state.get("research"))
    evidence = _collect_state_lists(state, node_ids=_RESEARCH_PROPOSAL_NODES + ("research-synthesizer",), suffix="evidence")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("id", "")).strip()
        if not evidence_id or evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        normalized.append(item)
    source_links = _dedupe_strings(
        [
            str(item.get("source_ref", "")).strip()
            for item in normalized
            if str(item.get("source_type", "")).strip() == "url"
        ]
    )
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "evidence"): normalized,
            _node_state_key(node_id, "source_links"): source_links,
            "research": {**research, "evidence": normalized, "source_links": source_links},
        },
        artifacts=_artifacts({"name": "claim-ledger", "kind": "research", "evidence": normalized, "source_links": source_links}),
    )


async def _execute_research_retry_node(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None,
    llm_runtime: LLMRuntime | None,
) -> NodeResult | None:
    if node_id == "competitor-analyst":
        return await _research_competitor_autonomous_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    if node_id == "market-researcher":
        return await _research_market_autonomous_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    if node_id == "user-researcher":
        return await _research_user_autonomous_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    if node_id == "tech-evaluator":
        return await _research_tech_autonomous_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    if node_id == "devils-advocate-researcher":
        return await _research_devils_advocate_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    if node_id == "cross-examiner":
        return _research_cross_examiner_handler(
            node_id,
            state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
    return None


async def _research_devils_advocate_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    threats = [str(item) for item in _as_list(research.get("threats")) if str(item).strip()]
    fallback_dissent = [
        _dissent_entry(
            f"dissent-{index + 1}",
            claim_id=str(claim.get("id", "")),
            challenger=node_id,
            argument=(
                threats[index % len(threats)]
                if threats
                else "This claim could collapse if the product becomes feature-broad before it proves operator trust and recovery."
            ),
            severity="high" if str(claim.get("category")) in {"competition", "technical"} else "medium",
            recommended_test="Define the observable evidence that would falsify this claim in the first milestone.",
        )
        for index, claim in enumerate(claims[:3])
        if str(claim.get("id", "")).strip()
    ]
    fallback_questions = _dedupe_strings(
        [
            "どの claim が外れていた場合に alpha scope を即座に縮小するか",
            "競合優位が UI の見た目ではなく運用面で再現可能か",
            "ユーザーは自律化より traceability を先に求めていないか",
        ]
    )
    llm_events: list[dict[str, Any]] = []
    if _provider_backed_lifecycle_available(provider_registry) and claims:
        payload, llm_events, llm_meta = await _research_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-research-{node_id}",
            static_instruction=(
                "You are a devil's advocate for product research. Return JSON only with keys dissent and open_questions. "
                "Attack weak assumptions, not formatting."
            ),
            user_prompt=(
                "Return JSON only.\n"
                f"Claims: {claims}\n"
                f"Threats: {threats}\n"
                f"User signals: {_as_dict(research.get('user_research')).get('signals')}\n"
                "dissent items must include claim_id, argument, severity, recommended_test."
            ),
            schema_name="research-devils-advocate",
            required_keys=["dissent", "open_questions"],
            phase="research",
            node_id=node_id,
        )
        raw_dissent = [
            _dissent_entry(
                f"dissent-llm-{index + 1}",
                claim_id=str(_as_dict(item).get("claim_id", "")),
                challenger=node_id,
                argument=_first_research_text(_as_dict(item).get("argument")),
                severity=_first_research_text(_as_dict(item).get("severity"), default="medium", char_limit=24) or "medium",
                recommended_test=_first_research_text(_as_dict(item).get("recommended_test")),
            )
            for index, item in enumerate(_as_list(_as_dict(payload).get("dissent")))
            if str(_as_dict(item).get("claim_id", "")).strip() and _first_research_text(_as_dict(item).get("argument"))
        ]
        if raw_dissent:
            fallback_dissent = raw_dissent
        llm_questions = _normalized_research_strings(_as_dict(payload).get("open_questions"), limit=4, char_limit=220)
        if llm_questions:
            fallback_questions = llm_questions
    else:
        llm_meta = {"parse_status": "strict", "raw_preview": ""}
    node_result = research_node_result(
        node_id,
        status="success" if fallback_dissent else "degraded",
        parse_status=str(llm_meta.get("parse_status", "strict")),
        artifact={
            "dissent_count": len(fallback_dissent),
            "open_question_count": len(fallback_questions),
        },
        degradation_reasons=list(llm_meta.get("degradation_reasons", [])),
        raw_preview=str(llm_meta.get("raw_preview", "")),
        llm_events=llm_events,
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "dissent"): fallback_dissent,
            _node_state_key(node_id, "open_questions"): fallback_questions,
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts({"name": "research-dissent", "kind": "research", "dissent": fallback_dissent, "open_questions": fallback_questions}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _research_cross_examiner_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    research = _as_dict(state.get("research"))
    claims = [_as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)]
    evidence = [_as_dict(item) for item in _as_list(research.get("evidence")) if _as_dict(item)]
    evidence_map = {str(item.get("id")): item for item in evidence if str(item.get("id", "")).strip()}
    dissent = _collect_state_lists(state, node_ids=("devils-advocate-researcher",), suffix="dissent")
    updated_claims: list[dict[str, Any]] = []
    updated_dissent: list[dict[str, Any]] = []
    open_questions = _dedupe_strings(
        _normalized_research_strings(
            state.get(_node_state_key("devils-advocate-researcher", "open_questions")),
            limit=8,
            char_limit=220,
        )
    )
    for claim in claims:
        claim_id = str(claim.get("id", "")).strip()
        claim_dissent = [item for item in dissent if str(item.get("claim_id", "")) == claim_id]
        evidence_count = sum(1 for ev_id in _as_list(claim.get("evidence_ids")) if str(ev_id) in evidence_map)
        resolved_claim_dissent: list[dict[str, Any]] = []
        for item in claim_dissent:
            patched = dict(item)
            severity = str(item.get("severity", "medium"))
            resolved = evidence_count >= 2 or (severity == "high" and evidence_count >= 1 and float(_as_dict(research.get("tech_feasibility")).get("score", 0.0) or 0.0) >= 0.8)
            if resolved:
                patched["resolved"] = True
                patched["resolution"] = "Cross examination found enough evidence or delivery control to keep this claim alive."
            resolved_claim_dissent.append(patched)
        unresolved = [item for item in resolved_claim_dissent if item.get("resolved") is not True]
        confidence = _claim_confidence(evidence_count=evidence_count, unresolved_dissent=unresolved, default=float(claim.get("confidence", 0.72) or 0.72))
        updated_claims.append({**claim, "confidence": confidence, "status": _claim_status(confidence, unresolved)})
        updated_dissent.extend(resolved_claim_dissent)
        if evidence_count < 2:
            open_questions.append(f"{claim.get('statement')} を裏づける追加 evidence が必要")
    node_result = research_node_result(
        node_id,
        status="success" if not [item for item in updated_dissent if str(item.get("severity")) == "critical" and item.get("resolved") is not True] else "degraded",
        parse_status="strict",
        artifact={
            "claim_count": len(updated_claims),
            "unresolved_dissent_count": len([item for item in updated_dissent if item.get("resolved") is not True]),
            "open_question_count": len(_dedupe_strings(open_questions)),
        },
        degradation_reasons=(
            []
            if not [item for item in updated_dissent if str(item.get("severity")) == "critical" and item.get("resolved") is not True]
            else ["critical_dissent_unresolved"]
        ),
        retry_count=_research_retry_count(state, node_id),
    )
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "claims"): updated_claims,
            _node_state_key(node_id, "dissent"): updated_dissent,
            _node_state_key(node_id, "open_questions"): _dedupe_strings(open_questions),
            _node_state_key(node_id, "result"): node_result,
        },
        artifacts=_artifacts({"name": "research-cross-examination", "kind": "research", "claims": updated_claims, "dissent": updated_dissent}),
    )


async def _research_judge_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    working_state = dict(state)
    llm_events: list[dict[str, Any]] = []
    remediation_trace: list[dict[str, Any]] = []
    remediation_iteration = 0
    max_remediation_iterations = 2
    retained_summary = ""
    retained_winning_theses: list[str] = []
    retained_open_questions: list[str] = []
    retained_overrides: dict[str, float] = {}
    target_language = str(state.get("output_language", "ja") or "ja")

    while True:
        research = _as_dict(working_state.get("research"))
        remediation_context = _research_remediation_context(working_state)
        claims = _collect_state_lists(working_state, node_ids=("cross-examiner",), suffix="claims") or [
            _as_dict(item) for item in _as_list(research.get("claims")) if _as_dict(item)
        ]
        dissent = _collect_state_lists(working_state, node_ids=("cross-examiner",), suffix="dissent")
        open_questions = _dedupe_strings(
            _normalized_research_strings(
                working_state.get(_node_state_key("cross-examiner", "open_questions")),
                limit=8,
                char_limit=220,
            )
        )
        if open_questions:
            retained_open_questions = _dedupe_strings(retained_open_questions + open_questions)
        llm_summary = ""
        llm_winning_theses: list[str] = []
        llm_meta = {"parse_status": "strict", "raw_preview": "", "degradation_reasons": []}
        if _provider_backed_lifecycle_available(provider_registry) and claims:
            payload, judge_events, llm_meta = await _research_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose=f"lifecycle-research-{node_id}",
                static_instruction=(
                    "You are a research judge. Return JSON only with keys winning_theses, claim_confidence_overrides, summary, open_questions, blocking_reasons, retry_node_ids. "
                    "Use conservative confidence updates."
                ),
                user_prompt=(
                    "Return JSON only.\n"
                    f"Claims: {claims}\n"
                    f"Dissent: {dissent}\n"
                    f"Open questions: {open_questions}\n"
                ),
                schema_name="research-judge",
                required_keys=[
                    "winning_theses",
                    "claim_confidence_overrides",
                    "summary",
                    "open_questions",
                    "blocking_reasons",
                    "retry_node_ids",
                ],
                phase="research",
                node_id=node_id,
            )
            llm_events.extend(judge_events)
            llm_summary = _first_research_text(_as_dict(payload).get("summary"), char_limit=280)
            if llm_summary:
                retained_summary = llm_summary
            overrides = _claim_confidence_overrides(_as_dict(payload).get("claim_confidence_overrides"))
            if not overrides:
                overrides = _claim_confidence_overrides(_as_dict(payload).get("winning_theses"))
            if overrides:
                retained_overrides.update(overrides)
            overrides = dict(retained_overrides)
            if overrides:
                patched_claims = []
                for claim in claims:
                    claim_id = str(claim.get("id", ""))
                    if claim_id in overrides:
                        confidence = _clamp_score(
                            overrides.get(claim_id),
                            default=float(claim.get("confidence", 0.72) or 0.72),
                        )
                        unresolved = [
                            item
                            for item in dissent
                            if str(item.get("claim_id", "")) == claim_id
                            and item.get("resolved") is not True
                        ]
                        patched_claims.append(
                            {
                                **claim,
                                "confidence": confidence,
                                "status": _claim_status(confidence, unresolved),
                            }
                        )
                    else:
                        patched_claims.append(claim)
                claims = patched_claims
            llm_questions = _normalized_research_strings(
                _as_dict(payload).get("open_questions"),
                limit=8,
                char_limit=220,
            )
            if llm_questions:
                retained_open_questions = _dedupe_strings(retained_open_questions + llm_questions)
            open_questions = _dedupe_strings(open_questions + retained_open_questions)
            llm_winning_theses = _normalized_research_strings(
                _resolved_winning_thesis_strings(
                    _as_dict(payload).get("winning_theses"),
                    claims=claims,
                    limit=3,
                    char_limit=220,
                ),
                limit=3,
                char_limit=220,
            )
            if llm_winning_theses:
                retained_winning_theses = llm_winning_theses
        open_questions = _dedupe_strings(open_questions + retained_open_questions)

        winners = _winning_claims(claims)
        confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in claims]
        node_results = collect_research_node_results(
            working_state,
            list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES),
        )
        final_research = {
            **research,
            "claims": claims,
            "evidence": _collect_state_lists(
                working_state,
                node_ids=("evidence-librarian",),
                suffix="evidence",
            ) or _as_list(research.get("evidence")),
            "dissent": dissent,
            "source_links": _as_list(
                working_state.get(_node_state_key("evidence-librarian", "source_links"))
            ) or _as_list(research.get("source_links")),
            "open_questions": open_questions,
            "winning_theses": retained_winning_theses
            or llm_winning_theses
            or _normalized_research_strings(
                [item.get("statement") for item in winners],
                limit=3,
                char_limit=220,
            ),
            "confidence_summary": {
                "average": round(sum(confidence_values) / len(confidence_values), 2)
                if confidence_values
                else 0.0,
                "floor": round(min(confidence_values), 2) if confidence_values else 0.0,
                "accepted": sum(
                    1 for item in claims if str(item.get("status")) == "accepted"
                ),
            },
            "judge_summary": llm_summary
            or retained_summary
            or "Claims that survived dissent are passed to planning together with unresolved questions.",
            "critical_dissent_count": sum(
                1
                for item in dissent
                if str(item.get("severity")) == "critical"
                and item.get("resolved") is not True
            ),
            "resolved_dissent_count": sum(
                1 for item in dissent if item.get("resolved") is True
            ),
            "model_assignments": _phase_model_assignments(
                list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)
            ),
            "low_diversity_mode": _phase_low_diversity_mode(
                list(_RESEARCH_PROPOSAL_NODES) + list(_RESEARCH_REVIEW_NODES)
            ),
            "execution_trace": remediation_trace,
        }
        quality_gates, readiness, remediation_plan = evaluate_research_quality(
            final_research,
            node_results=node_results,
            remaining_iterations=max(
                0,
                max_remediation_iterations - remediation_iteration,
            ),
            proposal_node_ids=list(_RESEARCH_PROPOSAL_NODES),
            review_node_ids=list(_RESEARCH_REVIEW_NODES),
            identity_profile=_research_identity_profile(working_state),
        )
        judge_reasons = list(llm_meta.get("degradation_reasons", []))
        if readiness != "ready":
            judge_reasons.extend(
                [
                    f"quality_gate_failed:{gate['id']}"
                    for gate in quality_gates
                    if gate.get("passed") is not True
                ]
            )
        judge_result = research_node_result(
            node_id,
            status="success" if readiness == "ready" else "degraded",
            parse_status=str(llm_meta.get("parse_status", "strict")),
            artifact={
                "readiness": readiness,
                "winning_thesis_count": len(final_research["winning_theses"]),
                "quality_gate_count": len(quality_gates),
            },
            degradation_reasons=judge_reasons,
            raw_preview=str(llm_meta.get("raw_preview", "")),
            llm_events=llm_events,
            retry_count=_research_retry_count(working_state, node_id)
            + remediation_iteration,
        )
        final_research["node_results"] = [*node_results, judge_result]
        final_research["quality_gates"] = quality_gates
        final_research["readiness"] = readiness
        if remediation_plan:
            final_research["remediation_plan"] = remediation_plan
        else:
            final_research.pop("remediation_plan", None)
        final_research["autonomous_remediation"] = _research_autonomous_remediation_state(
            final_research,
            quality_gates=quality_gates,
            remediation_plan=remediation_plan,
            remediation_context=remediation_context,
            readiness=readiness,
        )
        canonical_research = with_research_operator_copy(
            dict(final_research),
            target_language="en",
        )
        localized_research, localization_events, localization_meta = await _localize_research_output(
            canonical_research,
            target_language=target_language,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        localized_research["autonomous_remediation"] = _research_autonomous_remediation_state(
            localized_research,
            quality_gates=quality_gates,
            remediation_plan=localized_research.get("remediation_plan")
            if isinstance(localized_research.get("remediation_plan"), dict)
            else remediation_plan,
            remediation_context=remediation_context,
            readiness=readiness,
        )
        final_research = {
            **localized_research,
            "canonical": canonical_research,
            "localized": dict(localized_research),
        }
        final_research["view_model"] = build_research_view_model(final_research)
        runtime_output = _research_runtime_output(final_research)
        if localization_meta.get("status") not in {None, "noop", "skipped"}:
            judge_result["artifact"]["localized"] = True
        llm_events.extend(localization_events)

        if readiness == "ready" or remediation_plan is None:
            return NodeResult(
                state_patch={
                    "research": final_research,
                    "output": runtime_output,
                    _node_state_key(node_id, "result"): judge_result,
                },
                artifacts=_artifacts(_research_judgement_artifact(final_research)),
                llm_events=llm_events,
                metrics={
                    "review_mode": "provider-backed" if llm_events else "deterministic-reference",
                    "remediation_iterations": remediation_iteration,
                },
                event_output=runtime_output,
            )

        remediation_iteration += 1
        working_state["research"] = final_research
        remediation_trace.append(
            {
                "iteration": remediation_iteration,
                "retry_node_ids": list(remediation_plan.get("retryNodeIds", [])),
                "objective": str(remediation_plan.get("objective", "")),
            }
        )
        for retry_node_id in remediation_plan.get("retryNodeIds", []):
            retried = await _execute_research_retry_node(
                str(retry_node_id),
                working_state,
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            if retried is None:
                continue
            working_state.update(retried.state_patch)
            llm_events.extend(list(retried.llm_events))
        synth = _research_synthesizer_handler("research-synthesizer", working_state)
        working_state.update(synth.state_patch)
        librarian = _research_evidence_librarian_handler("evidence-librarian", working_state)
        working_state.update(librarian.state_patch)
        advocate = await _research_devils_advocate_handler(
            "devils-advocate-researcher",
            working_state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        working_state.update(advocate.state_patch)
        llm_events.extend(list(advocate.llm_events))
        examiner = _research_cross_examiner_handler(
            "cross-examiner",
            working_state,
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        working_state.update(examiner.state_patch)


def _planning_persona_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    personas, stories, journeys = _build_persona_bundle(state)
    return NodeResult(
        state_patch={
            "persona_report": personas,
            "story_report": stories,
            "journey_report": journeys,
        },
        artifacts=_artifacts({"name": "product-brief", "kind": "planning", "personas": personas}),
    )


def _planning_story_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    payload = _build_story_architecture_bundle(state)
    return NodeResult(
        state_patch=payload,
        artifacts=_artifacts({"name": "story-architecture", "kind": "planning", **payload}),
    )


def _planning_feature_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    kano_features = _default_kano_features_for_spec(state)
    features = _default_feature_selections_for_spec(state)
    return NodeResult(
        state_patch={
            "kano_report": kano_features,
            "feature_selections": features,
            _node_state_key(node_id, "feature_decisions"): _build_feature_decisions(state, features),
        },
        artifacts=_artifacts({"name": "feature-priority-matrix", "kind": "planning", "features": features}),
    )


def _planning_solution_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    plan_estimates = _build_plan_estimates(state)
    solution = _solution_bundle(state)
    return NodeResult(
        state_patch={
            "recommended_milestones": solution["recommended_milestones"],
            "plan_estimates_report": plan_estimates,
            "business_model_report": solution["business_model"],
            "design_tokens_report": solution["design_tokens"],
        },
        artifacts=_artifacts({"name": "delivery-plan", "kind": "planning", "plan_estimates": plan_estimates}),
    )


def _planning_synthesizer_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    features = list(state.get("feature_selections", []))
    plan_estimates = list(state.get("plan_estimates_report", []))
    milestones = list(state.get("recommended_milestones", []))
    traceability = _build_traceability(state, features, milestones)
    planning_context = _planning_context_payload(
        state,
        features=features,
        personas=list(state.get("persona_report", [])),
        use_cases=list(state.get("use_cases", [])),
        milestones=milestones,
        design_tokens=_as_dict(state.get("design_tokens_report")),
        business_model=_as_dict(state.get("business_model_report")),
    )
    analysis = {
        "personas": list(state.get("persona_report", [])),
        "user_stories": list(state.get("story_report", [])),
        "kano_features": list(state.get("kano_report", [])),
        "recommendations": _planning_recommendations(state),
        "business_model": _as_dict(state.get("business_model_report")),
        "user_journeys": list(state.get("journey_report", [])),
        "job_stories": list(state.get("job_stories", [])),
        "actors": list(state.get("actors", [])),
        "roles": list(state.get("roles", [])),
        "use_cases": list(state.get("use_cases", [])),
        "ia_analysis": _as_dict(state.get("ia_analysis")),
        "recommended_milestones": milestones,
        "design_tokens": _as_dict(state.get("design_tokens_report")),
        "feature_decisions": _build_feature_decisions(state, features),
        "rejected_features": [
            {
                "feature": str(item.get("feature", "")),
                "reason": "Held for later to preserve falsifiable scope and delivery confidence.",
                "counterarguments": ["This feature increases complexity before the first evidence loop is validated."],
            }
            for item in features
            if item.get("selected") is not True and str(item.get("feature", "")).strip()
        ],
        "assumptions": [],
        "red_team_findings": [],
        "negative_personas": [],
        "kill_criteria": [],
        "traceability": traceability,
        "coverage_summary": {},
        "planning_context": planning_context,
        "model_assignments": _phase_model_assignments(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
    }
    analysis["coverage_summary"] = _planning_coverage_summary(
        analysis=analysis,
        features=features,
        plan_estimates=plan_estimates,
    )
    planning_payload = {**analysis, "features": features, "plan_estimates": plan_estimates}
    return NodeResult(
        state_patch={
            "analysis": analysis,
            "features": features,
            "planEstimates": plan_estimates,
            "planning": planning_payload,
            "output": planning_payload,
        },
        artifacts=_artifacts({"name": "planning-summary", "kind": "planning", **planning_payload}),
    )


async def _planning_scope_skeptic_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    features = [_as_dict(item) for item in _as_list(state.get("feature_selections")) if _as_dict(item)]
    fallback_rejected = _planning_rejected_features(features)
    fallback_findings = _planning_scope_findings(node_id, features)
    llm_events: list[dict[str, Any]] = []
    if _provider_backed_lifecycle_available(provider_registry) and features:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-planning-{node_id}",
            static_instruction=(
                "You are a scope skeptic. Return JSON only with keys rejected_features and red_team_findings. "
                "Prefer cutting scope over vague risk language."
            ),
            user_prompt=f"Features: {features}\nResearch: {_as_dict(state.get('research'))}\n",
            phase="planning",
            node_id=node_id,
        )
        raw_rejected = [
            {
                "feature": str(_as_dict(item).get("feature", "")).strip(),
                "reason": str(_as_dict(item).get("reason", "")).strip(),
                "counterarguments": [str(arg).strip() for arg in _as_list(_as_dict(item).get("counterarguments")) if str(arg).strip()],
            }
            for item in _as_list(_as_dict(payload).get("rejected_features"))
            if str(_as_dict(item).get("feature", "")).strip() and str(_as_dict(item).get("reason", "")).strip()
        ]
        raw_findings = [
            _finding_entry(
                f"scope-llm-{index + 1}",
                title=str(_as_dict(item).get("title", "")).strip() or "Scope finding",
                challenger=node_id,
                severity=str(_as_dict(item).get("severity", "medium")).strip() or "medium",
                impact=str(_as_dict(item).get("impact", "")).strip(),
                recommendation=str(_as_dict(item).get("recommendation", "")).strip(),
                related_feature=str(_as_dict(item).get("related_feature", "")).strip(),
            )
            for index, item in enumerate(_as_list(_as_dict(payload).get("red_team_findings")))
            if str(_as_dict(item).get("recommendation", "")).strip()
        ]
        if raw_rejected:
            fallback_rejected = raw_rejected
        if raw_findings:
            fallback_findings = raw_findings
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "rejected_features"): fallback_rejected,
            _node_state_key(node_id, "red_team_findings"): fallback_findings,
        },
        artifacts=_artifacts({"name": "scope-review", "kind": "planning", "rejected_features": fallback_rejected, "red_team_findings": fallback_findings}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


def _planning_assumption_auditor_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    personas = [_as_dict(item) for item in _as_list(state.get("persona_report")) if _as_dict(item)]
    assumptions = _planning_assumption_records(state, personas)
    findings = _planning_assumption_findings(node_id)
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "assumptions"): assumptions,
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "assumption-audit", "kind": "planning", "assumptions": assumptions, "red_team_findings": findings}),
    )


def _planning_negative_persona_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    personas = _planning_negative_personas_for_state(state)
    findings = _planning_negative_persona_findings(node_id)
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "negative_personas"): personas,
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "negative-persona-review", "kind": "planning", "negative_personas": personas}),
    )


def _planning_milestone_falsifier_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    del provider_registry, llm_runtime
    milestones = [_as_dict(item) for item in _as_list(state.get("recommended_milestones")) if _as_dict(item)]
    kill_criteria = _planning_kill_criteria_for_milestones(milestones)
    findings = _planning_milestone_findings(node_id, milestones)
    return NodeResult(
        state_patch={
            _node_state_key(node_id, "kill_criteria"): kill_criteria,
            _node_state_key(node_id, "red_team_findings"): findings,
        },
        artifacts=_artifacts({"name": "milestone-falsification", "kind": "planning", "kill_criteria": kill_criteria, "red_team_findings": findings}),
    )


async def _planning_judge_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    analysis = _as_dict(state.get("analysis"))
    target_language = str(state.get("output_language", "ja") or "ja")
    features = [_as_dict(item) for item in _as_list(state.get("feature_selections")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(state.get("recommended_milestones")) if _as_dict(item)]
    feature_decisions = [_as_dict(item) for item in _as_list(analysis.get("feature_decisions")) if _as_dict(item)] or _build_feature_decisions(state, features)
    rejected_features = _collect_state_lists(state, node_ids=("scope-skeptic",), suffix="rejected_features") or _as_list(analysis.get("rejected_features"))
    assumptions = _collect_state_lists(state, node_ids=("assumption-auditor",), suffix="assumptions")
    negative_personas = _collect_state_lists(state, node_ids=("negative-persona-challenger",), suffix="negative_personas")
    kill_criteria = _collect_state_lists(state, node_ids=("milestone-falsifier",), suffix="kill_criteria")
    findings = (
        _collect_state_lists(state, node_ids=("scope-skeptic", "assumption-auditor", "negative-persona-challenger", "milestone-falsifier"), suffix="red_team_findings")
        or _as_list(analysis.get("red_team_findings"))
    )
    review_defaults = _planning_review_defaults(
        state,
        features=features,
        personas=[_as_dict(item) for item in _as_list(analysis.get("personas")) if _as_dict(item)],
        milestones=milestones,
    )
    rejected_features = rejected_features or list(review_defaults.get("rejected_features", []))
    assumptions = assumptions or list(review_defaults.get("assumptions", []))
    negative_personas = negative_personas or list(review_defaults.get("negative_personas", []))
    kill_criteria = kill_criteria or list(review_defaults.get("kill_criteria", []))
    findings = findings or list(review_defaults.get("red_team_findings", []))
    traceability = _build_traceability(state, features, milestones)
    llm_events: list[dict[str, Any]] = []
    judge_summary = ""
    if _provider_backed_lifecycle_available(provider_registry) and feature_decisions:
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-planning-{node_id}",
            static_instruction=(
                "You are a planning judge. Return JSON only with keys recommendations and headline_risks. "
                "Focus on what should survive to design and development."
            ),
            user_prompt=(
                "Return JSON only.\n"
                f"Feature decisions: {feature_decisions}\n"
                f"Red team findings: {findings}\n"
                f"Assumptions: {assumptions}\n"
                f"Negative personas: {negative_personas}\n"
            ),
            phase="planning",
            node_id=node_id,
        )
        llm_recommendations = _dedupe_strings([str(item).strip() for item in _as_list(_as_dict(payload).get("recommendations")) if str(item).strip()])
        if llm_recommendations:
            analysis["recommendations"] = _dedupe_strings(llm_recommendations + [str(item) for item in _as_list(analysis.get("recommendations")) if str(item).strip()])
        judge_summary = ", ".join(
            str(item).strip() for item in _as_list(_as_dict(payload).get("headline_risks")) if str(item).strip()
        )
    decision_map = {str(item.get("feature", "")): dict(item) for item in feature_decisions if str(item.get("feature", "")).strip()}
    rejected_map = {str(item.get("feature", "")): dict(item) for item in rejected_features if str(item.get("feature", "")).strip()}
    for feature in features:
        name = str(feature.get("feature", "")).strip()
        if not name or name not in decision_map:
            continue
        decision = decision_map[name]
        if name in rejected_map:
            decision["selected"] = False
            decision["rejection_reason"] = str(rejected_map[name].get("reason", decision.get("rejection_reason", "")))
            decision["counterarguments"] = _dedupe_strings(
                [str(item) for item in _as_list(decision.get("counterarguments")) if str(item).strip()]
                + [str(item) for item in _as_list(rejected_map[name].get("counterarguments")) if str(item).strip()]
            )
        elif str(feature.get("implementation_cost")) == "high":
            decision["counterarguments"] = _dedupe_strings(
                [str(item) for item in _as_list(decision.get("counterarguments")) if str(item).strip()]
                + ["High-cost scope must prove its necessity with a first-milestone signal."]
            )
    final_features = []
    for feature in features:
        name = str(feature.get("feature", "")).strip()
        decision = decision_map.get(name, {})
        final_features.append({**feature, "selected": decision.get("selected", feature.get("selected")) is True})
    confidence_values = [1.0 - float(item.get("uncertainty", 0.3) or 0.3) for item in decision_map.values()] or [0.7]
    final_plan_estimates = list(state.get("plan_estimates_report", []))
    final_analysis = {
        **analysis,
        "feature_decisions": list(decision_map.values()),
        "rejected_features": list(rejected_map.values()),
        "assumptions": assumptions,
        "red_team_findings": _dedupe_findings_by_title([_as_dict(item) for item in findings if _as_dict(item)]),
        "negative_personas": negative_personas,
        "kill_criteria": kill_criteria,
        "traceability": traceability,
        "confidence_summary": {
            "average": round(sum(confidence_values) / len(confidence_values), 2),
            "floor": round(min(confidence_values), 2),
            "critical_findings": sum(1 for item in findings if str(item.get("severity")) == "critical"),
        },
        "judge_summary": judge_summary or "The plan keeps only features that remain traceable to research claims and falsifiable milestones.",
        "model_assignments": _phase_model_assignments(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
        "low_diversity_mode": _phase_low_diversity_mode(list(_PLANNING_PROPOSAL_NODES) + list(_PLANNING_REVIEW_NODES)),
    }
    final_analysis["planning_context"] = _planning_context_payload(
        state,
        features=final_features,
        personas=[_as_dict(item) for item in _as_list(final_analysis.get("personas")) if _as_dict(item)],
        use_cases=[_as_dict(item) for item in _as_list(final_analysis.get("use_cases")) if _as_dict(item)],
        milestones=milestones,
        design_tokens=_as_dict(final_analysis.get("design_tokens")),
        business_model=_as_dict(final_analysis.get("business_model")),
    )
    final_analysis["coverage_summary"] = _planning_coverage_summary(
        analysis=final_analysis,
        features=final_features,
        plan_estimates=final_plan_estimates,
    )
    canonical_analysis = with_planning_operator_copy(dict(final_analysis), target_language="en")
    localized_analysis, localization_events, _ = await _localize_planning_output(
        canonical_analysis,
        target_language=target_language,
        provider_registry=provider_registry,
        llm_runtime=llm_runtime,
    )
    final_analysis = {
        **localized_analysis,
        "canonical": canonical_analysis,
        "localized": dict(localized_analysis),
    }
    llm_events.extend(localization_events)
    planning_payload = {**final_analysis, "features": final_features, "plan_estimates": final_plan_estimates}
    return NodeResult(
        state_patch={
            "analysis": final_analysis,
            "features": final_features,
            "planEstimates": final_plan_estimates,
            "planning": planning_payload,
            "output": planning_payload,
        },
        artifacts=_artifacts({"name": "planning-judgement", "kind": "planning", **planning_payload}),
        llm_events=llm_events,
        metrics={"review_mode": "provider-backed" if llm_events else "deterministic-reference"},
    )


_DISTILLED_FRONTEND_AESTHETICS = (
    "Avoid generic AI-generated UI. Choose a distinctive product aesthetic with strong typography, "
    "cohesive design tokens, layered backgrounds, and a clear visual point of view. "
    "Do not use landing-page tropes, weak hero sections, or safe filler dashboards. "
    "Favor memorable, production-grade product surfaces that feel closer to Linear, Stripe, or Vercel in craft."
)


_PRODUCT_PROTOTYPE_GUARDRAILS = (
    "This is the product itself, not a marketing site. "
    "Return application shells, task flows, approval/review surfaces, lineage or evidence views, "
    "status-heavy operator screens, and at least one degraded or blocked state. "
    "Do not return pricing sections, waitlists, testimonial carousels, or hero-only compositions. "
    "screen_labels must be short strings naming real in-product screens, never objects or section specs. "
    "navigation_style must be sidebar or top-nav. density must be low, medium, or high. "
    "visual_style must be obsidian-atelier, ivory-signal, or balanced-product."
)


def _design_variant_handler(
    model_name: str,
    pattern_name: str,
    description: str,
    primary: str,
    accent: str,
    creative_brief: str = "",
    prototype_seed_overrides: dict[str, Any] | None = None,
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
):
    def handler(node_id: str, state: dict[str, Any]) -> NodeResult:
        selected_features = _selected_feature_names(state)
        spec = str(state.get("spec", ""))
        decision_context = _decision_context_from_state(state, compact=True)
        decision_scope = _decision_scope_for_phase(state, phase="design")
        plan = {
            "phase": "design",
            "node_id": node_id,
            "agent_label": model_name,
            "objective": "Produce a differentiated design direction with strong operator clarity.",
            "candidate_skills": [],
            "selected_skills": [],
            "quality_targets": _phase_quality_targets("design"),
            "delegations": [],
            "mode": "deterministic-reference",
            "execution_note": description,
        }
        variant = _design_variant_payload(
            node_id=node_id,
            model_name=model_name,
            pattern_name=pattern_name,
            description=description,
            primary=primary,
            accent=accent,
            selected_features=selected_features,
            spec=spec,
            analysis=_as_dict(state.get("analysis")),
            rationale=description,
            prototype_overrides=prototype_seed_overrides,
            decision_context_fingerprint=str(decision_context.get("fingerprint") or ""),
            decision_scope=decision_scope,
            model_ref=_preferred_lifecycle_model(node_id, provider_registry),
            plan_estimates=[dict(item) for item in _as_list(state.get("planEstimates")) if isinstance(item, dict)],
            selected_preset=str(state.get("selectedPreset") or ""),
            target_language=str(_as_dict(state.get("researchConfig")).get("outputLanguage") or "ja"),
        )
        return NodeResult(
            state_patch={
                f"{node_id}_variant": variant,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): [],
                _peer_feedback_state_key(node_id): [],
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-variant", "kind": "design", **variant},
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
            ),
            metrics={"design_mode": "deterministic-reference"},
        )

    async def autonomous_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
        selected_features = _selected_feature_names(state)
        spec = str(state.get("spec", ""))
        analysis = _as_dict(state.get("analysis"))
        personas = _as_list(analysis.get("personas"))
        design_tokens = _as_dict(analysis.get("design_tokens"))
        planning_context = _as_dict(analysis.get("planning_context"))
        decision_context = _decision_context_from_state(state, compact=True)
        decision_scope = _decision_scope_for_phase(state, phase="design")
        plan, plan_events = await _plan_node_collaboration(
            phase="design",
            node_id=node_id,
            state=state,
            objective="Produce a differentiated design direction with operator trust, accessibility, and mobile resilience.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        proposal_prompt = (
            "Design a high-quality product experience for the following product.\n"
            "Return a JSON object with keys: "
            "pattern_name, description, primary_color, accent_color, rationale, "
            "quality_focus, scores, and optional prototype_kind, navigation_style, density, "
            "screen_labels, interaction_principles, visual_style, display_font, body_font, "
            "experience_thesis, operational_bet, signature_moments, handoff_note, implementation_brief.\n"
            "The scores object must include ux_quality, code_quality, performance, accessibility as 0-1 floats.\n"
            "screen_labels must be 3-4 short strings such as 'Run Ledger' or 'Approval Gate'. Do not return objects.\n"
            "signature_moments must be 2-4 short strings describing memorable operator moments.\n"
            "implementation_brief must be an object with keys: architecture_thesis, system_shape, technical_choices, agent_lanes, delivery_slices.\n"
            "architecture_thesis must be 1 sentence in Japanese explaining the system shape behind this direction.\n"
            "system_shape must be 3-5 short Japanese strings naming structural decisions.\n"
            "technical_choices must be 3-4 objects with keys area, decision, rationale.\n"
            "agent_lanes must be 2-3 objects with keys role, remit, skills.\n"
            "delivery_slices must be 3-5 short Japanese strings naming the build slices to carry into implementation.\n"
            "Every concept must describe the actual product UI, not an LP, launch page, hero, pricing page, or signup flow.\n"
            "All user-facing labels, screen names, actions, and short copy should be written in Japanese.\n"
            "The two directions must differ in workflow rhythm, information density, and operator ergonomics, not just color.\n"
            f"Current design theme anchor: {pattern_name} / {description}\n"
            f"Creative brief: {creative_brief or description}\n"
            f"Product spec: {spec}\n"
            f"Selected features: {selected_features}\n"
            f"Primary persona summary: {personas[:2]}\n"
            f"Planning context: {planning_context}\n"
            f"Decision context: {decision_context}\n"
            f"Design tokens: {design_tokens}\n"
            f"IA analysis: {_as_dict(analysis.get('ia_analysis'))}\n"
            f"Use cases: {_as_list(analysis.get('use_cases'))[:3]}\n"
            f"Job stories: {_as_list(analysis.get('job_stories'))[:2]}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
            f"Quality targets: {plan.get('quality_targets')}\n"
            f"Delegation plan: {plan.get('delegations')}\n"
            f"{_DISTILLED_FRONTEND_AESTHETICS}\n"
            f"{_PRODUCT_PROTOTYPE_GUARDRAILS}\n"
            "Bias toward clarity, mobile resilience, accessibility, and differentiation. "
            "Prefer app shells, task flows, and operational screens over hero-led storytelling. "
            "Use design tokens intentionally and make the interface feel authored rather than generated. "
            "Force the output toward concrete workflow screens, data-dense review surfaces, and recoverable states. "
            "The lead thesis in the decision context must be visible in the interface behavior, not merely repeated as copy. "
            "Show the product's winning path through approval ergonomics, evidence visibility, and handoff readiness."
        )
        proposal, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-design-{node_id}",
            static_instruction=(
                "You are a principal product designer improving a lifecycle artifact. "
                "Return JSON only and optimize for operator trust, visual clarity, accessibility, strong differentiation, "
                "and memorable product craft."
            ),
            user_prompt=proposal_prompt,
            phase="design",
            node_id=node_id,
        )
        critique_prompt = (
            "Critique and improve this design concept. Return JSON only with the same keys "
            "plus optional provider_note.\n"
            f"Original concept: {proposal or {'pattern_name': pattern_name, 'description': description}}\n"
            f"Creative brief: {creative_brief or description}\n"
            f"Selected features: {selected_features}\n"
            f"Planning context: {planning_context}\n"
            f"Decision context: {decision_context}\n"
            f"IA analysis: {_as_dict(analysis.get('ia_analysis'))}\n"
            f"{_DISTILLED_FRONTEND_AESTHETICS}\n"
            f"{_PRODUCT_PROTOTYPE_GUARDRAILS}\n"
            "Raise the quality bar on hierarchy, contrast, responsiveness, decision support, and prototype fidelity. "
            "Increase aesthetic conviction and remove any trace of landing-page hero composition. "
            "If any field drifts into prose-heavy metadata, collapse it back to short valid enum values and in-product screen names. "
            "Strengthen how the winning thesis shows up in workflow structure, trust cues, and handoff readiness. "
            "Keep user-facing copy in Japanese and make the result feel like a production product workspace, not a concept page. "
            "The implementation_brief must stay concrete enough for solution architecture and implementation planning to act on."
        )
        refined, critique_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose=f"lifecycle-design-{node_id}-critique",
            static_instruction=(
                "You are a design critic and reviser. Return JSON only. "
                "Strengthen weaknesses instead of restating the same concept."
            ),
            user_prompt=critique_prompt,
            phase="design",
            node_id=node_id,
        )
        payload = refined or proposal
        if not isinstance(payload, dict):
            return handler(node_id, state)
        peer_feedback: list[dict[str, Any]] = []
        delegations: list[dict[str, Any]] = []
        for delegation in _as_list(plan.get("delegations"))[:2]:
            delegation_payload = _as_dict(delegation)
            delegated = await _delegate_to_lifecycle_peer(
                phase="design",
                node_id=node_id,
                peer_name=str(delegation_payload.get("peer", "")),
                skill_name=str(delegation_payload.get("skill", "")),
                artifact_payload=payload,
                reason=str(delegation_payload.get("reason", "")),
                quality_targets=[str(item) for item in _as_list(plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        peer_recommendations = _dedupe_strings(
            [
                str(item)
                for feedback in peer_feedback
                for item in _as_list(_as_dict(feedback).get("recommendations"))
                if str(item).strip()
            ]
        )
        # ── LLM-generated preview HTML ──────────────────────────────
        preview_html_override = ""
        preview_meta_override: dict[str, Any] = {
            "source": "template",
            "extraction_ok": False,
            "fallback_reason": "template_preview_used",
        }
        resolved_primary = _color_or(payload.get("primary_color"), primary)
        resolved_accent = _color_or(payload.get("accent_color"), accent)
        resolved_pattern = str(payload.get("pattern_name") or pattern_name)
        resolved_description = str(payload.get("description") or description)
        screen_labels_hint = [str(item) for item in _as_list(payload.get("screen_labels")) if str(item).strip()]
        if not screen_labels_hint:
            screen_labels_hint = [str(item) for item in _as_list((prototype_seed_overrides or {}).get("screen_labels")) if str(item).strip()]
        preview_prompt = (
            "Generate a COMPLETE, self-contained HTML document for an interactive product prototype.\n"
            "The output MUST be a single HTML file (<!doctype html>…</html>) that works inside an iframe.\n"
            "Include all CSS in a <style> tag and all JavaScript in a <script> tag.\n\n"
            "REQUIREMENTS:\n"
            "1. Product workspace UI — NOT a landing page, NOT a marketing hero, NOT a signup flow.\n"
            "2. Sidebar or top-nav shell with working navigation that switches between screens via JS.\n"
            "3. At least 4 screens with distinct content: data tables, metric cards, status lists, form sections, charts (use CSS/SVG).\n"
            "4. Interactive elements: tab switching, accordion/collapsible sections, hover effects, active states, transitions.\n"
            "5. Realistic mock data in Japanese — use actual domain-specific content, not lorem ipsum.\n"
            "6. Responsive: works on desktop (1200px+), tablet (768px), and mobile (375px).\n"
            "7. Polished product craft: decisive typography, disciplined spacing, layered panels, and stateful controls.\n"
            "8. Commit to one visual direction. Avoid decorative glassmorphism unless the concept explicitly requires it.\n"
            "9. Status badges, progress indicators, approval states, and blocked/degraded cues where appropriate.\n"
            "10. Avoid raw milestone ids, implementation jargon, English UI copy, and concept-note prose inside the product UI.\n"
            "11. Include evidence/approval/lineage/recovery surfaces when the product context calls for them.\n"
            "12. Rich enough to feel production-grade; do not pad with repetitive filler just to increase line count.\n\n"
            "COPY AND VISUAL QUALITY:\n"
            "  - Visible labels must read like a real Japanese in-product workspace, not a design critique or implementation memo.\n"
            "  - Never show tokens such as ms-alpha, uc-ops-001, DAG, prototype app, prototype spec, App Router, Next.js, Tailwind, or CSS terminology.\n"
            "  - Use typography, spacing rhythm, contrast, and panel hierarchy intentionally so the product feels authored rather than generic.\n"
            "  - Dense variants should feel decisive and readable; spacious variants should feel calm without becoming empty or passive.\n"
            "  - The most important actions and blocked states must be obvious above the fold.\n\n"
            f"DESIGN DIRECTION:\n"
            f"  Pattern: {resolved_pattern}\n"
            f"  Description: {resolved_description}\n"
            f"  Primary color: {resolved_primary}\n"
            f"  Accent color: {resolved_accent}\n"
            f"  Creative brief: {creative_brief or resolved_description}\n\n"
            f"PRODUCT CONTEXT:\n"
            f"  Spec: {spec}\n"
            f"  Selected features: {selected_features}\n"
            f"  Screen labels: {screen_labels_hint or ['Dashboard', 'Detail View', 'Review Gate', 'Settings']}\n"
            f"  Personas: {[str(p.get('name', '')) + ': ' + str(p.get('role', '')) for p in personas[:2]]}\n"
            f"  Use cases: {[str(uc.get('title', '')) for uc in _as_list(analysis.get('use_cases'))[:3]]}\n"
            f"  Decision context: {decision_context}\n\n"
            "QUALITY BAR:\n"
            "  - The result must read like a real operator product, not a generated concept page.\n"
            "  - Use Japanese labels that sound like in-product controls and workflow surfaces.\n"
            "  - Make the winning thesis visible through layout, flows, and state handling, not marketing copy.\n"
            "  - If you include diagrams or graphs, they must support an operational task, not decorate the page.\n\n"
            "OUTPUT CONTRACT:\n"
            "  - Return ONLY one complete HTML document.\n"
            "  - The first line must be <!DOCTYPE html>.\n"
            "  - Include <html lang=\"ja\">, <head>, <meta charset>, <meta name=\"viewport\">, and <body>.\n"
            "  - No markdown fencing, no explanation, no JSON wrapper."
        )
        try:
            _, preview_events, preview_raw = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose=f"lifecycle-design-{node_id}-preview-html",
                static_instruction=(
                    "You are an elite frontend engineer and product designer. "
                    "Generate production-quality HTML prototypes with rich interactivity, "
                    "polished visual design, and realistic Japanese content. "
                    "The result must feel like a real operator workspace with deliberate typography, contrast, and hierarchy. "
                    "Do not expose internal IDs, implementation jargon, or concept-note prose in visible UI. "
                    "Return ONLY one valid HTML document that starts with <!DOCTYPE html>. "
                    "No JSON. No markdown."
                ),
                user_prompt=preview_prompt,
                phase="design",
                node_id=node_id,
            )
            llm_events.extend(preview_events)
            extracted = _extract_html_document(preview_raw)
            if extracted and len(extracted) > 500:
                preview_html_override = extracted
                preview_meta_override = {
                    "source": "llm",
                    "extraction_ok": True,
                    "fallback_reason": "",
                }
            elif extracted:
                preview_meta_override = {
                    "source": "template",
                    "extraction_ok": True,
                    "fallback_reason": "extracted_html_too_short",
                }
            else:
                preview_meta_override = {
                    "source": "template",
                    "extraction_ok": False,
                    "fallback_reason": "html_extraction_failed",
                }
        except Exception:
            preview_meta_override = {
                "source": "template",
                "extraction_ok": False,
                "fallback_reason": "preview_generation_failed",
            }
        # ────────────────────────────────────────────────────────────
        variant_usage, variant_cost = _aggregate_llm_event_metrics([*plan_events, *llm_events, *critique_events])
        variant = _design_variant_payload(
            node_id=node_id,
            model_name=model_name,
            pattern_name=str(payload.get("pattern_name") or pattern_name),
            description=str(payload.get("description") or description),
            primary=_color_or(payload.get("primary_color"), primary),
            accent=_color_or(payload.get("accent_color"), accent),
            selected_features=selected_features,
            spec=spec,
            analysis=analysis,
            rationale=_dedupe_strings(
                [
                    str(payload.get("rationale") or description),
                    *[str(item.get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            )[0],
            quality_focus=_dedupe_strings(
                [str(item) for item in _as_list(payload.get("quality_focus")) if str(item).strip()] + peer_recommendations
            ),
            score_overrides=_as_dict(payload.get("scores")),
            prototype_overrides=_merge_prototype_overrides(
                prototype_seed_overrides,
                _prototype_overrides_from_payload(payload),
            ),
            provider_note=_dedupe_strings(
                [
                    str(payload.get("provider_note") or ""),
                    *[str(_as_dict(item).get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            )[0] if _dedupe_strings(
                [
                    str(payload.get("provider_note") or ""),
                    *[str(_as_dict(item).get("summary", "")) for item in peer_feedback if isinstance(item, dict)],
                ]
            ) else "",
            decision_context_fingerprint=str(decision_context.get("fingerprint") or ""),
            decision_scope=decision_scope,
            token_usage=variant_usage,
            cost_override=variant_cost,
            model_ref=_preferred_lifecycle_model(node_id, provider_registry),
            narrative_overrides={
                "experience_thesis": payload.get("experience_thesis"),
                "operational_bet": payload.get("operational_bet"),
                "signature_moments": payload.get("signature_moments"),
                "handoff_note": payload.get("handoff_note"),
            },
            implementation_brief_overrides=_as_dict(
                payload.get("implementation_brief") or payload.get("implementationBrief")
            ),
            plan_estimates=[dict(item) for item in _as_list(state.get("planEstimates")) if isinstance(item, dict)],
            selected_preset=str(state.get("selectedPreset") or ""),
            target_language=str(_as_dict(state.get("researchConfig")).get("outputLanguage") or "ja"),
            preview_html_override=preview_html_override,
            preview_meta_overrides=preview_meta_override,
        )
        all_llm_events = [*plan_events, *llm_events, *critique_events]
        return NodeResult(
            state_patch={
                f"{node_id}_variant": variant,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): delegations,
                _peer_feedback_state_key(node_id): peer_feedback,
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-variant", "kind": "design", **variant},
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegations
                ],
            ),
            llm_events=all_llm_events,
            metrics={"design_mode": "provider-backed-autonomous"},
        )

    return autonomous_handler if _provider_backed_lifecycle_available(provider_registry) else handler


def _design_evaluator_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    variants = [
        item
        for key, item in state.items()
        if key.endswith("_variant") and isinstance(item, dict)
    ]
    peer_feedback = [
        dict(item)
        for key, value in state.items()
        if key.endswith("_peer_feedback") and isinstance(value, list)
        for item in value
        if isinstance(item, dict)
    ]
    ordered = _rank_design_variants(variants)

    async def autonomous() -> NodeResult:
        decision_context = _decision_context_from_state(state, compact=True)
        plan, plan_events = await _plan_node_collaboration(
            phase="design",
            node_id=node_id,
            state=state,
            objective="Judge competing design concepts, integrate peer critique, and select the strongest baseline.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        evaluation_prompt = (
            "Evaluate these design variants and rank them for product quality.\n"
            "Return JSON only with keys ranking, selected_design_id, score_adjustments, critique, winner_summary, winner_reasons, winner_tradeoffs, approval_guardrails.\n"
            f"Variants: {ordered}\n"
            f"Peer feedback: {peer_feedback}\n"
            f"Decision context: {decision_context}\n"
            f"Selected skills: {plan.get('selected_skills')}\n"
            "Use preview_meta.quality_score, preview_meta.copy_quality_score, preview_meta.source, scorecard evidence, workflow coverage, and implementation_brief quality in your judgement.\n"
            "Prefer variants that are product-grade workspaces with validated preview quality, strong workflow fidelity, and credible handoff readiness.\n"
            "Penalize variants that feel templated, marketing-like, shallow in workflow coverage, or weak in Japanese in-product copy.\n"
            "winner_reasons should be 2-4 concrete reasons phrased for an approval packet.\n"
            "winner_tradeoffs should be 1-3 explicit costs or risks of the winning direction.\n"
            "approval_guardrails should be 2-4 non-negotiable constraints that implementation must preserve.\n"
            "score_adjustments must be an object keyed by variant id with optional ux_quality, code_quality, performance, accessibility overrides."
        )
        payload, llm_events, _ = await _lifecycle_llm_json(
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
            preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
            purpose="lifecycle-design-judge",
            static_instruction=(
                "You are a principal design judge. Return JSON only. "
                "Prefer variants that are differentiated, accessible, responsive, product-grade, "
                "and clearly aligned with the selected product scope."
            ),
            user_prompt=evaluation_prompt,
            phase="design",
            node_id=node_id,
        )
        if not isinstance(payload, dict):
            design_payload = {"variants": ordered}
            return NodeResult(
                state_patch={
                    "variants": ordered,
                    "design": design_payload,
                    "output": design_payload,
                    _skill_plan_state_key(node_id): plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts(
                    {"name": "design-scorecard", "kind": "design", "variants": ordered},
                    {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
                ),
                metrics={"design_mode": "provider-backed-autonomous-fallback"},
                llm_events=[*plan_events, *llm_events],
            )
        ranking = [str(item) for item in _as_list(payload.get("ranking")) if str(item).strip()]
        by_id = {str(item.get("id", "")): dict(item) for item in ordered}
        adjusted: list[dict[str, Any]] = []
        for variant_id in ranking:
            variant = by_id.pop(variant_id, None)
            if variant is None:
                continue
            overrides = _as_dict(_as_dict(payload.get("score_adjustments")).get(variant_id))
            if overrides:
                variant_scores = dict(_as_dict(variant.get("scores")))
                for score_name, default in tuple(variant_scores.items()):
                    variant_scores[score_name] = _clamp_score(overrides.get(score_name), default=float(default))
                variant["scores"] = variant_scores
            adjusted.append(variant)
        adjusted.extend(by_id.values())
        adjusted = _rank_design_variants(adjusted)
        selected_design_id = _resolve_selected_design_id(
            adjusted,
            str(payload.get("selected_design_id") or ""),
        )
        adjusted = _apply_design_judge_enrichment(
            adjusted,
            selected_design_id=selected_design_id,
            payload=payload,
        )
        critique = [str(item) for item in _as_list(payload.get("critique")) if str(item).strip()]
        design_payload = {
            "variants": adjusted,
            "selected_design_id": selected_design_id,
            "critique": critique,
        }
        artifact_payload = {"name": "design-scorecard", "kind": "design", "variants": adjusted, "critique": critique}
        return NodeResult(
            state_patch={
                "variants": adjusted,
                "selected_design_id": selected_design_id,
                "design": design_payload,
                "output": design_payload,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): [],
            },
            artifacts=_artifacts(
                artifact_payload,
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan},
            ),
            llm_events=[*plan_events, *llm_events],
            metrics={"design_mode": "provider-backed-autonomous"},
        )

    if _provider_backed_lifecycle_available(provider_registry):
        return autonomous()

    design_payload = {"variants": ordered}
    return NodeResult(
        state_patch={"variants": ordered, "design": design_payload, "output": design_payload},
        artifacts=_artifacts({"name": "design-scorecard", "kind": "design", "variants": ordered}),
        metrics={"design_mode": "deterministic-reference"},
    )

def _selected_plan_estimate_from_state(state: dict[str, Any]) -> dict[str, Any]:
    estimates = [_as_dict(item) for item in _as_list(state.get("planEstimates")) if _as_dict(item)]
    if not estimates:
        return {}
    selected_preset = str(state.get("selectedPreset") or "standard")
    for preset_name in (selected_preset, "standard", "full", "minimal"):
        matched = next((item for item in estimates if str(item.get("preset", "")) == preset_name), None)
        if matched is not None:
            return matched
    return estimates[0]


def _development_agent_id_from_values(*values: Any) -> str:
    combined = " ".join(str(value or "") for value in values).lower()
    if any(token in combined for token in ("security", "safe", "policy", "threat")):
        return "security-reviewer"
    if any(token in combined for token in ("review", "release", "handoff", "sign-off")):
        return "reviewer"
    if any(token in combined for token in ("qa", "test", "acceptance", "verification", "quality")):
        return "qa-engineer"
    if any(token in combined for token in ("integrat", "merge", "compose", "shell", "routing")):
        return "integrator"
    if any(token in combined for token in ("backend", "api", "domain", "state", "schema", "model", "service")):
        return "backend-builder"
    return "frontend-builder"


def _selected_feature_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_item in state.get("features", []) or state.get("selected_features", []) or []:
        if not isinstance(raw_item, dict) or raw_item.get("selected", True) is False:
            continue
        feature_name = str(
            raw_item.get("feature")
            or raw_item.get("name")
            or raw_item.get("title")
            or ""
        ).strip()
        feature_id = str(raw_item.get("id") or "").strip()
        if not feature_name and not feature_id:
            continue
        records.append(
            {
                "id": feature_id or _slug(feature_name or f"feature-{len(records) + 1}", prefix="feature"),
                "name": feature_name or feature_id,
                "acceptance_criteria": [
                    str(item).strip()
                    for item in _as_list(raw_item.get("acceptance_criteria") or raw_item.get("acceptanceCriteria"))
                    if str(item).strip()
                ],
            }
        )
    return records


def _development_text_matches(text: Any, subject: Any) -> bool:
    lhs = str(text or "").strip().lower()
    rhs = str(subject or "").strip().lower()
    if not lhs or not rhs:
        return False
    if rhs in lhs:
        return True
    rhs_tokens = [
        token
        for token in rhs.replace("/", " ").replace("-", " ").split()
        if len(token) >= 3
    ]
    if not rhs_tokens:
        return False
    return sum(1 for token in rhs_tokens if token in lhs) >= max(1, min(2, len(rhs_tokens)))


def _development_task_rows(task_decomposition: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_item in _as_list(_as_dict(task_decomposition).get("tasks")):
        item = _as_dict(raw_item)
        task_id = str(item.get("id") or "").strip()
        if not task_id:
            continue
        rows.append(
            {
                "id": task_id,
                "title": str(item.get("title") or f"Task {len(rows) + 1}").strip(),
                "description": str(item.get("description") or "").strip(),
                "phase": str(item.get("phase") or "").strip(),
                "depends_on": [
                    str(dep).strip()
                    for dep in _as_list(item.get("dependsOn") or item.get("depends_on"))
                    if str(dep).strip()
                ],
                "effort_hours": float(item.get("effortHours") or item.get("effort_hours") or 0.0),
                "priority": str(item.get("priority") or "should").strip() or "should",
                "feature_id": str(item.get("featureId") or item.get("feature_id") or "").strip() or None,
                "requirement_id": str(item.get("requirementId") or item.get("requirement_id") or "").strip() or None,
                "milestone_id": str(item.get("milestoneId") or item.get("milestone_id") or "").strip() or None,
            }
        )
    return rows


def _development_plan_estimate_lookup(plan_estimate: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for raw_item in _as_list(_as_dict(plan_estimate).get("wbs")):
        item = _as_dict(raw_item)
        item_id = str(item.get("id") or "").strip()
        if item_id:
            lookup[item_id] = item
    return lookup


def _development_goal_spec(
    *,
    state: dict[str, Any],
    selected_features: list[str],
    requirements: dict[str, Any] | None,
    task_rows: list[dict[str, Any]],
    value_contract: dict[str, Any] | None,
    outcome_telemetry_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    requirement_rows = [
        _as_dict(item)
        for item in _as_list(_as_dict(requirements).get("requirements"))
        if _as_dict(item)
    ]
    milestones = [
        _as_dict(item)
        for item in _as_list(state.get("milestones"))
        if _as_dict(item)
    ]
    planning_analysis = _as_dict(state.get("analysis"))
    return {
        "objective": (
            "Decompose the approved product goal into dependency-ordered work units that remain compliant with "
            "design tokens, access policy, audit / operability, development standards, the value contract, and the "
            "outcome telemetry contract."
        ),
        "selected_features": [str(item) for item in selected_features if str(item).strip()],
        "requirement_ids": [
            str(item.get("id") or "").strip()
            for item in requirement_rows
            if str(item.get("id") or "").strip()
        ],
        "task_ids": [str(item.get("id") or "").strip() for item in task_rows if str(item.get("id") or "").strip()],
        "milestone_ids": [
            str(item.get("id") or "").strip()
            for item in milestones
            if str(item.get("id") or "").strip()
        ],
        "quality_targets": _phase_quality_targets("development"),
        "contract_injection": list(REQUIRED_DELIVERY_CONTRACT_IDS),
        "value_contract_summary": _ns(_as_dict(value_contract).get("summary")),
        "value_metric_ids": [
            str(_as_dict(item).get("id") or "").strip()
            for item in _as_list(_as_dict(value_contract).get("success_metrics"))
            if str(_as_dict(item).get("id") or "").strip()
        ],
        "telemetry_event_ids": [
            str(_as_dict(item).get("id") or "").strip()
            for item in _as_list(_as_dict(outcome_telemetry_contract).get("telemetry_events"))
            if str(_as_dict(item).get("id") or "").strip()
        ],
        "role_names": [
            str(_as_dict(item).get("name") or "").strip()
            for item in _as_list(planning_analysis.get("roles"))
            if str(_as_dict(item).get("name") or "").strip()
        ],
        "completion_signal": (
            "Each work unit clears embedded QA/security checks, each wave closes locally, and the final build passes "
            "repo execution plus deploy handoff."
        ),
    }


def _development_wave_plan(work_packages: list[dict[str, Any]]) -> dict[str, Any]:
    package_lookup = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in work_packages
        if str(_as_dict(item).get("id") or "").strip()
    }
    missing_dependencies = sorted(
        {
            str(dep).strip()
            for item in package_lookup.values()
            for dep in _as_list(item.get("depends_on"))
            if str(dep).strip() and str(dep).strip() not in package_lookup
        }
    )
    scheduler = WorkflowScheduler(max_scheduled_tasks=max(32, len(package_lookup) + 4))
    for index, item in enumerate(package_lookup.values()):
        scheduler.enqueue(
            WorkflowTask(
                id=str(item.get("id") or ""),
                workflow_id="lifecycle-development",
                tenant_id="default",
                priority=min(int(item.get("start_day", index) or index), 9),
                dependencies={
                    str(dep).strip()
                    for dep in _as_list(item.get("depends_on"))
                    if str(dep).strip()
                },
            )
        )
    try:
        computed_waves = scheduler.compute_waves()
    except SchedulerDependencyError as exc:
        details = getattr(exc, "details", {}) or {}
        return {
            "status": "invalid",
            "wave_count": 0,
            "waves": [],
            "wave_index_by_id": {},
            "unknown_dependencies": sorted(
                {
                    *missing_dependencies,
                    *[
                        str(dep).strip()
                        for dep in _as_list(details.get("missing_dependencies"))
                        if str(dep).strip()
                    ],
                }
            ),
            "has_cycles": bool(_as_list(details.get("remaining_tasks"))),
        }

    wave_index_by_id: dict[str, int] = {}
    waves: list[dict[str, Any]] = []
    for wave_index, wave in enumerate(computed_waves):
        unit_ids = [str(item.id) for item in wave if str(item.id).strip()]
        for unit_id in unit_ids:
            wave_index_by_id[unit_id] = wave_index
        lane_ids = _dedupe_strings(
            [
                str(_as_dict(package_lookup.get(unit_id)).get("lane") or "").strip()
                for unit_id in unit_ids
                if str(_as_dict(package_lookup.get(unit_id)).get("lane") or "").strip()
            ]
        )
        waves.append(
            {
                "wave_index": wave_index,
                "work_unit_ids": unit_ids,
                "lane_ids": lane_ids,
                "entry_criteria": (
                    ["Approved goal spec and contracts are injected before coding begins."]
                    if wave_index == 0
                    else ["All dependencies from earlier waves are complete and locally verified."]
                ),
                "exit_criteria": [
                    "Each work unit clears embedded QA and security checks.",
                    "Wave-local merge conflicts are resolved before the next wave starts.",
                ],
            }
        )
    return {
        "status": "ready",
        "wave_count": len(waves),
        "waves": waves,
        "wave_index_by_id": wave_index_by_id,
        "unknown_dependencies": missing_dependencies,
        "has_cycles": False,
    }


def _development_dependency_analysis(
    *,
    work_packages: list[dict[str, Any]],
    technical_design: dict[str, Any] | None,
    wave_plan: dict[str, Any],
) -> dict[str, Any]:
    nodes = [
        {
            "id": str(_as_dict(item).get("id") or "").strip(),
            "title": str(_as_dict(item).get("title") or "").strip(),
            "lane": str(_as_dict(item).get("lane") or "").strip(),
            "depends_on": [
                str(dep).strip()
                for dep in _as_list(_as_dict(item).get("depends_on"))
                if str(dep).strip()
            ],
        }
        for item in work_packages
        if str(_as_dict(item).get("id") or "").strip()
    ]
    edges = [
        {
            "source": str(dep).strip(),
            "target": str(_as_dict(item).get("id") or "").strip(),
            "reason": "task_dependency",
        }
        for item in work_packages
        if str(_as_dict(item).get("id") or "").strip()
        for dep in _as_list(_as_dict(item).get("depends_on"))
        if str(dep).strip()
    ]
    component_graph = _as_dict(_as_dict(technical_design).get("componentDependencyGraph"))
    component_edges = [
        {
            "source": str(source).strip(),
            "target": str(target).strip(),
            "reason": "technical_design_component",
        }
        for source, targets in component_graph.items()
        for target in _as_list(targets)
        if str(source).strip() and str(target).strip()
    ]
    return {
        "work_packages": nodes,
        "edges": edges,
        "component_edges": component_edges,
        "unknown_dependencies": [
            str(item)
            for item in _as_list(_as_dict(wave_plan).get("unknown_dependencies"))
            if str(item).strip()
        ],
        "has_cycles": _as_dict(wave_plan).get("has_cycles") is True,
        "wave_count": int(_as_dict(wave_plan).get("wave_count", 0) or 0),
    }


def _development_work_unit_contracts(
    *,
    state: dict[str, Any],
    work_packages: list[dict[str, Any]],
    requirements: dict[str, Any] | None,
    technical_design: dict[str, Any] | None,
    selected_design: dict[str, Any],
    wave_plan: dict[str, Any],
    value_contract: dict[str, Any] | None,
    outcome_telemetry_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    requirement_rows = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in _as_list(_as_dict(requirements).get("requirements"))
        if str(_as_dict(item).get("id") or "").strip()
    }
    milestone_rows = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in _as_list(state.get("milestones"))
        if str(_as_dict(item).get("id") or "").strip()
    }
    feature_rows = {
        str(item.get("id") or "").strip(): item
        for item in _selected_feature_records(state)
        if str(item.get("id") or "").strip()
    }
    selected_feature_names = [str(item.get("name") or "").strip() for item in feature_rows.values() if str(item.get("name") or "").strip()]
    routes = [
        _as_dict(item)
        for item in _as_list(_as_dict(selected_design.get("prototype_spec")).get("routes"))
        if _as_dict(item)
    ]
    api_rows = [
        _as_dict(item)
        for item in _as_list(_as_dict(technical_design).get("apiSpecification"))
        if _as_dict(item)
    ]
    component_graph = _as_dict(_as_dict(technical_design).get("componentDependencyGraph"))
    component_names = _dedupe_strings(
        [str(source).strip() for source in component_graph]
        + [
            str(target).strip()
            for targets in component_graph.values()
            for target in _as_list(targets)
            if str(target).strip()
        ]
    )
    wave_index_by_id = _as_dict(wave_plan).get("wave_index_by_id") or {}
    protected_api = [item for item in api_rows if item.get("authRequired", True) is True]
    value_metric_rows = [
        _as_dict(item)
        for item in _as_list(_as_dict(value_contract).get("success_metrics"))
        if _as_dict(item)
    ]
    telemetry_event_rows = [
        _as_dict(item)
        for item in _as_list(_as_dict(outcome_telemetry_contract).get("telemetry_events"))
        if _as_dict(item)
    ]

    contracts: list[dict[str, Any]] = []
    for item in work_packages:
        package = _as_dict(item)
        package_id = str(package.get("id") or "").strip()
        if not package_id:
            continue
        title = str(package.get("title") or package_id).strip()
        summary_text = " ".join(
            [
                title,
                str(package.get("summary") or "").strip(),
                *[
                    str(feature_name)
                    for feature_name in _as_list(package.get("feature_names"))
                    if str(feature_name).strip()
                ],
            ]
        )
        feature_id = str(package.get("source_feature_id") or "").strip()
        requirement_ids = [
            str(item).strip()
            for item in _as_list(package.get("requirement_ids"))
            if str(item).strip()
        ]
        milestone_id = str(package.get("milestone_id") or "").strip()
        requirement_row = _as_dict(requirement_rows.get(requirement_ids[0])) if requirement_ids else {}
        milestone_row = _as_dict(milestone_rows.get(milestone_id))
        feature_row = _as_dict(feature_rows.get(feature_id))
        matched_routes = [
            str(route.get("path") or "").strip()
            for route in routes
            if str(route.get("path") or "").strip()
            and _development_text_matches(
                " ".join(
                    [
                        str(route.get("path") or ""),
                        str(route.get("title") or ""),
                        str(route.get("screen_id") or ""),
                    ]
                ),
                summary_text,
            )
        ]
        matched_api = [
            {
                "method": str(api_item.get("method") or "GET").strip(),
                "path": str(api_item.get("path") or "").strip(),
                "authRequired": bool(api_item.get("authRequired", True)),
            }
            for api_item in api_rows
            if str(api_item.get("path") or "").strip()
            and _development_text_matches(
                " ".join([str(api_item.get("path") or ""), str(api_item.get("description") or "")]),
                summary_text,
            )
        ]
        matched_components = [
            component
            for component in component_names
            if _development_text_matches(summary_text, component)
        ]
        feature_names = _dedupe_strings(
            [str(feature_row.get("name") or "").strip()]
            + [
                str(item).strip()
                for item in _as_list(package.get("feature_names"))
                if str(item).strip()
            ]
        )
        acceptance_criteria = _dedupe_strings(
            [
                str(item).strip()
                for item in _as_list(package.get("acceptance_criteria"))
                if str(item).strip()
            ]
            + [
                str(item).strip()
                for item in _as_list(requirement_row.get("acceptanceCriteria"))
                if str(item).strip()
            ]
            + [
                str(feature_row.get("acceptance_criteria")[0]).strip()
                if _as_list(feature_row.get("acceptance_criteria"))
                else ""
            ]
            + [str(milestone_row.get("criteria") or "").strip()]
        )
        qa_checks = _dedupe_strings(
            acceptance_criteria[:3]
            + [
                f"Verify route bindings for {matched_routes[0]}" if matched_routes else "",
                (
                    f"Confirm milestone {str(milestone_row.get('name') or milestone_id).strip()} remains satisfied"
                    if milestone_row
                    else ""
                ),
            ]
        )
        security_checks = _dedupe_strings(
            [
                (
                    "Preserve authRequired truth and access-policy boundaries for protected API paths."
                    if matched_api or protected_api
                    else "Avoid unsafe DOM and permission regressions in this work unit."
                ),
                (
                    "Keep audit / operability events attached to approval and release-significant flows."
                    if matched_api or milestone_row
                    else "Do not bypass audit / operability expectations during implementation."
                ),
            ]
        )
        integration_checks = _dedupe_strings(
            [
                (
                    f"Merge after {', '.join(str(dep).strip() for dep in _as_list(package.get('depends_on')) if str(dep).strip())}"
                    if _as_list(package.get("depends_on"))
                    else "Can merge within the current wave once local checks pass."
                ),
                "Respect lane ownership, shared shell rules, and contract artifacts before integration.",
            ]
        )
        value_targets = [
            {
                "metric_id": str(metric.get("id") or "").strip(),
                "metric_name": str(metric.get("name") or "").strip(),
            }
            for metric in value_metric_rows
            if str(metric.get("id") or "").strip()
            and _development_text_matches(
                summary_text,
                " ".join([str(metric.get("name") or ""), str(metric.get("signal") or "")]),
            )
        ] or [
            {
                "metric_id": str(metric.get("id") or "").strip(),
                "metric_name": str(metric.get("name") or "").strip(),
            }
            for metric in value_metric_rows[:2]
            if str(metric.get("id") or "").strip()
        ]
        telemetry_events = [
            {
                "id": str(event.get("id") or "").strip(),
                "name": str(event.get("name") or "").strip(),
            }
            for event in telemetry_event_rows
            if str(event.get("id") or "").strip()
            and _development_text_matches(
                summary_text,
                " ".join([str(event.get("name") or ""), str(event.get("purpose") or "")]),
            )
        ] or [
            {
                "id": str(event.get("id") or "").strip(),
                "name": str(event.get("name") or "").strip(),
            }
            for event in telemetry_event_rows[:2]
            if str(event.get("id") or "").strip()
        ]
        contracts.append(
            {
                "id": f"wu-{_slug(package_id, prefix='wu')}",
                "work_package_id": package_id,
                "title": title,
                "lane": str(package.get("lane") or "").strip(),
                "wave_index": int(wave_index_by_id.get(package_id, 0) or 0),
                "depends_on": [
                    str(dep).strip()
                    for dep in _as_list(package.get("depends_on"))
                    if str(dep).strip()
                ],
                "feature_ids": [feature_id] if feature_id else [],
                "feature_names": feature_names or [
                    item for item in selected_feature_names if _development_text_matches(summary_text, item)
                ],
                "requirement_ids": requirement_ids,
                "milestone_ids": [milestone_id] if milestone_id else [],
                "route_paths": matched_routes,
                "api_surface": matched_api,
                "component_dependencies": matched_components,
                "deliverables": [
                    str(deliverable).strip()
                    for deliverable in _as_list(package.get("deliverables"))
                    if str(deliverable).strip()
                ],
                "acceptance_criteria": acceptance_criteria,
                "required_contracts": list(REQUIRED_DELIVERY_CONTRACT_IDS),
                "qa_checks": qa_checks,
                "security_checks": security_checks,
                "integration_checks": integration_checks,
                "value_targets": value_targets,
                "telemetry_events": telemetry_events,
                "repair_policy": {
                    "builder_failure": "retry_same_work_unit",
                    "qa_failure": "retry_same_work_unit",
                    "security_failure": "retry_same_work_unit",
                    "shared_conflict": "replan_current_wave_only",
                },
                "gate_owners": {
                    "builder": str(package.get("lane") or "").strip(),
                    "qa": "qa-engineer",
                    "security": "security-reviewer",
                    "review": "reviewer",
                },
                "status": str(package.get("status") or "planned").strip() or "planned",
            }
        )
    return contracts


def _development_shift_left_plan(
    *,
    work_unit_contracts: list[dict[str, Any]],
    waves: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mode": "work_unit_micro_loop",
        "principles": [
            "Each work unit starts with contract injection before code changes begin.",
            "QA and security checks run at the work-unit boundary instead of only at release time.",
            "Builder, QA, and security failures return to the same work unit unless a shared conflict forces wave-level replanning.",
            "Integrator and reviewer close at wave exits and final release readiness, not as the only quality gate.",
        ],
        "work_unit_count": len(work_unit_contracts),
        "wave_count": len(waves),
        "qa_placement": "embedded_per_work_unit",
        "security_placement": "embedded_per_work_unit",
        "review_placement": "wave_exit_and_final_release",
    }


def _build_development_topology(
    *,
    state: dict[str, Any],
    selected_design: dict[str, Any],
    selected_features: list[str],
    requirements: dict[str, Any] | None,
    technical_design: dict[str, Any] | None,
    work_packages: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    value_contract: dict[str, Any] | None,
    outcome_telemetry_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    work_packages = [dict(item) for item in work_packages if isinstance(item, dict)]
    critical_path = _development_critical_path(work_packages)
    critical_lookup = set(critical_path)
    for package in work_packages:
        package["is_critical"] = str(package.get("id", "")) in critical_lookup

    wave_plan = _development_wave_plan(work_packages)
    goal_spec = _development_goal_spec(
        state=state,
        selected_features=selected_features,
        requirements=requirements,
        task_rows=_development_task_rows(state.get("taskDecomposition")),
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    dependency_analysis = _development_dependency_analysis(
        work_packages=work_packages,
        technical_design=technical_design,
        wave_plan=wave_plan,
    )
    work_unit_contracts = _development_work_unit_contracts(
        state=state,
        work_packages=work_packages,
        requirements=requirements,
        technical_design=technical_design,
        selected_design=selected_design,
        wave_plan=wave_plan,
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    shift_left_plan = _development_shift_left_plan(
        work_unit_contracts=work_unit_contracts,
        waves=[dict(item) for item in _as_list(wave_plan.get("waves")) if isinstance(item, dict)],
    )
    implementation_brief = _as_dict(selected_design.get("implementation_brief"))
    lane_lookup = {str(item.get("agent", "")): item for item in lanes}
    gantt = [
        {
            "work_package_id": str(package.get("id", "")),
            "lane": str(package.get("lane", "")),
            "start_day": int(package.get("start_day", 0) or 0),
            "duration_days": int(package.get("duration_days", 1) or 1),
            "depends_on": [str(dep) for dep in _as_list(package.get("depends_on")) if str(dep).strip()],
            "is_critical": bool(package.get("is_critical")),
            "wave_index": int(_as_dict(wave_plan.get("wave_index_by_id")).get(str(package.get("id", "")), 0) or 0),
        }
        for package in sorted(
            work_packages,
            key=lambda item: (
                int(item.get("start_day", 0) or 0),
                int(item.get("duration_days", 1) or 1),
                str(item.get("id", "")),
            ),
        )
    ]
    merge_strategy = {
        "integration_order": [
            str(item.get("id", ""))
            for item in sorted(
                work_packages,
                key=lambda package: (
                    int(_as_dict(lane_lookup.get(str(package.get("lane", "")))).get("merge_order", 99) or 99),
                    int(_as_dict(wave_plan.get("wave_index_by_id")).get(str(package.get("id", "")), 0) or 0),
                    int(package.get("start_day", 0) or 0),
                    str(package.get("id", "")),
                ),
            )
        ],
        "conflict_prevention": _dedupe_strings(
            [
                guard
                for lane in lanes
                for guard in _as_list(_as_dict(lane).get("conflict_guards"))
                if str(guard).strip()
            ]
            + [
                "Builder failures return to the same work unit before any phase-wide replanning.",
                "Shared shell, routing, and contract conflicts are resolved at wave exit before the next wave unlocks.",
                "Reviewer closes deploy handoff only after wave-local QA and security checks are complete.",
            ]
        ),
        "shared_touchpoints": _dedupe_strings(
            [str(item) for item in _as_list(implementation_brief.get("delivery_slices")) if str(item).strip()]
            + [str(feature) for feature in selected_features[:3]]
        ),
    }
    return {
        "work_packages": work_packages,
        "critical_path": critical_path,
        "gantt": gantt,
        "merge_strategy": merge_strategy,
        "goal_spec": goal_spec,
        "dependency_analysis": dependency_analysis,
        "waves": [dict(item) for item in _as_list(wave_plan.get("waves")) if isinstance(item, dict)],
        "wave_count": int(wave_plan.get("wave_count", 0) or 0),
        "work_unit_contracts": work_unit_contracts,
        "shift_left_plan": shift_left_plan,
        "value_contract": _as_dict(value_contract),
        "outcome_telemetry_contract": _as_dict(outcome_telemetry_contract),
    }


_DEVELOPMENT_IMPLEMENTATION_AGENTS = frozenset(
    {"frontend-builder", "backend-builder", "integrator"}
)


def _development_work_unit_node_id(wave_index: int, work_unit_id: str) -> str:
    return f"wave-{wave_index}-wu-{_slug(work_unit_id, prefix='wu')}"


def _development_wave_gate_node_id(
    wave_index: int,
    agent_id: str,
    *,
    final_wave_index: int,
) -> str:
    if wave_index == final_wave_index and agent_id in {
        "integrator",
        "repo-executor",
        "qa-engineer",
        "security-reviewer",
        "reviewer",
    }:
        return agent_id
    return f"wave-{wave_index}-{agent_id}"


def _development_runtime_graph(delivery_plan: dict[str, Any]) -> dict[str, Any]:
    work_unit_lookup = {
        str(_as_dict(item).get("work_package_id") or _as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in _as_list(delivery_plan.get("work_unit_contracts"))
        if str(_as_dict(item).get("work_package_id") or _as_dict(item).get("id") or "").strip()
    }
    ordered_waves = [
        _as_dict(item)
        for item in sorted(
            _as_list(delivery_plan.get("waves")),
            key=lambda entry: int(_as_dict(entry).get("wave_index", 0) or 0),
        )
        if _as_dict(item)
    ]
    if not ordered_waves and work_unit_lookup:
        ordered_waves = [
            {
                "wave_index": 0,
                "work_unit_ids": list(work_unit_lookup.keys()),
                "lane_ids": _dedupe_strings(
                    [
                        str(_as_dict(unit).get("lane") or "").strip()
                        for unit in work_unit_lookup.values()
                        if str(_as_dict(unit).get("lane") or "").strip()
                    ]
                ),
            }
        ]
    if not ordered_waves:
        return {
            "mode": "fixed_lane_fallback",
            "node_count": 0,
            "work_unit_node_count": 0,
            "nodes": {},
            "runtime_assignments": [],
        }

    nodes: dict[str, dict[str, Any]] = {"planner": {"agent": "planner", "next": []}}
    assignments: list[dict[str, Any]] = [
        {
            "node_id": "planner",
            "agent": "planner",
            "stage": "planner",
            "wave_index": None,
            "work_unit_ids": [],
            "focus_work_unit_ids": [],
            "lane_ids": [],
        }
    ]
    previous_exit = "planner"
    cumulative_unit_ids: list[str] = []
    cumulative_skipped_ids: list[str] = []
    final_wave_index = int(ordered_waves[-1].get("wave_index", len(ordered_waves) - 1) or 0)
    work_unit_node_count = 0

    for raw_wave in ordered_waves:
        wave_index = int(raw_wave.get("wave_index", 0) or 0)
        current_unit_ids = [
            str(item).strip()
            for item in _as_list(raw_wave.get("work_unit_ids"))
            if str(item).strip()
        ]
        cumulative_unit_ids = _dedupe_strings([*cumulative_unit_ids, *current_unit_ids])
        work_unit_node_ids: list[str] = []
        current_lane_ids: list[str] = []
        current_skipped_ids: list[str] = []

        for unit_id in current_unit_ids:
            unit = _as_dict(work_unit_lookup.get(unit_id))
            lane_id = str(unit.get("lane") or "").strip()
            if lane_id not in _DEVELOPMENT_IMPLEMENTATION_AGENTS:
                current_skipped_ids.append(unit_id)
                continue
            current_lane_ids = _dedupe_strings([*current_lane_ids, lane_id])
            node_id = _development_work_unit_node_id(wave_index, unit_id)
            nodes[node_id] = {"agent": lane_id, "next": []}
            assignments.append(
                {
                    "node_id": node_id,
                    "agent": lane_id,
                    "stage": "work_unit",
                    "wave_index": wave_index,
                    "work_unit_ids": [unit_id],
                    "focus_work_unit_ids": [unit_id],
                    "lane_ids": [lane_id],
                }
            )
            work_unit_node_ids.append(node_id)
            work_unit_node_count += 1

        cumulative_skipped_ids = _dedupe_strings([*cumulative_skipped_ids, *current_skipped_ids])
        integrator_id = _development_wave_gate_node_id(
            wave_index,
            "integrator",
            final_wave_index=final_wave_index,
        )
        repo_executor_id = _development_wave_gate_node_id(
            wave_index,
            "repo-executor",
            final_wave_index=final_wave_index,
        )
        qa_id = _development_wave_gate_node_id(
            wave_index,
            "qa-engineer",
            final_wave_index=final_wave_index,
        )
        security_id = _development_wave_gate_node_id(
            wave_index,
            "security-reviewer",
            final_wave_index=final_wave_index,
        )
        reviewer_id = _development_wave_gate_node_id(
            wave_index,
            "reviewer",
            final_wave_index=final_wave_index,
        )
        if work_unit_node_ids:
            nodes[previous_exit]["next"] = list(work_unit_node_ids)
            for node_id in work_unit_node_ids:
                nodes[node_id]["next"] = [integrator_id]
        else:
            nodes[previous_exit]["next"] = [integrator_id]
        nodes[integrator_id] = {"agent": "integrator", "next": [repo_executor_id]}
        nodes[repo_executor_id] = {"agent": "repo-executor", "next": [qa_id, security_id]}
        nodes[qa_id] = {"agent": "qa-engineer", "next": [reviewer_id]}
        nodes[security_id] = {"agent": "security-reviewer", "next": [reviewer_id]}
        nodes[reviewer_id] = {"agent": "reviewer", "next": "END" if wave_index == final_wave_index else []}

        gate_work_unit_ids = list(cumulative_unit_ids)
        focus_work_unit_ids = list(current_unit_ids or cumulative_unit_ids)
        gate_lane_ids = _dedupe_strings(
            [
                str(_as_dict(work_unit_lookup.get(unit_id)).get("lane") or "").strip()
                for unit_id in gate_work_unit_ids
                if str(_as_dict(work_unit_lookup.get(unit_id)).get("lane") or "").strip()
            ]
        )
        for node_id, agent_id, stage in (
            (integrator_id, "integrator", "wave_integrator" if wave_index != final_wave_index else "final_integrator"),
            (repo_executor_id, "repo-executor", "wave_repo_execution" if wave_index != final_wave_index else "final_repo_execution"),
            (qa_id, "qa-engineer", "wave_qa" if wave_index != final_wave_index else "final_qa"),
            (security_id, "security-reviewer", "wave_security" if wave_index != final_wave_index else "final_security"),
            (reviewer_id, "reviewer", "wave_review" if wave_index != final_wave_index else "final_review"),
        ):
            assignments.append(
                {
                    "node_id": node_id,
                    "agent": agent_id,
                    "stage": stage,
                    "wave_index": wave_index,
                    "work_unit_ids": gate_work_unit_ids,
                    "focus_work_unit_ids": focus_work_unit_ids,
                    "lane_ids": gate_lane_ids,
                    "skipped_work_unit_ids": list(cumulative_skipped_ids),
                }
            )
        previous_exit = reviewer_id

    if previous_exit in nodes and nodes[previous_exit].get("next") == []:
        nodes[previous_exit]["next"] = "END"
    return {
        "mode": "wave_runtime_graph",
        "node_count": len(nodes),
        "work_unit_node_count": work_unit_node_count,
        "nodes": nodes,
        "runtime_assignments": assignments,
    }


def _stable_json_fingerprint(payload: Any) -> str:
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except TypeError:
        serialized = str(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _development_delivery_topology_frame(delivery_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_mode": str(delivery_plan.get("execution_mode") or ""),
        "topology_mode": str(delivery_plan.get("topology_mode") or ""),
        "selected_preset": str(delivery_plan.get("selected_preset") or ""),
        "source_plan_preset": str(delivery_plan.get("source_plan_preset") or ""),
        "goal_spec": _as_dict(delivery_plan.get("goal_spec")),
        "dependency_analysis": _as_dict(delivery_plan.get("dependency_analysis")),
        "lanes": [dict(item) for item in _as_list(delivery_plan.get("lanes")) if isinstance(item, dict)],
        "work_packages": [dict(item) for item in _as_list(delivery_plan.get("work_packages")) if isinstance(item, dict)],
        "waves": [dict(item) for item in _as_list(delivery_plan.get("waves")) if isinstance(item, dict)],
        "work_unit_contracts": [
            dict(item) for item in _as_list(delivery_plan.get("work_unit_contracts")) if isinstance(item, dict)
        ],
        "shift_left_plan": _as_dict(delivery_plan.get("shift_left_plan")),
        "value_contract": _as_dict(delivery_plan.get("value_contract")),
        "outcome_telemetry_contract": _as_dict(delivery_plan.get("outcome_telemetry_contract")),
        "critical_path": [str(item) for item in _as_list(delivery_plan.get("critical_path")) if str(item).strip()],
        "merge_strategy": _as_dict(delivery_plan.get("merge_strategy")),
    }


def _annotate_development_delivery_plan_lineage(
    delivery_plan: dict[str, Any],
    *,
    decision_context_fingerprint: str,
) -> dict[str, Any]:
    annotated = dict(delivery_plan)
    runtime_graph = _as_dict(annotated.get("runtime_graph")) or _development_runtime_graph(annotated)
    annotated["runtime_graph"] = runtime_graph
    annotated["decision_context_fingerprint"] = str(
        decision_context_fingerprint or annotated.get("decision_context_fingerprint") or ""
    )
    topology_fingerprint = _stable_json_fingerprint(
        {
            "decision_context_fingerprint": annotated["decision_context_fingerprint"],
            "topology": _development_delivery_topology_frame(annotated),
        }
    )
    annotated["topology_fingerprint"] = topology_fingerprint
    annotated["runtime_graph_fingerprint"] = _stable_json_fingerprint(
        {
            "topology_fingerprint": topology_fingerprint,
            "runtime_graph": runtime_graph,
        }
    )
    return annotated


def _development_runtime_node_context(node_id: str, state: dict[str, Any]) -> dict[str, Any]:
    delivery_plan = _as_dict(state.get("delivery_plan"))
    runtime_graph = _as_dict(delivery_plan.get("runtime_graph")) or _development_runtime_graph(delivery_plan)
    for raw_assignment in _as_list(runtime_graph.get("runtime_assignments")):
        assignment = _as_dict(raw_assignment)
        if str(assignment.get("node_id") or "") == node_id:
            return assignment
    return {
        "node_id": node_id,
        "agent": node_id,
        "stage": "legacy_static",
        "wave_index": None,
        "work_unit_ids": [],
        "focus_work_unit_ids": [],
        "lane_ids": [],
    }


def _development_execution_bucket(state: dict[str, Any], bucket_name: str) -> dict[str, Any]:
    return {
        str(key): _as_dict(value)
        for key, value in _as_dict(_as_dict(state.get("development_execution")).get(bucket_name)).items()
        if str(key).strip()
    }


def _updated_development_execution(
    state: dict[str, Any],
    bucket_name: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    execution = dict(_as_dict(state.get("development_execution")))
    bucket = _development_execution_bucket(state, bucket_name)
    bucket[node_id] = dict(payload)
    execution[bucket_name] = bucket
    return execution


def _aggregate_frontend_bundle(state: dict[str, Any]) -> dict[str, Any]:
    entries = list(_development_execution_bucket(state, "frontend_bundles").values())
    if not entries:
        return _as_dict(state.get("frontend_bundle"))
    latest = entries[-1]
    return {
        "sections": _dedupe_strings(
            [str(item) for entry in entries for item in _as_list(_as_dict(entry).get("sections")) if str(item).strip()]
        ),
        "feature_cards": _dedupe_strings(
            [str(item) for entry in entries for item in _as_list(_as_dict(entry).get("feature_cards")) if str(item).strip()]
        ),
        "css_tokens": _as_dict(latest.get("css_tokens")),
        "interaction_notes": _dedupe_strings(
            [
                str(item)
                for entry in entries
                for item in _as_list(_as_dict(entry).get("interaction_notes"))
                if str(item).strip()
            ]
        ),
        "decision_scope": _as_dict(latest.get("decision_scope")),
        "decision_context_fingerprint": str(latest.get("decision_context_fingerprint") or ""),
        "assigned_packages": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("assigned_packages"))
            if isinstance(item, dict)
        ],
        "assigned_work_units": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("assigned_work_units"))
            if isinstance(item, dict)
        ],
        "wave_plan": [dict(item) for item in _as_list(latest.get("wave_plan")) if isinstance(item, dict)],
        "shift_left_plan": _as_dict(latest.get("shift_left_plan")),
    }


def _aggregate_backend_bundle(state: dict[str, Any]) -> dict[str, Any]:
    entries = list(_development_execution_bucket(state, "backend_bundles").values())
    if not entries:
        return _as_dict(state.get("backend_bundle"))
    latest = entries[-1]
    return {
        "entities": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("entities"))
            if isinstance(item, dict)
        ],
        "api_endpoints": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("api_endpoints"))
            if isinstance(item, dict)
        ],
        "automation_notes": _dedupe_strings(
            [str(item) for entry in entries for item in _as_list(_as_dict(entry).get("automation_notes")) if str(item).strip()]
        ),
        "exposed_capabilities": _dedupe_strings(
            [
                str(item)
                for entry in entries
                for item in _as_list(_as_dict(entry).get("exposed_capabilities"))
                if str(item).strip()
            ]
        ),
        "decision_scope": _as_dict(latest.get("decision_scope")),
        "decision_context_fingerprint": str(latest.get("decision_context_fingerprint") or ""),
        "assigned_packages": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("assigned_packages"))
            if isinstance(item, dict)
        ],
        "assigned_work_units": [
            dict(item)
            for entry in entries
            for item in _as_list(_as_dict(entry).get("assigned_work_units"))
            if isinstance(item, dict)
        ],
        "wave_plan": [dict(item) for item in _as_list(latest.get("wave_plan")) if isinstance(item, dict)],
        "shift_left_plan": _as_dict(latest.get("shift_left_plan")),
    }


def _aggregate_qa_report(state: dict[str, Any]) -> dict[str, Any]:
    entries = list(_development_execution_bucket(state, "qa_reports").values())
    if not entries:
        return _as_dict(state.get("qa_report"))
    latest = entries[-1]
    work_unit_lookup: dict[str, dict[str, Any]] = {}
    wave_lookup: dict[int, dict[str, Any]] = {}
    for entry in entries:
        for item in _as_list(_as_dict(entry).get("work_unit_results")):
            result = _as_dict(item)
            result_id = str(result.get("id") or "").strip()
            if result_id:
                work_unit_lookup[result_id] = result
        for item in _as_list(_as_dict(entry).get("wave_results")):
            result = _as_dict(item)
            wave_lookup[int(result.get("wave_index", 0) or 0)] = result
    return {
        "milestone_results": [dict(item) for item in _as_list(latest.get("milestone_results")) if isinstance(item, dict)],
        "work_unit_results": list(work_unit_lookup.values()),
        "wave_results": [wave_lookup[key] for key in sorted(wave_lookup)],
    }


def _aggregate_security_report(state: dict[str, Any]) -> dict[str, Any]:
    entries = list(_development_execution_bucket(state, "security_reports").values())
    if not entries:
        return _as_dict(state.get("security_report"))
    latest = entries[-1]
    work_unit_lookup: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    findings: list[str] = []
    recommendations: list[str] = []
    for entry in entries:
        blockers = _dedupe_strings(
            blockers + [str(item) for item in _as_list(_as_dict(entry).get("blockers")) if str(item).strip()]
        )
        findings = _dedupe_strings(
            findings + [str(item) for item in _as_list(_as_dict(entry).get("findings")) if str(item).strip()]
        )
        recommendations = _dedupe_strings(
            recommendations + [str(item) for item in _as_list(_as_dict(entry).get("recommendations")) if str(item).strip()]
        )
        for item in _as_list(_as_dict(entry).get("work_unit_results")):
            result = _as_dict(item)
            result_id = str(result.get("id") or "").strip()
            if result_id:
                work_unit_lookup[result_id] = result
    return {
        "status": "pass" if not blockers and str(latest.get("status") or "pass") == "pass" else "warning",
        "findings": findings,
        "blockers": blockers,
        "recommendations": recommendations,
        "work_unit_results": list(work_unit_lookup.values()),
    }


def _stabilize_development_work_packages(
    reference_packages: list[dict[str, Any]],
    candidate_packages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_lookup = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in candidate_packages
        if str(_as_dict(item).get("id") or "").strip()
    }
    stabilized: list[dict[str, Any]] = []
    for reference in reference_packages:
        reference_row = dict(reference)
        candidate = _as_dict(candidate_lookup.get(str(reference_row.get("id") or "").strip()))
        if not candidate:
            stabilized.append(reference_row)
            continue
        stabilized.append(
            {
                **reference_row,
                "title": str(candidate.get("title") or reference_row.get("title") or ""),
                "summary": str(
                    candidate.get("summary")
                    or candidate.get("description")
                    or reference_row.get("summary")
                    or ""
                ),
                "deliverables": _dedupe_strings(
                    [
                        str(item)
                        for item in (
                            _as_list(candidate.get("deliverables"))
                            or _as_list(reference_row.get("deliverables"))
                        )
                        if str(item).strip()
                    ]
                ),
                "acceptance_criteria": _dedupe_strings(
                    [
                        str(item)
                        for item in (
                            _as_list(candidate.get("acceptance_criteria"))
                            or _as_list(reference_row.get("acceptance_criteria"))
                        )
                        if str(item).strip()
                    ]
                ),
                "status": str(candidate.get("status") or reference_row.get("status") or "planned"),
            }
        )
    return stabilized


def _build_development_runtime_workflow_nodes(project_record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(project_record, dict):
        return None
    state = dict(project_record)
    if "delivery_plan" not in state and isinstance(project_record.get("deliveryPlan"), dict):
        state["delivery_plan"] = dict(_as_dict(project_record.get("deliveryPlan")))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    if not selected_design:
        return None
    delivery_plan = _as_dict(state.get("delivery_plan"))
    fresh_delivery_plan = _build_development_delivery_plan(
        state,
        selected_design=selected_design,
        implementation_plan=_as_dict(state.get("implementation_plan")),
    )
    if delivery_plan:
        if (
            str(delivery_plan.get("topology_fingerprint") or "").strip()
            != str(fresh_delivery_plan.get("topology_fingerprint") or "").strip()
            or str(delivery_plan.get("runtime_graph_fingerprint") or "").strip()
            != str(fresh_delivery_plan.get("runtime_graph_fingerprint") or "").strip()
        ):
            delivery_plan = fresh_delivery_plan
    else:
        delivery_plan = fresh_delivery_plan
    runtime_graph = _as_dict(delivery_plan.get("runtime_graph")) or _development_runtime_graph(delivery_plan)
    nodes = _as_dict(runtime_graph.get("nodes"))
    return nodes or None


def _development_lane_defaults(agent_id: str) -> dict[str, Any]:
    defaults = {
        "frontend-builder": {
            "label": "Frontend Builder",
            "remit": "主要画面、操作導線、レスポンシブ UI を実装する",
            "skills": ["responsive-ui", "component-composition"],
            "owned_surfaces": ["workspace shell", "screen surfaces", "interaction flow"],
            "conflict_guards": [
                "UI shell と interaction surface は frontend-builder が単独で編集する",
                "API binding は backend contract が確定してから接続する",
            ],
            "merge_order": 1,
        },
        "backend-builder": {
            "label": "Backend Builder",
            "remit": "状態モデル、API 契約、ドメイン振る舞いを固める",
            "skills": ["api-design", "domain-modeling"],
            "owned_surfaces": ["domain model", "state contract", "integration API"],
            "conflict_guards": [
                "shared state keys と API contract は backend-builder が唯一の変更権を持つ",
                "schema 変更は integrator に公開してから UI 側へ展開する",
            ],
            "merge_order": 2,
        },
        "integrator": {
            "label": "Integrator",
            "remit": "共有 shell、routing、build artifact を統合し衝突を解消する",
            "skills": ["integration", "artifact-assembly"],
            "owned_surfaces": ["app shell", "routing", "shared composition"],
            "conflict_guards": [
                "shared shell と routing は integrator 経由でのみ merge する",
                "lane 間の共有 touchpoint は integrator が一本化する",
            ],
            "merge_order": 3,
        },
        "qa-engineer": {
            "label": "QA Engineer",
            "remit": "マイルストーンと受け入れ条件を検証する",
            "skills": ["acceptance-testing", "quality-assurance"],
            "owned_surfaces": ["acceptance gates", "milestone checks"],
            "conflict_guards": [
                "受け入れ条件は QA 承認なしに緩めない",
                "未達マイルストーンは reviewer に渡す前に明示する",
            ],
            "merge_order": 4,
        },
        "security-reviewer": {
            "label": "Security Reviewer",
            "remit": "安全性、unsafe DOM、運用リスクを精査する",
            "skills": ["security-review", "safety-review"],
            "owned_surfaces": ["security posture", "unsafe DOM checks"],
            "conflict_guards": [
                "unsafe DOM / policy regressions は security-reviewer の sign-off 前に release に載せない",
            ],
            "merge_order": 5,
        },
        "reviewer": {
            "label": "Release Reviewer",
            "remit": "delivery graph の完了と deploy handoff を確定する",
            "skills": ["delivery-review", "release-management"],
            "owned_surfaces": ["release candidate", "deploy handoff"],
            "conflict_guards": [
                "deploy handoff と operator checklist は reviewer が一本化する",
            ],
            "merge_order": 6,
        },
    }
    return dict(defaults.get(agent_id, defaults["frontend-builder"]))


def _build_development_lanes(selected_design: dict[str, Any]) -> list[dict[str, Any]]:
    implementation_brief = _as_dict(selected_design.get("implementation_brief"))
    lanes_by_agent: dict[str, dict[str, Any]] = {}
    for raw_lane in _as_list(implementation_brief.get("agent_lanes")):
        lane = _as_dict(raw_lane)
        role = str(lane.get("role") or "")
        remit = str(lane.get("remit") or "")
        skills = [str(item) for item in _as_list(lane.get("skills")) if str(item).strip()]
        agent_id = _development_agent_id_from_values(role, remit, " ".join(skills))
        defaults = _development_lane_defaults(agent_id)
        lanes_by_agent[agent_id] = {
            "agent": agent_id,
            "label": role or defaults["label"],
            "remit": remit or defaults["remit"],
            "skills": _dedupe_strings(skills or defaults["skills"]),
            "owned_surfaces": list(defaults["owned_surfaces"]),
            "conflict_guards": list(defaults["conflict_guards"]),
            "merge_order": int(defaults["merge_order"]),
        }
    for agent_id in (
        "frontend-builder",
        "backend-builder",
        "integrator",
        "qa-engineer",
        "security-reviewer",
        "reviewer",
    ):
        if agent_id not in lanes_by_agent:
            defaults = _development_lane_defaults(agent_id)
            lanes_by_agent[agent_id] = {
                "agent": agent_id,
                "label": defaults["label"],
                "remit": defaults["remit"],
                "skills": list(defaults["skills"]),
                "owned_surfaces": list(defaults["owned_surfaces"]),
                "conflict_guards": list(defaults["conflict_guards"]),
                "merge_order": int(defaults["merge_order"]),
            }
    return sorted(lanes_by_agent.values(), key=lambda item: (int(item.get("merge_order", 99)), str(item.get("agent", ""))))


def _development_critical_path(work_packages: list[dict[str, Any]]) -> list[str]:
    by_id = {str(item.get("id", "")): item for item in work_packages if str(item.get("id", "")).strip()}
    memo: dict[str, tuple[int, list[str]]] = {}
    visiting: set[str] = set()

    def _resolve(package_id: str) -> tuple[int, list[str]]:
        if package_id in memo:
            return memo[package_id]
        package = by_id.get(package_id)
        if package is None:
            return 0, []
        if package_id in visiting:
            duration = max(1, int(package.get("duration_days", 1) or 1))
            return duration, [package_id]
        visiting.add(package_id)
        best_duration = 0
        best_path: list[str] = []
        for dependency_id in [str(item) for item in _as_list(package.get("depends_on")) if str(item) in by_id]:
            dependency_duration, dependency_path = _resolve(dependency_id)
            if dependency_duration > best_duration:
                best_duration = dependency_duration
                best_path = dependency_path
        visiting.discard(package_id)
        total_duration = best_duration + max(1, int(package.get("duration_days", 1) or 1))
        resolved = (total_duration, [*best_path, package_id])
        memo[package_id] = resolved
        return resolved

    longest_duration = 0
    longest_path: list[str] = []
    for package_id in by_id:
        duration, path = _resolve(package_id)
        if duration > longest_duration:
            longest_duration = duration
            longest_path = path
    return longest_path


def _fallback_development_work_packages(
    *,
    selected_features: list[str],
    selected_design: dict[str, Any],
) -> list[dict[str, Any]]:
    implementation_brief = _as_dict(selected_design.get("implementation_brief"))
    slices = [str(item) for item in _as_list(implementation_brief.get("delivery_slices")) if str(item).strip()]
    package_specs = [
        ("pkg-ui-shell", "frontend-builder", slices[0] if slices else "フェーズナビゲーションと主要画面 shell", [], 0, 2),
        ("pkg-domain-contract", "backend-builder", slices[1] if len(slices) > 1 else "状態同期と domain contract", ["pkg-ui-shell"], 1, 2),
        ("pkg-integration", "integrator", slices[2] if len(slices) > 2 else "統合 build と shared routing", ["pkg-ui-shell", "pkg-domain-contract"], 3, 1),
        ("pkg-quality", "qa-engineer", slices[3] if len(slices) > 3 else "マイルストーン検証とレビュー準備", ["pkg-integration"], 4, 1),
    ]
    feature_summary = _dedupe_strings(selected_features)[:3]
    work_packages: list[dict[str, Any]] = []
    for package_id, lane_id, title, depends_on, start_day, duration_days in package_specs:
        defaults = _development_lane_defaults(lane_id)
        work_packages.append(
            {
                "id": package_id,
                "title": title,
                "lane": lane_id,
                "summary": f"{defaults['label']} が {title} を担当し、共有面の衝突を避けながら完了させる。",
                "depends_on": depends_on,
                "start_day": start_day,
                "duration_days": duration_days,
                "deliverables": [title],
                "acceptance_criteria": feature_summary or ["選択済み機能が build に反映されている"],
                "owned_surfaces": list(defaults["owned_surfaces"]),
                "source_epic": None,
                "status": "planned",
            }
        )
    return work_packages


def _build_development_delivery_plan(
    state: dict[str, Any],
    *,
    selected_design: dict[str, Any],
    implementation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_context_fingerprint = str(_decision_context_from_state(state, compact=True).get("fingerprint") or "")
    selected_features = _selected_feature_names(state)
    value_contract = _as_dict(state.get("valueContract"))
    outcome_telemetry_contract = _as_dict(state.get("outcomeTelemetryContract"))
    requirements = normalize_requirements_bundle(_as_dict(state.get("requirements")))
    task_decomposition = normalize_task_decomposition(_as_dict(state.get("taskDecomposition")))
    dcs_analysis = normalize_dcs_analysis(_as_dict(state.get("dcsAnalysis")))
    technical_design = normalize_technical_design_bundle(_as_dict(state.get("technicalDesign")))
    reverse_engineering = normalize_reverse_engineering_result(_as_dict(state.get("reverseEngineering")))
    lanes = _build_development_lanes(selected_design)
    plan_estimate = _selected_plan_estimate_from_state(state)
    wbs_lookup = _development_plan_estimate_lookup(plan_estimate)
    task_rows = _development_task_rows(task_decomposition)
    requirement_rows = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in _as_list(_as_dict(requirements).get("requirements"))
        if str(_as_dict(item).get("id") or "").strip()
    }
    milestone_rows = {
        str(_as_dict(item).get("id") or "").strip(): _as_dict(item)
        for item in _as_list(state.get("milestones"))
        if str(_as_dict(item).get("id") or "").strip()
    }
    feature_rows = {
        str(item.get("id") or "").strip(): item
        for item in _selected_feature_records(state)
        if str(item.get("id") or "").strip()
    }
    work_packages: list[dict[str, Any]] = []
    for task in task_rows:
        package_id = str(task.get("id") or f"pkg-{len(work_packages) + 1}")
        estimate = _as_dict(wbs_lookup.get(package_id))
        lane_id = _development_agent_id_from_values(
            estimate.get("assignee"),
            estimate.get("assignee_type"),
            " ".join(str(skill) for skill in _as_list(estimate.get("skills"))),
            task.get("title"),
            task.get("description"),
            task.get("phase"),
            task.get("feature_id"),
        )
        defaults = _development_lane_defaults(lane_id)
        lane = next(
            (item for item in lanes if str(_as_dict(item).get("agent") or "") == lane_id),
            {
                "agent": lane_id,
                "label": defaults["label"],
                "remit": defaults["remit"],
                "skills": list(defaults["skills"]),
                "owned_surfaces": list(defaults["owned_surfaces"]),
                "conflict_guards": list(defaults["conflict_guards"]),
                "merge_order": int(defaults["merge_order"]),
            },
        )
        requirement_row = _as_dict(requirement_rows.get(str(task.get("requirement_id") or "")))
        milestone_row = _as_dict(milestone_rows.get(str(task.get("milestone_id") or "")))
        feature_row = _as_dict(feature_rows.get(str(task.get("feature_id") or "")))
        work_packages.append(
            {
                "id": package_id,
                "title": str(task.get("title") or estimate.get("title") or f"Work package {len(work_packages) + 1}"),
                "lane": lane_id,
                "summary": str(task.get("description") or estimate.get("description") or lane.get("remit") or defaults["remit"]),
                "depends_on": [str(dep) for dep in _as_list(task.get("depends_on")) if str(dep).strip()],
                "start_day": max(0, int(estimate.get("start_day", 0) or 0)),
                "duration_days": max(
                    1,
                    int(
                        estimate.get("duration_days")
                        or max(1, math.ceil(float(task.get("effort_hours", 0.0) or 0.0) / 8.0))
                        or 1
                    ),
                ),
                "deliverables": _dedupe_strings(
                    [str(task.get("title") or ""), str(feature_row.get("name") or "")]
                    + [str(skill) for skill in _as_list(estimate.get("skills")) if str(skill).strip()]
                ),
                "acceptance_criteria": _dedupe_strings(
                    [str(task.get("description") or "")]
                    + [str(item).strip() for item in _as_list(requirement_row.get("acceptanceCriteria")) if str(item).strip()]
                    + [str(milestone_row.get("criteria") or "").strip()]
                ),
                "owned_surfaces": list(lane.get("owned_surfaces", defaults["owned_surfaces"])),
                "source_epic": str(estimate.get("epic_id") or estimate.get("epicId") or "") or None,
                "source_task_id": package_id,
                "source_feature_id": str(task.get("feature_id") or "") or None,
                "feature_names": _dedupe_strings([str(feature_row.get("name") or "").strip()]),
                "requirement_ids": [str(task.get("requirement_id") or "").strip()] if str(task.get("requirement_id") or "").strip() else [],
                "milestone_id": str(task.get("milestone_id") or "").strip() or None,
                "priority": str(task.get("priority") or "should"),
                "status": "planned",
            }
        )
    if not work_packages:
        for raw_item in _as_list(plan_estimate.get("wbs")):
            item = _as_dict(raw_item)
            package_id = str(item.get("id") or f"pkg-{len(work_packages) + 1}")
            lane_id = _development_agent_id_from_values(
                item.get("assignee"),
                item.get("assignee_type"),
                " ".join(str(skill) for skill in _as_list(item.get("skills"))),
                item.get("title"),
                item.get("description"),
            )
            defaults = _development_lane_defaults(lane_id)
            lane = next(
                (entry for entry in lanes if str(_as_dict(entry).get("agent") or "") == lane_id),
                {
                    "agent": lane_id,
                    "label": defaults["label"],
                    "remit": defaults["remit"],
                    "skills": list(defaults["skills"]),
                    "owned_surfaces": list(defaults["owned_surfaces"]),
                    "conflict_guards": list(defaults["conflict_guards"]),
                    "merge_order": int(defaults["merge_order"]),
                },
            )
            work_packages.append(
                {
                    "id": package_id,
                    "title": str(item.get("title") or f"Work package {len(work_packages) + 1}"),
                    "lane": lane_id,
                    "summary": str(item.get("description") or lane.get("remit") or defaults["remit"]),
                    "depends_on": [str(dep) for dep in _as_list(item.get("depends_on")) if str(dep).strip()],
                    "start_day": max(0, int(item.get("start_day", 0) or 0)),
                    "duration_days": max(1, int(item.get("duration_days", 1) or 1)),
                    "deliverables": _dedupe_strings(
                        [str(item.get("title") or "")]
                        + [str(skill) for skill in _as_list(item.get("skills")) if str(skill).strip()]
                    ),
                    "acceptance_criteria": _dedupe_strings(
                        [str(item.get("description") or "")]
                        + [
                            str(milestone.get("criteria") or "")
                            for milestone in _as_list(state.get("milestones"))[:2]
                            if isinstance(milestone, dict)
                        ]
                    ),
                    "owned_surfaces": list(lane.get("owned_surfaces", defaults["owned_surfaces"])),
                    "source_epic": str(item.get("epic_id") or "") or None,
                    "status": "planned",
                }
            )
    if not work_packages:
        work_packages = _fallback_development_work_packages(
            selected_features=selected_features,
            selected_design=selected_design,
        )

    topology = _build_development_topology(
        state=state,
        selected_design=selected_design,
        selected_features=selected_features,
        requirements=requirements,
        technical_design=technical_design,
        work_packages=work_packages,
        lanes=lanes,
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    runtime_graph = _development_runtime_graph(topology)
    code_workspace = build_development_code_workspace(
        spec=str(state.get("spec") or ""),
        selected_features=selected_features,
        selected_design=selected_design,
        requirements=requirements,
        task_decomposition=task_decomposition,
        technical_design=technical_design,
        reverse_engineering=reverse_engineering,
        planning_analysis=_as_dict(state.get("analysis")),
        milestones=[dict(item) for item in _as_list(state.get("milestones")) if isinstance(item, dict)],
        goal_spec=_as_dict(topology.get("goal_spec")),
        dependency_analysis=_as_dict(topology.get("dependency_analysis")),
        work_unit_contracts=[dict(item) for item in _as_list(topology.get("work_unit_contracts")) if isinstance(item, dict)],
        waves=[dict(item) for item in _as_list(topology.get("waves")) if isinstance(item, dict)],
        critical_path=[str(item) for item in _as_list(topology.get("critical_path")) if str(item).strip()],
        shift_left_plan=_as_dict(topology.get("shift_left_plan")),
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    spec_audit = build_development_spec_audit(
        selected_features=selected_features,
        requirements=requirements,
        task_decomposition=task_decomposition,
        dcs_analysis=dcs_analysis,
        technical_design=technical_design,
        reverse_engineering=reverse_engineering,
        code_workspace=code_workspace,
        selected_design=selected_design,
        planning_analysis=_as_dict(state.get("analysis")),
        delivery_plan_context=topology,
        value_contract=value_contract,
        outcome_telemetry_contract=outcome_telemetry_contract,
    )
    delivery_plan = {
        "execution_mode": "autonomous_repo_delivery",
        "topology_mode": "work_unit_wave_mesh",
        "summary": (
            "Approved planning/design context を goal spec -> dependency DAG -> execution waves -> work-unit contracts に展開し、"
            " 各 work unit で shift-left QA / security を回しながら build から deploy handoff まで閉じる。"
            " requirements / task DAG / technical design / code workspace を正本として扱う。"
        ),
        "selected_preset": str(state.get("selectedPreset") or plan_estimate.get("preset") or "standard"),
        "source_plan_preset": str(plan_estimate.get("preset") or state.get("selectedPreset") or "standard"),
        "success_definition": str(
            _as_dict(implementation_plan).get("success_definition")
            or "各 work unit が局所的に検証され、wave ごとに閉じたうえで主要機能が統合 build と deploy handoff に反映されていること。"
        ),
        "lanes": lanes,
        **topology,
        "runtime_graph": runtime_graph,
        "spec_audit": spec_audit,
        "code_workspace": code_workspace,
        "value_contract": value_contract,
        "outcome_telemetry_contract": outcome_telemetry_contract,
    }
    return _annotate_development_delivery_plan_lineage(
        delivery_plan,
        decision_context_fingerprint=decision_context_fingerprint,
    )


def _build_development_handoff(
    *,
    state: dict[str, Any],
    delivery_plan: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    spec_audit = _as_dict(delivery_plan.get("spec_audit"))
    code_workspace = _as_dict(delivery_plan.get("code_workspace"))
    workspace_paths = {
        str(_as_dict(item).get("path") or "").strip()
        for item in _as_list(code_workspace.get("files"))
        if str(_as_dict(item).get("path") or "").strip()
    }
    repo_execution = _as_dict(delivery_plan.get("repo_execution")) or _as_dict(snapshot.get("repo_execution_report"))
    security_report = _as_dict(snapshot.get("security_report"))
    workspace_summary = _as_dict(code_workspace.get("artifact_summary"))
    milestone_results = [_as_dict(item) for item in _as_list(snapshot.get("milestone_results")) if _as_dict(item)]
    work_unit_contracts = [_as_dict(item) for item in _as_list(delivery_plan.get("work_unit_contracts")) if _as_dict(item)]
    waves = [_as_dict(item) for item in _as_list(delivery_plan.get("waves")) if _as_dict(item)]
    shift_left_plan = _as_dict(delivery_plan.get("shift_left_plan"))
    value_contract = _as_dict(delivery_plan.get("value_contract") or state.get("valueContract"))
    outcome_telemetry_contract = _as_dict(
        delivery_plan.get("outcome_telemetry_contract") or state.get("outcomeTelemetryContract")
    )
    execution = _as_dict(state.get("development_execution"))
    qa_wave_results = [
        _as_dict(item)
        for item in _as_list(snapshot.get("wave_results"))
        if _as_dict(item)
    ] or [
        _as_dict(item)
        for item in _as_list(_as_dict(state.get("qa_report")).get("wave_results"))
        if _as_dict(item)
    ]
    wave_review_rows = [
        _as_dict(item)
        for item in _as_dict(execution.get("reviews")).values()
        if _as_dict(item)
        and int(_as_dict(item).get("wave_index", -1) or -1) >= 0
        and _as_dict(item).get("ready") is not None
    ]
    ready_wave_indices = {
        int(item.get("wave_index", -1) or -1)
        for item in wave_review_rows
        if item.get("ready") is True
    }
    non_final_wave_count = max(0, len(waves) - 1)
    wave_exit_ready = non_final_wave_count == 0 or len(ready_wave_indices) >= non_final_wave_count
    blocked_work_unit_ids = _dedupe_strings(
        [
            str(_as_dict(item).get("id") or "").strip()
            for item in _as_list(snapshot.get("work_unit_results"))
            if str(_as_dict(item).get("status") or "") not in {"satisfied", "pass"}
            and str(_as_dict(item).get("id") or "").strip()
        ]
    )
    qa_wave_ready = (
        all(str(item.get("status") or "") == "satisfied" for item in qa_wave_results)
        if qa_wave_results
        else not blocked_work_unit_ids
    )
    security_blockers = [
        str(item)
        for item in _as_list(security_report.get("blockers"))
        if str(item).strip() and not _is_non_blocking_review_finding(item)
    ]
    if not security_blockers and str(security_report.get("status") or "") != "pass":
        security_blockers = [
            str(item)
            for item in _as_list(security_report.get("findings"))
            if str(item).strip() and not str(item).startswith("No obvious")
        ]
    blocker_strings = _dedupe_strings(
        [
            str(item)
            for item in _as_list(snapshot.get("blockers"))
            if str(item).strip() and not _is_non_blocking_review_finding(item)
        ]
        + security_blockers
        + [
            str(_as_dict(item).get("title") or "")
            for item in _as_list(spec_audit.get("unresolved_gaps"))
            if str(_as_dict(item).get("severity") or "") in {"critical", "high"}
            and str(_as_dict(item).get("title") or "").strip()
        ]
        + [
            str(item)
            for item in _as_list(repo_execution.get("errors"))
            if str(item).strip()
        ]
        + (["Not every execution wave has closed with a ready wave-exit review."] if not wave_exit_ready else [])
        + (["At least one execution wave still fails its QA exit criteria."] if not qa_wave_ready else [])
    )
    blockers: list[BlockingIssue] = [
        {
            "id": f"blocker-{idx}",
            "severity": "critical" if idx < len(_as_list(snapshot.get("blockers"))) + len(security_blockers) else "major",
            "description": desc,
            "source_phase": "development",
        }
        for idx, desc in enumerate(blocker_strings)
    ]
    satisfied = sum(1 for item in milestone_results if str(item.get("status", "")) == "satisfied")
    total = len(milestone_results)
    repo_ready = repo_execution.get("ready") is True
    readiness_status = (
        "ready_for_deploy"
        if not blockers and repo_ready and total > 0 and satisfied == total and wave_exit_ready and qa_wave_ready
        else "needs_rework"
    )
    operator_summary = (
        "全 work package が依存順どおり統合され、repo/worktree 実行まで通過したので deploy phase がそのまま release gate を実行できる状態です。"
        if readiness_status == "ready_for_deploy"
        else "未解決 blocker または repo execution failure が残っているため、deploy へ渡す前に development mesh で再ループが必要です。"
    )
    review_focus_raw = _dedupe_strings(
        [
            str(item)
            for item in _as_list(
                _as_dict(_as_dict(_selected_design_from_state(state)).get("approval_packet")).get("review_checklist")
            )
            if str(item).strip()
        ]
        + [str(item.get("name") or "") for item in milestone_results if str(item.get("status", "")) != "satisfied"]
    )
    review_focus: list[ReviewFocusItem] = [
        {"area": "review", "description": desc, "priority": "high" if idx == 0 else "medium"}
        for idx, desc in enumerate(review_focus_raw)
    ]
    deploy_checklist: list[ChecklistItem] = [
        {"id": "critical-path-integrated", "label": "critical path の全 package が統合済みである", "category": "integration", "required": True},
        {"id": "milestones-satisfied", "label": f"マイルストーン {satisfied}/{total} 件が満たされている", "category": "quality", "required": True},
        {"id": "shell-routing-merged", "label": "shared shell と routing の merge が integrator 経由で一本化されている", "category": "integration", "required": True},
        {"id": "security-findings-resolved", "label": "security review の blocking finding が解消されている", "category": "security", "required": True},
        {"id": "spec-audit-closed", "label": "requirements / task DAG / technical design の spec audit が閉じている", "category": "quality", "required": True},
        {"id": "goal-spec-attached", "label": "goal spec / wave plan / work-unit contracts が handoff に添付されている", "category": "readiness", "required": True},
        {"id": "value-contracts-attached", "label": "value contract と outcome telemetry contract が deploy handoff に添付されている", "category": "readiness", "required": True},
        {"id": "shift-left-complete", "label": "shift-left QA / security が work-unit 単位で完了している", "category": "security", "required": True},
        {"id": "wave-exits-ready", "label": "各 execution wave が ready 状態で close されている", "category": "readiness", "required": True},
        {"id": "workspace-package-tree", "label": "code workspace の package tree と route binding が handoff に含まれている", "category": "integration", "required": True},
        {"id": "design-token-contracts", "label": "design token / access-control / operability contract が workspace に含まれている", "category": "quality", "required": False},
        {"id": "development-standards", "label": "標準開発ルールとコーディング規約が workspace に含まれている", "category": "quality", "required": False},
        {"id": "repo-execution-passed", "label": "materialized repo/worktree で install / build / test が成功している", "category": "readiness", "required": True},
    ] + [
        {"id": f"review-focus-{idx}", "label": desc, "category": "review", "required": False}
        for idx, desc in enumerate(review_focus_raw[:2])
    ]
    work_package_count = len(_as_list(delivery_plan.get("work_packages")))
    critical_path_items = _as_list(delivery_plan.get("critical_path"))
    design_token_present = "present" if "app/lib/design-tokens.ts" in workspace_paths and "docs/spec/design-system.md" in workspace_paths else "missing"
    dev_standards_present = "present" if "app/lib/development-standards.ts" in workspace_paths and "docs/spec/development-standards.md" in workspace_paths else "missing"
    access_policy_present = "present" if "server/contracts/access-policy.ts" in workspace_paths and "docs/spec/access-control.md" in workspace_paths else "missing"
    operability_present = "present" if "server/contracts/audit-events.ts" in workspace_paths and "docs/spec/operability.md" in workspace_paths else "missing"
    value_contract_present = "present" if "app/lib/value-contract.ts" in workspace_paths and "docs/spec/value-contract.md" in workspace_paths else "missing"
    telemetry_contract_present = "present" if "server/contracts/outcome-telemetry.ts" in workspace_paths and "docs/spec/outcome-telemetry.md" in workspace_paths else "missing"
    evidence: list[EvidenceItem] = [
        {"category": "work_package", "label": "完了 work package", "value": work_package_count, "unit": "count"},
    ] + [
        {"category": "milestone", "label": f"{item.get('name', 'Milestone')} を満たした", "value": str(item.get("name", "Milestone")), "unit": "id"}
        for item in milestone_results
        if str(item.get("status", "")) == "satisfied"
    ] + ([
        {"category": "critical_path", "label": "critical path", "value": " → ".join(str(item) for item in critical_path_items), "unit": "path"},
    ] if critical_path_items else []) + [
        {"category": "execution", "label": "execution waves", "value": len(waves), "unit": "count"},
        {"category": "execution", "label": "work-unit contracts", "value": len(work_unit_contracts), "unit": "count"},
        {"category": "execution", "label": "ready wave exits", "value": f"{len(ready_wave_indices)}/{non_final_wave_count}" if non_final_wave_count > 0 else "single-wave flow", "unit": "count"},
        {"category": "execution", "label": "shift-left mode", "value": str(shift_left_plan.get("mode") or "unknown"), "unit": "id"},
        {"category": "file", "label": "workspace files", "value": int(workspace_summary.get("file_count", 0) or 0), "unit": "count"},
        {"category": "package", "label": "workspace packages", "value": int(workspace_summary.get("package_count", 0) or 0), "unit": "count"},
        {"category": "route", "label": "route bindings", "value": int(workspace_summary.get("route_binding_count", 0) or 0), "unit": "count"},
        {"category": "contract", "label": "design token contract", "value": design_token_present, "unit": "id"},
        {"category": "contract", "label": "development standards", "value": dev_standards_present, "unit": "id"},
        {"category": "contract", "label": "access policy", "value": access_policy_present, "unit": "id"},
        {"category": "contract", "label": "operability contract", "value": operability_present, "unit": "id"},
        {"category": "contract", "label": "value contract", "value": value_contract_present, "unit": "id"},
        {"category": "contract", "label": "telemetry contract", "value": telemetry_contract_present, "unit": "id"},
        {"category": "contract", "label": "value metrics", "value": len(_as_list(value_contract.get("success_metrics"))), "unit": "count"},
        {"category": "contract", "label": "telemetry events", "value": len(_as_list(outcome_telemetry_contract.get("telemetry_events"))), "unit": "count"},
        {"category": "execution", "label": "topology fingerprint", "value": str(delivery_plan.get("topology_fingerprint") or "missing"), "unit": "id"},
        {"category": "execution", "label": "runtime graph fingerprint", "value": str(delivery_plan.get("runtime_graph_fingerprint") or "missing"), "unit": "id"},
        {"category": "execution", "label": "spec audit", "value": str(spec_audit.get("status") or "unknown"), "unit": "id"},
        {"category": "execution", "label": "repo execution", "value": str(repo_execution.get("mode") or "unknown"), "unit": "id"},
        {"category": "execution", "label": "repo build", "value": str(_as_dict(repo_execution.get("build")).get("status") or "unknown"), "unit": "id"},
        {"category": "execution", "label": "repo test", "value": str(_as_dict(repo_execution.get("test")).get("status") or "skipped"), "unit": "id"},
    ]
    return {
        "readiness_status": readiness_status,
        "release_candidate": "Approved context を反映した release-reviewable build candidate",
        "operator_summary": operator_summary,
        "deploy_checklist": deploy_checklist,
        "evidence": evidence,
        "blocking_issues": blockers,
        "review_focus": review_focus,
        "topology_fingerprint": str(delivery_plan.get("topology_fingerprint") or ""),
        "runtime_graph_fingerprint": str(delivery_plan.get("runtime_graph_fingerprint") or ""),
        "wave_exit_ready": wave_exit_ready,
        "ready_wave_count": len(ready_wave_indices),
        "non_final_wave_count": non_final_wave_count,
        "blocked_work_unit_ids": blocked_work_unit_ids,
    }


def _development_planner_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    planning_context = _as_dict(_as_dict(state.get("analysis")).get("planning_context"))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    selected_plan_estimate = _selected_plan_estimate_from_state(state)
    decision_context = _decision_context_from_state(state, compact=True)
    decision_scope = _decision_scope_for_phase(state, phase="development")
    workstreams = [
        {
            "agent": "frontend-builder",
            "focus": "UI shell and interaction layout",
            "skills": ["responsive-ui", "component-composition"],
            "depends_on": [],
        },
        {
            "agent": "backend-builder",
            "focus": "Domain model and data contract",
            "skills": ["api-design", "state-modeling"],
            "depends_on": [],
        },
        {
            "agent": "integrator",
            "focus": "Shared shell, merge order, and release-reviewable build assembly",
            "skills": ["integration", "artifact-assembly"],
            "depends_on": ["frontend-builder", "backend-builder"],
        },
        {
            "agent": "repo-executor",
            "focus": "Materialize the code workspace into a real repo or detached worktree and verify install/build/test",
            "skills": ["repo-materialization", "build-verification"],
            "depends_on": ["integrator"],
        },
    ]
    if state.get("milestones"):
        workstreams.append(
            {
                "agent": "qa-engineer",
                "focus": "Milestone verification",
                "skills": ["acceptance-testing"],
                "depends_on": ["repo-executor"],
            }
        )
    workstreams.extend(
        [
            {
                "agent": "security-reviewer",
                "focus": "Security and unsafe DOM review",
                "skills": ["security-review", "safety-review"],
                "depends_on": ["repo-executor"],
            },
            {
                "agent": "reviewer",
                "focus": "Deploy handoff and final release-readiness review",
                "skills": ["delivery-review", "release-management"],
                "depends_on": ["qa-engineer", "security-reviewer"],
            },
        ]
    )
    plan = {
        "selected_features": selected_features,
        "workstreams": workstreams,
        "success_definition": "Selected design plus must-have features are visible in a release-reviewable build artifact with a deploy-ready handoff packet.",
        "decision_scope": decision_scope,
        "source_plan_preset": str(selected_plan_estimate.get("preset") or state.get("selectedPreset") or "standard"),
    }
    delivery_plan = _build_development_delivery_plan(
        state,
        selected_design=selected_design,
        implementation_plan=plan,
    )
    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Route implementation work to the smallest high-leverage skill set and identify where peer review should be delegated.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-plan",
                static_instruction=(
                    "You are an autonomous build planner. Return JSON only. "
                    "Create a concise but high-quality autonomous delivery plan grounded in the provided design, WBS, and milestones. "
                    "You must preserve dependency ordering, anti-conflict lane ownership, and deploy handoff readiness."
                ),
                user_prompt=(
                    "Return JSON with keys selected_features, workstreams, success_definition, delivery_plan.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Planning context: {planning_context}\n"
                    f"Decision context: {decision_context}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Selected design: {state.get('selected_design') or state.get('design')}\n"
                    f"Selected plan estimate: {selected_plan_estimate}\n"
                    f"Baseline delivery plan: {delivery_plan}\n"
                    f"Skill plan: {collaboration_plan}\n"
                ),
                phase="development",
                node_id=node_id,
            )
            if not isinstance(payload, dict):
                return NodeResult(
                    state_patch={
                        "implementation_plan": plan,
                        "delivery_plan": delivery_plan,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    artifacts=_artifacts(
                        {"name": "implementation-plan", "kind": "development", **plan},
                        {"name": "delivery-plan", "kind": "development", **delivery_plan},
                        {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                    ),
                    metrics={"development_mode": "provider-backed-fallback"},
                    llm_events=[*plan_events, *llm_events],
                )
            llm_plan = {
                "selected_features": [str(item) for item in _as_list(payload.get("selected_features")) if str(item).strip()] or selected_features,
                "workstreams": [dict(item) for item in _as_list(payload.get("workstreams")) if isinstance(item, dict)] or workstreams,
                "success_definition": str(payload.get("success_definition") or plan["success_definition"]),
                "decision_scope": decision_scope,
                "source_plan_preset": str(selected_plan_estimate.get("preset") or state.get("selectedPreset") or "standard"),
            }
            llm_delivery_plan = _as_dict(payload.get("delivery_plan"))
            finalized_delivery_plan = _build_development_delivery_plan(
                {
                    **state,
                    "selected_design": selected_design,
                },
                selected_design=selected_design,
                implementation_plan=llm_plan,
            )
            if llm_delivery_plan:
                finalized_delivery_plan.update(
                    {
                        "summary": str(llm_delivery_plan.get("summary") or finalized_delivery_plan.get("summary")),
                        "success_definition": str(llm_delivery_plan.get("success_definition") or llm_plan["success_definition"]),
                    }
                )
                if _as_list(llm_delivery_plan.get("work_packages")):
                    finalized_delivery_plan["work_packages"] = _stabilize_development_work_packages(
                        [
                            dict(item)
                            for item in _as_list(finalized_delivery_plan.get("work_packages"))
                            if isinstance(item, dict)
                        ],
                        [
                            {
                                **dict(item),
                                "status": str(_as_dict(item).get("status") or "planned"),
                            }
                            for item in _as_list(llm_delivery_plan.get("work_packages"))
                            if isinstance(item, dict)
                        ],
                    )
                    topology = _build_development_topology(
                        state={
                            **state,
                            "selected_design": selected_design,
                        },
                        selected_design=selected_design,
                        selected_features=llm_plan["selected_features"],
                        requirements=normalize_requirements_bundle(_as_dict(state.get("requirements"))),
                        technical_design=normalize_technical_design_bundle(_as_dict(state.get("technicalDesign"))),
                        work_packages=[
                            dict(item)
                            for item in finalized_delivery_plan["work_packages"]
                            if isinstance(item, dict)
                        ],
                        lanes=[
                            dict(item)
                            for item in _as_list(finalized_delivery_plan.get("lanes"))
                            if isinstance(item, dict)
                        ] or _build_development_lanes(selected_design),
                    )
                    refreshed_code_workspace = build_development_code_workspace(
                        spec=str(state.get("spec") or ""),
                        selected_features=llm_plan["selected_features"],
                        selected_design=selected_design,
                        requirements=normalize_requirements_bundle(_as_dict(state.get("requirements"))),
                        task_decomposition=normalize_task_decomposition(_as_dict(state.get("taskDecomposition"))),
                        technical_design=normalize_technical_design_bundle(_as_dict(state.get("technicalDesign"))),
                        reverse_engineering=normalize_reverse_engineering_result(_as_dict(state.get("reverseEngineering"))),
                        planning_analysis=_as_dict(state.get("analysis")),
                        milestones=[dict(item) for item in _as_list(state.get("milestones")) if isinstance(item, dict)],
                        goal_spec=_as_dict(topology.get("goal_spec")),
                        dependency_analysis=_as_dict(topology.get("dependency_analysis")),
                        work_unit_contracts=[dict(item) for item in _as_list(topology.get("work_unit_contracts")) if isinstance(item, dict)],
                        waves=[dict(item) for item in _as_list(topology.get("waves")) if isinstance(item, dict)],
                        critical_path=[str(item) for item in _as_list(topology.get("critical_path")) if str(item).strip()],
                        shift_left_plan=_as_dict(topology.get("shift_left_plan")),
                    )
                    refreshed_spec_audit = build_development_spec_audit(
                        selected_features=llm_plan["selected_features"],
                        requirements=normalize_requirements_bundle(_as_dict(state.get("requirements"))),
                        task_decomposition=normalize_task_decomposition(_as_dict(state.get("taskDecomposition"))),
                        dcs_analysis=normalize_dcs_analysis(_as_dict(state.get("dcsAnalysis"))),
                        technical_design=normalize_technical_design_bundle(_as_dict(state.get("technicalDesign"))),
                        reverse_engineering=normalize_reverse_engineering_result(_as_dict(state.get("reverseEngineering"))),
                        code_workspace=refreshed_code_workspace,
                        selected_design=selected_design,
                        planning_analysis=_as_dict(state.get("analysis")),
                        delivery_plan_context=topology,
                    )
                    finalized_delivery_plan.update(topology)
                    finalized_delivery_plan["code_workspace"] = refreshed_code_workspace
                    finalized_delivery_plan["spec_audit"] = refreshed_spec_audit
                    finalized_delivery_plan = _annotate_development_delivery_plan_lineage(
                        finalized_delivery_plan,
                        decision_context_fingerprint=str(decision_context.get("fingerprint") or ""),
                    )
            return NodeResult(
                state_patch={
                    "implementation_plan": llm_plan,
                    "delivery_plan": finalized_delivery_plan,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts(
                    {"name": "implementation-plan", "kind": "development", **llm_plan},
                    {"name": "delivery-plan", "kind": "development", **finalized_delivery_plan},
                    {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                ),
                metrics={"development_mode": "provider-backed-autonomous"},
                llm_events=[*plan_events, *llm_events],
            )

        return autonomous()
    return NodeResult(
        state_patch={
            "implementation_plan": plan,
            "delivery_plan": delivery_plan,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Build Planner",
                "objective": "Break delivery into dependency-aware, conflict-safe workstreams.",
                "candidate_skills": ["task-routing", "implementation-planning"],
                "selected_skills": ["task-routing", "implementation-planning"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Use planning WBS and design lanes to build a delivery graph before coding starts.",
            },
            _delegation_state_key(node_id): [],
        },
        artifacts=_artifacts(
            {"name": "implementation-plan", "kind": "development", **plan},
            {"name": "delivery-plan", "kind": "development", **delivery_plan},
        ),
    )


def _development_frontend_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    node_context = _development_runtime_node_context(node_id, state)
    focus_work_unit_ids = {
        str(item).strip()
        for item in _as_list(node_context.get("focus_work_unit_ids"))
        if str(item).strip()
    }
    analysis = _as_dict(state.get("analysis"))
    planning_context = _as_dict(analysis.get("planning_context"))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    decision_context = _decision_context_from_state(state, compact=True)
    decision_scope = _decision_scope_for_phase(state, phase="development", selected_design=selected_design)
    prototype = _as_dict(selected_design.get("prototype")) or _build_design_prototype(
        spec=str(state.get("spec", "")),
        analysis=analysis,
        selected_features=selected_features,
        pattern_name=str(selected_design.get("pattern_name") or "Prototype baseline"),
        description=str(selected_design.get("description") or "Build-ready product prototype"),
    )
    prototype_screens = [dict(item) for item in _as_list(prototype.get("screens")) if isinstance(item, dict)]
    delivery_plan = _as_dict(state.get("delivery_plan"))
    assigned_packages = [
        dict(item)
        for item in _as_list(delivery_plan.get("work_packages"))
        if isinstance(item, dict)
        and str(item.get("lane", "")) == "frontend-builder"
        and (
            not focus_work_unit_ids
            or str(item.get("id") or "").strip() in focus_work_unit_ids
        )
    ]
    assigned_work_units = [
        dict(item)
        for item in _as_list(delivery_plan.get("work_unit_contracts"))
        if isinstance(item, dict)
        and str(item.get("lane", "")) == "frontend-builder"
        and (
            not focus_work_unit_ids
            or str(item.get("work_package_id") or item.get("id") or "").strip() in focus_work_unit_ids
        )
    ]
    wave_rows = [
        dict(item)
        for item in _as_list(delivery_plan.get("waves"))
        if isinstance(item, dict)
        and (
            (
                node_context.get("wave_index") is not None
                and int(item.get("wave_index", -1) or -1) == int(node_context.get("wave_index", -2) or -2)
            )
            or any(
                str(unit.get("work_package_id") or "").strip() in set(_as_list(item.get("work_unit_ids")))
                for unit in assigned_work_units
            )
        )
    ]
    sections = [
        str(screen.get("id") or f"screen-{index + 1}")
        for index, screen in enumerate(prototype_screens[:4])
        if str(screen.get("id") or "").strip()
    ] or [
        "workspace",
        "workflow-map",
        "readiness-rail",
    ]
    cards = _dedupe_strings(
        [str(screen.get("title") or screen.get("headline") or "") for screen in prototype_screens[:4]]
        + selected_features
    ) or ["Primary workspace", "Key flow", "Readiness rail"]
    interaction_notes = [
        str(item) for item in _as_list(prototype.get("interaction_principles")) if str(item).strip()
    ][:4]
    payload = {
        "sections": sections,
        "feature_cards": cards,
        "css_tokens": {
            "radius": "18px",
            "shadow": "0 20px 60px rgba(15,23,42,0.12)",
            "layout": str(_as_dict(prototype.get("app_shell")).get("layout") or "sidebar"),
        },
        "interaction_notes": interaction_notes,
        "decision_scope": decision_scope,
        "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
        "assigned_packages": assigned_packages,
        "assigned_work_units": assigned_work_units,
        "wave_plan": wave_rows,
        "shift_left_plan": _as_dict(delivery_plan.get("shift_left_plan")),
        "runtime_node": node_context,
    }

    def _patched_frontend_state(bundle_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        execution = _updated_development_execution(state, "frontend_bundles", node_id, bundle_payload)
        aggregate_state = {**state, "development_execution": execution}
        aggregate_bundle = _aggregate_frontend_bundle(aggregate_state)
        return execution, aggregate_bundle

    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Choose the skills that will maximize differentiated, accessible, mobile-safe UI execution.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-frontend-plan",
                static_instruction=(
                    "You are a principal frontend architect. Return JSON only. "
                    "Produce a UI composition plan that is differentiated, accessible, mobile-safe, "
                    "and compliant with the approved design tokens and development standards. "
                    "Do not rely on hard-coded brand presentation values."
                ),
                user_prompt=(
                    "Return JSON with keys sections, feature_cards, css_tokens, interaction_notes.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Planning context: {planning_context}\n"
                    f"Design tokens: {_as_dict(_as_dict(state.get('analysis')).get('design_tokens'))}\n"
                    f"Roles: {_as_list(_as_dict(state.get('analysis')).get('roles'))}\n"
                    f"Decision context: {decision_context}\n"
                    f"Design prototype: {prototype}\n"
                    f"Assigned delivery packages: {assigned_packages}\n"
                    f"Assigned work-unit contracts: {assigned_work_units}\n"
                    f"Wave plan: {wave_rows}\n"
                    f"Shift-left plan: {_as_dict(delivery_plan.get('shift_left_plan'))}\n"
                    f"Design context: {state.get('selected_design') or state.get('design')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    "Bias toward application/workspace surfaces. Do not collapse the layout into a landing page. "
                    "Process work in dependency order, keep repairs local to the same work unit when possible, "
                    "and keep the output compliant with approved tokens, auth-facing surfaces, and coding rules."
                ),
                phase="development",
                node_id=node_id,
            )
            if not isinstance(llm_payload, dict):
                execution, aggregate_bundle = _patched_frontend_state(payload)
                return NodeResult(
                    state_patch={
                        "frontend_bundle": aggregate_bundle,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    llm_events=[*plan_events, *llm_events],
                    metrics={"frontend_mode": "provider-backed-fallback"},
                )
            llm_bundle = {
                "sections": [str(item) for item in _as_list(llm_payload.get("sections")) if str(item).strip()] or sections,
                "feature_cards": [str(item) for item in _as_list(llm_payload.get("feature_cards")) if str(item).strip()] or cards,
                "css_tokens": _as_dict(llm_payload.get("css_tokens")) or payload["css_tokens"],
                "interaction_notes": [str(item) for item in _as_list(llm_payload.get("interaction_notes")) if str(item).strip()],
                "decision_scope": decision_scope,
                "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
                "assigned_packages": assigned_packages,
                "assigned_work_units": assigned_work_units,
                "wave_plan": wave_rows,
                "shift_left_plan": _as_dict(delivery_plan.get("shift_left_plan")),
                "runtime_node": node_context,
            }
            execution, aggregate_bundle = _patched_frontend_state(llm_bundle)
            return NodeResult(
                state_patch={
                    "frontend_bundle": aggregate_bundle,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                llm_events=[*plan_events, *llm_events],
                metrics={"frontend_mode": "provider-backed-autonomous"},
            )

        return autonomous()
    execution, aggregate_bundle = _patched_frontend_state(payload)
    return NodeResult(
        state_patch={
            "frontend_bundle": aggregate_bundle,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Frontend Builder",
                "objective": "Translate the selected design into a resilient UI composition.",
                "candidate_skills": ["frontend-implementation", "responsive-ui"],
                "selected_skills": ["frontend-implementation", "responsive-ui"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Favor responsive structure and clear operator hierarchy.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_backend_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    selected_features = _selected_feature_names(state)
    node_context = _development_runtime_node_context(node_id, state)
    focus_work_unit_ids = {
        str(item).strip()
        for item in _as_list(node_context.get("focus_work_unit_ids"))
        if str(item).strip()
    }
    planning_context = _as_dict(_as_dict(state.get("analysis")).get("planning_context"))
    delivery_plan = _as_dict(state.get("delivery_plan"))
    assigned_packages = [
        dict(item)
        for item in _as_list(delivery_plan.get("work_packages"))
        if isinstance(item, dict)
        and str(item.get("lane", "")) == "backend-builder"
        and (
            not focus_work_unit_ids
            or str(item.get("id") or "").strip() in focus_work_unit_ids
        )
    ]
    assigned_work_units = [
        dict(item)
        for item in _as_list(delivery_plan.get("work_unit_contracts"))
        if isinstance(item, dict)
        and str(item.get("lane", "")) == "backend-builder"
        and (
            not focus_work_unit_ids
            or str(item.get("work_package_id") or item.get("id") or "").strip() in focus_work_unit_ids
        )
    ]
    wave_rows = [
        dict(item)
        for item in _as_list(delivery_plan.get("waves"))
        if isinstance(item, dict)
        and (
            (
                node_context.get("wave_index") is not None
                and int(item.get("wave_index", -1) or -1) == int(node_context.get("wave_index", -2) or -2)
            )
            or any(
                str(unit.get("work_package_id") or "").strip() in set(_as_list(item.get("work_unit_ids")))
                for unit in assigned_work_units
            )
        )
    ]
    decision_context = _decision_context_from_state(state, compact=True)
    decision_scope = _decision_scope_for_phase(state, phase="development")
    payload = {
        "entities": [
            {"name": "LifecycleProject", "fields": ["phaseStatuses", "artifacts", "releases", "feedbackItems"]},
            {"name": "PhaseArtifact", "fields": ["phase", "kind", "summary", "createdAt"]},
        ],
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/control-plane",
                "description": "Return the delivery control-plane snapshot for route bindings and lane status.",
                "authRequired": True,
            },
            {
                "method": "POST",
                "path": "/api/approval/decision",
                "description": "Persist the operator approval or rework decision for the current milestone packet.",
                "authRequired": True,
            },
            {
                "method": "POST",
                "path": "/api/releases/promote",
                "description": "Promote the validated build into the deploy handoff once gates pass.",
                "authRequired": True,
            },
        ],
        "automation_notes": [
            "Persist project record as control-plane surface record.",
            "Derive release gates from build artifact checks.",
        ],
        "exposed_capabilities": selected_features,
        "decision_scope": decision_scope,
        "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
        "assigned_packages": assigned_packages,
        "assigned_work_units": assigned_work_units,
        "wave_plan": wave_rows,
        "shift_left_plan": _as_dict(delivery_plan.get("shift_left_plan")),
        "runtime_node": node_context,
    }

    def _patched_backend_state(bundle_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        execution = _updated_development_execution(state, "backend_bundles", node_id, bundle_payload)
        aggregate_state = {**state, "development_execution": execution}
        aggregate_bundle = _aggregate_backend_bundle(aggregate_state)
        return execution, aggregate_bundle

    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Choose the backend/domain skills that keep the implementation durable and operable.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-backend-plan",
                static_instruction=(
                    "You are a principal backend architect. Return JSON only. "
                    "Design a durable domain model and execution contract for the requested product. "
                    "Preserve access policy, authRequired truth, auditability, and explicit development standards."
                ),
                user_prompt=(
                    "Return JSON with keys entities, automation_notes, exposed_capabilities, api_endpoints.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {selected_features}\n"
                    f"Planning context: {planning_context}\n"
                    f"Roles: {_as_list(_as_dict(state.get('analysis')).get('roles'))}\n"
                    f"Design tokens: {_as_dict(_as_dict(state.get('analysis')).get('design_tokens'))}\n"
                    f"Decision context: {decision_context}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Assigned delivery packages: {assigned_packages}\n"
                    f"Assigned work-unit contracts: {assigned_work_units}\n"
                    f"Wave plan: {wave_rows}\n"
                    f"Shift-left plan: {_as_dict(delivery_plan.get('shift_left_plan'))}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    "Process work in dependency order and keep failures local to the same work unit before asking for broader replanning.\n"
                    "Protected endpoints must keep authRequired markers and remain consistent with the access policy contract.\n"
                ),
                phase="development",
                node_id=node_id,
            )
            if not isinstance(llm_payload, dict):
                execution, aggregate_bundle = _patched_backend_state(payload)
                return NodeResult(
                    state_patch={
                        "backend_bundle": aggregate_bundle,
                        _skill_plan_state_key(node_id): collaboration_plan,
                        _delegation_state_key(node_id): [],
                    },
                    llm_events=[*plan_events, *llm_events],
                    metrics={"backend_mode": "provider-backed-fallback"},
                )
            llm_bundle = {
                "entities": [dict(item) for item in _as_list(llm_payload.get("entities")) if isinstance(item, dict)] or payload["entities"],
                "automation_notes": [str(item) for item in _as_list(llm_payload.get("automation_notes")) if str(item).strip()] or payload["automation_notes"],
                "exposed_capabilities": [str(item) for item in _as_list(llm_payload.get("exposed_capabilities")) if str(item).strip()] or selected_features,
                "api_endpoints": [dict(item) for item in _as_list(llm_payload.get("api_endpoints")) if isinstance(item, dict)],
                "decision_scope": decision_scope,
                "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
                "assigned_packages": assigned_packages,
                "assigned_work_units": assigned_work_units,
                "wave_plan": wave_rows,
                "shift_left_plan": _as_dict(delivery_plan.get("shift_left_plan")),
                "runtime_node": node_context,
            }
            execution, aggregate_bundle = _patched_backend_state(llm_bundle)
            return NodeResult(
                state_patch={
                    "backend_bundle": aggregate_bundle,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                llm_events=[*plan_events, *llm_events],
                metrics={"backend_mode": "provider-backed-autonomous"},
            )

        return autonomous()
    execution, aggregate_bundle = _patched_backend_state(payload)
    return NodeResult(
        state_patch={
            "backend_bundle": aggregate_bundle,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Backend Builder",
                "objective": "Model a durable backend contract for lifecycle delivery.",
                "candidate_skills": ["api-design", "domain-modeling"],
                "selected_skills": ["api-design", "domain-modeling"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Prioritize durable entities and a truthful API contract.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_integrator_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    node_context = _development_runtime_node_context(node_id, state)
    analysis = _as_dict(state.get("analysis"))
    planning_context = _as_dict(analysis.get("planning_context"))
    selected_design = _as_dict(state.get("selected_design")) or _selected_design_from_state(state)
    selected_features = _selected_feature_names(state)
    decision_context = _decision_context_from_state(state, compact=True)
    decision_scope = _decision_scope_for_phase(state, phase="development", selected_design=selected_design)
    prototype = _as_dict(selected_design.get("prototype")) or _build_design_prototype(
        spec=str(state.get("spec", "")),
        analysis=analysis,
        selected_features=selected_features,
        pattern_name=str(selected_design.get("pattern_name") or "Integrated prototype"),
        description=str(selected_design.get("description") or "Integrated build artifact"),
    )
    design_tokens = _as_dict(analysis.get("design_tokens"))
    delivery_plan = _as_dict(state.get("delivery_plan"))
    frontend_bundle = _aggregate_frontend_bundle(state)
    backend_bundle = _aggregate_backend_bundle(state)
    primary_color = _color_or(selected_design.get("primary_color"), _color_or(_as_dict(design_tokens.get("colors")).get("primary"), "#0f172a"))
    accent_color = _color_or(selected_design.get("accent_color"), _color_or(_as_dict(design_tokens.get("colors")).get("cta"), "#10b981"))
    feature_cards = _as_list(frontend_bundle.get("feature_cards"))
    frontend_sections = _as_list(frontend_bundle.get("sections"))
    interaction_notes = [str(item) for item in _as_list(frontend_bundle.get("interaction_notes")) if str(item).strip()]
    backend_entities = _as_list(backend_bundle.get("entities"))
    code = _build_preview_html(
        title=_preview_title(str(state.get("spec", ""))),
        subtitle=str(selected_design.get("description") or "Integrated build artifact aligned to the selected prototype."),
        primary=primary_color,
        accent=accent_color,
        features=[str(item) for item in feature_cards if isinstance(item, str)] or selected_features,
        prototype=prototype,
        design_tokens=design_tokens,
        backend_entities=[dict(item) for item in backend_entities if isinstance(item, dict)],
        milestones=[dict(item) for item in state.get("milestones", []) if isinstance(item, dict)],
        interaction_notes=interaction_notes,
        section_focus=[str(item) for item in frontend_sections if str(item).strip()],
        mode="build",
    )
    payload = {
        "code": code,
        "build_sections": frontend_sections or [str(screen.get("id") or "") for screen in _as_list(prototype.get("screens")) if isinstance(screen, dict)],
        "prototype": prototype,
        "decision_scope": decision_scope,
        "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
        "delivery_plan": delivery_plan,
        "runtime_node": node_context,
    }

    def _updated_delivery_plan() -> dict[str, Any]:
        refined_code_workspace = refine_development_code_workspace(
            code_workspace=_as_dict(delivery_plan.get("code_workspace")),
            spec=str(state.get("spec") or ""),
            selected_features=selected_features,
            selected_design=selected_design,
            frontend_bundle=frontend_bundle,
            backend_bundle=backend_bundle,
            delivery_plan=delivery_plan,
            milestones=[dict(item) for item in _as_list(state.get("milestones")) if isinstance(item, dict)],
            technical_design=normalize_technical_design_bundle(_as_dict(state.get("technicalDesign"))),
            planning_analysis=_as_dict(state.get("analysis")),
        )
        refreshed_spec_audit = build_development_spec_audit(
            selected_features=selected_features,
            requirements=normalize_requirements_bundle(_as_dict(state.get("requirements"))),
            task_decomposition=normalize_task_decomposition(_as_dict(state.get("taskDecomposition"))),
            dcs_analysis=normalize_dcs_analysis(_as_dict(state.get("dcsAnalysis"))),
            technical_design=normalize_technical_design_bundle(_as_dict(state.get("technicalDesign"))),
            reverse_engineering=normalize_reverse_engineering_result(_as_dict(state.get("reverseEngineering"))),
            code_workspace=refined_code_workspace,
            selected_design=selected_design,
            planning_analysis=_as_dict(state.get("analysis")),
            delivery_plan_context=delivery_plan,
        )
        updated_plan = dict(delivery_plan)
        updated_plan["code_workspace"] = refined_code_workspace
        updated_plan["spec_audit"] = refreshed_spec_audit
        return _annotate_development_delivery_plan_lineage(
            updated_plan,
            decision_context_fingerprint=str(decision_context.get("fingerprint") or ""),
        )

    def _patched_integrated_state(integrated_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        execution = _updated_development_execution(state, "integrated_builds", node_id, integrated_payload)
        return execution, integrated_payload

    if _provider_backed_lifecycle_available(provider_registry):
        async def autonomous() -> NodeResult:
            collaboration_plan, plan_events = await _plan_node_collaboration(
                phase="development",
                node_id=node_id,
                state=state,
                objective="Assemble a single-file build artifact that is coherent, accessible, and reviewable.",
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
            )
            llm_payload, llm_events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose="lifecycle-development-integrate",
                static_instruction=(
                    "You are an autonomous product engineer. Return JSON only. "
                    "Produce a single-file HTML app with embedded CSS and JS, strong accessibility, responsive behavior, "
                    "and product-prototype fidelity. The build must remain compliant with design tokens, access policy, "
                    "audit / operability contracts, and the standard development rules."
                ),
                user_prompt=(
                    "Return JSON with keys code, build_sections, implementation_notes.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Planning context: {planning_context}\n"
                    f"Design tokens: {_as_dict(_as_dict(state.get('analysis')).get('design_tokens'))}\n"
                    f"Roles: {_as_list(_as_dict(state.get('analysis')).get('roles'))}\n"
                    f"Decision context: {decision_context}\n"
                    f"Selected design: {selected_design}\n"
                    f"Prototype blueprint: {prototype}\n"
                    f"Delivery plan: {delivery_plan}\n"
                    f"Frontend bundle: {frontend_bundle}\n"
                    f"Backend bundle: {backend_bundle}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    "The code must be previewable HTML, include <main>, aria labels for primary actions, "
                    "a viewport meta tag, real application navigation, and multiple prototype screen surfaces. "
                    "Do not return a landing page or hero-only layout. "
                    "Do not introduce one-off visual tokens or bypass the access / audit contracts."
                ),
                phase="development",
                node_id=node_id,
            )
            llm_code = str(_as_dict(llm_payload).get("code") or "")
            llm_sections = [str(item) for item in _as_list(_as_dict(llm_payload).get("build_sections")) if str(item).strip()] or frontend_sections
            integrated_code = llm_code if _looks_like_prototype_html(llm_code) else code
            updated_delivery_plan = _updated_delivery_plan()
            integrated_payload = {
                "code": integrated_code,
                "build_sections": llm_sections,
                "prototype": prototype,
                "decision_scope": decision_scope,
                "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
                "delivery_plan": updated_delivery_plan,
                "runtime_node": node_context,
            }
            execution, integrated_payload = _patched_integrated_state(integrated_payload)
            return NodeResult(
                state_patch={
                    "integrated_build": integrated_payload,
                    "code": integrated_code,
                    "delivery_plan": updated_delivery_plan,
                    "development_execution": execution,
                    _skill_plan_state_key(node_id): collaboration_plan,
                    _delegation_state_key(node_id): [],
                },
                artifacts=_artifacts({"name": "build-artifact", "kind": "development", "code_bytes": len(integrated_code.encode('utf-8'))}),
                llm_events=[*plan_events, *llm_events],
                metrics={"integrator_mode": "provider-backed-autonomous" if integrated_code == llm_code else "provider-backed-fallback"},
            )

        return autonomous()
    updated_delivery_plan = _updated_delivery_plan()
    payload["delivery_plan"] = updated_delivery_plan
    execution, payload = _patched_integrated_state(payload)
    return NodeResult(
        state_patch={
            "integrated_build": payload,
            "code": code,
            "delivery_plan": updated_delivery_plan,
            "development_execution": execution,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Integrator",
                "objective": "Assemble a previewable and reviewable artifact.",
                "candidate_skills": ["integration", "artifact-assembly"],
                "selected_skills": ["integration", "artifact-assembly"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Integrate frontend and backend outputs into one coherent artifact.",
            },
            _delegation_state_key(node_id): [],
        },
        artifacts=_artifacts({"name": "build-artifact", "kind": "development", "code_bytes": len(code.encode('utf-8'))}),
    )


def _development_repo_executor_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    node_context = _development_runtime_node_context(node_id, state)
    delivery_plan = _as_dict(state.get("delivery_plan"))
    code_workspace = _as_dict(delivery_plan.get("code_workspace"))
    spec_audit = _as_dict(delivery_plan.get("spec_audit"))
    project_key = _slug(str(state.get("project_key") or state.get("slug") or state.get("spec") or "project"), prefix="project")
    if not code_workspace:
        repo_execution = {
            "mode": "unavailable",
            "workspace_path": "",
            "worktree_path": None,
            "repo_root": None,
            "materialized_file_count": 0,
            "install": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "build": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "test": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "ready": False,
            "errors": ["Code workspace is missing; repo execution cannot start."],
        }
    elif str(spec_audit.get("status") or "") != "ready_for_autonomous_build":
        repo_execution = {
            "mode": "blocked_by_spec_audit",
            "workspace_path": "",
            "worktree_path": None,
            "repo_root": None,
            "materialized_file_count": 0,
            "install": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "build": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "test": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
            "ready": False,
            "errors": [
                "Spec audit is not closed; repo execution was blocked.",
                *[
                    str(_as_dict(item).get("title") or "")
                    for item in _as_list(spec_audit.get("unresolved_gaps"))
                    if str(_as_dict(item).get("severity") or "") in {"critical", "high"}
                    and str(_as_dict(item).get("title") or "").strip()
                ],
            ],
        }
    else:
        try:
            repo_execution = execute_development_code_workspace(
                project_key=project_key,
                github_repo=state.get("githubRepo"),
                code_workspace=code_workspace,
            )
        except Exception as exc:
            repo_execution = {
                "mode": "execution_error",
                "workspace_path": "",
                "worktree_path": None,
                "repo_root": None,
                "materialized_file_count": 0,
                "install": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
                "build": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
                "test": {"status": "skipped", "command": "", "exit_code": None, "duration_ms": 0, "stdout_tail": "", "stderr_tail": ""},
                "ready": False,
                "errors": [str(exc) or "Repo execution failed unexpectedly."],
            }
    updated_delivery_plan = dict(delivery_plan)
    updated_delivery_plan["repo_execution"] = repo_execution
    execution = _updated_development_execution(
        state,
        "repo_executions",
        node_id,
        {
            **repo_execution,
            "runtime_node": node_context,
        },
    )
    return NodeResult(
        state_patch={
            "delivery_plan": updated_delivery_plan,
            "repo_execution": repo_execution,
            "development_execution": execution,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Repo Executor",
                "objective": "Materialize the code workspace into a real repo/worktree and verify install/build/test.",
                "candidate_skills": ["repo-materialization", "build-verification"],
                "selected_skills": ["repo-materialization", "build-verification"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Trust actual file materialization and command results over speculative readiness.",
            },
            _delegation_state_key(node_id): [],
        },
        artifacts=_artifacts(
            {
                "name": "repo-execution",
                "kind": "development",
                "mode": str(repo_execution.get("mode") or "unknown"),
                "ready": repo_execution.get("ready") is True,
                "materialized_file_count": int(repo_execution.get("materialized_file_count", 0) or 0),
                "workspace_path": str(repo_execution.get("workspace_path") or ""),
                "build_status": str(_as_dict(repo_execution.get("build")).get("status") or "unknown"),
                "test_status": str(_as_dict(repo_execution.get("test")).get("status") or "unknown"),
                "errors": [str(item) for item in _as_list(repo_execution.get("errors")) if str(item).strip()],
            }
        ),
        metrics={
            "repo_execution_ready": repo_execution.get("ready") is True,
            "repo_execution_mode": str(repo_execution.get("mode") or "unknown"),
        },
    )


def _development_qa_handler(node_id: str, state: dict[str, Any]) -> NodeResult:
    node_context = _development_runtime_node_context(node_id, state)
    focus_work_unit_ids = {
        str(item).strip()
        for item in _as_list(node_context.get("focus_work_unit_ids"))
        if str(item).strip()
    }
    build = _as_dict(state.get("integrated_build"))
    code = str(build.get("code", ""))
    delivery_plan = _as_dict(state.get("delivery_plan"))
    milestones = []
    for raw in state.get("milestones", []) or []:
        if not isinstance(raw, dict):
            continue
        criteria = str(raw.get("criteria", ""))
        score = _milestone_score(criteria, code)
        milestones.append(
            {
                "id": str(raw.get("id", "")),
                "name": str(raw.get("name", "")),
                "status": "satisfied" if score >= 0.6 else "not_satisfied",
                "reason": "Build contains the required structural signals." if score >= 0.6 else "Criteria is only partially represented in the current build artifact.",
            }
        )
    if not milestones:
        milestones.append(
            {
                "id": "alpha-default",
                "name": "Alpha readiness",
                "status": "satisfied" if "<html" in code.lower() else "not_satisfied",
                "reason": "Generated build is previewable and structurally complete." if "<html" in code.lower() else "No previewable build artifact was generated.",
            }
        )
    work_unit_results = []
    wave_totals: dict[int, dict[str, int]] = {}
    for raw_unit in _as_list(delivery_plan.get("work_unit_contracts")):
        unit = _as_dict(raw_unit)
        unit_id = str(unit.get("work_package_id") or unit.get("id") or "").strip()
        if focus_work_unit_ids and unit_id not in focus_work_unit_ids:
            continue
        acceptance = [
            str(item).strip()
            for item in _as_list(unit.get("acceptance_criteria"))
            if str(item).strip()
        ]
        checks = acceptance or [
            str(item).strip()
            for item in _as_list(unit.get("qa_checks"))
            if str(item).strip()
        ]
        scores = [_milestone_score(check, code) for check in checks[:3]]
        score = max(scores) if scores else (1.0 if "<html" in code.lower() else 0.0)
        wave_index = int(unit.get("wave_index", 0) or 0)
        status = "satisfied" if score >= 0.55 else "not_satisfied"
        work_unit_results.append(
            {
                "id": unit_id,
                "wave_index": wave_index,
                "lane": str(unit.get("lane") or "").strip(),
                "status": status,
                "reason": (
                    "The integrated build still reflects the unit acceptance and QA signals."
                    if status == "satisfied"
                    else "The integrated build does not yet satisfy this work unit's local acceptance checks."
                ),
            }
        )
        wave_entry = wave_totals.setdefault(wave_index, {"satisfied": 0, "total": 0})
        wave_entry["total"] += 1
        if status == "satisfied":
            wave_entry["satisfied"] += 1
    wave_results = [
        {
            "wave_index": wave_index,
            "status": "satisfied" if counts["total"] > 0 and counts["satisfied"] == counts["total"] else "not_satisfied",
            "satisfied": counts["satisfied"],
            "total": counts["total"],
        }
        for wave_index, counts in sorted(wave_totals.items())
    ]
    current_report = {
        "milestone_results": milestones,
        "work_unit_results": work_unit_results,
        "wave_results": wave_results,
        "runtime_node": node_context,
    }
    execution = _updated_development_execution(state, "qa_reports", node_id, current_report)
    aggregate_report = _aggregate_qa_report({**state, "development_execution": execution})
    return NodeResult(
        state_patch={
            "qa_report": aggregate_report,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "QA Engineer",
                "objective": "Validate milestone and acceptance readiness.",
                "candidate_skills": ["acceptance-testing", "quality-assurance"],
                "selected_skills": ["acceptance-testing", "quality-assurance"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Convert milestone criteria into explicit acceptance checks.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_security_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    node_context = _development_runtime_node_context(node_id, state)
    focus_work_unit_ids = {
        str(item).strip()
        for item in _as_list(node_context.get("focus_work_unit_ids"))
        if str(item).strip()
    }
    code = str(_as_dict(state.get("integrated_build")).get("code", ""))
    delivery_plan = _as_dict(state.get("delivery_plan"))
    findings = []
    if "eval(" in code:
        findings.append("Avoid eval() in generated artifacts.")
    if "innerHTML =" in code:
        findings.append("Prefer DOM-safe rendering over innerHTML assignment.")
    if not findings:
        findings.append("No obvious unsafe DOM execution pattern was detected.")
    status = "pass" if len(findings) == 1 and findings[0].startswith("No obvious") else "warning"

    async def autonomous() -> NodeResult:
        collaboration_plan, plan_events = await _plan_node_collaboration(
            phase="development",
            node_id=node_id,
            state=state,
            objective="Escalate security and safe-autonomy review to the right peer when it materially improves release confidence.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        delegations: list[dict[str, Any]] = []
        peer_feedback: list[dict[str, Any]] = []
        for delegation in _as_list(collaboration_plan.get("delegations"))[:2]:
            delegated = await _delegate_to_lifecycle_peer(
                phase="development",
                node_id=node_id,
                peer_name=str(_as_dict(delegation).get("peer", "")),
                skill_name=str(_as_dict(delegation).get("skill", "")),
                artifact_payload={"code": code},
                reason=str(_as_dict(delegation).get("reason", "")),
                quality_targets=[str(item) for item in _as_list(collaboration_plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        merged_blockers = _dedupe_strings(
            findings + [
                str(item)
                for feedback in peer_feedback
                for item in _as_list(_as_dict(feedback).get("blockers"))
                if str(item).strip() and not _is_non_blocking_review_finding(item)
            ]
        )
        merged_recommendations = _dedupe_strings(
            [
                str(item)
                for feedback in peer_feedback
                for item in _as_list(_as_dict(feedback).get("recommendations"))
                if str(item).strip()
            ]
        )
        work_unit_results = [
            {
                "id": str(_as_dict(unit).get("work_package_id") or _as_dict(unit).get("id") or "").strip(),
                "wave_index": int(_as_dict(unit).get("wave_index", 0) or 0),
                "status": "pass" if not merged_blockers else "warning",
                "checks": [str(item).strip() for item in _as_list(_as_dict(unit).get("security_checks")) if str(item).strip()],
            }
            for unit in _as_list(delivery_plan.get("work_unit_contracts"))
            if isinstance(unit, dict)
            and (
                not focus_work_unit_ids
                or str(_as_dict(unit).get("work_package_id") or _as_dict(unit).get("id") or "").strip() in focus_work_unit_ids
            )
        ]
        current_report = {
            "status": "pass" if not merged_blockers else "warning",
            "findings": merged_blockers or findings,
            "blockers": merged_blockers,
            "recommendations": merged_recommendations,
            "work_unit_results": work_unit_results,
            "runtime_node": node_context,
        }
        execution = _updated_development_execution(state, "security_reports", node_id, current_report)
        security_report = _aggregate_security_report({**state, "development_execution": execution})
        return NodeResult(
            state_patch={
                "security_report": security_report,
                _skill_plan_state_key(node_id): collaboration_plan,
                _delegation_state_key(node_id): delegations,
                _peer_feedback_state_key(node_id): peer_feedback,
            },
            artifacts=_artifacts(
                {"name": f"{node_id}-skill-plan", "kind": "skill-plan", **collaboration_plan},
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegations
                ],
            ),
            llm_events=plan_events,
            metrics={"security_mode": "provider-backed-autonomous" if delegations else "provider-backed-fallback"},
        )

    if _provider_backed_lifecycle_available(provider_registry):
        return autonomous()
    work_unit_results = [
        {
            "id": str(_as_dict(unit).get("work_package_id") or _as_dict(unit).get("id") or "").strip(),
            "wave_index": int(_as_dict(unit).get("wave_index", 0) or 0),
            "status": status,
            "checks": [str(item).strip() for item in _as_list(_as_dict(unit).get("security_checks")) if str(item).strip()],
        }
        for unit in _as_list(delivery_plan.get("work_unit_contracts"))
        if isinstance(unit, dict)
        and (
            not focus_work_unit_ids
            or str(_as_dict(unit).get("work_package_id") or _as_dict(unit).get("id") or "").strip() in focus_work_unit_ids
        )
    ]
    current_report = {
        "status": status,
        "findings": findings,
        "blockers": [item for item in findings if not item.startswith("No obvious")],
        "recommendations": [],
        "work_unit_results": work_unit_results,
        "runtime_node": node_context,
    }
    execution = _updated_development_execution(state, "security_reports", node_id, current_report)
    security_report = _aggregate_security_report({**state, "development_execution": execution})
    return NodeResult(
        state_patch={
            "security_report": security_report,
            _skill_plan_state_key(node_id): {
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Security Reviewer",
                "objective": "Protect the release from obvious safety and security regressions.",
                "candidate_skills": ["security-review", "safety-review"],
                "selected_skills": ["security-review", "safety-review"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [{"peer": "safety-guardian", "skill": "security-review", "reason": "Escalate security posture when external scrutiny is useful."}],
                "mode": "deterministic-reference",
                "execution_note": "Check unsafe DOM patterns before release.",
            },
            _delegation_state_key(node_id): [],
        }
    )


def _development_reviewer_handler(
    node_id: str,
    state: dict[str, Any],
    *,
    provider_registry: ProviderRegistry | None = None,
    llm_runtime: LLMRuntime | None = None,
) -> NodeResult:
    node_context = _development_runtime_node_context(node_id, state)
    is_final_review = str(node_context.get("stage") or "") == "final_review" or node_id == "reviewer"
    build = _as_dict(state.get("integrated_build"))
    qa_report = _as_dict(state.get("qa_report"))
    security_report = _as_dict(state.get("security_report"))
    decision_context = _decision_context_from_state(state, compact=True)
    decision_scope = _decision_scope_for_phase(
        state,
        phase="development",
        selected_design=_as_dict(state.get("selected_design")) or _selected_design_from_state(state),
    )
    initial_code = str(build.get("code", ""))
    build_sections = [str(item) for item in _as_list(build.get("build_sections")) if str(item).strip()]

    def finalize(
        *,
        code: str,
        snapshot: dict[str, Any],
        iteration_count: int,
        llm_events: list[dict[str, Any]] | None = None,
        critique_history: list[dict[str, Any]] | None = None,
        collaboration_plan: dict[str, Any] | None = None,
        delegations: list[dict[str, Any]] | None = None,
        peer_feedback: list[dict[str, Any]] | None = None,
        mode: str,
    ) -> NodeResult:
        llm_event_log = list(llm_events or [])
        plan = dict(collaboration_plan or {})
        delegation_records = list(delegations or [])
        peer_reviews = list(peer_feedback or [])
        review_milestones = [dict(item) for item in _as_list(snapshot.get("milestone_results"))]
        review_work_units = [dict(item) for item in _as_list(snapshot.get("work_unit_results")) if isinstance(item, dict)]
        review_waves = [dict(item) for item in _as_list(_as_dict(state.get("qa_report")).get("wave_results")) if isinstance(item, dict)]
        review_security = _as_dict(snapshot.get("security_report"))
        repo_execution = _as_dict(snapshot.get("repo_execution_report")) or _as_dict(state.get("repo_execution"))
        delivery_plan = _as_dict(state.get("delivery_plan")) or _build_development_delivery_plan(
            state,
            selected_design=_as_dict(state.get("selected_design")) or _selected_design_from_state(state),
            implementation_plan=_as_dict(state.get("implementation_plan")),
        )
        critical_lookup = {str(item) for item in _as_list(delivery_plan.get("critical_path")) if str(item).strip()}
        unresolved_blockers = [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()]
        delivery_plan["work_packages"] = [
            {
                **dict(item),
                "status": (
                    "completed"
                    if not unresolved_blockers
                    else "blocked" if str(_as_dict(item).get("id", "")) in critical_lookup else "completed"
                ),
            }
            for item in _as_list(delivery_plan.get("work_packages"))
            if isinstance(item, dict)
        ]
        development_handoff = _build_development_handoff(
            state=state,
            delivery_plan=delivery_plan,
            snapshot={
                **snapshot,
                "milestone_results": review_milestones,
                "security_report": review_security,
            },
        )
        estimated_cost = round(
            0.9
            + len(_selected_feature_names(state)) * 0.08
            + len(review_milestones) * 0.04
            + sum(float(_as_dict(item).get("estimated_cost_usd", 0.0) or 0.0) for item in llm_event_log),
            3,
        )
        development = {
            "code": code,
            "milestone_results": review_milestones,
            "work_unit_results": review_work_units,
            "wave_results": review_waves,
            "decision_scope": decision_scope,
            "decision_context_fingerprint": str(decision_context.get("fingerprint") or ""),
            "review_summary": {
                "milestonesSatisfied": int(snapshot.get("milestones_satisfied", 0) or 0),
                "milestonesTotal": int(snapshot.get("milestones_total", len(review_milestones)) or len(review_milestones)),
                "securityStatus": str(review_security.get("status", "pass") or "pass"),
                "blockerCount": len(_as_list(snapshot.get("blockers"))),
                "deployReadiness": str(development_handoff.get("readiness_status", "needs_rework")),
                "repoExecutionReady": repo_execution.get("ready") is True,
            },
            "delivery_plan": delivery_plan,
            "handoff": development_handoff,
            "repo_execution": repo_execution,
        }
        if critique_history:
            development["critique_history"] = critique_history
        if peer_reviews:
            development["peer_feedback"] = peer_reviews
        integrated_build = dict(build)
        integrated_build["code"] = code
        integrated_build["decision_scope"] = decision_scope
        integrated_build["decision_context_fingerprint"] = str(decision_context.get("fingerprint") or "")
        if build_sections:
            integrated_build["build_sections"] = build_sections
        artifact_payload = {"name": "milestone-report", "kind": "development", **development}
        execution = _updated_development_execution(
            state,
            "reviews",
            node_id,
            {
                "runtime_node": node_context,
                "review_summary": dict(development.get("review_summary", {})),
                "handoff": development_handoff,
                "blockers": [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()],
                "mode": mode,
            },
        )
        return NodeResult(
            state_patch={
                "integrated_build": integrated_build,
                "code": code,
                "qa_report": {
                    "milestone_results": review_milestones,
                    "work_unit_results": review_work_units,
                    "wave_results": review_waves,
                },
                "security_report": review_security,
                "development": development,
                "delivery_plan": delivery_plan,
                "development_handoff": development_handoff,
                "development_execution": execution,
                "review": development,
                "_build_iteration": iteration_count,
                "estimated_cost_usd": estimated_cost,
                "output": development,
                _skill_plan_state_key(node_id): plan,
                _delegation_state_key(node_id): delegation_records,
                _peer_feedback_state_key(node_id): peer_reviews,
            },
            artifacts=_artifacts(
                artifact_payload,
                {"name": "deploy-handoff", "kind": "development", **development_handoff},
                *([{"name": f"{node_id}-skill-plan", "kind": "skill-plan", **plan}] if plan else []),
                *[
                    {
                        "name": f"{node_id}-{str(item.get('peer', 'peer'))}-review",
                        "kind": "peer-review",
                        **_as_dict(item.get("feedback")),
                    }
                    for item in delegation_records
                ],
            ),
            llm_events=llm_event_log,
            metrics={"review_mode": mode},
        )

    baseline_snapshot = _development_quality_snapshot(state, code=initial_code)
    if qa_report.get("milestone_results"):
        baseline_snapshot["milestone_results"] = list(qa_report.get("milestone_results", []))
        baseline_snapshot["milestones_satisfied"] = sum(
            1 for item in baseline_snapshot["milestone_results"] if _as_dict(item).get("status") == "satisfied"
        )
        baseline_snapshot["milestones_total"] = len(baseline_snapshot["milestone_results"])
    if qa_report.get("work_unit_results"):
        baseline_snapshot["work_unit_results"] = list(qa_report.get("work_unit_results", []))
        baseline_snapshot["blockers"] = [
            *[
                item
                for item in _as_list(baseline_snapshot.get("blockers"))
                if isinstance(item, str) and not item.startswith("Work unit not satisfied:")
            ],
            *[
                f"Work unit not satisfied: {str(_as_dict(item).get('id') or '').strip()}"
                for item in _as_list(qa_report.get("work_unit_results"))
                if _as_dict(item).get("status") != "satisfied"
                and str(_as_dict(item).get("id") or "").strip()
            ],
        ]
    if security_report:
        baseline_snapshot["security_report"] = security_report
        if security_report.get("status") == "pass":
            baseline_snapshot["blockers"] = [
                item
                for item in _as_list(baseline_snapshot.get("blockers"))
                if isinstance(item, str) and item not in _as_list(security_report.get("findings"))
            ]
    if not is_final_review:
        wave_review = {
            "node_id": node_id,
            "wave_index": node_context.get("wave_index"),
            "work_unit_ids": [
                str(item).strip()
                for item in _as_list(node_context.get("work_unit_ids"))
                if str(item).strip()
            ],
            "focus_work_unit_ids": [
                str(item).strip()
                for item in _as_list(node_context.get("focus_work_unit_ids"))
                if str(item).strip()
            ],
            "ready": not [str(item) for item in _as_list(baseline_snapshot.get("blockers")) if str(item).strip()],
            "blockers": [str(item) for item in _as_list(baseline_snapshot.get("blockers")) if str(item).strip()],
            "milestones_satisfied": int(baseline_snapshot.get("milestones_satisfied", 0) or 0),
            "milestones_total": int(baseline_snapshot.get("milestones_total", 0) or 0),
            "security_status": str(_as_dict(baseline_snapshot.get("security_report")).get("status") or "pass"),
        }
        execution = _updated_development_execution(state, "reviews", node_id, wave_review)
        return NodeResult(
            state_patch={
                "development_execution": execution,
                "wave_review": wave_review,
                _skill_plan_state_key(node_id): {
                    "phase": "development",
                    "node_id": node_id,
                    "agent_label": "Wave Reviewer",
                    "objective": "Close the current wave before unlocking downstream work.",
                    "candidate_skills": ["delivery-review", "policy-review"],
                    "selected_skills": ["delivery-review", "policy-review"],
                    "quality_targets": _phase_quality_targets("development"),
                    "delegations": [],
                    "mode": "deterministic-wave-gate",
                    "execution_note": "Keep validation local to the current wave and expose unresolved blockers immediately.",
                },
                _delegation_state_key(node_id): [],
            },
            artifacts=_artifacts({"name": "wave-review", "kind": "development", **wave_review}),
            metrics={"review_mode": "wave-gate"},
        )
    if not _provider_backed_lifecycle_available(provider_registry):
        return finalize(
            code=initial_code,
            snapshot=baseline_snapshot,
            iteration_count=1 if int(baseline_snapshot.get("milestones_satisfied", 0) or 0) == int(baseline_snapshot.get("milestones_total", 0) or 0) else 2,
            collaboration_plan={
                "phase": "development",
                "node_id": node_id,
                "agent_label": "Release Reviewer",
                "objective": "Judge release readiness and push the build over the quality bar.",
                "candidate_skills": ["code-review", "delivery-review"],
                "selected_skills": ["code-review", "delivery-review"],
                "quality_targets": _phase_quality_targets("development"),
                "delegations": [],
                "mode": "deterministic-reference",
                "execution_note": "Review the integrated build against milestones and release quality gates.",
            },
            mode="deterministic-reference",
        )

    async def autonomous() -> NodeResult:
        collaboration_plan, plan_events = await _plan_node_collaboration(
            phase="development",
            node_id=node_id,
            state=state,
            objective="Use the minimum skill set and the right peers to raise release quality before final approval.",
            provider_registry=provider_registry,
            llm_runtime=llm_runtime,
        )
        current_code = initial_code
        snapshot = baseline_snapshot
        critique_history: list[dict[str, Any]] = []
        llm_events: list[dict[str, Any]] = list(plan_events)
        delegations: list[dict[str, Any]] = []
        peer_feedback: list[dict[str, Any]] = []
        iteration_count = 1
        max_iterations = 3
        for delegation in _as_list(collaboration_plan.get("delegations"))[:2]:
            delegated = await _delegate_to_lifecycle_peer(
                phase="development",
                node_id=node_id,
                peer_name=str(_as_dict(delegation).get("peer", "")),
                skill_name=str(_as_dict(delegation).get("skill", "")),
                artifact_payload={"code": current_code},
                reason=str(_as_dict(delegation).get("reason", "")),
                quality_targets=[str(item) for item in _as_list(collaboration_plan.get("quality_targets")) if str(item).strip()],
            )
            if delegated is None:
                continue
            delegations.append(delegated)
            feedback = _as_dict(delegated.get("feedback"))
            if feedback:
                peer_feedback.append(feedback)
        peer_blockers = [
            str(item)
            for feedback in peer_feedback
            for item in _as_list(_as_dict(feedback).get("blockers"))
            if str(item).strip() and not _is_non_blocking_review_finding(item)
        ]
        if peer_blockers:
            snapshot = dict(snapshot)
            snapshot["blockers"] = _dedupe_strings(
                [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()] + peer_blockers
            )
        while _as_list(snapshot.get("blockers")) and iteration_count <= max_iterations:
            blockers = [str(item) for item in _as_list(snapshot.get("blockers")) if str(item).strip()]
            payload, events, _ = await _lifecycle_llm_json(
                provider_registry=provider_registry,
                llm_runtime=llm_runtime,
                preferred_model=_preferred_lifecycle_model(node_id, provider_registry),
                purpose=f"lifecycle-development-review-{iteration_count}",
                static_instruction=(
                    "You are an autonomous reviewer and reviser for a production-bound single-file app. "
                    "Return JSON only. Improve the build instead of summarizing it. "
                    "Always preserve a complete previewable HTML document with embedded CSS and JS."
                ),
                user_prompt=(
                    "Return JSON with keys code, revision_summary, resolved_blockers, remaining_risks.\n"
                    f"Spec: {state.get('spec')}\n"
                    f"Selected features: {_selected_feature_names(state)}\n"
                    f"Decision context: {decision_context}\n"
                    f"Milestones: {state.get('milestones')}\n"
                    f"Current quality snapshot: {snapshot}\n"
                    f"Peer feedback: {peer_feedback}\n"
                    f"Skill plan: {collaboration_plan}\n"
                    f"Current blockers: {blockers}\n"
                    "Revise the current HTML so the blockers are addressed while improving accessibility, responsive behavior, and clarity.\n"
                    f"Current HTML:\n{current_code}"
                ),
                phase="development",
                node_id=node_id,
            )
            llm_events.extend(events)
            if not isinstance(payload, dict):
                break
            revised_code = str(payload.get("code") or "")
            critique_history.append(
                {
                    "iteration": iteration_count,
                    "blockers": blockers,
                    "revision_summary": str(payload.get("revision_summary") or "No revision summary returned."),
                    "resolved_blockers": [
                        str(item) for item in _as_list(payload.get("resolved_blockers")) if str(item).strip()
                    ],
                    "remaining_risks": [
                        str(item) for item in _as_list(payload.get("remaining_risks")) if str(item).strip()
                    ],
                }
            )
            if "<html" not in revised_code.lower() or "<main" not in revised_code.lower():
                break
            if revised_code.strip() == current_code.strip():
                break
            current_code = revised_code
            snapshot = _development_quality_snapshot(state, code=current_code)
            iteration_count += 1

        mode = "provider-backed-autonomous" if critique_history else "provider-backed-fallback"
        return finalize(
            code=current_code,
            snapshot=snapshot,
            iteration_count=iteration_count,
            llm_events=llm_events,
            critique_history=critique_history,
            collaboration_plan=collaboration_plan,
            delegations=delegations,
            peer_feedback=peer_feedback,
            mode=mode,
        )

    return autonomous()


def _segment_from_spec(spec: str) -> str:
    if _contains_any(spec, "enterprise", "B2B", "業務", "運用"):
        return "B2B"
    if _contains_any(spec, "consumer", "toC", "ユーザー向け", "モバイル"):
        return "B2C"
    return "Product"


def _market_trends(spec: str) -> list[str]:
    trends = [
        "意思決定の根拠を artifact として残す要求が高まっている",
        "単体 AI から orchestrated workflow への移行が進んでいる",
    ]
    if _contains_any(spec, "approval", "承認", "safety", "安全"):
        trends.append("ガバナンス付き自律実行への関心が強い")
    if _contains_any(spec, "dashboard", "運用", "studio"):
        trends.append("operator UI の品質が採用可否を左右する")
    return trends


def _market_size_from_spec(spec: str, keywords: list[str]) -> str:
    if _contains_any(spec, "enterprise", "B2B", "workflow", "platform"):
        return "Mid-market to enterprise orchestration spend with expanding platform budgets"
    if len(keywords) > 8:
        return "Cross-functional delivery tooling budget with clear consolidation pressure"
    return "Early but expanding workflow productivity segment"


def _estimate_use_case_effort_hours(
    use_case: dict[str, Any],
    features: list[dict[str, Any]],
    *,
    preset: str,
    kind: str,
) -> tuple[int, int, int]:
    priority = str(use_case.get("priority", "should") or "should")
    related_features = _use_case_related_features(use_case, features)
    base = {"must": 12, "should": 8, "could": 6}.get(priority, 8)
    base += 2 * sum(
        1 if str(feature.get("implementation_cost", "medium")) == "medium" else 2 if str(feature.get("implementation_cost")) == "high" else 0
        for feature in related_features
    )
    if kind == "operations":
        base += 3
    if preset == "full":
        base = math.ceil(base * 1.2)
    elif preset == "minimal":
        base = max(8, math.ceil(base * 0.82))
    definition = max(2, math.ceil(base * 0.2))
    implementation = max(4, math.ceil(base * 0.58))
    verification = max(2, base - definition - implementation)
    return definition, implementation, verification


def _implementation_assignee(kind: str, preset: str, use_case: dict[str, Any]) -> tuple[str, list[str]]:
    category = str(use_case.get("category", ""))
    if kind == "operations" or any(term in category for term in ("ガバナンス", "品質", "リリース", "プラットフォーム")):
        if preset == "minimal":
            return "planner", ["solution-architecture", "workflow-design"]
        return "backend-builder", ["api-design", "domain-modeling"]
    if any(term in category for term in ("設定", "運営")) and preset != "minimal":
        return "backend-builder", ["configuration-management", "integration"]
    return "frontend-builder", ["responsive-ui", "interaction-design"]


def _verification_assignee(preset: str, use_case: dict[str, Any]) -> tuple[str, list[str]]:
    if preset == "full":
        return "qa-engineer", ["quality-assurance", "acceptance-testing"]
    if "ガバナンス" in str(use_case.get("category", "")) and preset != "minimal":
        return "reviewer", ["delivery-review", "policy-review"]
    return "reviewer", ["acceptance-testing", "delivery-review"]


_ASSIGNEE_DAILY_CAPACITY_HOURS: dict[str, int] = {
    "planner": 6,
    "frontend-builder": 6,
    "backend-builder": 6,
    "qa-engineer": 5,
    "reviewer": 5,
    "security-reviewer": 4,
}

_PLANNING_WORKDAYS_PER_WEEK = 5


def _planning_task_duration_days(effort_hours: int, assignee: str) -> int:
    capacity = _ASSIGNEE_DAILY_CAPACITY_HOURS.get(assignee, 6)
    return max(1, math.ceil(max(effort_hours, 1) / capacity))


def _build_plan_estimates(state: dict[str, Any]) -> list[dict[str, Any]]:
    kind = _infer_product_kind(str(state.get("spec", "")))
    features = _planning_selected_or_default_features(state)
    selected_features = [feature for feature in features if feature.get("selected") is True] or features
    use_cases = _planning_use_cases_from_state(state)
    milestones = _planning_milestones_from_state(state)
    presets = [
        ("minimal", "Minimal", 0.7, 0.6, ["planner", "frontend-builder", "reviewer"], ["feature-prioritization", "responsive-ui"]),
        ("standard", "Standard", 1.0, 1.0, ["planner", "frontend-builder", "backend-builder", "reviewer"], ["feature-prioritization", "responsive-ui", "api-design"]),
        ("full", "Full", 1.35, 1.4, ["planner", "frontend-builder", "backend-builder", "qa-engineer", "security-reviewer", "reviewer"], ["feature-prioritization", "responsive-ui", "api-design", "quality-assurance", "security-review"]),
    ]
    estimates: list[dict[str, Any]] = []
    for preset, label, effort_factor, cost_factor, agents, base_skills in presets:
        included_use_cases = _plan_estimate_use_cases(use_cases, preset)
        grouped_use_cases: dict[str, list[dict[str, Any]]] = {}
        for use_case in included_use_cases:
            category = str(use_case.get("category", "") or "Core flow")
            grouped_use_cases.setdefault(category, []).append(use_case)

        epics: list[dict[str, Any]] = []
        wbs: list[dict[str, Any]] = []
        review_task_ids_by_use_case: dict[str, str] = {}
        assignee_available_day: dict[str, int] = {}
        task_end_day: dict[str, int] = {}

        for epic_index, (category, epic_use_cases) in enumerate(grouped_use_cases.items()):
            epic_id = f"epic-{preset}-{_slug(category, prefix='track')}"
            epic_priority = min(
                (_planning_priority_rank(str(use_case.get("priority", "should"))) for use_case in epic_use_cases),
                default=1,
            )
            epics.append(
                {
                    "id": epic_id,
                    "name": f"{category} track",
                    "description": f"{category} に関する主要導線と運用条件を成立させる。",
                    "use_cases": [str(use_case.get("title", "")) for use_case in epic_use_cases if str(use_case.get("title", "")).strip()],
                    "priority": "must" if epic_priority == 0 else "should" if epic_priority == 1 else "could",
                    "stories": _dedupe_strings(
                        [
                            str(story)
                            for use_case in epic_use_cases
                            for story in _as_list(use_case.get("related_stories"))
                            if str(story).strip()
                        ]
                    )[:6],
                }
            )

            for use_case_index, use_case in enumerate(epic_use_cases):
                use_case_id = str(use_case.get("id", f"uc-{epic_index}-{use_case_index}"))
                definition_effort, implementation_effort, verification_effort = _estimate_use_case_effort_hours(
                    use_case,
                    selected_features,
                    preset=preset,
                    kind=kind,
                )
                implementation_assignee, implementation_skills = _implementation_assignee(kind, preset, use_case)
                verification_assignee, verification_skills = _verification_assignee(preset, use_case)
                define_assignee = "planner"
                define_duration = _planning_task_duration_days(definition_effort, define_assignee)
                define_start = assignee_available_day.get(define_assignee, 0)
                define_end = define_start + define_duration
                implementation_duration = _planning_task_duration_days(implementation_effort, implementation_assignee)
                implementation_start = max(
                    define_end,
                    assignee_available_day.get(implementation_assignee, 0),
                )
                implementation_end = implementation_start + implementation_duration
                verification_duration = _planning_task_duration_days(verification_effort, verification_assignee)
                verification_start = max(
                    implementation_end,
                    assignee_available_day.get(verification_assignee, 0),
                )
                verification_end = verification_start + verification_duration

                define_id = f"wbs-{preset}-{use_case_id}-define"
                build_id = f"wbs-{preset}-{use_case_id}-build"
                review_id = f"wbs-{preset}-{use_case_id}-review"
                review_task_ids_by_use_case[use_case_id] = review_id
                assignee_available_day[define_assignee] = define_end
                assignee_available_day[implementation_assignee] = implementation_end
                assignee_available_day[verification_assignee] = verification_end
                task_end_day[define_id] = define_end
                task_end_day[build_id] = implementation_end
                task_end_day[review_id] = verification_end

                wbs.extend(
                    [
                        {
                            "id": define_id,
                            "epic_id": epic_id,
                            "title": f"Define acceptance for {use_case.get('title', 'use case')}",
                            "description": "受け入れ条件、計測、停止条件を固める。",
                            "assignee_type": "agent",
                            "assignee": "planner",
                            "skills": ["acceptance-design", "instrumentation-planning"],
                            "depends_on": [],
                            "effort_hours": definition_effort,
                            "start_day": define_start,
                            "duration_days": define_duration,
                            "status": "pending",
                        },
                        {
                            "id": build_id,
                            "epic_id": epic_id,
                            "title": f"Implement {use_case.get('title', 'use case')}",
                            "description": "主要導線と必要な状態遷移を実装する。",
                            "assignee_type": "agent",
                            "assignee": implementation_assignee,
                            "skills": implementation_skills,
                            "depends_on": [define_id],
                            "effort_hours": implementation_effort,
                            "start_day": implementation_start,
                            "duration_days": implementation_duration,
                            "status": "pending",
                        },
                        {
                            "id": review_id,
                            "epic_id": epic_id,
                            "title": f"Verify {use_case.get('title', 'use case')}",
                            "description": "受け入れ条件、記録、例外系を検証する。",
                            "assignee_type": "agent",
                            "assignee": verification_assignee,
                            "skills": verification_skills,
                            "depends_on": [build_id],
                            "effort_hours": verification_effort,
                            "start_day": verification_start,
                            "duration_days": verification_duration,
                            "status": "pending",
                        },
                    ]
                )

        if milestones:
            milestone_epic_id = f"epic-{preset}-milestone-validation"
            epics.append(
                {
                    "id": milestone_epic_id,
                    "name": "Milestone validation",
                    "description": "各マイルストーンの完了証跡と停止条件を確認する。",
                    "use_cases": [str(item.get("name", "")) for item in milestones if str(item.get("name", "")).strip()],
                    "priority": "must",
                    "stories": [],
                }
            )
            for milestone_index, milestone in enumerate(milestones):
                dependency_ids = [
                    review_task_ids_by_use_case[str(use_case_id)]
                    for use_case_id in _as_list(milestone.get("depends_on_use_cases"))
                    if str(use_case_id) in review_task_ids_by_use_case
                ]
                milestone_assignee = "qa-engineer" if preset == "full" else "reviewer"
                milestone_skills = (
                    ["milestone-review", "quality-gating"]
                    if preset == "full"
                    else ["delivery-review", "quality-gating"]
                )
                dependency_ready_day = max(
                    (task_end_day.get(task_id, 0) for task_id in dependency_ids),
                    default=milestone_index * 3,
                )
                milestone_start = max(
                    dependency_ready_day,
                    assignee_available_day.get(milestone_assignee, 0),
                )
                milestone_effort = max(3, math.ceil((len(dependency_ids) or 1) * 1.5))
                milestone_duration = _planning_task_duration_days(milestone_effort, milestone_assignee)
                milestone_id = f"wbs-{preset}-{str(milestone.get('id', milestone_index))}-gate"
                wbs.append(
                    {
                        "id": milestone_id,
                        "epic_id": milestone_epic_id,
                        "title": f"Validate {milestone.get('name', 'milestone')}",
                        "description": "完了証跡、停止条件、判断責任者を確認する。",
                        "assignee_type": "agent",
                        "assignee": milestone_assignee,
                        "skills": milestone_skills,
                        "depends_on": dependency_ids,
                        "effort_hours": milestone_effort,
                        "start_day": milestone_start,
                        "duration_days": milestone_duration,
                        "status": "pending",
                    }
                )
                assignee_available_day[milestone_assignee] = milestone_start + milestone_duration
                task_end_day[milestone_id] = milestone_start + milestone_duration

        total_effort = sum(int(item.get("effort_hours", 0)) for item in wbs)
        collaboration_buffer = max(4, math.ceil(total_effort * 0.08 * effort_factor))
        total_effort += collaboration_buffer
        total_duration_days = max(
            (int(item.get("start_day", 0)) + int(item.get("duration_days", 1)) for item in wbs),
            default=1,
        )
        duration_weeks = max(1, math.ceil(total_duration_days / _PLANNING_WORKDAYS_PER_WEEK))
        rate = {"minimal": 92, "standard": 108, "full": 126}[preset]
        total_cost = round(total_effort * rate * cost_factor + len(agents) * 240, 2)
        skills_used = _dedupe_strings(
            list(base_skills)
            + [
                str(skill)
                for item in wbs
                for skill in _as_list(item.get("skills"))
                if str(skill).strip()
            ]
        )
        estimates.append(
            {
                "preset": preset,
                "label": label,
                "description": f"{label} scope covering the selected use cases and milestone evidence loops",
                "total_effort_hours": total_effort,
                "total_cost_usd": total_cost,
                "duration_weeks": duration_weeks,
                "epics": epics,
                "wbs": wbs,
                "agents_used": agents,
                "skills_used": skills_used,
            }
        )
    return estimates


def _planning_coverage_summary(
    *,
    analysis: dict[str, Any],
    features: list[dict[str, Any]],
    plan_estimates: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_features = [
        str(item.get("feature", "")).strip()
        for item in features
        if item.get("selected") is True and str(item.get("feature", "")).strip()
    ]
    use_cases = [_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)]
    milestones = [_as_dict(item) for item in _as_list(analysis.get("recommended_milestones")) if _as_dict(item)]
    traceability = [_as_dict(item) for item in _as_list(analysis.get("traceability")) if _as_dict(item)]
    required_use_cases = _planning_required_traceability_use_cases(use_cases, milestones)
    traced_features = {
        str(item.get("feature", "")).strip()
        for item in traceability
        if str(item.get("feature", "")).strip()
    }
    milestone_use_case_ids = {
        str(use_case_id)
        for milestone in milestones
        for use_case_id in _as_list(milestone.get("depends_on_use_cases"))
        if str(use_case_id).strip()
    }
    traced_use_case_ids = {
        str(item.get("use_case_id", "")).strip()
        for item in traceability
        if str(item.get("use_case_id", "")).strip()
    }
    required_traceability_ids = {
        str(item.get("id", "")).strip()
        for item in required_use_cases
        if str(item.get("id", "")).strip()
    }
    preset_breakdown = [
        {
            "preset": str(plan.get("preset", "")),
            "epic_count": len([_as_dict(item) for item in _as_list(plan.get("epics")) if _as_dict(item)]),
            "wbs_count": len([_as_dict(item) for item in _as_list(plan.get("wbs")) if _as_dict(item)]),
            "total_effort_hours": int(float(plan.get("total_effort_hours", 0) or 0)),
        }
        for plan in plan_estimates
        if isinstance(plan, dict)
    ]
    return {
        "selected_feature_count": len(selected_features),
        "job_story_count": len(_as_list(analysis.get("job_stories"))),
        "use_case_count": len(use_cases),
        "actor_count": len(_as_list(analysis.get("actors"))),
        "role_count": len(_as_list(analysis.get("roles"))),
        "traceability_count": len(traceability),
        "required_traceability_use_case_count": len(required_traceability_ids),
        "milestone_count": len(milestones),
        "uncovered_features": [name for name in selected_features if name not in traced_features],
        "use_cases_without_milestone": [
            str(item.get("title", ""))
            for item in use_cases
            if str(item.get("id", "")) not in milestone_use_case_ids and str(item.get("title", "")).strip()
        ],
        "use_cases_without_traceability": [
            str(item.get("title", ""))
            for item in use_cases
            if str(item.get("id", "")) not in traced_use_case_ids and str(item.get("title", "")).strip()
        ],
        "required_use_cases_without_traceability": [
            str(item.get("title", ""))
            for item in required_use_cases
            if str(item.get("id", "")) not in traced_use_case_ids and str(item.get("title", "")).strip()
        ],
        "preset_breakdown": preset_breakdown,
    }


def _planning_feature_defaults_need_backfill(
    state: dict[str, Any],
    features: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> bool:
    if not features:
        return True
    kind = _infer_product_kind(str(state.get("spec", "")))
    if kind == "generic":
        return False
    generic_feature_names = {name.casefold() for name, *_ in _feature_catalog_for_spec({"spec": ""})}
    current_feature_names = {
        str(item.get("feature", "")).strip().casefold()
        for item in features
        if str(item.get("feature", "")).strip()
    }
    use_case_ids = {
        str(item.get("id", "")).strip()
        for item in _as_list(analysis.get("use_cases"))
        if isinstance(item, dict)
    }
    if current_feature_names and current_feature_names.issubset(generic_feature_names):
        return True
    return any(item.startswith("uc-generic-") for item in use_case_ids)


def _planning_bundle_needs_backfill(
    state: dict[str, Any],
    analysis: dict[str, Any],
    features: list[dict[str, Any]],
) -> bool:
    if not analysis:
        return True
    selected_feature_count = len([item for item in features if item.get("selected") is True])
    use_case_count = len(_as_list(analysis.get("use_cases")))
    return (
        _planning_feature_defaults_need_backfill(state, features, analysis)
        or len(_as_list(analysis.get("job_stories"))) < 4
        or len(_as_list(analysis.get("actors"))) < 3
        or len(_as_list(analysis.get("roles"))) < 3
        or use_case_count < max(4, selected_feature_count)
        or _planning_analysis_consistency_needs_backfill(state, analysis)
    )


def _planning_analysis_consistency_needs_backfill(
    state: dict[str, Any],
    analysis: dict[str, Any],
) -> bool:
    kind = _infer_product_kind(str(state.get("spec", "")))
    if kind == "generic" or not analysis:
        return False
    design_style = str(_as_dict(_as_dict(analysis.get("design_tokens")).get("style")).get("name", "")).casefold()
    business_model = _as_dict(analysis.get("business_model"))
    customer_segments = {
        str(item).strip().casefold()
        for item in _as_list(business_model.get("customer_segments"))
        if str(item).strip()
    }
    channels = {
        str(item).strip().casefold()
        for item in _as_list(business_model.get("channels"))
        if str(item).strip()
    }
    kano_features = {
        str(_as_dict(item).get("feature", "")).strip().casefold()
        for item in _as_list(analysis.get("kano_features"))
        if str(_as_dict(item).get("feature", "")).strip()
    }
    persona_roles = {
        str(_as_dict(item).get("role", "")).strip().casefold()
        for item in _as_list(analysis.get("personas"))
        if _as_dict(item)
    }
    negative_persona_names = {
        str(_as_dict(item).get("name", "")).strip().casefold()
        for item in _as_list(analysis.get("negative_personas"))
        if _as_dict(item)
    }
    kill_conditions = " ".join(
        str(_as_dict(item).get("condition", "")).strip()
        for item in _as_list(analysis.get("kill_criteria"))
        if _as_dict(item)
    ).casefold()
    red_team_titles = " ".join(
        str(_as_dict(item).get("title", "")).strip()
        for item in _as_list(analysis.get("red_team_findings"))
        if _as_dict(item)
    ).casefold()
    planning_context = _as_dict(analysis.get("planning_context"))
    generic_feature_names = {name.casefold() for name, *_ in _feature_catalog_for_spec({"spec": ""})}
    if "balanced product" in design_style or "バランス型プロダクト" in design_style:
        return True
    if customer_segments & {"primary users", "product teams"}:
        return True
    if channels & {"web", "mobile", "team sharing"}:
        return True
    if kano_features and kano_features.issubset(generic_feature_names):
        return True
    if kind == "operations":
        if not any(("platform lead" in role or "workflow operator" in role) for role in persona_roles):
            return True
        if negative_persona_names and negative_persona_names & {"impatient evaluator", "すぐ離脱する評価者"}:
            return True
        if any(marker in kill_conditions for marker in ("configuration and recovery", "release quality", "core workflow ready")):
            return True
        if any(marker in red_team_titles for marker in ("configuration and recovery", "release quality", "core workflow ready")):
            return True
    return str(planning_context.get("product_kind", "")).strip() not in {"", kind}


def _planning_plan_estimates_need_backfill(
    features: list[dict[str, Any]],
    plan_estimates: list[dict[str, Any]],
) -> bool:
    selected_feature_count = len([item for item in features if item.get("selected") is True]) or len(features)
    if not plan_estimates:
        return True
    for plan in plan_estimates:
        epics = [_as_dict(item) for item in _as_list(plan.get("epics")) if _as_dict(item)]
        wbs = [_as_dict(item) for item in _as_list(plan.get("wbs")) if _as_dict(item)]
        if len(epics) < 2 or len(wbs) < max(6, selected_feature_count * 2):
            return True
        scheduled_workdays = max(
            (int(item.get("start_day", 0)) + int(item.get("duration_days", 1)) for item in wbs),
            default=1,
        )
        expected_weeks = max(1, math.ceil(scheduled_workdays / _PLANNING_WORKDAYS_PER_WEEK))
        if int(plan.get("duration_weeks", 0) or 0) != expected_weeks:
            return True
    return False


def backfill_planning_artifacts(project_record: dict[str, Any]) -> dict[str, Any]:
    project = dict(project_record)
    if not str(project.get("spec", "")).strip():
        return project

    analysis = _as_dict(project.get("analysis"))
    features = [_as_dict(item) for item in _as_list(project.get("features")) if _as_dict(item)]
    plan_estimates = [_as_dict(item) for item in _as_list(project.get("planEstimates")) if _as_dict(item)]
    feature_defaults_replaced = _planning_feature_defaults_need_backfill(project, features, analysis)

    if feature_defaults_replaced:
        features = _default_feature_selections_for_spec(project)
        project["features"] = features

    working_state = {**project, "feature_selections": features or _default_feature_selections_for_spec(project)}
    bundle = _build_story_architecture_bundle(working_state)
    solution = _solution_bundle(working_state)
    personas, stories, journeys = _build_persona_bundle(working_state)
    review_defaults = _planning_review_defaults(
        working_state,
        features=features or _default_feature_selections_for_spec(project),
        personas=personas,
        milestones=list(solution.get("recommended_milestones", [])),
    )

    if _planning_bundle_needs_backfill(working_state, analysis, features):
        analysis = {
            **{key: value for key, value in analysis.items() if key not in {"canonical", "localized", "display_language", "localization_status"}},
            "personas": personas,
            "user_stories": stories,
            "user_journeys": journeys,
            "job_stories": list(bundle.get("job_stories", [])),
            "actors": list(bundle.get("actors", [])),
            "roles": list(bundle.get("roles", [])),
            "use_cases": list(bundle.get("use_cases", [])),
            "ia_analysis": _as_dict(bundle.get("ia_analysis")),
            "business_model": _as_dict(solution.get("business_model")),
            "recommended_milestones": list(solution.get("recommended_milestones", [])),
            "design_tokens": _as_dict(solution.get("design_tokens")),
            "kano_features": list(_default_kano_features_for_spec(working_state)),
            "feature_decisions": _build_feature_decisions(working_state, features),
            "recommendations": _planning_recommendations(working_state),
            "rejected_features": list(review_defaults.get("rejected_features", [])),
            "assumptions": list(review_defaults.get("assumptions", [])),
            "red_team_findings": list(review_defaults.get("red_team_findings", [])),
            "negative_personas": list(review_defaults.get("negative_personas", [])),
            "kill_criteria": list(review_defaults.get("kill_criteria", [])),
            "judge_summary": _planning_fallback_judge_summary(
                _planning_recommendations(working_state),
                review_defaults,
            ),
        }
    else:
        analysis = dict(analysis)

    working_state.update(
        {
            "analysis": analysis,
            "use_cases": list(analysis.get("use_cases", [])),
            "recommended_milestones": list(analysis.get("recommended_milestones") or solution.get("recommended_milestones", [])),
        }
    )
    traceability = _build_traceability(working_state, features, _planning_milestones_from_state(working_state))
    if len(traceability) >= len([item for item in features if item.get("selected") is True]):
        analysis["traceability"] = traceability
    analysis["planning_context"] = _planning_context_payload(
        working_state,
        features=features,
        personas=[_as_dict(item) for item in _as_list(analysis.get("personas")) if _as_dict(item)],
        use_cases=[_as_dict(item) for item in _as_list(analysis.get("use_cases")) if _as_dict(item)],
        milestones=[_as_dict(item) for item in _as_list(analysis.get("recommended_milestones")) if _as_dict(item)],
        design_tokens=_as_dict(analysis.get("design_tokens")),
        business_model=_as_dict(analysis.get("business_model")),
    )

    if _planning_plan_estimates_need_backfill(features, plan_estimates):
        plan_estimates = _build_plan_estimates(working_state)
        project["planEstimates"] = plan_estimates

    analysis["coverage_summary"] = _planning_coverage_summary(
        analysis=analysis,
        features=features,
        plan_estimates=plan_estimates,
    )
    project["analysis"] = analysis
    project["features"] = features
    project["planEstimates"] = plan_estimates
    value_contract = build_value_contract(project)
    project["valueContract"] = value_contract or None
    project["outcomeTelemetryContract"] = (
        build_outcome_telemetry_contract(project, value_contract=value_contract) or None
    )
    return project


def _selected_design_from_state(state: dict[str, Any]) -> dict[str, Any]:
    design_input = state.get("design")
    if isinstance(design_input, dict):
        return dict(design_input)
    variants = state.get("designVariants", [])
    selected_id = state.get("selectedDesignId")
    if isinstance(variants, list) and selected_id:
        for variant in variants:
            if isinstance(variant, dict) and variant.get("id") == selected_id:
                return dict(variant)
    return {}


def _decision_context_from_state(
    state: dict[str, Any],
    *,
    compact: bool,
) -> dict[str, Any]:
    existing = _as_dict(state.get("decision_context"))
    if existing:
        return existing
    return build_lifecycle_decision_context(state, target_language="en", compact=compact)


def _decision_scope_for_phase(
    state: dict[str, Any],
    *,
    phase: str,
    selected_design: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_context = _decision_context_from_state(state, compact=True)
    project_frame = _as_dict(decision_context.get("project_frame"))
    decision_graph = _as_dict(decision_context.get("decision_graph"))
    selected = selected_design or _selected_design_from_state(state)
    selected_feature_names = [
        str(item.get("name") or item.get("feature") or "").strip()
        for item in _as_list(project_frame.get("selected_features"))
        if str(_as_dict(item).get("name") or _as_dict(item).get("feature") or "").strip()
    ]
    primary_use_case_ids = [
        str(_as_dict(item).get("id") or "").strip()
        for item in _as_list(project_frame.get("primary_use_cases"))
        if str(_as_dict(item).get("id") or "").strip()
    ]
    milestone_ids = [
        str(_as_dict(item).get("id") or "").strip()
        for item in _as_list(project_frame.get("milestones"))
        if str(_as_dict(item).get("id") or "").strip()
    ]
    thesis_ids = [
        str(_as_dict(item).get("id") or "").strip()
        for item in _as_list(decision_graph.get("nodes"))
        if str(_as_dict(item).get("type")) == "thesis" and str(_as_dict(item).get("id") or "").strip()
    ][:3]
    risk_ids = [
        str(_as_dict(item).get("id") or "").strip()
        for item in _as_list(decision_graph.get("nodes"))
        if str(_as_dict(item).get("type")) == "risk" and str(_as_dict(item).get("id") or "").strip()
    ][:3]
    scope = {
        "phase": phase,
        "fingerprint": str(decision_context.get("fingerprint") or ""),
        "lead_thesis": str(project_frame.get("lead_thesis") or ""),
        "thesis_ids": [item for item in thesis_ids if item],
        "risk_ids": [item for item in risk_ids if item],
        "primary_use_case_ids": [item for item in primary_use_case_ids if item][:4],
        "selected_features": [item for item in selected_feature_names if item][:5],
        "milestone_ids": [item for item in milestone_ids if item][:4],
    }
    if selected:
        scope["selected_design_id"] = str(selected.get("id") or "")
        scope["selected_design_name"] = str(selected.get("pattern_name") or "")
    return scope


def _preview_theme_tokens(
    *,
    visual_style: str,
    primary: str,
    accent: str,
    background: str,
    text_color: str,
) -> dict[str, str]:
    if visual_style == "obsidian-atelier":
        return {
            "canvas": (
                "radial-gradient(circle at 15% 15%, rgba(245, 158, 11, 0.16), transparent 22%), "
                "radial-gradient(circle at 82% 18%, rgba(37, 99, 235, 0.16), transparent 26%), "
                "linear-gradient(180deg, #060b14 0%, #0b1020 44%, #101a2f 100%)"
            ),
            "panel": "rgba(11, 16, 32, 0.82)",
            "shell": "rgba(6, 11, 20, 0.92)",
            "text": _accessible_preview_text_color(
                preferred=text_color,
                background="#0b1020",
                light_fallback="#f8fafc",
                dark_fallback="#152033",
            ),
            "muted": "#93a4bd",
            "border": "rgba(148, 163, 184, 0.16)",
            "surface": "rgba(255, 255, 255, 0.04)",
            "surface_strong": "rgba(148, 163, 184, 0.08)",
            "shadow": "0 36px 120px rgba(2, 6, 23, 0.48)",
            "topbar": "rgba(17, 24, 39, 0.68)",
            "rail": "linear-gradient(180deg, rgba(245,158,11,0.16), rgba(37,99,235,0.06))",
            "accent_soft": "rgba(245, 158, 11, 0.16)",
            "backdrop": "blur(18px)",
        }
    if visual_style == "ivory-signal":
        return {
            "canvas": (
                "radial-gradient(circle at 16% 18%, rgba(37, 99, 235, 0.12), transparent 20%), "
                "radial-gradient(circle at 82% 12%, rgba(245, 158, 11, 0.12), transparent 22%), "
            "linear-gradient(160deg, #f6efe5 0%, #f5f7fb 52%, #e9eef8 100%)"
        ),
        "panel": "rgba(255, 251, 246, 0.82)",
        "shell": "rgba(255, 247, 238, 0.92)",
        "text": _accessible_preview_text_color(
            preferred=text_color,
            background="#f8fafc",
            light_fallback="#f8fafc",
            dark_fallback="#14213d",
        ),
        "muted": "#5f6b7f",
        "border": "rgba(20, 33, 61, 0.12)",
        "surface": "rgba(255, 255, 255, 0.72)",
        "surface_strong": "rgba(20, 33, 61, 0.05)",
        "shadow": "0 32px 90px rgba(15, 23, 42, 0.12)",
            "topbar": "rgba(255, 250, 244, 0.76)",
            "rail": "linear-gradient(135deg, rgba(37,99,235,0.08), rgba(245,158,11,0.08))",
            "accent_soft": "rgba(37, 99, 235, 0.1)",
            "backdrop": "blur(16px)",
        }
    return {
        "canvas": (
            "linear-gradient(180deg, rgba(255,255,255,0.85), rgba(255,255,255,0.55)), "
            f"linear-gradient(160deg, #e2e8f0 0%, {background} 58%, #eef2ff 100%)"
        ),
        "panel": "rgba(255,255,255,0.88)",
        "shell": "rgba(255,255,255,0.92)",
        "text": _accessible_preview_text_color(
            preferred=text_color,
            background=background,
            light_fallback="#f8fafc",
            dark_fallback="#0f172a",
        ),
        "muted": "#5b6474",
        "border": "rgba(15, 23, 42, 0.12)",
        "surface": "rgba(255,255,255,0.72)",
        "surface_strong": "rgba(15, 23, 42, 0.05)",
        "shadow": "0 24px 60px rgba(15, 23, 42, 0.08)",
        "topbar": "rgba(255,255,255,0.76)",
        "rail": "linear-gradient(135deg, rgba(59,130,246,0.08), rgba(245,158,11,0.08))",
        "accent_soft": "rgba(59, 130, 246, 0.08)",
        "backdrop": "blur(10px)",
    }


def _preview_style_class(visual_style: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(visual_style or "").strip().lower()).strip("-")
    return normalized or "balanced-product"


def _preview_surface_mode_label(visual_style: str, shell_layout: str) -> str:
    normalized_style = str(visual_style or "").strip().lower()
    if normalized_style == "obsidian-atelier":
        return "制御室ビュー"
    if normalized_style == "ivory-signal":
        return "判断ギャラリー"
    return "主要ワークサーフェス" if str(shell_layout or "").strip().lower() == "top-nav" else "主要ワークスペース"


def _build_preview_html(
    *,
    title: str,
    subtitle: str,
    primary: str,
    accent: str,
    features: list[str],
    prototype: dict[str, Any] | None = None,
    design_tokens: dict[str, Any] | None = None,
    backend_entities: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    interaction_notes: list[str] | None = None,
    section_focus: list[str] | None = None,
    mode: str = "design",
) -> str:
    preview_kind = _infer_prototype_context_kind(prototype)
    prototype_payload = _sanitize_design_prototype(_as_dict(prototype), kind=preview_kind)
    design_tokens_payload = _as_dict(design_tokens)
    shell = _as_dict(prototype_payload.get("app_shell"))
    design_anchor = _as_dict(prototype_payload.get("design_anchor"))
    visual_direction = _as_dict(prototype_payload.get("visual_direction"))
    screens = [dict(item) for item in _as_list(prototype_payload.get("screens")) if isinstance(item, dict)]
    flows = [dict(item) for item in _as_list(prototype_payload.get("flows")) if isinstance(item, dict)]
    primary_navigation = [dict(item) for item in _as_list(shell.get("primary_navigation")) if isinstance(item, dict)]
    status_badges = [str(item) for item in _as_list(shell.get("status_badges")) if str(item).strip()] or features[:3]
    if preview_kind == "operations" and screens:
        primary_navigation = [
            {
                "id": str(screen.get("id") or f"screen-{index + 1}"),
                "label": _preferred_operations_screen_label(
                    screen_id=str(screen.get("id") or f"screen-{index + 1}"),
                    label=str(screen.get("title") or f"画面 {index + 1}"),
                    variant_style=str(screen.get("variant_style") or visual_direction.get("visual_style") or ""),
                ),
                "priority": "primary" if index < 3 else "secondary",
            }
            for index, screen in enumerate(screens[:4])
        ]
        status_badges = [
            _preferred_operations_screen_label(
                screen_id=str(screen.get("id") or f"screen-{index + 1}"),
                label=str(screen.get("title") or f"画面 {index + 1}"),
                variant_style=str(screen.get("variant_style") or visual_direction.get("visual_style") or ""),
            )
            for index, screen in enumerate(screens[:3])
        ]
    focus_ids = {str(item).strip() for item in _as_list(section_focus) if str(item).strip()}
    if focus_ids:
        ordered = [screen for screen in screens if str(screen.get("id")) in focus_ids]
        screens = ordered or screens
    active_screen = screens[0] if screens else {}
    active_screen_id = str(active_screen.get("id") or "screen-1")
    active_modules = [dict(item) for item in _as_list(_as_dict(active_screen).get("modules")) if isinstance(item, dict)]
    interaction_principles = [
        str(item) for item in _as_list(prototype_payload.get("interaction_principles")) if str(item).strip()
    ]
    if interaction_notes:
        interaction_principles = _dedupe_strings(
            interaction_principles + [str(item) for item in interaction_notes if str(item).strip()]
        )
    backend_modules = [dict(item) for item in _as_list(backend_entities) if isinstance(item, dict)]
    milestone_payload = [dict(item) for item in _as_list(milestones) if isinstance(item, dict)]
    body_font = str(visual_direction.get("body_font") or _as_dict(design_tokens_payload.get("typography")).get("body") or "Noto Sans JP")
    heading_font = str(visual_direction.get("display_font") or _as_dict(design_tokens_payload.get("typography")).get("heading") or "IBM Plex Sans")
    background = str(_as_dict(design_tokens_payload.get("colors")).get("background") or "#f8fafc")
    text_color = str(_as_dict(design_tokens_payload.get("colors")).get("text") or primary or "")
    prototype_kind = str(prototype_payload.get("kind") or "product-workspace")
    shell_layout = str(shell.get("layout") or "sidebar")
    density = str(shell.get("density") or "medium")
    visual_style = str(visual_direction.get("visual_style") or "balanced-product")
    theme = _preview_theme_tokens(
        visual_style=visual_style,
        primary=primary,
        accent=accent,
        background=background,
        text_color=text_color,
    )
    preview_style_class = _preview_style_class(visual_style)
    surface_mode_label = _preview_surface_mode_label(visual_style, shell_layout)
    localized_title = _preview_copy_or_fallback(
        title,
        fallback="オペレーター主導のマルチエージェント ライフサイクルワークスペース",
        max_length=96,
    )
    localized_subtitle = _preview_copy_or_fallback(
        subtitle,
        fallback=_preview_subtitle_fallback(
            screens=screens[:4],
            flows=flows[:3],
            features=features,
            variant_style=visual_style,
        ),
        max_length=180,
    )

    nav_items_html = "".join(
        (
            f'<li><a href="#{escape(str(item.get("id") or "screen"))}" data-screen-target="{escape(str(item.get("id") or "screen"))}" data-tab="true" role="tab" aria-selected="{"true" if str(item.get("id") or "screen") == active_screen_id else "false"}" aria-controls="{escape(str(item.get("id") or "screen"))}">'
            f'<span>{escape(_design_preview_text(item.get("label") or "セクション"))}</span>'
            f"<small>{escape(_design_preview_text(item.get('priority') or 'primary'))}</small>"
            "</a></li>"
        )
        for item in primary_navigation[:6]
    )
    badge_html = "".join(
        f"<span class='status-badge'>{escape(_design_preview_text(item))}</span>"
        for item in status_badges[:4]
    )
    shell_meta_html = "".join(
        f"<span class='shell-chip'>{escape(_design_preview_text(item))}</span>"
        for item in _dedupe_strings(
            [
                str(design_anchor.get("pattern_name") or ""),
                f"{prototype_kind} shell",
                f"{shell_layout} nav",
                f"{density} density",
            ]
        )[:4]
        if item
    )
    action_html = "".join(
        f'<button type="button" aria-label="{escape(_preview_primary_action(action, screen=_as_dict(active_screen)))}">{escape(_preview_primary_action(action, screen=_as_dict(active_screen)))}</button>'
        for action in _as_list(_as_dict(active_screen).get("primary_actions"))[:3]
        if _preview_primary_action(action, screen=_as_dict(active_screen))
    )
    review_table_html = "".join(
        (
            "<tr>"
            f"<td>{escape(_design_preview_text(screen.get('title') or '画面'))}</td>"
            f"<td>{escape(_preview_screen_purpose(screen))}</td>"
            f"<td>{escape(_preview_primary_action((_as_list(screen.get('primary_actions')) or [''])[0], screen=screen))}</td>"
            "</tr>"
        )
        for screen in screens[:4]
    )
    status_list_html = "".join(
        (
            "<li>"
            f"<strong>{escape(_design_preview_text(item.get('name') or item.get('id') or '状態'))}</strong>"
            f"<span>{escape(_design_preview_text(item.get('criteria') or item.get('status') or '次の判断を確認'))}</span>"
            "</li>"
        )
        for item in milestone_payload[:4]
    ) or "".join(
        (
            "<li>"
            f"<strong>{escape(_design_preview_text(flow.get('name') or '主要フロー'))}</strong>"
            f"<span>{escape(_design_preview_text(flow.get('goal') or '主要判断の次アクションを定義する'))}</span>"
            "</li>"
        )
        for flow in flows[:3]
    )
    form_options_html = "".join(
        f"<option>{escape(_design_preview_text(item))}</option>"
        for item in status_badges[:3]
    ) or "<option>要確認</option>"
    tab_html = "".join(
        (
            f'<button type="button" class="preview-tab{" is-active" if str(screen.get("id") or "screen") == active_screen_id else ""}" '
            f'id="{escape(str(screen.get("id") or "screen"))}-tab" role="tab" data-tab-target="{escape(str(screen.get("id") or "screen"))}" '
            f'aria-selected="{"true" if str(screen.get("id") or "screen") == active_screen_id else "false"}" '
            f'aria-controls="{escape(str(screen.get("id") or "screen"))}">'
            f"{escape(_design_preview_text(screen.get('title') or '画面'))}"
            "</button>"
        )
        for screen in screens[:4]
    )
    active_module_html = "".join(
        (
            "<article class='module-card'>"
            f"<p class='module-type'>{escape(_design_preview_text(module.get('type') or 'panel'))}</p>"
            f"<h3>{escape(_design_preview_text(module.get('name') or 'Module'))}</h3>"
            f"<ul>{''.join(f'<li>{escape(_design_preview_text(item))}</li>' for item in _as_list(module.get('items'))[:4] if str(item).strip())}</ul>"
            "</article>"
        )
        for module in active_modules[:4]
    )
    screen_gallery_html = "".join(
        (
            f'<article class="screen-frame{" is-hidden" if str(screen.get("id") or "screen") != active_screen_id else ""}" id="{escape(str(screen.get("id") or "screen"))}" data-screen-id="{escape(str(screen.get("id") or "screen"))}" role="tabpanel" aria-labelledby="{escape(str(screen.get("id") or "screen"))}-tab" aria-hidden="{"false" if str(screen.get("id") or "screen") == active_screen_id else "true"}">'
            '<div class="screen-topbar">'
            f"<span>{escape(_design_preview_text(screen.get('title') or 'Screen'))}</span>"
            f"<span>{escape(_design_preview_text(screen.get('layout') or 'layout'))}</span>"
            "</div>"
            f"<h3>{escape(_design_preview_text(screen.get('headline') or screen.get('title') or 'Screen headline'))}</h3>"
            f"<p>{escape(_preview_screen_purpose(screen))}</p>"
            '<div class="screen-modules">'
            + "".join(
                (
                    '<div class="mini-module">'
                    f"<p>{escape(_design_preview_text(module.get('name') or 'Module'))}</p>"
                    f"<span>{escape(_design_preview_text(str((_as_list(module.get('items')) or [''])[0])))}</span>"
                    "</div>"
                )
                for module in [dict(item) for item in _as_list(screen.get("modules")) if isinstance(item, dict)][:3]
            )
            + "</div>"
            "</article>"
        )
        for screen in screens[:4]
    )
    flow_html = "".join(
        (
            "<article class='flow-card'>"
            f"<h3>{escape(_design_preview_text(flow.get('name') or 'Flow'))}</h3>"
            f"<ol>{''.join(f'<li>{escape(_design_preview_text(step))}</li>' for step in _as_list(flow.get('steps'))[:5] if str(step).strip())}</ol>"
            f"<p>{escape(_design_preview_text(flow.get('goal') or ''))}</p>"
            "</article>"
        )
        for flow in flows[:3]
    )
    principle_html = "".join(
        f"<li>{escape(_design_preview_text(item))}</li>"
        for item in interaction_principles[:4]
    )
    entity_html = "".join(
        (
            "<li>"
            f"<strong>{escape(_design_preview_text(entity.get('name') or entity.get('title') or 'Entity'))}</strong>"
            f"<span>{escape(_design_preview_text(entity.get('description') or ''))}</span>"
            "</li>"
        )
        for entity in backend_modules[:6]
    )
    milestone_html = "".join(
        (
            "<li>"
            f"<strong>{escape(_design_preview_text(item.get('name') or item.get('id') or 'Milestone'))}</strong>"
            f"<span>{escape(_design_preview_text(item.get('criteria') or item.get('status') or ''))}</span>"
            "</li>"
        )
        for item in milestone_payload[:4]
    )
    shell_html = (
        f"""
      <aside class="sidebar panel shell-rail">
        <div class="eyebrow"><span class="accent" aria-hidden="true"></span> オペレーターシェル</div>
        <p class="shell-title">{escape(localized_title)}</p>
        <div class="shell-meta">{shell_meta_html}</div>
        <p class="shell-note">{escape(localized_subtitle)}</p>
        <div class="status-row">{badge_html}</div>
        <nav aria-label="主要ナビゲーション">
          <ul role="tablist">{nav_items_html}</ul>
        </nav>
      </aside>
        """
        if shell_layout != "top-nav"
        else f"""
      <header class="panel shell-topbar">
        <div class="shell-topbar-head">
          <div>
            <div class="eyebrow"><span class="accent" aria-hidden="true"></span> オペレーターシェル</div>
            <p class="shell-title">{escape(localized_title)}</p>
            <div class="shell-meta">{shell_meta_html}</div>
            <p class="shell-note">{escape(localized_subtitle)}</p>
          </div>
          <div class="status-row">{badge_html}</div>
        </div>
        <nav class="top-nav" aria-label="主要ナビゲーション">
          <ul role="tablist">{nav_items_html}</ul>
        </nav>
      </header>
        """
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(localized_title)}</title>
  <style>
    :root {{
      --bg: {background};
      --canvas: {theme["canvas"]};
      --panel: {theme["panel"]};
      --shell: {theme["shell"]};
      --text: {theme["text"]};
      --accent: {accent};
      --muted: {theme["muted"]};
      --border: {theme["border"]};
      --surface: {theme["surface"]};
      --surface-strong: {theme["surface_strong"]};
      --shadow: {theme["shadow"]};
      --topbar: {theme["topbar"]};
      --rail: {theme["rail"]};
      --accent-soft: {theme["accent_soft"]};
      --backdrop: {theme["backdrop"]};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "{escape(body_font)}", "Hiragino Sans", sans-serif;
      color: var(--text);
      background: var(--canvas);
    }}
    main {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 24px 56px;
    }}
    .workspace {{
      display: grid;
      grid-template-columns: {("260px 1fr" if shell_layout == "sidebar" else "1fr")};
      gap: 20px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: var(--backdrop);
    }}
    h1, h2, h3, h4 {{ font-family: "{escape(heading_font)}", "Hiragino Sans", sans-serif; }}
    h1 {{ margin: 0; font-size: clamp(1.35rem, 2.2vw, 1.8rem); line-height: 1.08; }}
    h2 {{ margin: 0 0 10px; font-size: 0.95rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }}
    h3 {{ margin: 0; font-size: 1rem; }}
    p {{ color: var(--muted); line-height: 1.6; margin: 0; }}
    ul, ol {{ margin: 0; padding-left: 18px; color: var(--text); }}
    .sidebar {{
      position: sticky;
      top: 24px;
    }}
    .shell-rail {{
      background: linear-gradient(180deg, var(--shell), color-mix(in srgb, var(--shell) 86%, transparent));
      overflow: hidden;
      position: sticky;
    }}
    .shell-rail::after {{
      content: "";
      position: absolute;
      inset: auto -18% -22% 18%;
      height: 180px;
      background: var(--rail);
      filter: blur(26px);
      pointer-events: none;
      opacity: 0.95;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 11px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 84%, transparent);
      border: 1px solid var(--border);
      font-size: 0.82rem;
    }}
    .accent {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 24px color-mix(in srgb, var(--accent) 60%, white);
    }}
    .sidebar nav ul {{
      list-style: none;
      padding: 0;
      margin: 18px 0 0;
      display: grid;
      gap: 10px;
    }}
    .sidebar nav a, .top-nav a {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      text-decoration: none;
      color: var(--text);
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface-strong) 90%, transparent);
      gap: 10px;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}
    .sidebar nav a:hover, .top-nav a:hover {{
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      transform: translateY(-1px);
    }}
    .sidebar nav a[aria-selected="true"], .top-nav a[aria-selected="true"] {{
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
      background: color-mix(in srgb, var(--accent) 16%, var(--surface));
    }}
    .sidebar nav a span, .top-nav a span {{
      font-weight: 600;
    }}
    .sidebar nav a small, .top-nav a small {{
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.66rem;
      color: var(--muted);
    }}
    .shell-topbar {{
      display: grid;
      gap: 18px;
      background: linear-gradient(180deg, var(--shell), var(--topbar));
    }}
    .shell-topbar-head {{
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
    }}
    .top-nav ul {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .status-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    .shell-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .shell-title {{
      margin: 14px 0 0;
      font-family: "{escape(heading_font)}", "Hiragino Sans", sans-serif;
      font-size: 0.94rem;
      line-height: 1.35;
      color: color-mix(in srgb, var(--text) 90%, var(--muted));
      letter-spacing: 0.02em;
    }}
    .shell-chip {{
      display: inline-flex;
      align-items: center;
      padding: 7px 10px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 90%, transparent);
      border: 1px solid var(--border);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .shell-note {{
      margin-top: 12px;
      font-size: 0.84rem;
      line-height: 1.55;
      max-width: 34ch;
    }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      padding: 8px 10px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      border: 1px solid var(--border);
      font-size: 0.76rem;
    }}
    .content {{
      display: grid;
      gap: 20px;
    }}
    .topbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
    }}
    .topbar-copy {{
      max-width: 640px;
      display: grid;
      gap: 8px;
    }}
    .surface-title {{
      margin: 0;
      font-family: "{escape(heading_font)}", "Hiragino Sans", sans-serif;
      font-size: clamp(1.08rem, 1.8vw, 1.42rem);
      line-height: 1.2;
    }}
    .surface-copy {{
      font-size: 0.84rem;
      max-width: 44ch;
    }}
    .topbar-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    .topbar-actions button {{
      appearance: none;
      border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--border));
      background: color-mix(in srgb, var(--accent) 18%, var(--surface));
      color: var(--text);
      border-radius: 14px;
      padding: 11px 14px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }}
    .topbar-actions button:hover {{
      transform: translateY(-1px);
      background: color-mix(in srgb, var(--accent) 24%, var(--surface));
    }}
    .command-surface {{
      display: grid;
      gap: 16px;
      background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--panel) 78%, transparent));
    }}
    .command-metadata {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      border-radius: 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 14px;
    }}
    .metric p:first-child {{
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 1rem;
    }}
    .module-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    .module-card {{
      border-radius: 18px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      padding: 16px;
    }}
    .module-card ul {{
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }}
    .module-type {{
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .secondary-grid {{
      display: grid;
      grid-template-columns: 1.45fr 0.95fr;
      gap: 20px;
    }}
    .screen-gallery {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }}
    .preview-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .preview-tab {{
      appearance: none;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      color: var(--text);
      border-radius: 999px;
      padding: 9px 14px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}
    .preview-tab:hover {{
      transform: translateY(-1px);
    }}
    .preview-tab.is-active {{
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
      background: color-mix(in srgb, var(--accent) 18%, var(--surface));
    }}
    .screen-frame {{
      border-radius: 22px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      padding: 16px;
      min-height: 240px;
      display: grid;
      align-content: start;
      gap: 12px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.12);
      transition: opacity 180ms ease, transform 180ms ease;
    }}
    .screen-frame.is-hidden {{
      display: none;
    }}
    .screen-topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .screen-modules {{
      display: grid;
      gap: 10px;
    }}
    .mini-module {{
      border-radius: 14px;
      background: linear-gradient(180deg, var(--surface-strong), color-mix(in srgb, var(--accent-soft) 32%, var(--surface-strong)));
      padding: 12px;
      border: 1px solid rgba(15,23,42,0.06);
    }}
    .mini-module p {{
      color: var(--text);
      font-size: 0.82rem;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .mini-module span {{
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .flow-card {{
      border-radius: 18px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      padding: 16px;
      display: grid;
      gap: 12px;
    }}
    .evidence-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }}
    .evidence-table th,
    .evidence-table td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    .evidence-table th {{
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .flow-card ol {{
      display: grid;
      gap: 8px;
    }}
    .rail-list {{
      display: grid;
      gap: 10px;
      padding-left: 0;
    }}
    .rail-list li {{
      border-radius: 14px;
      background: var(--surface-strong);
      padding: 12px;
      display: grid;
      gap: 6px;
      list-style: none;
    }}
    .rail-list span {{
      color: var(--muted);
      font-size: 0.8rem;
      line-height: 1.5;
    }}
    .rail-list strong {{
      font-size: 0.86rem;
    }}
    .review-form {{
      display: grid;
      gap: 12px;
    }}
    .review-form label {{
      display: grid;
      gap: 6px;
      font-size: 0.8rem;
      color: var(--muted);
    }}
    .review-form input,
    .review-form select,
    .review-form textarea {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      color: var(--text);
      padding: 11px 12px;
      font: inherit;
    }}
    .review-form textarea {{
      min-height: 92px;
      resize: vertical;
    }}
    .review-form-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .review-form-actions button {{
      appearance: none;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface-strong) 92%, transparent);
      color: var(--text);
      border-radius: 14px;
      padding: 10px 14px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }}
    .review-form-actions button:hover {{
      transform: translateY(-1px);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
    }}
    .accordion {{
      border-radius: 18px;
      border: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      overflow: hidden;
    }}
    .accordion-toggle {{
      width: 100%;
      appearance: none;
      border: 0;
      border-bottom: 1px solid var(--border);
      background: transparent;
      color: var(--text);
      padding: 14px 16px;
      text-align: left;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }}
    .accordion-panel {{
      padding: 14px 16px;
    }}
    .accordion-panel[hidden] {{
      display: none;
    }}
    .principles {{
      display: grid;
      gap: 8px;
    }}
    .principles li {{
      margin-left: 18px;
    }}
    .mode-chip {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .preview-style-obsidian-atelier .command-surface {{
      border-color: color-mix(in srgb, var(--accent) 20%, var(--border));
      background:
        linear-gradient(180deg, rgba(8, 13, 24, 0.96), rgba(14, 22, 38, 0.9)),
        linear-gradient(135deg, rgba(245, 158, 11, 0.12), transparent 45%);
    }}
    .preview-style-obsidian-atelier .metric,
    .preview-style-obsidian-atelier .module-card,
    .preview-style-obsidian-atelier .flow-card,
    .preview-style-obsidian-atelier .screen-frame,
    .preview-style-obsidian-atelier .rail-list li {{
      border-color: rgba(148, 163, 184, 0.18);
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.88), rgba(15, 23, 42, 0.72));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }}
    .preview-style-obsidian-atelier .preview-tab.is-active,
    .preview-style-obsidian-atelier .sidebar nav a[aria-selected="true"] {{
      box-shadow: 0 18px 36px rgba(245, 158, 11, 0.12);
    }}
    .preview-style-obsidian-atelier .mini-module {{
      border-color: rgba(245, 158, 11, 0.12);
      background: linear-gradient(180deg, rgba(245, 158, 11, 0.14), rgba(30, 41, 59, 0.5));
    }}
    .preview-style-ivory-signal .command-surface {{
      gap: 22px;
      border-color: rgba(37, 99, 235, 0.12);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.82)),
        linear-gradient(135deg, rgba(37, 99, 235, 0.08), rgba(245, 158, 11, 0.04));
    }}
    .preview-style-ivory-signal .topbar {{
      display: grid;
      grid-template-columns: minmax(0, 1.18fr) minmax(18rem, 0.82fr);
      align-items: stretch;
    }}
    .preview-style-ivory-signal .surface-title {{
      font-size: clamp(1.4rem, 2.8vw, 2.2rem);
      max-width: 15ch;
      line-height: 1.05;
      letter-spacing: -0.02em;
    }}
    .preview-style-ivory-signal .surface-copy {{
      max-width: 52ch;
      font-size: 0.88rem;
    }}
    .preview-style-ivory-signal .topbar-actions {{
      align-content: start;
      justify-content: flex-start;
      padding: 18px;
      border-radius: 20px;
      border: 1px solid rgba(20, 33, 61, 0.08);
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(246,239,229,0.8));
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    .preview-style-ivory-signal .metric,
    .preview-style-ivory-signal .module-card,
    .preview-style-ivory-signal .flow-card,
    .preview-style-ivory-signal .screen-frame,
    .preview-style-ivory-signal .rail-list li {{
      border-color: rgba(20, 33, 61, 0.08);
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(248,250,252,0.88));
      box-shadow: 0 20px 48px rgba(15, 23, 42, 0.07);
    }}
    .preview-style-ivory-signal .preview-tab {{
      background: rgba(255,255,255,0.78);
    }}
    .preview-style-ivory-signal .preview-tab.is-active,
    .preview-style-ivory-signal .top-nav a[aria-selected="true"] {{
      box-shadow: 0 14px 34px rgba(37, 99, 235, 0.12);
    }}
    .preview-style-ivory-signal .mini-module {{
      border-color: rgba(37, 99, 235, 0.08);
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(226,232,240,0.72));
    }}
    @media (max-width: 1100px) {{
      .workspace, .secondary-grid, .screen-gallery, .module-grid, .command-metadata {{
        grid-template-columns: 1fr;
      }}
      .preview-style-ivory-signal .topbar {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
      }}
      .shell-topbar-head {{
        flex-direction: column;
      }}
    }}
    @media (max-width: 860px) {{
      main {{ padding: 18px 14px 32px; }}
      .panel, .screen-frame {{ border-radius: 18px; }}
      .top-nav ul {{
        display: grid;
        grid-template-columns: 1fr 1fr;
      }}
    }}
  </style>
</head>
<body class="preview-style-{escape(preview_style_class)}" data-prototype-kind="{escape(prototype_kind)}" data-density="{escape(density)}">
  <main>
    <section class="workspace" aria-label="プロトタイプワークスペース">
      {shell_html}
      <div class="content">
        <section class="panel command-surface">
          <div class="topbar">
            <div class="topbar-copy">
              <span class="mode-chip">{escape(surface_mode_label)}</span>
              <h1 class="surface-title">{escape(_design_preview_text(_as_dict(active_screen).get("headline") or title))}</h1>
              <p class="surface-copy">{escape(_design_preview_text(_as_dict(active_screen).get("supporting_text") or _as_dict(active_screen).get("purpose") or subtitle))}</p>
            </div>
            <div class="topbar-actions">{action_html}</div>
          </div>
          <div class="command-metadata">
            <div class="metric">
              <p>アクティブ画面</p>
              <strong>{escape(_design_preview_text(_as_dict(active_screen).get("title") or "主要ワークスペース"))}</strong>
            </div>
            <div class="metric">
              <p>主要フロー</p>
              <strong>{escape(_design_preview_text(_as_dict(flows[0] if flows else {}).get("name") or "中核フロー"))}</strong>
            </div>
            <div class="metric">
              <p>レイアウト</p>
              <strong>{escape(_design_preview_text(_as_dict(active_screen).get("layout") or shell_layout))}</strong>
            </div>
          </div>
          <div class="module-grid">{active_module_html}</div>
        </section>
        <section class="secondary-grid">
          <div class="panel">
            <h2>画面ストーリーボード</h2>
            <div class="preview-tabs" role="tablist" aria-label="画面切替">{tab_html}</div>
            <div class="screen-gallery" aria-label="画面ストーリーボード">{screen_gallery_html}</div>
          </div>
          <div class="panel">
            <h2>操作原則</h2>
            <ul class="principles">{principle_html}</ul>
          </div>
        </section>
        <section class="secondary-grid">
          <div class="panel">
            <h2>主要フロー</h2>
            <div class="rail-list">{flow_html}</div>
          </div>
          <div class="panel">
            <h2>{escape("マイルストーン準備" if mode == "build" else "システムシグナル")}</h2>
            <ul class="rail-list">{status_list_html or entity_html}</ul>
          </div>
        </section>
        <section class="secondary-grid">
          <div class="panel">
            <h2>判断テーブル</h2>
            <table class="evidence-table" aria-label="判断テーブル">
              <thead>
                <tr>
                  <th>画面</th>
                  <th>目的</th>
                  <th>主操作</th>
                </tr>
              </thead>
              <tbody>{review_table_html}</tbody>
            </table>
          </div>
          <div class="panel">
            <h2>承認フォーム</h2>
            <form class="review-form" aria-label="承認フォーム">
              <label>
                判定
                <select name="decision">
                  <option>承認して次へ進む</option>
                  <option>条件付きで差し戻す</option>
                  <option>追加検証が必要</option>
                </select>
              </label>
              <label>
                担当レーン
                <select name="lane">{form_options_html}</select>
              </label>
              <label>
                コメント
                <textarea name="comment" placeholder="判断理由、懸念、次のアクションを記録します。"></textarea>
              </label>
              <div class="review-form-actions">
                <button type="button">承認パケットを作成</button>
                <button type="button">差し戻し条件を追加</button>
              </div>
            </form>
            <div class="accordion" data-accordion>
              <button type="button" class="accordion-toggle" aria-expanded="false">品質ゲートの確認</button>
              <div class="accordion-panel" hidden>
                <ul class="rail-list">{milestone_html or entity_html}</ul>
              </div>
            </div>
          </div>
        </section>
      </div>
    </section>
  </main>
  <script>
    (() => {{
      const tabs = Array.from(document.querySelectorAll('[data-tab-target]'));
      const navLinks = Array.from(document.querySelectorAll('[data-screen-target]'));
      const panels = Array.from(document.querySelectorAll('[data-screen-id]'));
      const showScreen = (screenId) => {{
        panels.forEach((panel) => {{
          const active = panel.dataset.screenId === screenId;
          panel.classList.toggle('is-hidden', !active);
          panel.setAttribute('aria-hidden', active ? 'false' : 'true');
        }});
        tabs.forEach((tab) => {{
          const active = tab.getAttribute('data-tab-target') === screenId;
          tab.classList.toggle('is-active', active);
          tab.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        navLinks.forEach((link) => {{
          const active = link.getAttribute('data-screen-target') === screenId;
          link.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
      }};
      tabs.forEach((tab) => tab.addEventListener('click', () => showScreen(tab.getAttribute('data-tab-target') || '')));
      navLinks.forEach((link) => link.addEventListener('click', (event) => {{
        event.preventDefault();
        showScreen(link.getAttribute('data-screen-target') || '');
      }}));
      document.querySelectorAll('[data-accordion] .accordion-toggle').forEach((button) => {{
        button.addEventListener('click', () => {{
          const panel = button.nextElementSibling;
          const expanded = button.getAttribute('aria-expanded') === 'true';
          button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
          if (panel) {{
            panel.hidden = expanded;
          }}
        }});
      }});
      if (panels[0]) {{
        showScreen(panels[0].dataset.screenId || '{escape(active_screen_id)}');
      }}
    }})();
  </script>
</body>
</html>"""


def _milestone_score(criteria: str, code: str) -> float:
    criteria_words = [word for word in _keywords(criteria) if len(word) > 2]
    if not criteria_words:
        return 1.0 if code else 0.0
    hits = sum(1 for word in criteria_words if word in code.lower())
    return hits / max(len(criteria_words), 1)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
