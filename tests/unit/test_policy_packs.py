"""Tests for policy pack evaluation engine."""

from __future__ import annotations

import pytest

from pylon.safety.policy_pack import (
    PolicyPack,
    PolicyPackEngine,
    PolicyRule,
    RuleEffect,
    evaluate_condition,
)

# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    def test_equals_string(self):
        assert evaluate_condition("action == 'write_external'", {"action": "write_external"})

    def test_equals_string_mismatch(self):
        assert not evaluate_condition("action == 'write_external'", {"action": "read"})

    def test_not_equals(self):
        assert evaluate_condition("action != 'read'", {"action": "write"})

    def test_greater_than(self):
        assert evaluate_condition("cost_usd > 100", {"cost_usd": 150})

    def test_greater_than_boundary(self):
        assert not evaluate_condition("cost_usd > 100", {"cost_usd": 100})

    def test_less_than(self):
        assert evaluate_condition("cost_usd < 50", {"cost_usd": 25})

    def test_greater_equal(self):
        assert evaluate_condition("cost_usd >= 100", {"cost_usd": 100})

    def test_less_equal(self):
        assert evaluate_condition("cost_usd <= 100", {"cost_usd": 100})

    def test_in_list(self):
        assert evaluate_condition("autonomy in ['A3', 'A4']", {"autonomy": "A3"})

    def test_in_list_miss(self):
        assert not evaluate_condition("autonomy in ['A3', 'A4']", {"autonomy": "A2"})

    def test_not_in_list(self):
        assert evaluate_condition("autonomy not_in ['A3', 'A4']", {"autonomy": "A1"})

    def test_not_in_list_miss(self):
        assert not evaluate_condition("autonomy not_in ['A3', 'A4']", {"autonomy": "A3"})

    def test_contains(self):
        assert evaluate_condition("resource_type contains 'secret'", {"resource_type": "secret_key"})

    def test_contains_miss(self):
        assert not evaluate_condition("resource_type contains 'secret'", {"resource_type": "config"})

    def test_float_comparison(self):
        assert evaluate_condition("cost_usd > 9.99", {"cost_usd": 10.0})

    def test_boolean_value(self):
        assert evaluate_condition("is_admin == true", {"is_admin": True})

    def test_missing_field_returns_false(self):
        assert not evaluate_condition("missing_field > 10", {"other": 5})

    def test_invalid_condition_format(self):
        assert not evaluate_condition("not a valid condition", {"x": 1})

    def test_type_mismatch_returns_false(self):
        assert not evaluate_condition("cost_usd > 100", {"cost_usd": "not_a_number"})

    def test_numeric_list(self):
        assert evaluate_condition("level in [1, 2, 3]", {"level": 2})

    def test_empty_list(self):
        assert not evaluate_condition("x in []", {"x": "anything"})


# ---------------------------------------------------------------------------
# PolicyPack from_dict / to_dict
# ---------------------------------------------------------------------------


class TestPolicyPack:
    @pytest.fixture()
    def pack_dict(self) -> dict:
        return {
            "version": "1.0",
            "name": "cost-guardrails",
            "description": "Enterprise cost controls",
            "rules": [
                {
                    "name": "high-cost-deny",
                    "condition": "cost_usd > 500",
                    "effect": "deny",
                    "priority": 10,
                    "description": "Block very high cost actions",
                },
                {
                    "name": "medium-cost-approval",
                    "condition": "cost_usd > 100",
                    "effect": "require_approval",
                    "priority": 5,
                    "description": "Require approval for medium cost",
                },
            ],
        }

    def test_from_dict(self, pack_dict: dict):
        pack = PolicyPack.from_dict(pack_dict)
        assert pack.name == "cost-guardrails"
        assert pack.version == "1.0"
        assert len(pack.rules) == 2
        assert pack.rules[0].effect == RuleEffect.DENY
        assert pack.rules[1].priority == 5

    def test_to_dict_roundtrip(self, pack_dict: dict):
        pack = PolicyPack.from_dict(pack_dict)
        result = pack.to_dict()
        assert result["name"] == pack_dict["name"]
        assert len(result["rules"]) == 2
        assert result["rules"][0]["effect"] == "deny"

    def test_from_dict_defaults(self):
        data = {
            "name": "minimal",
            "rules": [
                {
                    "name": "r1",
                    "condition": "x == 1",
                    "effect": "allow",
                },
            ],
        }
        pack = PolicyPack.from_dict(data)
        assert pack.version == "1.0"
        assert pack.description == ""
        assert pack.rules[0].priority == 0
        assert pack.rules[0].description == ""

    def test_from_dict_no_rules(self):
        pack = PolicyPack.from_dict({"name": "empty", "version": "2.0"})
        assert pack.rules == []


# ---------------------------------------------------------------------------
# PolicyPackEngine
# ---------------------------------------------------------------------------


class TestPolicyPackEngine:
    def _make_engine(self, *pack_dicts: dict) -> PolicyPackEngine:
        engine = PolicyPackEngine()
        for d in pack_dicts:
            engine.load_from_dict(d)
        return engine

    def test_single_deny_rule(self):
        engine = self._make_engine(
            {
                "name": "test",
                "version": "1.0",
                "rules": [
                    {
                        "name": "block-external",
                        "condition": "action == 'write_external'",
                        "effect": "deny",
                        "priority": 10,
                    }
                ],
            }
        )
        result = engine.evaluate({"action": "write_external"})
        assert result.effect == RuleEffect.DENY
        assert result.matched_rule == "block-external"
        assert result.pack_name == "test"

    def test_no_match_defaults_deny(self):
        engine = self._make_engine(
            {
                "name": "test",
                "version": "1.0",
                "rules": [
                    {
                        "name": "r1",
                        "condition": "action == 'dangerous'",
                        "effect": "deny",
                    }
                ],
            }
        )
        result = engine.evaluate({"action": "safe_read"})
        assert result.effect == RuleEffect.DENY
        assert result.matched_rule is None

    def test_require_approval(self):
        engine = self._make_engine(
            {
                "name": "approvals",
                "version": "1.0",
                "rules": [
                    {
                        "name": "high-autonomy",
                        "condition": "autonomy in ['A3', 'A4']",
                        "effect": "require_approval",
                        "priority": 5,
                    }
                ],
            }
        )
        result = engine.evaluate({"autonomy": "A3"})
        assert result.effect == RuleEffect.REQUIRE_APPROVAL

    def test_priority_ordering_higher_wins(self):
        engine = self._make_engine(
            {
                "name": "mixed",
                "version": "1.0",
                "rules": [
                    {
                        "name": "low-allow",
                        "condition": "cost_usd > 50",
                        "effect": "allow",
                        "priority": 1,
                    },
                    {
                        "name": "high-deny",
                        "condition": "cost_usd > 50",
                        "effect": "deny",
                        "priority": 10,
                    },
                ],
            }
        )
        result = engine.evaluate({"cost_usd": 100})
        assert result.effect == RuleEffect.DENY
        assert result.matched_rule == "high-deny"

    def test_same_priority_deny_wins_over_allow(self):
        engine = self._make_engine(
            {
                "name": "same-prio",
                "version": "1.0",
                "rules": [
                    {
                        "name": "allow-rule",
                        "condition": "cost_usd > 50",
                        "effect": "allow",
                        "priority": 5,
                    },
                    {
                        "name": "deny-rule",
                        "condition": "cost_usd > 50",
                        "effect": "deny",
                        "priority": 5,
                    },
                ],
            }
        )
        result = engine.evaluate({"cost_usd": 100})
        assert result.effect == RuleEffect.DENY

    def test_multiple_packs_composition(self):
        cost_pack = {
            "name": "cost-pack",
            "version": "1.0",
            "rules": [
                {
                    "name": "cost-limit",
                    "condition": "cost_usd > 200",
                    "effect": "deny",
                    "priority": 10,
                }
            ],
        }
        action_pack = {
            "name": "action-pack",
            "version": "1.0",
            "rules": [
                {
                    "name": "action-limit",
                    "condition": "action == 'write_external'",
                    "effect": "require_approval",
                    "priority": 5,
                }
            ],
        }
        engine = self._make_engine(cost_pack, action_pack)

        # High cost triggers deny from cost-pack (higher priority)
        r1 = engine.evaluate({"cost_usd": 300, "action": "write_external"})
        assert r1.effect == RuleEffect.DENY
        assert r1.pack_name == "cost-pack"

        # Low cost + write_external triggers approval from action-pack
        r2 = engine.evaluate({"cost_usd": 50, "action": "write_external"})
        assert r2.effect == RuleEffect.REQUIRE_APPROVAL
        assert r2.pack_name == "action-pack"

        # Low cost + safe action => default deny (no explicit allow rule)
        r3 = engine.evaluate({"cost_usd": 50, "action": "read"})
        assert r3.effect == RuleEffect.DENY

    def test_load_pack_object(self):
        pack = PolicyPack(
            version="1.0",
            name="direct",
            description="Loaded directly",
            rules=[
                PolicyRule(
                    name="r1",
                    condition="x > 10",
                    effect=RuleEffect.DENY,
                    priority=1,
                )
            ],
        )
        engine = PolicyPackEngine()
        engine.load_pack(pack)
        result = engine.evaluate({"x": 20})
        assert result.effect == RuleEffect.DENY

    def test_empty_engine_denies_everything(self):
        engine = PolicyPackEngine()
        result = engine.evaluate({"action": "anything", "cost_usd": 9999})
        assert result.effect == RuleEffect.DENY
        assert result.matched_rule is None

    def test_missing_context_key_skips_rule(self):
        engine = self._make_engine(
            {
                "name": "test",
                "version": "1.0",
                "rules": [
                    {
                        "name": "needs-cost",
                        "condition": "cost_usd > 100",
                        "effect": "deny",
                        "priority": 10,
                    }
                ],
            }
        )
        # Context doesn't have cost_usd — rule skipped, default deny
        result = engine.evaluate({"action": "read"})
        assert result.effect == RuleEffect.DENY

    def test_unknown_fields_in_dict_ignored(self):
        data = {
            "name": "with-extra",
            "version": "1.0",
            "description": "Has extra fields",
            "author": "test-author",
            "metadata": {"env": "prod"},
            "rules": [
                {
                    "name": "r1",
                    "condition": "x == 1",
                    "effect": "allow",
                    "extra_field": "ignored",
                }
            ],
        }
        pack = PolicyPack.from_dict(data)
        assert pack.name == "with-extra"
        assert len(pack.rules) == 1

    def test_rule_description_in_reason(self):
        engine = self._make_engine(
            {
                "name": "test",
                "version": "1.0",
                "rules": [
                    {
                        "name": "cost-block",
                        "condition": "cost_usd > 100",
                        "effect": "deny",
                        "description": "Cost exceeds enterprise limit",
                    }
                ],
            }
        )
        result = engine.evaluate({"cost_usd": 200})
        assert result.reason == "Cost exceeds enterprise limit"

    def test_rule_without_description_uses_name(self):
        engine = self._make_engine(
            {
                "name": "test",
                "version": "1.0",
                "rules": [
                    {
                        "name": "my-rule",
                        "condition": "x > 0",
                        "effect": "deny",
                    }
                ],
            }
        )
        result = engine.evaluate({"x": 1})
        assert "my-rule" in result.reason
