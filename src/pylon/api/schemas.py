"""Pydantic-free schema validation for API requests.

Each schema is a dict mapping field names to validation rules.
validate() returns (valid: bool, errors: list[str]).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_UNSET = object()


@dataclass(frozen=True)
class FieldRule:
    """Validation rule for a single field."""

    required: bool = True
    field_type: type | tuple[type, ...] = str
    min_length: int | None = None
    max_length: int | None = None
    choices: list[Any] | None = None
    default: Any = _UNSET


Schema = dict[str, FieldRule]


def validate(data: dict, schema: Schema) -> tuple[bool, list[str]]:
    """Validate data against a schema.

    Returns (valid, errors).
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["Request body must be a JSON object"]

    for field_name, rule in schema.items():
        has_value = field_name in data
        value = data.get(field_name, _UNSET)

        if not has_value:
            if rule.required and rule.default is _UNSET:
                errors.append(f"Field '{field_name}' is required")
            continue

        allows_null = rule.field_type is type(None) or (
            isinstance(rule.field_type, tuple) and type(None) in rule.field_type
        )
        if value is None and not allows_null:
            errors.append(f"Field '{field_name}' must not be null")
            continue

        if not isinstance(value, rule.field_type):
            type_names = (
                rule.field_type.__name__
                if isinstance(rule.field_type, type)
                else " | ".join(t.__name__ for t in rule.field_type)
            )
            errors.append(f"Field '{field_name}' must be of type {type_names}")
            continue

        if rule.min_length is not None and isinstance(value, str) and len(value) < rule.min_length:
            errors.append(f"Field '{field_name}' must be at least {rule.min_length} characters")

        if rule.max_length is not None and isinstance(value, str) and len(value) > rule.max_length:
            errors.append(f"Field '{field_name}' must be at most {rule.max_length} characters")

        if rule.choices is not None and value not in rule.choices:
            errors.append(f"Field '{field_name}' must be one of {rule.choices}")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Concrete schemas
# ---------------------------------------------------------------------------

CREATE_AGENT_SCHEMA: Schema = {
    "name": FieldRule(required=True, field_type=str, min_length=1, max_length=128),
    "model": FieldRule(required=False, field_type=str, default=""),
    "role": FieldRule(required=False, field_type=str, default=""),
    "autonomy": FieldRule(
        required=False,
        field_type=(str, int),
        choices=["A0", "A1", "A2", "A3", "A4", 0, 1, 2, 3, 4],
        default="A2",
    ),
    "tools": FieldRule(required=False, field_type=list, default=[]),
    "sandbox": FieldRule(
        required=False,
        field_type=str,
        choices=["gvisor", "firecracker", "docker", "none"],
        default="gvisor",
    ),
}

WORKFLOW_RUN_SCHEMA: Schema = {
    "input": FieldRule(required=False, field_type=dict, default={}),
    "parameters": FieldRule(required=False, field_type=dict, default={}),
    "idempotency_key": FieldRule(required=False, field_type=str, default=""),
    "execution_mode": FieldRule(
        required=False,
        field_type=str,
        choices=["inline", "queued"],
        default="inline",
    ),
}

WORKFLOW_DEFINITION_SCHEMA: Schema = {
    "id": FieldRule(required=True, field_type=str, min_length=1),
    "project": FieldRule(required=True, field_type=dict),
}

APPROVAL_DECISION_SCHEMA: Schema = {
    "reason": FieldRule(required=False, field_type=str, default=""),
}

KILL_SWITCH_SCHEMA: Schema = {
    "scope": FieldRule(required=True, field_type=str, min_length=1),
    "reason": FieldRule(required=True, field_type=str, min_length=1),
    "issued_by": FieldRule(required=True, field_type=str, min_length=1),
    "parent_scope": FieldRule(required=False, field_type=str, default=""),
}
