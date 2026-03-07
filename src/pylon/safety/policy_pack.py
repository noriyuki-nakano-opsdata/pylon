"""Policy Packs — YAML-based enterprise guardrails.

Provides rule-based policy evaluation with safe expression parsing.
Multiple packs compose with priority ordering: deny > require_approval > allow.
"""

from __future__ import annotations

import enum
import operator
import re
from dataclasses import dataclass, field
from typing import Any


class RuleEffect(enum.Enum):
    """Effect of a policy rule match."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


# Priority for effect-based ordering when same rule priority
_EFFECT_PRIORITY = {
    RuleEffect.DENY: 2,
    RuleEffect.REQUIRE_APPROVAL: 1,
    RuleEffect.ALLOW: 0,
}

_OPERATORS: dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}

# Pattern: field operator value
# Supports: field == 'string', field > 123, field in ['a', 'b'], field contains 'x'
_CONDITION_RE = re.compile(
    r"^(\w+)\s+(==|!=|>=|<=|>|<|in|not_in|contains)\s+(.+)$"
)


def _parse_value(raw: str) -> Any:
    """Parse a value string into a typed Python object. No eval()."""
    raw = raw.strip()

    # List: ['a', 'b'] or ['A3', 'A4']
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        items = [_parse_value(item.strip()) for item in _split_list(inner)]
        return items

    # Quoted string
    if (raw.startswith("'") and raw.endswith("'")) or (
        raw.startswith('"') and raw.endswith('"')
    ):
        return raw[1:-1]

    # Boolean
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False

    # Numeric
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass

    # Bare string (unquoted)
    return raw


def _split_list(s: str) -> list[str]:
    """Split comma-separated list items, respecting quotes."""
    items: list[str] = []
    current: list[str] = []
    in_quote: str | None = None

    for ch in s:
        if ch in ("'", '"') and in_quote is None:
            in_quote = ch
            current.append(ch)
        elif ch == in_quote:
            in_quote = None
            current.append(ch)
        elif ch == "," and in_quote is None:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        items.append("".join(current).strip())
    return items


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Safely evaluate a condition string against a context dict.

    Supports: ==, !=, >, <, >=, <=, in, not_in, contains
    """
    match = _CONDITION_RE.match(condition.strip())
    if not match:
        return False

    field_name, op, raw_value = match.group(1), match.group(2), match.group(3)
    expected = _parse_value(raw_value)

    if field_name not in context:
        return False

    actual = context[field_name]

    if op in _OPERATORS:
        try:
            return _OPERATORS[op](actual, expected)
        except TypeError:
            return False

    if op == "in":
        if not isinstance(expected, list):
            return False
        return actual in expected

    if op == "not_in":
        if not isinstance(expected, list):
            return False
        return actual not in expected

    if op == "contains":
        try:
            return expected in actual
        except TypeError:
            return False

    return False


@dataclass
class PolicyRule:
    """A single policy rule within a pack."""

    name: str
    condition: str
    effect: RuleEffect
    priority: int = 0
    description: str = ""


@dataclass
class RuleEvaluation:
    """Result of evaluating rules against a context."""

    effect: RuleEffect
    matched_rule: str | None = None
    pack_name: str | None = None
    reason: str = ""


@dataclass
class PolicyPack:
    """A named collection of policy rules."""

    version: str
    name: str
    description: str
    rules: list[PolicyRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyPack:
        """Create a PolicyPack from a parsed YAML/JSON dict."""
        rules = []
        for r in data.get("rules", []):
            rules.append(
                PolicyRule(
                    name=r["name"],
                    condition=r["condition"],
                    effect=RuleEffect(r["effect"]),
                    priority=r.get("priority", 0),
                    description=r.get("description", ""),
                )
            )
        return cls(
            version=data.get("version", "1.0"),
            name=data["name"],
            description=data.get("description", ""),
            rules=rules,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML/JSON output."""
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "rules": [
                {
                    "name": r.name,
                    "condition": r.condition,
                    "effect": r.effect.value,
                    "priority": r.priority,
                    "description": r.description,
                }
                for r in self.rules
            ],
        }


class PolicyPackEngine:
    """Evaluates context against loaded policy packs.

    Multiple packs are evaluated in rule priority order (highest first).
    Among rules with the same priority, deny > require_approval > allow.
    First match wins.
    """

    def __init__(self) -> None:
        self._packs: list[PolicyPack] = []

    def load_pack(self, pack: PolicyPack) -> None:
        """Register a policy pack."""
        self._packs.append(pack)

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Load a pack from a parsed YAML/JSON dict."""
        self.load_pack(PolicyPack.from_dict(data))

    def evaluate(self, context: dict[str, Any]) -> RuleEvaluation:
        """Evaluate all loaded rules against the given context.

        Rules are sorted by priority (descending), then by effect severity.
        First matching rule wins. If no rule matches, default is ALLOW.
        """
        # Collect all (rule, pack_name) pairs
        all_rules: list[tuple[PolicyRule, str]] = []
        for pack in self._packs:
            for rule in pack.rules:
                all_rules.append((rule, pack.name))

        # Sort: highest priority first, then by effect severity (deny first)
        all_rules.sort(
            key=lambda rp: (rp[0].priority, _EFFECT_PRIORITY.get(rp[0].effect, 0)),
            reverse=True,
        )

        for rule, pack_name in all_rules:
            if evaluate_condition(rule.condition, context):
                return RuleEvaluation(
                    effect=rule.effect,
                    matched_rule=rule.name,
                    pack_name=pack_name,
                    reason=rule.description or f"Matched rule '{rule.name}'",
                )

        return RuleEvaluation(
            effect=RuleEffect.DENY,
            reason="No rules matched; default deny",
        )
