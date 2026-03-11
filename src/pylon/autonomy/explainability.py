"""Structured decision explanation for observability and transparency.

Converts internal decision objects (ModelRouteDecision, TerminationDecision,
VerificationDecision) into human-readable explanations with structured
context, following OpenTelemetry GenAI semantic conventions.

Every explanation includes:
- What was decided
- Why (the reasoning chain)
- What alternatives were considered
- Confidence and risk assessment
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExplanationStep:
    """A single step in a decision explanation."""

    action: str
    reason: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Explanation:
    """Structured explanation of an agent decision."""

    decision_type: str  # "model_route", "termination", "verification", "safety"
    summary: str
    steps: list[ExplanationStep] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    risk_level: str = "low"  # "low", "medium", "high", "critical"
    telemetry_attributes: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        """Format as human-readable text."""
        lines = [f"Decision: {self.decision_type}", f"Summary: {self.summary}"]

        if self.steps:
            lines.append("\nReasoning:")
            for i, step in enumerate(self.steps, 1):
                lines.append(f"  {i}. {step.action}: {step.reason}")

        if self.alternatives:
            lines.append("\nAlternatives considered:")
            for alt in self.alternatives:
                lines.append(f"  - {alt.get('name', '?')}: {alt.get('reason', '')}")

        lines.append(f"\nConfidence: {self.confidence:.1%}")
        lines.append(f"Risk: {self.risk_level}")
        return "\n".join(lines)

    def to_otel_attributes(self) -> dict[str, Any]:
        """Convert to OpenTelemetry span attributes.

        Follows the gen_ai.* semantic conventions where possible.
        """
        attrs = {
            "pylon.decision.type": self.decision_type,
            "pylon.decision.summary": self.summary,
            "pylon.decision.confidence": self.confidence,
            "pylon.decision.risk_level": self.risk_level,
            "pylon.decision.steps_count": len(self.steps),
            "pylon.decision.alternatives_count": len(self.alternatives),
        }
        attrs.update(self.telemetry_attributes)
        return attrs


class DecisionExplainer:
    """Generates structured explanations for agent decisions.

    Usage:
        explainer = DecisionExplainer()
        explanation = explainer.explain_route(route_decision)
        print(explanation.to_text())
    """

    def explain_route(self, decision: Any) -> Explanation:
        """Explain a model routing decision."""
        provider = getattr(decision, "provider_name", "unknown")
        model = getattr(decision, "model_id", "unknown")
        tier = getattr(decision, "tier", None)
        reasoning = getattr(decision, "reasoning", "")
        cache_strategy = getattr(decision, "cache_strategy", None)
        batch_eligible = getattr(decision, "batch_eligible", False)

        steps = [
            ExplanationStep(
                action="Provider selection",
                reason=f"Selected {provider}/{model}",
                data={"provider": provider, "model": model},
            ),
        ]

        if tier:
            tier_value = tier.value if hasattr(tier, "value") else str(tier)
            steps.append(
                ExplanationStep(
                    action="Tier assignment",
                    reason=f"Assigned to {tier_value} tier",
                    data={"tier": tier_value},
                )
            )

        if reasoning:
            steps.append(
                ExplanationStep(
                    action="Reasoning",
                    reason=reasoning,
                )
            )

        if cache_strategy:
            cache_val = (
                cache_strategy.value
                if hasattr(cache_strategy, "value")
                else str(cache_strategy)
            )
            steps.append(
                ExplanationStep(
                    action="Cache strategy",
                    reason=f"Using {cache_val} caching",
                    data={"cache_strategy": cache_val},
                )
            )

        return Explanation(
            decision_type="model_route",
            summary=f"Routed to {provider}/{model}"
            + (" (batch)" if batch_eligible else ""),
            steps=steps,
            confidence=0.9,
            telemetry_attributes={
                "gen_ai.system": provider,
                "gen_ai.request.model": model,
            },
        )

    def explain_termination(self, decision: Any) -> Explanation:
        """Explain a termination decision."""
        should_stop = getattr(decision, "should_stop", False)
        reason = getattr(decision, "reason", "unknown")
        state = getattr(decision, "state", None)

        steps = [
            ExplanationStep(
                action="Termination check",
                reason=f"{'Should stop' if should_stop else 'Continue'}: {reason}",
            ),
        ]

        if state:
            iterations = getattr(state, "iterations", 0)
            tokens = getattr(state, "total_tokens", 0)
            steps.append(
                ExplanationStep(
                    action="State context",
                    reason=f"After {iterations} iterations, {tokens} tokens",
                    data={
                        "iterations": iterations,
                        "total_tokens": tokens,
                    },
                )
            )

        return Explanation(
            decision_type="termination",
            summary=f"{'Stopping' if should_stop else 'Continuing'}: {reason}",
            steps=steps,
            risk_level="medium" if should_stop else "low",
        )

    def explain_verification(self, decision: Any) -> Explanation:
        """Explain a verification decision."""
        disposition = getattr(decision, "disposition", None)
        score = getattr(decision, "score", 0.0)
        criteria = getattr(decision, "criteria_results", [])

        disp_str = (
            disposition.value if hasattr(disposition, "value") else str(disposition)
        )

        steps = [
            ExplanationStep(
                action="Verification result",
                reason=f"Disposition: {disp_str} (score: {score:.2f})",
                data={"disposition": disp_str, "score": score},
            ),
        ]

        for crit in criteria:
            name = crit.get("name", "unknown")
            passed = crit.get("passed", False)
            crit_score = crit.get("score", 0.0)
            steps.append(
                ExplanationStep(
                    action=f"Criterion: {name}",
                    reason=f"{'Passed' if passed else 'Failed'} ({crit_score:.2f})",
                    data=crit,
                )
            )

        risk = "low" if score >= 0.8 else "medium" if score >= 0.5 else "high"
        return Explanation(
            decision_type="verification",
            summary=f"Verification {disp_str}: score {score:.2f}",
            steps=steps,
            confidence=score,
            risk_level=risk,
        )

    def explain_safety(
        self,
        *,
        action: str,
        allowed: bool,
        policy_name: str = "",
        violations: list[str] | None = None,
    ) -> Explanation:
        """Explain a safety decision."""
        steps = [
            ExplanationStep(
                action="Safety evaluation",
                reason=f"Action '{action}' {'allowed' if allowed else 'blocked'}",
                data={"action": action, "allowed": allowed},
            ),
        ]

        if policy_name:
            steps.append(
                ExplanationStep(
                    action="Policy",
                    reason=f"Evaluated against '{policy_name}'",
                )
            )

        if violations:
            for v in violations:
                steps.append(
                    ExplanationStep(
                        action="Violation",
                        reason=v,
                    )
                )

        return Explanation(
            decision_type="safety",
            summary=f"Safety {'allowed' if allowed else 'blocked'}: {action}",
            steps=steps,
            confidence=1.0 if not allowed else 0.85,
            risk_level="critical" if not allowed else "low",
        )
