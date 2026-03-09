from __future__ import annotations

import importlib
from typing import Any

from pylon.sdk.builder import WorkflowBuilder
from pylon.sdk.config import SDKConfig
from pylon.sdk.decorators import AgentRegistry, ToolRegistry, agent, tool, workflow

__all__ = [
    "PylonHTTPClient",
    "PylonClient",
    "agent",
    "workflow",
    "tool",
    "AgentRegistry",
    "ToolRegistry",
    "WorkflowBuilder",
    "SDKConfig",
    "WorkflowDispatchPlan",
    "WorkflowDispatchTask",
    "materialize_workflow_definition",
    "workflow_graph_to_project",
]


def __getattr__(name: str) -> Any:
    # Lazy imports to break circular dependency chains that arise from
    # eagerly importing heavy modules (runtime, control_plane, api, config).
    _lazy_map: dict[str, tuple[str, str]] = {
        "PylonClient": ("pylon.sdk.client", "PylonClient"),
        "PylonHTTPClient": ("pylon.sdk.http_client", "PylonHTTPClient"),
        "WorkflowDispatchPlan": ("pylon.runtime.planning", "WorkflowDispatchPlan"),
        "WorkflowDispatchTask": ("pylon.runtime.planning", "WorkflowDispatchTask"),
        "materialize_workflow_definition": (
            "pylon.sdk.project",
            "materialize_workflow_definition",
        ),
        "workflow_graph_to_project": ("pylon.sdk.project", "workflow_graph_to_project"),
    }
    if name in _lazy_map:
        module_path, attr = _lazy_map[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
