"""Public runtime entry points for compiled workflow execution."""

from __future__ import annotations

import importlib
from typing import Any

from pylon.observability.execution_summary import build_execution_summary
from pylon.runtime.execution import (
    ExecutionArtifacts,
    compile_project_graph,
    deserialize_run,
    execute_project_sync,
    execute_single_node_sync,
    normalize_runtime_input,
    resume_project_sync,
    serialize_run,
)
from pylon.runtime.llm import LLMRuntime, ModelPricing, ProviderRegistry

__all__ = [
    "ExecutionArtifacts",
    "LLMRuntime",
    "ModelPricing",
    "ProviderRegistry",
    "WorkflowDispatchPlan",
    "WorkflowDispatchTask",
    "QueuedDispatchRun",
    "QueuedDispatchStep",
    "QueuedWorkflowDispatchRunner",
    "build_execution_summary",
    "build_dispatch_plan",
    "compile_project_graph",
    "deserialize_run",
    "execute_project_sync",
    "execute_single_node_sync",
    "normalize_runtime_input",
    "plan_project_dispatch",
    "resume_project_sync",
    "serialize_run",
]


def __getattr__(name: str) -> Any:
    # Lazy imports to break circular dependency:
    #   pylon.runtime -> pylon.runtime.planning -> pylon.control_plane.scheduler
    #   -> pylon.control_plane -> pylon.control_plane.workflow_service -> pylon.runtime
    _lazy_map: dict[str, tuple[str, str]] = {
        "WorkflowDispatchPlan": ("pylon.runtime.planning", "WorkflowDispatchPlan"),
        "WorkflowDispatchTask": ("pylon.runtime.planning", "WorkflowDispatchTask"),
        "build_dispatch_plan": ("pylon.runtime.planning", "build_dispatch_plan"),
        "plan_project_dispatch": ("pylon.runtime.planning", "plan_project_dispatch"),
        "QueuedDispatchRun": ("pylon.runtime.queued_runner", "QueuedDispatchRun"),
        "QueuedDispatchStep": ("pylon.runtime.queued_runner", "QueuedDispatchStep"),
        "QueuedWorkflowDispatchRunner": (
            "pylon.runtime.queued_runner",
            "QueuedWorkflowDispatchRunner",
        ),
    }
    if name in _lazy_map:
        module_path, attr = _lazy_map[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
