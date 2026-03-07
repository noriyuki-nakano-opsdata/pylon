"""Policy Engine — unified action evaluation.

Integrates CapabilityValidator and AutonomyEnforcer with resource limit checks
(cost, duration, file changes).
"""

from __future__ import annotations

from dataclasses import dataclass

from pylon.types import AgentConfig, PolicyConfig


@dataclass
class PolicyDecision:
    """Result of policy evaluation."""

    allowed: bool
    reason: str
    requires_approval: bool = False


@dataclass
class ActionState:
    """Current state for policy evaluation."""

    current_cost_usd: float = 0.0
    elapsed_seconds: int = 0
    file_changes: int = 0


class PolicyEngine:
    """Evaluates actions against policy constraints.

    Checks:
    1. Blocked actions
    2. Cost limit (max_cost_usd)
    3. Duration limit (max_duration_seconds)
    4. File change limit (max_file_changes)
    5. Autonomy level approval requirements
    """

    def __init__(self, policy: PolicyConfig) -> None:
        self._policy = policy

    def evaluate_action(
        self,
        agent_config: AgentConfig,
        action: str,
        state: ActionState,
    ) -> PolicyDecision:
        """Evaluate whether an action is allowed under current policy."""
        # 1. Blocked actions
        if action in self._policy.blocked_actions:
            return PolicyDecision(
                allowed=False,
                reason=f"Action '{action}' is blocked by policy",
            )

        # 2. Cost limit
        if state.current_cost_usd > self._policy.max_cost_usd:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Cost limit exceeded: ${state.current_cost_usd:.2f} > "
                    f"${self._policy.max_cost_usd:.2f}"
                ),
            )

        # 3. Duration limit
        if state.elapsed_seconds > self._policy.max_duration_seconds:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Duration limit exceeded: {state.elapsed_seconds}s > "
                    f"{self._policy.max_duration_seconds}s"
                ),
            )

        # 4. File change limit
        if state.file_changes > self._policy.max_file_changes:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"File change limit exceeded: {state.file_changes} > "
                    f"{self._policy.max_file_changes}"
                ),
            )

        # 5. Autonomy approval check
        if agent_config.autonomy >= self._policy.require_approval_above:
            return PolicyDecision(
                allowed=True,
                reason=f"Action allowed but requires approval (autonomy={agent_config.autonomy.name})",
                requires_approval=True,
            )

        return PolicyDecision(allowed=True, reason="Action permitted by policy")
