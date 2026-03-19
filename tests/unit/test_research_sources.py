from pylon.lifecycle.services.research_sources import research_context


def test_research_context_prefers_canonical_research_payload() -> None:
    state = {
        "spec": "Operator-led AI lifecycle platform",
        "research": {
            "opportunities": ["Japanese localized opportunity should not drive canonical planning."],
            "threats": ["Japanese localized threat should not drive canonical planning."],
            "user_research": {
                "signals": ["Japanese localized signal should not drive canonical planning."],
                "pain_points": ["Japanese localized pain point should not drive canonical planning."],
                "segment": "Japanese localized segment",
            },
            "canonical": {
                "opportunities": ["Operator teams need artifact lineage before scale."],
                "threats": ["Governance-heavy products lose if approval evidence is unclear."],
                "user_research": {
                    "signals": ["Teams need decision context to survive handoffs."],
                    "pain_points": ["Evidence fragments across phases."],
                    "segment": "Enterprise AI platform leaders",
                },
            },
        },
    }

    context = research_context(state, segment_from_spec=lambda _spec: "Fallback segment")

    assert context["research"]["opportunities"] == ["Operator teams need artifact lineage before scale."]
    assert context["research"]["threats"] == ["Governance-heavy products lose if approval evidence is unclear."]
    assert context["user_signals"] == ["Teams need decision context to survive handoffs."]
    assert context["pain_points"] == ["Evidence fragments across phases."]
    assert context["segment"] == "Enterprise AI platform leaders"
