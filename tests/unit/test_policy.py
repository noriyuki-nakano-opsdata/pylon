"""Tests for policy engine."""

from pylon.types import AgentConfig, AutonomyLevel, PolicyConfig
from pylon.safety.policy import ActionState, PolicyDecision, PolicyEngine


def _default_policy(**overrides) -> PolicyConfig:
    defaults = dict(
        max_cost_usd=10.0,
        max_duration_seconds=3600,
        max_file_changes=50,
        blocked_actions=["rm -rf /"],
    )
    defaults.update(overrides)
    return PolicyConfig(**defaults)


def _default_agent(**overrides) -> AgentConfig:
    defaults = dict(name="test-agent", autonomy=AutonomyLevel.A2)
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestPolicyEngine:
    def test_allowed_action(self):
        engine = PolicyEngine(_default_policy())
        decision = engine.evaluate_action(
            _default_agent(),
            "file-write",
            ActionState(),
        )
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_blocked_action(self):
        engine = PolicyEngine(_default_policy())
        decision = engine.evaluate_action(
            _default_agent(),
            "rm -rf /",
            ActionState(),
        )
        assert decision.allowed is False
        assert "blocked" in decision.reason.lower()

    def test_cost_exceeded(self):
        engine = PolicyEngine(_default_policy(max_cost_usd=5.0))
        decision = engine.evaluate_action(
            _default_agent(),
            "llm-call",
            ActionState(current_cost_usd=5.01),
        )
        assert decision.allowed is False
        assert "cost" in decision.reason.lower()

    def test_cost_at_limit_is_allowed(self):
        engine = PolicyEngine(_default_policy(max_cost_usd=5.0))
        decision = engine.evaluate_action(
            _default_agent(),
            "llm-call",
            ActionState(current_cost_usd=5.0),
        )
        assert decision.allowed is True

    def test_duration_exceeded(self):
        engine = PolicyEngine(_default_policy(max_duration_seconds=60))
        decision = engine.evaluate_action(
            _default_agent(),
            "long-task",
            ActionState(elapsed_seconds=61),
        )
        assert decision.allowed is False
        assert "duration" in decision.reason.lower()

    def test_file_changes_exceeded(self):
        engine = PolicyEngine(_default_policy(max_file_changes=10))
        decision = engine.evaluate_action(
            _default_agent(),
            "file-write",
            ActionState(file_changes=11),
        )
        assert decision.allowed is False
        assert "file change" in decision.reason.lower()

    def test_requires_approval_for_high_autonomy(self):
        policy = _default_policy()
        # A3 >= require_approval_above (A3)
        agent = _default_agent(autonomy=AutonomyLevel.A3)
        engine = PolicyEngine(policy)
        decision = engine.evaluate_action(agent, "deploy", ActionState())
        assert decision.allowed is True
        assert decision.requires_approval is True

    def test_no_approval_for_low_autonomy(self):
        policy = _default_policy()
        agent = _default_agent(autonomy=AutonomyLevel.A2)
        engine = PolicyEngine(policy)
        decision = engine.evaluate_action(agent, "file-read", ActionState())
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_blocked_action_takes_precedence_over_cost(self):
        engine = PolicyEngine(_default_policy(max_cost_usd=5.0))
        decision = engine.evaluate_action(
            _default_agent(),
            "rm -rf /",
            ActionState(current_cost_usd=100.0),
        )
        assert decision.allowed is False
        assert "blocked" in decision.reason.lower()
