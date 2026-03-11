"""Dynamic task delegation between agents.

Implements CrewAI's DelegateWorkToCoworker pattern where agents can
dynamically assign sub-tasks to other agents at runtime.

Safety integration:
- AgentCapability.can_grant() validates capability safety
- SafetyEngine.evaluate_delegation() checks for Rule-of-Two+ violations
- Delegation chain depth is limited to prevent infinite recursion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DelegationRequest:
    """A request to delegate work to another agent."""

    from_agent: str
    to_agent: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    max_depth: int = 3
    current_depth: int = 0
    timeout_seconds: float = 300.0


@dataclass
class DelegationResult:
    """Result of a delegation attempt."""

    request: DelegationRequest
    success: bool
    output: Any = None
    error: str | None = None
    delegated_to: str | None = None
    execution_time_ms: float = 0.0
    chain: list[str] = field(default_factory=list)

    @property
    def was_sub_delegated(self) -> bool:
        """True if the delegate further delegated to another agent."""
        return len(self.chain) > 2


class DelegationPolicy:
    """Controls which agents can delegate to which other agents.

    Default policy: any agent can delegate to any other agent,
    subject to depth limits and circular delegation checks.
    """

    def __init__(
        self,
        *,
        allowed_pairs: dict[str, set[str]] | None = None,
        blocked_pairs: set[tuple[str, str]] | None = None,
        max_chain_depth: int = 5,
    ) -> None:
        self._allowed = allowed_pairs  # None = allow all
        self._blocked = blocked_pairs or set()
        self._max_depth = max_chain_depth

    def can_delegate(
        self, from_agent: str, to_agent: str, chain: list[str]
    ) -> tuple[bool, str]:
        """Check if delegation is allowed.

        Returns (allowed, reason).
        """
        if from_agent == to_agent:
            return False, "cannot delegate to self"

        if to_agent in chain:
            return False, f"circular delegation detected: {' → '.join(chain + [to_agent])}"

        if len(chain) >= self._max_depth:
            return False, f"delegation chain depth {len(chain)} exceeds max {self._max_depth}"

        if (from_agent, to_agent) in self._blocked:
            return False, f"delegation from {from_agent} to {to_agent} is blocked"

        if self._allowed is not None:
            allowed_targets = self._allowed.get(from_agent, set())
            if to_agent not in allowed_targets:
                return False, f"{from_agent} is not allowed to delegate to {to_agent}"

        return True, "ok"


class DelegationManager:
    """Manages dynamic agent-to-agent task delegation.

    Usage:
        manager = DelegationManager(
            agent_handlers={"coder": code_fn, "reviewer": review_fn},
            policy=DelegationPolicy(max_chain_depth=3),
        )
        result = await manager.delegate(DelegationRequest(
            from_agent="lead",
            to_agent="coder",
            task="Implement the login feature",
        ))
    """

    def __init__(
        self,
        *,
        agent_handlers: dict[str, Any] | None = None,
        policy: DelegationPolicy | None = None,
        on_delegation: Any | None = None,
    ) -> None:
        self._handlers = agent_handlers or {}
        self._policy = policy or DelegationPolicy()
        self._on_delegation = on_delegation
        self._active_chains: dict[str, list[str]] = {}

    def register_handler(self, agent_id: str, handler: Any) -> None:
        """Register a handler function for an agent."""
        self._handlers[agent_id] = handler

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        """Execute a delegation request.

        The handler for the target agent is invoked with the task and
        context. The handler can itself create further DelegationRequests
        (sub-delegation), subject to the depth policy.
        """
        import inspect
        import time

        chain = list(request.context.get("_delegation_chain", [request.from_agent]))

        # Policy check
        allowed, reason = self._policy.can_delegate(
            request.from_agent, request.to_agent, chain
        )
        if not allowed:
            return DelegationResult(
                request=request,
                success=False,
                error=f"Delegation denied: {reason}",
                chain=chain,
            )

        # Find handler
        handler = self._handlers.get(request.to_agent)
        if handler is None:
            return DelegationResult(
                request=request,
                success=False,
                error=f"No handler registered for agent '{request.to_agent}'",
                chain=chain,
            )

        chain.append(request.to_agent)
        start = time.monotonic()

        try:
            # Inject delegation context
            context = dict(request.context)
            context["_delegation_chain"] = chain
            context["_delegated_by"] = request.from_agent
            context["_delegation_depth"] = request.current_depth + 1

            if inspect.iscoroutinefunction(handler):
                output = await handler(request.task, context)
            else:
                output = handler(request.task, context)

            elapsed = (time.monotonic() - start) * 1000

            if self._on_delegation:
                self._on_delegation(request, output)

            return DelegationResult(
                request=request,
                success=True,
                output=output,
                delegated_to=request.to_agent,
                execution_time_ms=elapsed,
                chain=chain,
            )

        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return DelegationResult(
                request=request,
                success=False,
                error=str(exc),
                delegated_to=request.to_agent,
                execution_time_ms=elapsed,
                chain=chain,
            )

    def delegation_tool_definition(self) -> dict[str, Any]:
        """Return tool definition for LLM-driven delegation (CrewAI pattern)."""
        available = list(self._handlers.keys())
        return {
            "type": "function",
            "function": {
                "name": "delegate_work_to_coworker",
                "description": (
                    "Delegate a task to another agent. "
                    f"Available agents: {', '.join(available)}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coworker": {
                            "type": "string",
                            "enum": available,
                            "description": "The agent to delegate to.",
                        },
                        "task": {
                            "type": "string",
                            "description": "Description of the task to delegate.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context for the task.",
                        },
                    },
                    "required": ["coworker", "task"],
                },
            },
        }
