"""Data flow taint tracking for prompt injection defense.

Implements the CaMeL pattern: track taint labels on data flowing from
LLM outputs through tool calls to prevent unauthorized actions via
prompt injection.

Key concepts:
- TaintSource: where data originates (LLM output, external input, etc.)
- TaintSink: where data is consumed (tool call, file write, etc.)
- TaintLabel: attached to data, tracks its provenance
- TaintPolicy: rules for what happens when tainted data reaches a sink
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class TaintSource(enum.Enum):
    """Origin of potentially untrusted data."""

    LLM_OUTPUT = "llm_output"
    EXTERNAL_INPUT = "external_input"
    MCP_RESPONSE = "mcp_response"
    A2A_INPUT = "a2a_input"  # Agent-to-agent
    USER_INPUT = "user_input"  # Trusted
    SYSTEM = "system"  # Trusted


class TaintSink(enum.Enum):
    """Destination where tainted data could cause harm."""

    TOOL_CALL = "tool_call"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    NETWORK_REQUEST = "network_request"
    SECRET_ACCESS = "secret_access"
    SHELL_COMMAND = "shell_command"
    DATABASE_QUERY = "database_query"


class TaintAction(enum.Enum):
    """Action to take when tainted data reaches a sink."""

    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"
    SANITIZE = "sanitize"
    LOG_ONLY = "log_only"


# Sources that are inherently untrusted
_UNTRUSTED_SOURCES = frozenset({
    TaintSource.LLM_OUTPUT,
    TaintSource.EXTERNAL_INPUT,
    TaintSource.MCP_RESPONSE,
    TaintSource.A2A_INPUT,
})

# High-risk sinks that require extra scrutiny
_HIGH_RISK_SINKS = frozenset({
    TaintSink.SHELL_COMMAND,
    TaintSink.SECRET_ACCESS,
    TaintSink.FILE_DELETE,
    TaintSink.DATABASE_QUERY,
})


@dataclass(frozen=True)
class TaintLabel:
    """Taint label attached to a piece of data."""

    source: TaintSource
    origin_id: str = ""  # e.g., message ID, tool call ID
    depth: int = 0  # How many processing steps from the source
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trusted(self) -> bool:
        return self.source not in _UNTRUSTED_SOURCES

    def propagate(self, new_depth: int | None = None) -> TaintLabel:
        """Create a propagated label (same source, incremented depth)."""
        return TaintLabel(
            source=self.source,
            origin_id=self.origin_id,
            depth=new_depth if new_depth is not None else self.depth + 1,
            metadata=dict(self.metadata),
        )


@dataclass
class TaintedValue:
    """A value with attached taint labels."""

    value: Any
    labels: list[TaintLabel] = field(default_factory=list)

    @property
    def is_tainted(self) -> bool:
        return any(not label.is_trusted for label in self.labels)

    @property
    def taint_sources(self) -> set[TaintSource]:
        return {label.source for label in self.labels if not label.is_trusted}

    def add_label(self, label: TaintLabel) -> None:
        self.labels.append(label)


@dataclass
class TaintCheckResult:
    """Result of checking tainted data at a sink."""

    allowed: bool
    action: TaintAction
    tainted_sources: set[TaintSource]
    sink: TaintSink
    reason: str = ""
    requires_approval: bool = False

    @property
    def severity(self) -> str:
        if self.action == TaintAction.BLOCK:
            return "critical"
        elif self.action == TaintAction.REQUIRE_APPROVAL:
            return "high"
        elif self.action == TaintAction.SANITIZE:
            return "medium"
        return "low"


class TaintPolicy:
    """Configurable policy for taint checking.

    Defines what action to take for each (source, sink) combination.
    """

    def __init__(self, rules: dict[tuple[TaintSource, TaintSink], TaintAction] | None = None) -> None:
        self._rules = rules or self._default_rules()

    def get_action(self, source: TaintSource, sink: TaintSink) -> TaintAction:
        """Get the action for a specific source-sink combination."""
        action = self._rules.get((source, sink))
        if action is not None:
            return action

        # Default: untrusted source + high-risk sink = require approval
        if source in _UNTRUSTED_SOURCES and sink in _HIGH_RISK_SINKS:
            return TaintAction.REQUIRE_APPROVAL

        # Untrusted source + any sink = log
        if source in _UNTRUSTED_SOURCES:
            return TaintAction.LOG_ONLY

        return TaintAction.ALLOW

    @staticmethod
    def _default_rules() -> dict[tuple[TaintSource, TaintSink], TaintAction]:
        """Default CaMeL-inspired taint policy."""
        rules: dict[tuple[TaintSource, TaintSink], TaintAction] = {}

        # LLM output → high-risk sinks: always require approval
        for sink in _HIGH_RISK_SINKS:
            rules[(TaintSource.LLM_OUTPUT, sink)] = TaintAction.REQUIRE_APPROVAL

        # External input → any sink: require approval
        for sink in TaintSink:
            rules[(TaintSource.EXTERNAL_INPUT, sink)] = TaintAction.REQUIRE_APPROVAL

        # MCP response → tool call: sanitize
        rules[(TaintSource.MCP_RESPONSE, TaintSink.TOOL_CALL)] = TaintAction.SANITIZE

        # LLM → tool call: allow (normal operation)
        rules[(TaintSource.LLM_OUTPUT, TaintSink.TOOL_CALL)] = TaintAction.ALLOW

        # LLM → file write: allow (normal operation)
        rules[(TaintSource.LLM_OUTPUT, TaintSink.FILE_WRITE)] = TaintAction.ALLOW

        return rules


class TaintTracker:
    """Tracks data provenance through the execution pipeline.

    Usage:
        tracker = TaintTracker()

        # When LLM produces output:
        tainted = tracker.taint("rm -rf /", TaintSource.LLM_OUTPUT)

        # When that output is used in a tool call:
        result = tracker.check_sink(tainted, TaintSink.SHELL_COMMAND)
        if result.requires_approval:
            # Request human approval before executing
            pass
    """

    def __init__(self, policy: TaintPolicy | None = None) -> None:
        self._policy = policy or TaintPolicy()
        self._tracked: dict[str, TaintedValue] = {}
        self._check_log: list[TaintCheckResult] = []
        self._log_max = 10000

    def taint(
        self,
        value: Any,
        source: TaintSource,
        *,
        origin_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaintedValue:
        """Apply a taint label to a value."""
        label = TaintLabel(
            source=source,
            origin_id=origin_id,
            metadata=metadata or {},
        )
        tainted = TaintedValue(value=value, labels=[label])

        # Track for later lookup
        if origin_id:
            self._tracked[origin_id] = tainted

        return tainted

    def check_sink(
        self,
        value: Any,
        sink: TaintSink,
    ) -> TaintCheckResult:
        """Check if a value is safe to use at a sink.

        This is the core security checkpoint. Call this before executing
        any sensitive operation with potentially tainted data.
        """
        if isinstance(value, TaintedValue):
            tainted = value
        elif isinstance(value, str) and value in self._tracked:
            tainted = self._tracked[value]
        else:
            return TaintCheckResult(
                allowed=True,
                action=TaintAction.ALLOW,
                tainted_sources=set(),
                sink=sink,
                reason="value is not tainted",
            )

        if not tainted.is_tainted:
            return TaintCheckResult(
                allowed=True,
                action=TaintAction.ALLOW,
                tainted_sources=set(),
                sink=sink,
                reason="all sources are trusted",
            )

        # Check each taint source against the sink
        actions: list[TaintAction] = []
        for label in tainted.labels:
            if not label.is_trusted:
                action = self._policy.get_action(label.source, sink)
                actions.append(action)

        # Take the most restrictive action
        if TaintAction.BLOCK in actions:
            final_action = TaintAction.BLOCK
        elif TaintAction.REQUIRE_APPROVAL in actions:
            final_action = TaintAction.REQUIRE_APPROVAL
        elif TaintAction.SANITIZE in actions:
            final_action = TaintAction.SANITIZE
        elif TaintAction.LOG_ONLY in actions:
            final_action = TaintAction.LOG_ONLY
        else:
            final_action = TaintAction.ALLOW

        result = TaintCheckResult(
            allowed=final_action in (TaintAction.ALLOW, TaintAction.LOG_ONLY),
            action=final_action,
            tainted_sources=tainted.taint_sources,
            sink=sink,
            reason=f"tainted by {', '.join(s.value for s in tainted.taint_sources)}",
            requires_approval=final_action == TaintAction.REQUIRE_APPROVAL,
        )

        self._record_check(result)
        return result

    def propagate(
        self,
        operation: str,
        inputs: list[Any],
    ) -> list[TaintLabel]:
        """Propagate taint through a data transformation.

        When multiple tainted inputs are combined, the output inherits
        all taint labels with incremented depth.
        """
        labels: list[TaintLabel] = []
        for inp in inputs:
            if isinstance(inp, TaintedValue):
                for label in inp.labels:
                    labels.append(label.propagate())
        return labels

    def get_check_log(self, *, limit: int = 100) -> list[TaintCheckResult]:
        """Get recent taint check results for audit."""
        return self._check_log[-limit:]

    def get_blocked_count(self) -> int:
        """Count of checks that resulted in BLOCK."""
        return sum(
            1 for r in self._check_log if r.action == TaintAction.BLOCK
        )

    def get_approval_required_count(self) -> int:
        """Count of checks that required approval."""
        return sum(1 for r in self._check_log if r.requires_approval)

    def _record_check(self, result: TaintCheckResult) -> None:
        self._check_log.append(result)
        if len(self._check_log) > self._log_max:
            self._check_log = self._check_log[-self._log_max:]
