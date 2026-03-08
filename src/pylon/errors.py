"""Pylon error hierarchy.

Structured error codes for API responses and internal handling.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ExitCode(enum.IntEnum):
    """Structured process exit codes for CLI and supervisors."""

    SUCCESS = 0
    INTERNAL_ERROR = 70
    SANDBOX_ERROR = 71
    AGENT_LIFECYCLE_ERROR = 72
    WORKFLOW_ERROR = 73
    PROVIDER_ERROR = 74
    POLICY_VIOLATION = 75
    PROMPT_INJECTION = 76
    APPROVAL_REQUIRED = 77
    CONFIG_INVALID = 78
    TASK_QUEUE_ERROR = 79
    SCHEDULER_ERROR = 80
    WORKER_ERROR = 81


class PylonError(Exception):
    """Base error for all Pylon errors."""

    code: str = "PYLON_INTERNAL_ERROR"
    status_code: int = 500
    exit_code: ExitCode = ExitCode.INTERNAL_ERROR
    retryable: bool = False
    category: str = "general"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "exit_code": int(self.exit_code),
                "message": self.message,
                "details": self.details,
                "retryable": self.retryable,
                "category": self.category,
            }
        }


class ConfigError(PylonError):
    """Invalid pylon.yaml configuration."""

    code = "CONFIG_INVALID"
    status_code = 400
    exit_code = ExitCode.CONFIG_INVALID
    retryable = False
    category = "validation"


class PolicyViolationError(PylonError):
    """Safety policy violated (Rule-of-Two+, autonomy, etc.)."""

    code = "POLICY_VIOLATION"
    status_code = 403
    exit_code = ExitCode.POLICY_VIOLATION
    retryable = False
    category = "safety"


class AgentLifecycleError(PylonError):
    """Invalid agent state transition."""

    code = "AGENT_LIFECYCLE_ERROR"
    status_code = 409
    exit_code = ExitCode.AGENT_LIFECYCLE_ERROR
    retryable = False
    category = "lifecycle"


class WorkflowError(PylonError):
    """Workflow execution error."""

    code = "WORKFLOW_ERROR"
    status_code = 500
    exit_code = ExitCode.WORKFLOW_ERROR
    retryable = False
    category = "lifecycle"


class SandboxError(PylonError):
    """Sandbox creation or execution error."""

    code = "SANDBOX_ERROR"
    status_code = 500
    exit_code = ExitCode.SANDBOX_ERROR
    retryable = False
    category = "safety"


class ProviderError(PylonError):
    """LLM provider error."""

    code = "PROVIDER_ERROR"
    status_code = 502
    exit_code = ExitCode.PROVIDER_ERROR
    retryable = True
    category = "infrastructure"


class PromptInjectionError(PylonError):
    """Prompt injection detected by Prompt Guard."""

    code = "PROMPT_INJECTION_DETECTED"
    status_code = 403
    exit_code = ExitCode.PROMPT_INJECTION
    retryable = False
    category = "safety"


class ApprovalRequiredError(PylonError):
    """Action requires human approval (A3+)."""

    code = "APPROVAL_REQUIRED"
    status_code = 202
    exit_code = ExitCode.APPROVAL_REQUIRED
    retryable = False
    category = "lifecycle"


class ConcurrencyError(PylonError):
    """Optimistic lock conflict on concurrent write."""

    code = "CONCURRENCY_CONFLICT"
    status_code = 409
    exit_code = ExitCode.WORKFLOW_ERROR
    retryable = True
    category = "infrastructure"


@dataclass(frozen=True)
class ErrorSpec:
    """Immutable metadata for a PylonError subclass."""

    code: str
    status_code: int
    exit_code: ExitCode
    retryable: bool
    category: str


ERROR_REGISTRY: dict[str, ErrorSpec] = {}


def _collect_subclasses(cls: type[PylonError]) -> list[type[PylonError]]:
    """Recursively collect all subclasses of a PylonError class."""
    result: list[type[PylonError]] = []
    for sub in cls.__subclasses__():
        result.append(sub)
        result.extend(_collect_subclasses(sub))
    return result


def _build_registry() -> None:
    """Populate ERROR_REGISTRY by introspecting all PylonError subclasses.

    Builds into a local dict first, then atomically swaps into the global
    registry to avoid TOCTOU races in multi-threaded servers.
    """
    new: dict[str, ErrorSpec] = {}
    for cls in _collect_subclasses(PylonError):
        spec = ErrorSpec(
            code=cls.code,
            status_code=cls.status_code,
            exit_code=cls.exit_code,
            retryable=cls.retryable,
            category=cls.category,
        )
        new[cls.code] = spec
    ERROR_REGISTRY.clear()
    ERROR_REGISTRY.update(new)


def resolve_error(code: str) -> ErrorSpec | None:
    """Look up error metadata by error code.

    Rebuilds the registry before lookup to ensure all subclasses are included.
    """
    _build_registry()
    return ERROR_REGISTRY.get(code)


def resolve_exit_code(exc: BaseException | None) -> ExitCode:
    """Resolve an exception into a structured process exit code."""
    if exc is None:
        return ExitCode.SUCCESS

    exit_code = getattr(exc, "exit_code", None)
    if isinstance(exit_code, ExitCode):
        return exit_code
    if isinstance(exit_code, int):
        try:
            return ExitCode(exit_code)
        except ValueError:
            return ExitCode.INTERNAL_ERROR
    return ExitCode.INTERNAL_ERROR


_build_registry()
