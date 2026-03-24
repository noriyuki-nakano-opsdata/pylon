from __future__ import annotations

from pylon.lifecycle import orchestrator


def test_search_web_short_circuits_after_network_failure(monkeypatch) -> None:
    calls = {"count": 0}

    monkeypatch.setattr(orchestrator, "_research_network_enabled", lambda: True)
    orchestrator._RESEARCH_NETWORK_BACKOFF.clear()

    def _boom(*_args, **_kwargs):
        calls["count"] += 1
        raise TimeoutError("offline")

    monkeypatch.setattr(orchestrator.urllib_request, "urlopen", _boom)

    assert orchestrator._search_web("care ops", limit=3) == []
    assert orchestrator._search_web("care ops", limit=3) == []
    assert calls["count"] == 1

    orchestrator._RESEARCH_NETWORK_BACKOFF.clear()


def test_fetch_research_packet_short_circuits_failed_host(monkeypatch) -> None:
    calls = {"count": 0}

    monkeypatch.setattr(orchestrator, "_research_network_enabled", lambda: True)
    orchestrator._RESEARCH_NETWORK_BACKOFF.clear()

    def _boom(*_args, **_kwargs):
        calls["count"] += 1
        raise TimeoutError("offline")

    monkeypatch.setattr(orchestrator.urllib_request, "urlopen", _boom)

    assert orchestrator._fetch_research_packet("https://care.example.com/product") == {}
    assert orchestrator._fetch_research_packet("https://care.example.com/pricing") == {}
    assert calls["count"] == 1

    orchestrator._RESEARCH_NETWORK_BACKOFF.clear()
