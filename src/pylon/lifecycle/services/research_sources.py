"""Shared source-shaping helpers for lifecycle research."""

from __future__ import annotations

import re
from typing import Any, Callable

from pylon.lifecycle.services.research_runtime import (
    first_research_text,
    normalize_space,
    normalized_research_strings,
    truncate_research_text,
)


def source_observations(
    packets: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[str]:
    observations: list[str] = []
    seen: set[str] = set()
    for packet in packets:
        title = normalize_space(packet.get("title"))
        excerpt = truncate_research_text(
            packet.get("excerpt") or packet.get("description") or packet.get("text_excerpt"),
            limit=170,
        )
        if not title and not excerpt:
            continue
        summary = f"{title}: {excerpt}" if title and excerpt else (title or excerpt)
        summary = truncate_research_text(summary, limit=190)
        if not summary or summary in seen:
            continue
        seen.add(summary)
        observations.append(summary)
        if len(observations) >= limit:
            break
    return observations


def pricing_hint_from_packet(packet: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(packet.get("description", "") or ""),
            str(packet.get("excerpt", "") or ""),
            str(packet.get("text_excerpt", "") or ""),
        ]
    )
    price_match = re.search(
        r"(\$\s?\d[\d,]*(?:\.\d+)?(?:\s*/\s*(?:month|mo|year|yr|user|seat))?)",
        text,
        re.IGNORECASE,
    )
    if price_match:
        return normalize_space(price_match.group(1))
    if re.search(r"\bpricing\b|\bplans?\b|料金|価格", text, re.IGNORECASE):
        return "Pricing page found"
    return "Not publicly listed"


def research_context(
    state: dict[str, Any],
    *,
    segment_from_spec: Callable[[str], str],
) -> dict[str, Any]:
    research = dict(state.get("research")) if isinstance(state.get("research"), dict) else {}
    raw_user_research = research.get("user_research")
    if isinstance(raw_user_research, dict):
        user_research = dict(raw_user_research)
    elif isinstance(state.get("user_research"), dict):
        user_research = dict(state.get("user_research"))
    else:
        user_research = {}

    return {
        "research": research,
        "user_signals": normalized_research_strings(user_research.get("signals"), limit=4),
        "pain_points": normalized_research_strings(user_research.get("pain_points"), limit=4),
        "opportunities": normalized_research_strings(research.get("opportunities"), limit=4),
        "threats": normalized_research_strings(research.get("threats"), limit=4),
        "segment": first_research_text(
            user_research.get("segment"),
            default=segment_from_spec(str(state.get("spec", ""))),
            char_limit=80,
        ),
    }
