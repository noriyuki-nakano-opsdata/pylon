"""Pylon error hierarchy.

Structured error codes for API responses and internal handling.
"""

from __future__ import annotations


class PylonError(Exception):
    """Base error for all Pylon errors."""

    code: str = "PYLON_INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ConfigError(PylonError):
    """Invalid pylon.yaml configuration."""

    code = "CONFIG_INVALID"
    status_code = 400


class PolicyViolationError(PylonError):
    """Safety policy violated (Rule-of-Two+, autonomy, etc.)."""

    code = "POLICY_VIOLATION"
    status_code = 403


class AgentLifecycleError(PylonError):
    """Invalid agent state transition."""

    code = "AGENT_LIFECYCLE_ERROR"
    status_code = 409


class WorkflowError(PylonError):
    """Workflow execution error."""

    code = "WORKFLOW_ERROR"
    status_code = 500


class SandboxError(PylonError):
    """Sandbox creation or execution error."""

    code = "SANDBOX_ERROR"
    status_code = 500


class ProviderError(PylonError):
    """LLM provider error."""

    code = "PROVIDER_ERROR"
    status_code = 502


class PromptInjectionError(PylonError):
    """Prompt injection detected by Prompt Guard."""

    code = "PROMPT_INJECTION_DETECTED"
    status_code = 403


class ApprovalRequiredError(PylonError):
    """Action requires human approval (A3+)."""

    code = "APPROVAL_REQUIRED"
    status_code = 202


class ImmutableEntryError(PylonError):
    """Attempt to modify or delete a WORM audit entry."""

    code = "IMMUTABLE_ENTRY"
    status_code = 403


class IntegrityViolationError(PylonError):
    """Audit chain verification failed."""

    code = "INTEGRITY_VIOLATION"
    status_code = 500


class ImportValidationError(PylonError):
    """JSONL import failed verification."""

    code = "IMPORT_VALIDATION_ERROR"
    status_code = 400
