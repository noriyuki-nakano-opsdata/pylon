"""Structured node execution results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.errors import WorkflowError
from pylon.safety.scrubber import scrub_secrets


@dataclass(frozen=True)
class NodeResult:
    """Structured output emitted by a workflow node."""

    state_patch: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    edge_decisions: dict[str, bool] = field(default_factory=dict)
    llm_events: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    event_output: dict[str, Any] | None = None
    requires_approval: bool = False
    approval_request_id: str | None = None
    approval_reason: str = ""

    @classmethod
    def from_raw(cls, value: Any) -> NodeResult:
        """Normalize legacy handler output into a structured node result."""
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(state_patch=dict(value))
        raise WorkflowError(
            "Workflow node handler must return dict or NodeResult",
            details={"result_type": type(value).__name__},
        )

    def to_event_dict(self, *, scrub_metadata: bool = False) -> dict[str, Any]:
        """Serialize the node result for event logs and checkpoints."""
        artifacts = list(self.artifacts)
        llm_events = list(self.llm_events)
        tool_events = list(self.tool_events)
        metrics = dict(self.metrics)
        if scrub_metadata:
            artifacts = scrub_secrets(artifacts)
            llm_events = scrub_secrets(llm_events)
            tool_events = scrub_secrets(tool_events)
            metrics = scrub_secrets(metrics)

        return {
            "state_patch": dict(self.state_patch),
            "output": (
                dict(self.event_output)
                if self.event_output is not None
                else dict(self.state_patch)
            ),
            "artifacts": artifacts,
            "edge_decisions": dict(self.edge_decisions),
            "llm_events": llm_events,
            "tool_events": tool_events,
            "metrics": metrics,
            "requires_approval": self.requires_approval,
            "approval_request_id": self.approval_request_id,
            "approval_reason": self.approval_reason,
        }
