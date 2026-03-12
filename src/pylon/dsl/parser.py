"""pylon.yaml parser with Pydantic v2 strict validation (FR-01).

Supports YAML, JSON, and Python dict input.
Configuration priority: Environment variables > pylon.yaml > built-in defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from pylon.autonomy.goals import (
    FailurePolicy,
    GoalConstraints,
    GoalSpec,
    RefinementPolicy,
    RunCompletionPolicy,
    SuccessCriterion,
)
from pylon.types import AutonomyLevel, SandboxTier, TrustLevel, WorkflowJoinPolicy

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-20250514"


def _duration_to_seconds(value: str | int | float) -> int:
    """Parse duration string (30m, 1h, 90s) to seconds."""
    if isinstance(value, (int, float)):
        return int(value)
    value = value.strip().lower()
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("s"):
        return int(value[:-1])
    return int(value)


class AgentDef(BaseModel):
    """Agent definition in pylon.yaml."""

    model: str = ""
    role: str = ""
    autonomy: str = "A2"
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    sandbox: str = "gvisor"
    input_trust: str = "untrusted"

    @field_validator("autonomy")
    @classmethod
    def validate_autonomy(cls, v: str) -> str:
        valid = {"A0", "A1", "A2", "A3", "A4"}
        if v.upper() not in valid:
            msg = f"Invalid autonomy level: {v}. Must be one of {valid}"
            raise ValueError(msg)
        return v.upper()

    @field_validator("sandbox")
    @classmethod
    def validate_sandbox(cls, v: str) -> str:
        valid = {t.value for t in SandboxTier}
        if v.lower() not in valid:
            msg = f"Invalid sandbox tier: {v}. Must be one of {valid}"
            raise ValueError(msg)
        return v.lower()

    @field_validator("input_trust")
    @classmethod
    def validate_trust(cls, v: str) -> str:
        valid = {t.value for t in TrustLevel}
        if v.lower() not in valid:
            msg = f"Invalid trust level: {v}. Must be one of {valid}"
            raise ValueError(msg)
        return v.lower()

    def resolve_model(self) -> str:
        if self.model:
            return self.model
        return os.environ.get("PYLON_DEFAULT_MODEL", _DEFAULT_MODEL)

    def to_autonomy_level(self) -> AutonomyLevel:
        return AutonomyLevel[self.autonomy]

    def to_sandbox_tier(self) -> SandboxTier:
        return SandboxTier(self.sandbox)

    def to_trust_level(self) -> TrustLevel:
        return TrustLevel(self.input_trust)


class ConditionalNext(BaseModel):
    """Conditional edge target."""

    target: str
    condition: str | None = None


class WorkflowNodeDef(BaseModel):
    """Workflow node definition."""

    agent: str
    node_type: str = "agent"
    join_policy: WorkflowJoinPolicy = WorkflowJoinPolicy.ALL_RESOLVED
    loop_max_iterations: int | None = None
    loop_criterion: str | None = None
    loop_threshold: float | None = None
    loop_metadata: dict[str, Any] = Field(default_factory=dict)
    next: str | list[ConditionalNext | str] | None = None

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, v: str) -> str:
        valid = {"agent", "subgraph", "router", "loop"}
        if v.lower() not in valid:
            msg = f"Invalid workflow node type: {v}. Must be one of {valid}"
            raise ValueError(msg)
        return v.lower()

    @field_validator("next", mode="before")
    @classmethod
    def normalize_next(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    result.append(ConditionalNext(target=item))
                elif isinstance(item, dict):
                    result.append(ConditionalNext(**item))
                else:
                    result.append(item)
            return result
        return v


class SafetyDef(BaseModel):
    """Safety policy sub-section."""

    blocked_actions: list[str] = Field(default_factory=list)
    max_file_changes: int = 50


class ComplianceDef(BaseModel):
    """Compliance sub-section."""

    audit_log: str = "required"


class PolicyDef(BaseModel):
    """Policy section of pylon.yaml."""

    max_cost_usd: float = 10.0
    max_duration: str | int = "60m"
    require_approval_above: str = "A3"
    safety: SafetyDef = Field(default_factory=SafetyDef)
    compliance: ComplianceDef = Field(default_factory=ComplianceDef)

    @field_validator("require_approval_above")
    @classmethod
    def validate_approval_level(cls, v: str) -> str:
        valid = {"A0", "A1", "A2", "A3", "A4"}
        if v.upper() not in valid:
            msg = f"Invalid autonomy level: {v}"
            raise ValueError(msg)
        return v.upper()

    def max_duration_seconds(self) -> int:
        return _duration_to_seconds(self.max_duration)


class WorkflowDef(BaseModel):
    """Workflow section of pylon.yaml."""

    type: Literal["graph"] = "graph"
    nodes: dict[str, WorkflowNodeDef] = Field(default_factory=dict)


class GoalCriterionDef(BaseModel):
    """Goal success criterion declaration."""

    type: str
    threshold: float | None = None
    rubric: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalConstraintsDef(BaseModel):
    """Goal-specific resource ceilings."""

    max_iterations: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    timeout: str | int | float | None = None
    max_replans: int | None = None

    def to_goal_constraints(self) -> GoalConstraints:
        timeout_seconds = (
            _duration_to_seconds(self.timeout) if self.timeout is not None else None
        )
        return GoalConstraints(
            max_iterations=self.max_iterations,
            max_tokens=self.max_tokens,
            max_cost_usd=self.max_cost_usd,
            timeout_seconds=timeout_seconds,
            max_replans=self.max_replans,
        )


class GoalRefinementDef(BaseModel):
    """Explicit refinement policy declaration."""

    max_replans: int | None = None
    exhaustion_policy: FailurePolicy | None = None

    def to_refinement_policy(self) -> RefinementPolicy:
        return RefinementPolicy(
            max_replans=self.max_replans,
            exhaustion_policy=self.exhaustion_policy,
        )


class GoalDef(BaseModel):
    """Optional top-level goal declaration for bounded autonomy."""

    objective: str
    success_criteria: list[GoalCriterionDef] = Field(default_factory=list)
    constraints: GoalConstraintsDef = Field(default_factory=GoalConstraintsDef)
    failure_policy: FailurePolicy = FailurePolicy.ESCALATE
    completion_policy: RunCompletionPolicy = RunCompletionPolicy.REQUIRE_WORKFLOW_END
    refinement: GoalRefinementDef = Field(default_factory=GoalRefinementDef)
    allowed_effect_scopes: list[str] = Field(default_factory=list)
    allowed_secret_scopes: list[str] = Field(default_factory=list)

    def to_goal_spec(self) -> GoalSpec:
        return GoalSpec(
            objective=self.objective,
            success_criteria=tuple(
                SuccessCriterion(
                    type=criterion.type,
                    threshold=criterion.threshold,
                    rubric=criterion.rubric,
                    metadata=dict(criterion.metadata),
                )
                for criterion in self.success_criteria
            ),
            constraints=self.constraints.to_goal_constraints(),
            failure_policy=self.failure_policy,
            completion_policy=self.completion_policy,
            refinement_policy=self.refinement.to_refinement_policy(),
            allowed_effect_scopes=frozenset(self.allowed_effect_scopes),
            allowed_secret_scopes=frozenset(self.allowed_secret_scopes),
        )


class PylonProject(BaseModel):
    """Top-level pylon.yaml project model.

    30 lines for Hello World, scales to enterprise.
    """

    version: str = "1"
    name: str
    description: str = ""
    agents: dict[str, AgentDef] = Field(default_factory=dict)
    workflow: WorkflowDef = Field(default_factory=WorkflowDef)
    policy: PolicyDef = Field(default_factory=PolicyDef)
    goal: GoalDef | None = None

    @model_validator(mode="after")
    def validate_workflow_agents(self) -> PylonProject:
        """Ensure all workflow nodes reference defined agents."""
        for node_id, node in self.workflow.nodes.items():
            if node.agent not in self.agents:
                msg = f"Workflow node '{node_id}' references undefined agent '{node.agent}'"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_workflow_targets(self) -> PylonProject:
        """Ensure all edge targets reference defined nodes or END."""
        valid_targets = set(self.workflow.nodes.keys()) | {"END"}
        for node_id, node in self.workflow.nodes.items():
            if node.next is None:
                continue
            if isinstance(node.next, str):
                if node.next not in valid_targets:
                    msg = f"Node '{node_id}' targets undefined node '{node.next}'"
                    raise ValueError(msg)
            elif isinstance(node.next, list):
                for edge in node.next:
                    target = edge.target if isinstance(edge, ConditionalNext) else edge
                    if target not in valid_targets:
                        msg = f"Node '{node_id}' targets undefined node '{target}'"
                        raise ValueError(msg)
        return self


def load_project(path: str | Path) -> PylonProject:
    """Load and validate a pylon.yaml project file.

    Args:
        path: Path to pylon.yaml, pylon.json, or directory containing pylon.yaml

    Returns:
        Validated PylonProject instance

    Raises:
        FileNotFoundError: If file doesn't exist
        pydantic.ValidationError: If validation fails
    """
    path = Path(path)
    if path.is_dir():
        for name in ("pylon.yaml", "pylon.yml", "pylon.json"):
            candidate = path / name
            if candidate.exists():
                path = candidate
                break
        else:
            msg = f"No pylon.yaml found in {path}"
            raise FileNotFoundError(msg)

    content = path.read_text()

    if path.suffix == ".json":
        import json
        data = json.loads(content)
    else:
        data = yaml.safe_load(content) or {}

    return PylonProject.model_validate(data)
