from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pylon.sdk.config import SDKConfig


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentHandle:
    """A reference to a registered agent."""

    id: str
    name: str
    role: str
    capabilities: list[str]
    tools: list[str]


@dataclass
class WorkflowResult:
    """The outcome of a completed workflow run."""

    run_id: str
    status: RunStatus
    output: Any = None
    error: str | None = None


@dataclass
class WorkflowRun:
    """Status snapshot of a workflow run."""

    run_id: str
    workflow_name: str
    status: RunStatus
    input_data: Any = None
    output: Any = None
    error: str | None = None


class PylonClientError(Exception):
    """Raised on client-level errors."""


class PylonClient:
    """In-memory Pylon client for defining and running agent workflows.

    This implementation stores all state locally so it can be used
    without a running Pylon server.  A future version will add HTTP
    transport.

    Args:
        base_url: The Pylon API base URL (unused in in-memory mode).
        api_key: Optional API key for authentication.
        timeout: Request timeout in seconds.
        config: Optional SDKConfig; overrides individual params when provided.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: int = 30,
        *,
        config: SDKConfig | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = SDKConfig(base_url=base_url, api_key=api_key, timeout=timeout)

        self._agents: dict[str, AgentHandle] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._workflows: dict[str, Any] = {}

    @property
    def config(self) -> SDKConfig:
        return self._config

    # -- Agent CRUD ----------------------------------------------------------

    def create_agent(
        self,
        name: str,
        role: str = "default",
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> AgentHandle:
        """Register a new agent and return its handle.

        Raises PylonClientError if an agent with the same name already exists.
        """
        if name in self._agents:
            raise PylonClientError(f"Agent {name!r} already exists")

        handle = AgentHandle(
            id=uuid.uuid4().hex[:12],
            name=name,
            role=role,
            capabilities=capabilities or [],
            tools=tools or [],
        )
        self._agents[name] = handle
        return handle

    def list_agents(self) -> list[AgentHandle]:
        """Return a list of all registered agents."""
        return list(self._agents.values())

    def get_agent(self, name: str) -> AgentHandle:
        """Look up an agent by name.

        Raises PylonClientError if not found.
        """
        if name not in self._agents:
            raise PylonClientError(f"Agent {name!r} not found")
        return self._agents[name]

    def delete_agent(self, name: str) -> None:
        """Remove an agent by name.

        Raises PylonClientError if not found.
        """
        if name not in self._agents:
            raise PylonClientError(f"Agent {name!r} not found")
        del self._agents[name]

    # -- Workflow execution --------------------------------------------------

    def run_workflow(
        self,
        name: str,
        input_data: Any = None,
    ) -> WorkflowResult:
        """Execute a workflow synchronously and return the result.

        In this in-memory implementation the workflow handler is looked up
        from registered workflows (via ``register_workflow``).  If no
        handler is found the run is recorded with COMPLETED status and
        the input_data is echoed as output.
        """
        run_id = uuid.uuid4().hex[:12]
        run = WorkflowRun(
            run_id=run_id,
            workflow_name=name,
            status=RunStatus.RUNNING,
            input_data=input_data,
        )
        self._runs[run_id] = run

        handler = self._workflows.get(name)
        try:
            if handler is not None:
                output = handler(input_data)
            else:
                output = input_data

            run.status = RunStatus.COMPLETED
            run.output = output
            return WorkflowResult(run_id=run_id, status=RunStatus.COMPLETED, output=output)
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            return WorkflowResult(
                run_id=run_id, status=RunStatus.FAILED, error=str(exc)
            )

    def register_workflow(self, name: str, handler: Any) -> None:
        """Register a callable as a named workflow handler."""
        self._workflows[name] = handler

    def get_run(self, run_id: str) -> WorkflowRun:
        """Retrieve the status of a workflow run by its ID.

        Raises PylonClientError if the run ID is unknown.
        """
        if run_id not in self._runs:
            raise PylonClientError(f"Run {run_id!r} not found")
        return self._runs[run_id]
