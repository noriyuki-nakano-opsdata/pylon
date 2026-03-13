from pylon.lifecycle.services.research_sources import (
    pricing_hint_from_packet,
    research_context,
    source_observations,
)


def test_source_observations_prefers_title_and_excerpt() -> None:
    packets = [
        {
            "title": "Vendor pricing",
            "excerpt": "Starter plan starts at $29 / month with audit logs and SSO support.",
        },
        {
            "title": "Vendor pricing",
            "excerpt": "Starter plan starts at $29 / month with audit logs and SSO support.",
        },
    ]

    assert source_observations(packets) == [
        "Vendor pricing: Starter plan starts at $29 / month with audit logs and SSO support.",
    ]


def test_pricing_hint_from_packet_extracts_price() -> None:
    packet = {
        "description": "Teams plan is available for $99 / month and includes exports.",
    }

    assert pricing_hint_from_packet(packet) == "$99 / month"


def test_research_context_uses_structured_research_and_segment_fallback() -> None:
    state = {
        "spec": "Manufacturing ops assistant",
        "research": {
            "opportunities": ["現場の判断を早める"],
            "threats": ["導入前の信頼形成が必要"],
            "user_research": {
                "signals": [{"statement": "状況をすぐ把握したい"}],
                "pain_points": [{"pain_point": "履歴が分散している"}],
            },
        },
    }

    context = research_context(
        state,
        segment_from_spec=lambda spec: f"segment:{spec}",
    )

    assert context["user_signals"] == ["状況をすぐ把握したい"]
    assert context["pain_points"] == ["履歴が分散している"]
    assert context["opportunities"] == ["現場の判断を早める"]
    assert context["threats"] == ["導入前の信頼形成が必要"]
    assert context["segment"] == "segment:Manufacturing ops assistant"
