"""ConfigValidator - Schema-based configuration validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldConstraint:
    """Constraint for a config field."""

    field_name: str
    field_type: type | None = None  # expected type after coercion
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    choices: list[Any] | None = None


@dataclass
class ConfigSchema:
    """Schema definition for config validation."""

    name: str
    fields: list[FieldConstraint] = field(default_factory=list)

    def get_field(self, name: str) -> FieldConstraint | None:
        for f in self.fields:
            if f.field_name == name:
                return f
        return None


@dataclass
class ValidationError:
    """Single validation error."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)


def _coerce_value(value: Any, target_type: type) -> Any:
    """Coerce string values to target types."""
    if isinstance(value, target_type):
        return value
    if target_type is bool and isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    if target_type is int and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    if target_type is float and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    return value


class ConfigValidator:
    """Validates configuration against a schema."""

    @staticmethod
    def validate(config: dict[str, Any], schema: ConfigSchema) -> ValidationResult:
        """Validate a config dict against a schema. Returns ValidationResult."""
        errors: list[ValidationError] = []

        for fc in schema.fields:
            value = config.get(fc.field_name)

            if value is None:
                if fc.required:
                    errors.append(ValidationError(fc.field_name, "required field is missing"))
                continue

            if fc.field_type is not None:
                coerced = _coerce_value(value, fc.field_type)
                if not isinstance(coerced, fc.field_type):
                    errors.append(
                        ValidationError(
                            fc.field_name,
                            f"expected {fc.field_type.__name__}, got {type(value).__name__}",
                        )
                    )
                    continue
                config[fc.field_name] = coerced
                value = coerced

            if fc.min_value is not None and isinstance(value, (int, float)):
                if value < fc.min_value:
                    errors.append(
                        ValidationError(fc.field_name, f"value {value} < minimum {fc.min_value}")
                    )

            if fc.max_value is not None and isinstance(value, (int, float)):
                if value > fc.max_value:
                    errors.append(
                        ValidationError(fc.field_name, f"value {value} > maximum {fc.max_value}")
                    )

            if fc.choices is not None and value not in fc.choices:
                errors.append(
                    ValidationError(fc.field_name, f"value {value!r} not in {fc.choices}")
                )

        return ValidationResult(valid=len(errors) == 0, errors=errors)


# Pre-built schemas

AgentConfigSchema = ConfigSchema(
    name="agent",
    fields=[
        FieldConstraint("name", str, required=True),
        FieldConstraint("model", str),
        FieldConstraint("role", str),
        FieldConstraint("autonomy", str, choices=["A0", "A1", "A2", "A3", "A4"]),
        FieldConstraint("sandbox", str, choices=["gvisor", "firecracker", "docker", "none"]),
    ],
)

WorkflowConfigSchema = ConfigSchema(
    name="workflow",
    fields=[
        FieldConstraint("type", str, required=True, choices=["graph"]),
    ],
)

ServerConfigSchema = ConfigSchema(
    name="server",
    fields=[
        FieldConstraint("host", str),
        FieldConstraint("port", int, min_value=1, max_value=65535),
        FieldConstraint("debug", bool),
    ],
)
