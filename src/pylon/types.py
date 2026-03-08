"""Core type definitions for Pylon platform.

Covers: Agent capabilities, lifecycle states, autonomy levels, policy config,
trust levels, sandbox tiers, and workflow primitives.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from pylon.errors import PolicyViolationError


class AutonomyLevel(enum.IntEnum):
    """Autonomy Ladder (ADR-004). A3+ requires human approval."""

    A0 = 0  # Manual: agent suggests, human executes
    A1 = 1  # Supervised: human approves each step
    A2 = 2  # Semi-autonomous: within policy bounds
    A3 = 3  # Autonomous-guarded: human approves plan
    A4 = 4  # Fully autonomous: within safety envelope


class AgentState(enum.Enum):
    """Agent lifecycle state machine (FR-02)."""

    INIT = "init"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"

    def can_transition_to(self, target: AgentState) -> bool:
        return target in _VALID_TRANSITIONS.get(self, set())


_VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.INIT: {AgentState.READY, AgentState.FAILED},
    AgentState.READY: {AgentState.RUNNING, AgentState.KILLED},
    AgentState.RUNNING: {
        AgentState.PAUSED,
        AgentState.COMPLETED,
        AgentState.FAILED,
        AgentState.KILLED,
    },
    AgentState.PAUSED: {AgentState.RUNNING, AgentState.KILLED},
    AgentState.COMPLETED: set(),
    AgentState.FAILED: set(),
    AgentState.KILLED: set(),
}


class TrustLevel(enum.Enum):
    """Input trust levels for Prompt Guard pipeline (Section 2.4)."""

    TRUSTED = "trusted"  # pylon.yaml (local)
    INTERNAL = "internal"  # User CLI input, memory recall
    UNTRUSTED = "untrusted"  # MCP responses, A2A input, GitHub content, LLM output


class SandboxTier(enum.Enum):
    """Execution isolation tiers (ADR-006, FR-05)."""

    GVISOR = "gvisor"  # Standard: <500ms, Linux only
    FIRECRACKER = "firecracker"  # High: <2s, Linux KVM
    DOCKER = "docker"  # Development: <1s, all platforms
    NONE = "none"  # Host process: requires SuperAdmin


class RunStatus(enum.StrEnum):
    """Shared workflow run phase across runtime and public surfaces."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStopReason(enum.StrEnum):
    """Machine-readable reason for run stop or suspension."""

    NONE = "none"
    LIMIT_EXCEEDED = "limit_exceeded"
    TIMEOUT_EXCEEDED = "timeout_exceeded"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    EXTERNAL_STOP = "external_stop"
    ESCALATION_REQUIRED = "escalation_required"
    STUCK_DETECTED = "stuck_detected"
    LOOP_EXHAUSTED = "loop_exhausted"
    QUALITY_REACHED = "quality_reached"
    QUALITY_FAILED = "quality_failed"
    STATE_CONFLICT = "state_conflict"
    WORKFLOW_ERROR = "workflow_error"


@dataclass(frozen=True)
class AgentCapability:
    """Agent capability model with Rule-of-Two+ enforcement (Section 2.3).

    No single agent may have all three capabilities.
    Additionally, untrusted input + secret access is a forbidden pair.
    """

    can_read_untrusted: bool = False
    can_access_secrets: bool = False
    can_write_external: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        flags = [self.can_read_untrusted, self.can_access_secrets, self.can_write_external]
        if all(flags):
            raise PolicyViolationError("Rule-of-Two: agent cannot have all three capabilities")
        if self.can_read_untrusted and self.can_access_secrets:
            raise PolicyViolationError("Forbidden pair: untrusted input + secret access")

    def can_grant(self, additional: AgentCapability) -> bool:
        """Check if granting additional capabilities would violate Rule-of-Two+."""
        merged_untrusted = self.can_read_untrusted or additional.can_read_untrusted
        merged_secrets = self.can_access_secrets or additional.can_access_secrets
        merged_write = self.can_write_external or additional.can_write_external
        if all([merged_untrusted, merged_secrets, merged_write]):
            return False
        if merged_untrusted and merged_secrets:
            return False
        return True


class WorkflowNodeType(enum.Enum):
    """Workflow graph node types (FR-03)."""

    AGENT = "agent"
    SUBGRAPH = "subgraph"
    ROUTER = "router"
    LOOP = "loop"


class WorkflowJoinPolicy(enum.Enum):
    """Inbound edge readiness policy for a workflow node."""

    ALL_RESOLVED = "all_resolved"
    ANY = "any"
    FIRST = "first"


@dataclass
class ConditionalEdge:
    """Conditional edge in workflow graph."""

    target: str  # Node ID or "END"
    condition: str | None = None  # Python expression or None for default


@dataclass
class WorkflowNode:
    """Node in the workflow graph."""

    id: str
    agent: str  # Agent name from agents section
    node_type: WorkflowNodeType = WorkflowNodeType.AGENT
    join_policy: WorkflowJoinPolicy = WorkflowJoinPolicy.ALL_RESOLVED
    loop_max_iterations: int | None = None
    loop_criterion: str | None = None
    loop_threshold: float | None = None
    loop_metadata: dict[str, Any] = field(default_factory=dict)
    next: list[ConditionalEdge] = field(default_factory=list)


@dataclass
class PolicyConfig:
    """Policy configuration from pylon.yaml."""

    max_cost_usd: float = 10.0
    max_duration_seconds: int = 3600  # 60m
    require_approval_above: AutonomyLevel = AutonomyLevel.A3
    blocked_actions: list[str] = field(default_factory=list)
    max_file_changes: int = 50
    audit_log: str = "required"
    allow_host_sandbox: bool = False


@dataclass
class SafetyConfig:
    """Safety sub-configuration."""

    blocked_actions: list[str] = field(default_factory=list)
    max_file_changes: int = 50


@dataclass
class AgentConfig:
    """Agent definition from pylon.yaml (FR-01)."""

    name: str
    model: str = ""  # Defaults to PYLON_DEFAULT_MODEL or anthropic/claude-sonnet-4-20250514
    role: str = ""
    autonomy: AutonomyLevel = AutonomyLevel.A2
    tools: list[str] = field(default_factory=list)
    sandbox: SandboxTier = SandboxTier.GVISOR
    input_trust: TrustLevel = TrustLevel.UNTRUSTED
    capability: AgentCapability = field(default_factory=AgentCapability)

    def requires_approval(self, policy: PolicyConfig) -> bool:
        return self.autonomy >= policy.require_approval_above


@dataclass
class WorkflowConfig:
    """Workflow definition from pylon.yaml."""

    type: str = "graph"
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)


@dataclass
class KillSwitchEvent:
    """Kill switch event payload (FR-10)."""

    scope: str  # "global", "tenant:{id}", "workflow:{id}", "agent:{id}"
    reason: str
    issued_by: str
    require_dual_approval: bool = False


@dataclass
class EventLogEntry:
    """Event log entry for deterministic replay (FR-03, ADR-007).

    Checkpoints are NOT state snapshots. They are event logs.
    """

    node_id: str
    input_data: Any
    llm_response: Any | None = None
    tool_results: list[Any] = field(default_factory=list)
    output_data: Any | None = None
    state_ref: str | None = None  # URI for large state (>1MB) stored in S3/MinIO
