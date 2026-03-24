"""Pure research quality helpers shared by lifecycle orchestration and projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

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


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate_research_text(value: Any, *, limit: int = 220) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{(clipped or text[:limit].strip())}..."


def _first_research_text(value: Any, *, default: str = "", char_limit: int = 180) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_research_text(item, char_limit=char_limit)
            if text:
                return text
        return default
    if isinstance(value, Mapping):
        for key in (
            "question",
            "statement",
            "thesis",
            "claim_statement",
            "core_claim",
            "primary",
            "signal",
            "pain_point",
            "segment",
            "summary",
            "title",
            "name",
            "text",
            "draft",
            "argument",
            "recommendation",
            "rationale",
            "target",
            "notes",
        ):
            if key in value:
                text = _first_research_text(value.get(key), char_limit=char_limit)
                if text:
                    return text
        return default
    text = _truncate_research_text(value, limit=char_limit)
    return text or default


def _research_text_fragments(
    value: Any,
    *,
    max_items: int = 6,
    char_limit: int = 180,
) -> list[str]:
    items: list[str] = []

    def visit(current: Any) -> None:
        if len(items) >= max_items:
            return
        if isinstance(current, list):
            for child in current:
                visit(child)
                if len(items) >= max_items:
                    return
            return
        if isinstance(current, Mapping):
            text = _first_research_text(current, char_limit=char_limit)
            if text:
                items.append(text)
            return
        text = _truncate_research_text(current, limit=char_limit)
        if text:
            items.append(text)

    visit(value)
    return _dedupe_strings(items)[:max_items]


def _normalized_research_strings(
    values: Any,
    *,
    limit: int = 3,
    char_limit: int = 180,
) -> list[str]:
    return _research_text_fragments(values, max_items=limit, char_limit=char_limit)


def _is_external_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _source_host(url: str) -> str:
    parsed = urlparse(str(url or ""))
    host = (parsed.netloc or "").strip().lower()
    return host[4:] if host.startswith("www.") else host


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
    path_segments = [segment.strip().lower() for segment in parsed.path.split("/") if segment.strip()]
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


def _research_required_source_classes(node_id: str) -> list[str]:
    mapping = {
        "competitor-analyst": ["vendor_page"],
        "market-researcher": ["market_report"],
        "user-researcher": ["user_signal"],
        "tech-evaluator": ["technical_source"],
    }
    return list(mapping.get(node_id, []))


def _research_source_classes_for_packets(
    node_id: str,
    packets: list[dict[str, Any]],
) -> list[str]:
    classes: set[str] = set()
    url_packets = [
        packet
        for packet in packets
        if str(packet.get("source_type", "")).strip() == "url"
    ]
    if node_id == "competitor-analyst":
        if any(_looks_like_vendor_product_packet(packet) for packet in url_packets):
            classes.add("vendor_page")
        if any("/pricing" in str(packet.get("url", "")) for packet in url_packets):
            classes.add("pricing_page")
    elif node_id == "market-researcher":
        if url_packets:
            classes.add("market_report")
    elif node_id == "user-researcher":
        if len(url_packets) >= 2:
            classes.add("secondary_user_source")
        if url_packets:
            classes.add("user_signal")
    elif node_id == "tech-evaluator":
        if url_packets:
            classes.add("technical_source")
    return sorted(classes)


def research_node_result(
    node_id: str,
    *,
    status: str,
    parse_status: str,
    artifact: dict[str, Any] | None = None,
    source_packets: list[dict[str, Any]] | None = None,
    degradation_reasons: list[str] | None = None,
    raw_preview: str = "",
    llm_events: list[dict[str, Any]] | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    packets = list(source_packets or [])
    satisfied = _research_source_classes_for_packets(node_id, packets)
    required = _research_required_source_classes(node_id)
    missing = [item for item in required if item not in satisfied]
    reasons = _dedupe_strings(list(degradation_reasons or []))
    if missing:
        reasons.append(f"missing_source_classes:{','.join(missing)}")
    normalized_status = status
    if normalized_status == "success" and (missing or parse_status in {"fallback", "failed"}):
        normalized_status = "degraded"
    event = next(
        (
            item
            for item in reversed(list(llm_events or []))
            if isinstance(item, Mapping) and not str(item.get("error", "")).strip()
        ),
        {},
    )
    payload = {
        "nodeId": node_id,
        "status": normalized_status,
        "parseStatus": parse_status,
        "degradationReasons": reasons,
        "sourceClassesSatisfied": satisfied,
        "missingSourceClasses": missing,
        "artifact": dict(artifact or {}),
        "retryCount": retry_count,
    }
    if raw_preview:
        payload["rawPreview"] = raw_preview[:400]
    if event:
        payload["llmModel"] = str(event.get("model", ""))
        payload["llmProvider"] = str(event.get("provider", ""))
    return payload


def collect_research_node_results(state: dict[str, Any], node_ids: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_id in node_ids:
        item = _as_dict(state.get(f"{node_id}_result"))
        if item:
            results.append(item)
    return results


def _research_has_external_evidence(research: dict[str, Any]) -> bool:
    source_links = [item for item in _as_list(research.get("source_links")) if _is_external_url(item)]
    if source_links:
        return True
    return any(
        isinstance(item, Mapping)
        and str(item.get("source_type", "")).strip() == "url"
        and _is_external_url(item.get("source_ref"))
        for item in _as_list(research.get("evidence"))
    )


def _blocking_claim_node_ids(research: dict[str, Any]) -> list[str]:
    node_ids: list[str] = []
    for item in _as_list(research.get("claims")):
        claim = _as_dict(item)
        if str(claim.get("status", "")).strip() == "accepted":
            continue
        owner = str(claim.get("owner", "")).strip()
        if owner:
            node_ids.append(owner)
    return _dedupe_strings(node_ids)


def _research_quality_gate_payload(
    gate_id: str,
    title: str,
    passed: bool,
    reason: str,
    blocking_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "title": title,
        "passed": passed,
        "reason": reason,
        "blockingNodeIds": _dedupe_strings(list(blocking_node_ids or [])),
    }


def _normalize_identity_profile(value: Any) -> dict[str, Any]:
    profile = _as_dict(value)
    official_domains = _dedupe_strings(
        [
            _source_host(str(item))
            for item in _as_list(profile.get("officialDomains"))
            if _source_host(str(item))
        ]
    )
    if str(profile.get("officialWebsite", "")).strip():
        website_host = _source_host(str(profile.get("officialWebsite", "")))
        if website_host and website_host not in official_domains:
            official_domains.append(website_host)
    return {
        "companyName": _normalize_space(profile.get("companyName")),
        "productName": _normalize_space(profile.get("productName")),
        "aliases": _dedupe_strings(
            [_normalize_space(item) for item in _as_list(profile.get("aliases")) if _normalize_space(item)]
        ),
        "excludedEntityNames": _dedupe_strings(
            [_normalize_space(item) for item in _as_list(profile.get("excludedEntityNames")) if _normalize_space(item)]
        ),
        "officialDomains": official_domains,
    }


def _identity_text_match(text: str, candidates: list[str]) -> bool:
    normalized = _normalize_space(text).lower()
    return any(candidate.lower() in normalized for candidate in candidates if candidate)


def _identity_homonym_collision(
    research: dict[str, Any],
    identity_profile: dict[str, Any],
) -> bool:
    product_terms = _dedupe_strings(
        [
            str(identity_profile.get("productName", "")).strip(),
            *[str(item).strip() for item in _as_list(identity_profile.get("aliases"))],
        ]
    )
    company_name = str(identity_profile.get("companyName", "")).strip()
    official_domains = [str(item).strip() for item in _as_list(identity_profile.get("officialDomains")) if str(item).strip()]
    excluded_names = [str(item).strip() for item in _as_list(identity_profile.get("excludedEntityNames")) if str(item).strip()]
    official_match = lambda url: any(
        _source_host(url) == domain or _source_host(url).endswith(f".{domain}")
        for domain in official_domains
    )

    for item in _as_list(research.get("source_links")):
        url = str(item).strip()
        if not url:
            continue
        if _identity_text_match(url, excluded_names):
            return True
        if product_terms and not official_match(url) and _identity_text_match(url, product_terms) and not _identity_text_match(url, [company_name]):
            return True
    for item in _as_list(research.get("evidence")):
        evidence = _as_dict(item)
        source_ref = str(evidence.get("source_ref", "")).strip()
        combined = " ".join(
            part for part in [source_ref, str(evidence.get("snippet", "")).strip()] if part
        )
        if _identity_text_match(combined, excluded_names):
            return True
        if source_ref and product_terms and not official_match(source_ref) and _identity_text_match(combined, product_terms) and not _identity_text_match(combined, [company_name]):
            return True
    for item in _as_list(research.get("competitors")):
        competitor = _as_dict(item)
        url = str(competitor.get("url", "")).strip()
        combined = " ".join(
            part
            for part in [
                str(competitor.get("name", "")).strip(),
                url,
                str(competitor.get("target", "")).strip(),
            ]
            if part
        )
        if _identity_text_match(combined, excluded_names):
            return True
        if url and official_match(url):
            return True
        if product_terms and url and not official_match(url) and _identity_text_match(combined, product_terms) and not _identity_text_match(combined, [company_name]):
            return True
    return False


def evaluate_research_quality(
    research: dict[str, Any],
    *,
    node_results: list[dict[str, Any]],
    remaining_iterations: int,
    proposal_node_ids: list[str],
    review_node_ids: list[str],
    identity_profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    winning_theses = _normalized_research_strings(research.get("winning_theses"), limit=3, char_limit=220)
    floor = float(_as_dict(research.get("confidence_summary")).get("floor", 0.0) or 0.0)
    critical_dissent = int(research.get("critical_dissent_count", 0) or 0)
    degraded_nodes = [item for item in node_results if str(item.get("status", "")) != "success"]
    degraded_ids = [str(item.get("nodeId", "")) for item in degraded_nodes if str(item.get("nodeId", "")).strip()]
    source_gate_nodes = [
        str(item.get("nodeId", ""))
        for item in node_results
        if _as_list(item.get("missingSourceClasses"))
    ]
    accepted_claim_nodes = _blocking_claim_node_ids(research)
    has_external_evidence = _research_has_external_evidence(research)
    normalized_identity = _normalize_identity_profile(identity_profile)
    has_company_name = bool(str(normalized_identity.get("companyName", "")).strip())
    has_product_name = bool(str(normalized_identity.get("productName", "")).strip())
    has_official_domains = bool(_as_list(normalized_identity.get("officialDomains")))
    has_excluded_entities = bool(_as_list(normalized_identity.get("excludedEntityNames")))
    identity_lock_ready = (
        (has_company_name and has_product_name)
        or has_official_domains
        or has_excluded_entities
    )
    identity_gate_required = identity_lock_ready
    gates = [
        *(
            [
                _research_quality_gate_payload(
                    "target-identity-locked",
                    "調査対象の会社名と自社プロダクト名が固定されている",
                    identity_lock_ready,
                    (
                        "target identity lock signals are present"
                        if identity_lock_ready
                        else "target identity is incomplete"
                    ),
                    ["research-judge"],
                ),
                _research_quality_gate_payload(
                    "homonym-risk-cleared",
                    "同名他社との混同が検出されていない",
                    not _identity_homonym_collision(research, normalized_identity),
                    (
                        "no homonym collision detected"
                        if not _identity_homonym_collision(research, normalized_identity)
                        else "same-name or excluded entity contamination detected"
                    ),
                    ["competitor-analyst", "evidence-librarian", "research-judge"],
                ),
            ]
            if identity_gate_required
            else []
        ),
        _research_quality_gate_payload(
            "source-grounding",
            "採択主張が source と evidence に接地している",
            has_external_evidence,
            "external url evidence is present" if has_external_evidence else "external url evidence is missing",
            source_gate_nodes or accepted_claim_nodes,
        ),
        _research_quality_gate_payload(
            "counterclaim-coverage",
            "主要仮説に対する反証が生成されている",
            bool(_as_list(research.get("dissent"))),
            "dissent coverage present" if bool(_as_list(research.get("dissent"))) else "dissent coverage missing",
            ["devils-advocate-researcher"],
        ),
        _research_quality_gate_payload(
            "critical-dissent-resolved",
            "重大な dissent が未解決のまま残っていない",
            critical_dissent == 0,
            "no unresolved critical dissent" if critical_dissent == 0 else f"{critical_dissent} unresolved critical dissent remain",
            ["cross-examiner", "research-judge", *accepted_claim_nodes],
        ),
        _research_quality_gate_payload(
            "confidence-floor",
            "採択 thesis が planning に渡せる信頼度を満たしている",
            floor >= 0.6 and bool(winning_theses),
            "confidence floor satisfied" if floor >= 0.6 and bool(winning_theses) else f"confidence floor={floor:.2f}, winning_theses={len(winning_theses)}",
            accepted_claim_nodes or ["research-judge"],
        ),
        _research_quality_gate_payload(
            "critical-node-health",
            "critical research nodes が degraded / failed ではない",
            not degraded_ids,
            "all critical nodes healthy" if not degraded_ids else f"degraded nodes: {', '.join(degraded_ids)}",
            degraded_ids,
        ),
    ]
    if all(item.get("passed") is True for item in gates):
        return gates, "ready", None
    retry_candidates = _dedupe_strings(
        [
            node_id
            for gate in gates
            if gate.get("passed") is not True
            for node_id in _as_list(gate.get("blockingNodeIds"))
            if str(node_id).strip()
        ]
    )
    retry_node_ids = [
        node_id
        for node_id in _dedupe_strings(retry_candidates + degraded_ids + source_gate_nodes + accepted_claim_nodes)
        if node_id in proposal_node_ids or node_id in {"devils-advocate-researcher", "cross-examiner"} or node_id in review_node_ids
    ]
    remediation_plan = None
    if remaining_iterations > 0 and retry_node_ids:
        remediation_plan = {
            "objective": "Address degraded nodes, strengthen source grounding, and re-evaluate blocked claims.",
            "retryNodeIds": retry_node_ids[:4],
            "maxIterations": remaining_iterations,
        }
    return gates, "rework", remediation_plan
