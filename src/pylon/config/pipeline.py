"""Layered validation pipeline for configuration and project definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError as PydanticValidationError

from pylon.api.schemas import Schema
from pylon.api.schemas import validate as validate_api_schema
from pylon.config.validator import ConfigSchema, ConfigValidator
from pylon.dsl.parser import AgentDef, GoalDef, PolicyDef, WorkflowNodeDef

ValidationStage = Literal["schema", "semantic", "referential", "protocol"]
ValidationSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    stage: ValidationStage
    field: str
    message: str
    severity: ValidationSeverity = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationContext:
    agents: dict[str, Any] = field(default_factory=dict)
    workflow_nodes: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    config_schema: ConfigSchema | None = None
    api_schema: Schema | None = None


@dataclass
class PipelineResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    stages_passed: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    def to_dict(self, *, source: str = "project_definition") -> dict[str, Any]:
        return build_validation_report(self, source=source)


StageHandler = Callable[[dict[str, Any], ValidationContext], list[ValidationIssue]]


class ValidationPipeline:
    """Sequential fail-fast validation pipeline."""

    def __init__(
        self,
        stages: list[tuple[ValidationStage, StageHandler]] | None = None,
        *,
        fail_fast: bool = True,
    ) -> None:
        self._stages = stages or []
        self._fail_fast = fail_fast

    def run(
        self,
        config: dict[str, Any],
        context: ValidationContext | None = None,
    ) -> PipelineResult:
        context = context or ValidationContext()
        issues: list[ValidationIssue] = []
        stages_passed: list[str] = []

        for stage_name, stage_handler in self._stages:
            stage_issues = stage_handler(config, context)
            issues.extend(stage_issues)
            has_errors = any(issue.severity == "error" for issue in stage_issues)
            if has_errors:
                if self._fail_fast:
                    break
            else:
                stages_passed.append(stage_name)

        return PipelineResult(
            valid=not any(issue.severity == "error" for issue in issues),
            issues=issues,
            stages_passed=stages_passed,
        )

    @classmethod
    def for_config_schema(cls, schema: ConfigSchema) -> ValidationPipeline:
        return cls(
            stages=[("schema", lambda config, _: _config_schema_stage(config, schema))],
        )

    @classmethod
    def for_api_schema(cls, schema: Schema) -> ValidationPipeline:
        return cls(
            stages=[("schema", lambda config, _: _api_schema_stage(config, schema))],
        )

    @classmethod
    def for_project_definition(cls) -> ValidationPipeline:
        return cls(
            stages=[
                ("schema", _project_schema_stage),
                ("semantic", _project_semantic_stage),
                ("referential", _project_referential_stage),
                ("protocol", _project_protocol_stage),
            ],
        )


def validate_project_definition(config: dict[str, Any]) -> PipelineResult:
    """Validate a raw workflow project dict with layered stages."""
    context = ValidationContext(
        agents=_as_dict(config.get("agents")),
        workflow_nodes=_as_dict(_as_dict(config.get("workflow")).get("nodes")),
        policy=_as_dict(config.get("policy")),
    )
    return ValidationPipeline.for_project_definition().run(config, context)


def build_validation_report(
    result: PipelineResult,
    *,
    source: str = "project_definition",
) -> dict[str, Any]:
    """Normalize validation results into a public report shape."""
    return {
        "source": source,
        "valid": result.valid,
        "stages_passed": list(result.stages_passed),
        "issues": [issue.to_dict() for issue in result.issues],
        "errors": [issue.to_dict() for issue in result.errors],
        "warnings": [issue.to_dict() for issue in result.warnings],
        "summary": {
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
        },
    }


def _config_schema_stage(config: dict[str, Any], schema: ConfigSchema) -> list[ValidationIssue]:
    result = ConfigValidator.validate(dict(config), schema)
    return [
        ValidationIssue(stage="schema", field=error.field, message=error.message)
        for error in result.errors
    ]


def _api_schema_stage(config: dict[str, Any], schema: Schema) -> list[ValidationIssue]:
    valid, errors = validate_api_schema(config, schema)
    if valid:
        return []
    return [
        ValidationIssue(stage="schema", field="body", message=message)
        for message in errors
    ]


def _project_schema_stage(
    config: dict[str, Any],
    _context: ValidationContext,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(config, dict):
        return [
            ValidationIssue(
                stage="schema",
                field="project",
                message="Project definition must be a mapping",
            )
        ]

    if not isinstance(config.get("name"), str) or not str(config.get("name", "")).strip():
        issues.append(
            ValidationIssue(stage="schema", field="name", message="Project name is required")
        )

    for field_name in ("agents", "workflow", "policy", "goal"):
        value = config.get(field_name)
        if value is not None and not isinstance(value, dict):
            issues.append(
                ValidationIssue(
                    stage="schema",
                    field=field_name,
                    message=f"Field '{field_name}' must be a mapping",
                )
            )

    workflow = _as_dict(config.get("workflow"))
    nodes = workflow.get("nodes")
    if nodes is not None and not isinstance(nodes, dict):
        issues.append(
            ValidationIssue(
                stage="schema",
                field="workflow.nodes",
                message="Field 'workflow.nodes' must be a mapping",
            )
        )

    return issues


def _project_semantic_stage(
    config: dict[str, Any],
    context: ValidationContext,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for agent_name, payload in context.agents.items():
        if not isinstance(payload, dict):
            issues.append(
                ValidationIssue(
                    stage="semantic",
                    field=f"agents.{agent_name}",
                    message="Agent definition must be a mapping",
                )
            )
            continue
        issues.extend(_pydantic_issues(f"agents.{agent_name}", payload, AgentDef))

    for node_id, payload in context.workflow_nodes.items():
        if not isinstance(payload, dict):
            issues.append(
                ValidationIssue(
                    stage="semantic",
                    field=f"workflow.nodes.{node_id}",
                    message="Workflow node definition must be a mapping",
                )
            )
            continue
        issues.extend(_pydantic_issues(f"workflow.nodes.{node_id}", payload, WorkflowNodeDef))

    policy = context.policy
    if policy:
        issues.extend(_pydantic_issues("policy", policy, PolicyDef))

    goal = _as_dict(config.get("goal"))
    if goal:
        issues.extend(_pydantic_issues("goal", goal, GoalDef))

    return issues


def _project_referential_stage(
    _config: dict[str, Any],
    context: ValidationContext,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    agents = context.agents
    nodes = context.workflow_nodes
    valid_targets = set(nodes) | {"END"}

    for node_id, payload in nodes.items():
        if not isinstance(payload, dict):
            continue

        agent_name = payload.get("agent")
        if isinstance(agent_name, str) and agent_name not in agents:
            issues.append(
                ValidationIssue(
                    stage="referential",
                    field=f"workflow.nodes.{node_id}.agent",
                    message=f"Undefined agent reference: {agent_name}",
                )
            )

        issues.extend(_target_issues(node_id, payload.get("next"), valid_targets))

    return issues


def _project_protocol_stage(
    _config: dict[str, Any],
    context: ValidationContext,
) -> list[ValidationIssue]:
    nodes = context.workflow_nodes
    if not nodes:
        return []

    targeted: set[str] = set()
    for payload in nodes.values():
        if not isinstance(payload, dict):
            continue
        for target in _extract_targets(payload.get("next")):
            if target != "END":
                targeted.add(target)

    entry_points = sorted(set(nodes) - targeted)
    if not entry_points:
        return [
            ValidationIssue(
                stage="protocol",
                field="workflow.nodes",
                message="No entry point found",
            )
        ]
    if len(entry_points) > 1:
        return [
            ValidationIssue(
                stage="protocol",
                field="workflow.nodes",
                message=f"Multiple entry points detected: {entry_points}",
                severity="warning",
            )
        ]
    return []


def _pydantic_issues(prefix: str, payload: dict[str, Any], model: Any) -> list[ValidationIssue]:
    try:
        model.model_validate(payload)
    except PydanticValidationError as exc:
        issues: list[ValidationIssue] = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", ()))
            field = prefix if not loc else f"{prefix}.{loc}"
            issues.append(
                ValidationIssue(
                    stage="semantic",
                    field=field,
                    message=error.get("msg", "validation error"),
                )
            )
        return issues
    return []


def _target_issues(
    node_id: str,
    next_payload: Any,
    valid_targets: set[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, target in enumerate(_extract_targets(next_payload)):
        if target not in valid_targets:
            field = f"workflow.nodes.{node_id}.next"
            if isinstance(next_payload, list):
                field = f"{field}[{index}]"
            issues.append(
                ValidationIssue(
                    stage="referential",
                    field=field,
                    message=f"Undefined workflow target: {target}",
                )
            )
    return issues


def _extract_targets(next_payload: Any) -> list[str]:
    if next_payload is None:
        return []
    if isinstance(next_payload, str):
        return [next_payload]
    if isinstance(next_payload, list):
        targets: list[str] = []
        for item in next_payload:
            if isinstance(item, str):
                targets.append(item)
            elif isinstance(item, dict) and isinstance(item.get("target"), str):
                targets.append(item["target"])
        return targets
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
