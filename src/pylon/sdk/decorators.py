from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentInfo:
    """Metadata attached to a function decorated with @agent."""

    name: str
    role: str
    tools: list[str]
    handler: Callable[..., Any]


@dataclass(frozen=True)
class ToolInfo:
    """Metadata attached to a function decorated with @tool."""

    name: str
    description: str
    handler: Callable[..., Any]


@dataclass(frozen=True)
class WorkflowInfo:
    """Metadata attached to a function decorated with @workflow."""

    name: str
    handler: Callable[..., Any]


class AgentRegistry:
    """Global registry for @agent-decorated functions."""

    _agents: dict[str, AgentInfo] = {}

    @classmethod
    def register(cls, info: AgentInfo) -> None:
        cls._agents[info.name] = info

    @classmethod
    def get_agents(cls) -> dict[str, AgentInfo]:
        return dict(cls._agents)

    @classmethod
    def get(cls, name: str) -> AgentInfo | None:
        return cls._agents.get(name)

    @classmethod
    def clear(cls) -> None:
        cls._agents.clear()


class ToolRegistry:
    """Global registry for @tool-decorated functions."""

    _tools: dict[str, ToolInfo] = {}

    @classmethod
    def register(cls, info: ToolInfo) -> None:
        cls._tools[info.name] = info

    @classmethod
    def get_tools(cls) -> dict[str, ToolInfo]:
        return dict(cls._tools)

    @classmethod
    def get(cls, name: str) -> ToolInfo | None:
        return cls._tools.get(name)

    @classmethod
    def clear(cls) -> None:
        cls._tools.clear()


class WorkflowRegistry:
    """Global registry for @workflow-decorated functions."""

    _workflows: dict[str, WorkflowInfo] = {}

    @classmethod
    def register(cls, info: WorkflowInfo) -> None:
        cls._workflows[info.name] = info

    @classmethod
    def get_workflows(cls) -> dict[str, WorkflowInfo]:
        return dict(cls._workflows)

    @classmethod
    def get(cls, name: str) -> WorkflowInfo | None:
        return cls._workflows.get(name)

    @classmethod
    def clear(cls) -> None:
        cls._workflows.clear()


def agent(
    name: str,
    role: str = "default",
    tools: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as a Pylon agent handler.

    Usage::

        @agent(name="researcher", role="research", tools=["web_search"])
        def handle_research(input_data):
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        info = AgentInfo(
            name=name,
            role=role,
            tools=tools or [],
            handler=fn,
        )
        AgentRegistry.register(info)
        fn._pylon_agent = info  # type: ignore[attr-defined]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._pylon_agent = info  # type: ignore[attr-defined]
        return wrapper

    return decorator


def workflow(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as a Pylon workflow definition.

    Usage::

        @workflow(name="research_pipeline")
        def my_workflow(builder):
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        info = WorkflowInfo(name=name, handler=fn)
        WorkflowRegistry.register(info)
        fn._pylon_workflow = info  # type: ignore[attr-defined]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._pylon_workflow = info  # type: ignore[attr-defined]
        return wrapper

    return decorator


def tool(
    name: str,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as a Pylon tool.

    Usage::

        @tool(name="web_search", description="Search the web")
        def search(query: str) -> str:
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        info = ToolInfo(name=name, description=description, handler=fn)
        ToolRegistry.register(info)
        fn._pylon_tool = info  # type: ignore[attr-defined]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._pylon_tool = info  # type: ignore[attr-defined]
        return wrapper

    return decorator
