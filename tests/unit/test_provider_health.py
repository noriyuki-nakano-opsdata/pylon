"""Tests for ProviderHealthTracker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pylon.providers.health import EndpointHealth, ProviderHealthTracker


class _FakeError(Exception):
    def __init__(self, status_code: int = 500) -> None:
        super().__init__("boom")
        self.status_code = status_code


def test_record_success_marks_healthy() -> None:
    tracker = ProviderHealthTracker()
    tracker.record_success("anthropic", "claude-haiku", latency_ms=100.0)

    ep = tracker.get_endpoint_health("anthropic", "claude-haiku")
    assert ep.is_healthy is True
    assert ep.consecutive_failures == 0
    assert ep.total_requests == 1
    assert ep.last_success_time is not None


def test_record_failure_marks_unhealthy_after_threshold() -> None:
    tracker = ProviderHealthTracker()
    error = _FakeError(status_code=429)

    # First two failures: still healthy
    tracker.record_failure("anthropic", "claude-opus", error)
    tracker.record_failure("anthropic", "claude-opus", error)
    ep = tracker.get_endpoint_health("anthropic", "claude-opus")
    assert ep.is_healthy is True
    assert ep.consecutive_failures == 2

    # Third failure: unhealthy
    tracker.record_failure("anthropic", "claude-opus", error)
    ep = tracker.get_endpoint_health("anthropic", "claude-opus")
    assert ep.is_healthy is False
    assert ep.consecutive_failures == 3
    assert ep.total_failures == 3
    assert ep.total_requests == 3
    assert ep.last_error_code == 429


def test_is_available_checks_rate_limiter() -> None:
    mock_rlm = MagicMock()
    mock_rlm.can_send.return_value = False
    tracker = ProviderHealthTracker(rate_limiter=mock_rlm)

    # Rate limiter says no -> not available
    assert tracker.is_available("anthropic", "claude-haiku") is False
    mock_rlm.can_send.assert_called_with("anthropic")

    # Rate limiter says yes, unknown endpoint -> available
    mock_rlm.can_send.return_value = True
    assert tracker.is_available("anthropic", "claude-haiku") is True

    # Rate limiter says yes, but endpoint unhealthy -> not available
    error = _FakeError(500)
    for _ in range(3):
        tracker.record_failure("openai", "gpt-4o", error)
    assert tracker.is_available("openai", "gpt-4o") is False

    # Provider-only check (no model) passes if rate limiter allows
    assert tracker.is_available("openai") is True


def test_reset_clears_state() -> None:
    mock_rlm = MagicMock()
    mock_rlm.can_send.return_value = True
    tracker = ProviderHealthTracker(rate_limiter=mock_rlm)

    tracker.record_success("anthropic", "claude-haiku")
    tracker.record_success("anthropic", "claude-opus")

    # Reset single model
    tracker.reset("anthropic", "claude-haiku")
    ep = tracker.get_endpoint_health("anthropic", "claude-haiku")
    assert ep.total_requests == 0  # freshly created

    # Opus still has data
    ep2 = tracker.get_endpoint_health("anthropic", "claude-opus")
    assert ep2.total_requests == 1

    # Reset entire provider
    tracker.reset("anthropic")
    ep3 = tracker.get_endpoint_health("anthropic", "claude-opus")
    assert ep3.total_requests == 0
    mock_rlm.reset_provider.assert_called_with("anthropic")
