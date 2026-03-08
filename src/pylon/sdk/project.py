from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pylon.dsl.parser import AgentDef, PylonProject
from pylon.sdk.builder import WorkflowBuilder, WorkflowBuilderError, WorkflowGraph
from pylon.sdk.decorators import AgentInfo, WorkflowInfo


def _agent_def_from_metadata(metadata: Any) -> AgentDef:
    if isinstance(metadata, AgentInfo):
        return AgentDef(role=metadata.role, tools=list(metadata.tools))
    role = getattr(metadata, "role", "")
    tools = getattr(metadata, "tools", [])
    return AgentDef(role=str(role), tools=list(tools))


def _invoke_workflow_factory(
    workflow_name: str,
    factory: Callable[..., Any],
) -> PylonProject | WorkflowGraph | WorkflowBuilder:
    builder = WorkflowBuilder(workflow_name)
    signature = inspect.signature(factory)
    parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if len(parameters) == 0:
        produced = factory()
    else:
        produced = factory(builder)
    if produced is None:
        return builder
    if isinstance(produced, (PylonProject, WorkflowGraph, WorkflowBuilder)):
        return produced
    raise WorkflowBuilderError(
        "Workflow factory must return PylonProject, WorkflowGraph, WorkflowBuilder, or None"
    )


def _agent_handlers_for_project(
    project: PylonProject,
    *,
    registry_agents: Mapping[str, AgentInfo] | None = None,
    client_agents: Mapping[str, Any] | None = None,
) -> dict[str, Callable[..., Any]]:
    registry_agents = registry_agents or {}
    client_agents = client_agents or {}
    agent_handlers: dict[str, Callable[..., Any]] = {}
    for agent_name in project.agents:
        metadata = registry_agents.get(agent_name) or client_agents.get(agent_name)
        handler = getattr(metadata, "handler", None)
        if callable(handler):
            agent_handlers[agent_name] = handler
    return agent_handlers


def workflow_graph_to_project(
    graph: WorkflowGraph,
    *,
    project_name: str | None = None,
    registry_agents: Mapping[str, AgentInfo] | None = None,
    client_agents: Mapping[str, Any] | None = None,
) -> tuple[PylonProject, dict[str, Callable[..., Any]], dict[str, Callable[..., Any]]]:
    registry_agents = registry_agents or {}
    client_agents = client_agents or {}

    targeted = {edge.target for edge in graph.edges}
    structural_entry_points = set(graph.nodes) - targeted
    if len(structural_entry_points) != 1 or graph.entry_point not in structural_entry_points:
        raise WorkflowBuilderError(
            "WorkflowGraph entry point must be the single structural entry point "
            "for canonical runtime execution"
        )

    agents: dict[str, AgentDef] = {}
    node_handlers: dict[str, Callable[..., Any]] = {}
    agent_handlers: dict[str, Callable[..., Any]] = {}
    nodes_payload: dict[str, dict[str, Any]] = {}

    outgoing: dict[str, list[dict[str, Any] | str]] = {node_id: [] for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.condition is not None and not isinstance(edge.condition, str):
            raise WorkflowBuilderError(
                "Callable edge conditions cannot be converted to canonical runtime "
                "workflow definitions"
            )
        if edge.condition is None:
            outgoing[edge.source].append(edge.target)
        else:
            outgoing[edge.source].append(
                {"target": edge.target, "condition": edge.condition}
            )

    for node_id, node in graph.nodes.items():
        if node.handler is not None:
            node_handlers[node_id] = node.handler

        agent_metadata = registry_agents.get(node.agent) or client_agents.get(node.agent)
        if node.agent not in agents:
            agents[node.agent] = (
                _agent_def_from_metadata(agent_metadata)
                if agent_metadata
                else AgentDef()
            )
        if isinstance(agent_metadata, AgentInfo):
            agent_handlers[node.agent] = agent_metadata.handler

        node_payload: dict[str, Any] = {"agent": node.agent}
        next_nodes = outgoing[node_id]
        if len(next_nodes) == 1 and isinstance(next_nodes[0], str):
            node_payload["next"] = next_nodes[0]
        elif next_nodes:
            node_payload["next"] = next_nodes
        nodes_payload[node_id] = node_payload

    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": project_name or graph.name,
            "agents": {
                agent_name: agent_def.model_dump(mode="json")
                for agent_name, agent_def in agents.items()
            },
            "workflow": {"nodes": nodes_payload},
        }
    )
    return project, node_handlers, agent_handlers


def materialize_workflow_definition(
    definition: (
        PylonProject
        | dict[str, Any]
        | str
        | Path
        | WorkflowGraph
        | WorkflowBuilder
        | WorkflowInfo
        | Callable[..., Any]
    ),
    *,
    workflow_name: str,
    registry_agents: Mapping[str, AgentInfo] | None = None,
    client_agents: Mapping[str, Any] | None = None,
    project_loader: Callable[[str | Path], PylonProject] | None = None,
) -> tuple[PylonProject, dict[str, Callable[..., Any]], dict[str, Callable[..., Any]]]:
    if isinstance(definition, PylonProject):
        return definition, {}, _agent_handlers_for_project(
            definition,
            registry_agents=registry_agents,
            client_agents=client_agents,
        )
    if isinstance(definition, dict):
        project = PylonProject.model_validate(definition)
        return project, {}, _agent_handlers_for_project(
            project,
            registry_agents=registry_agents,
            client_agents=client_agents,
        )
    if isinstance(definition, (str, Path)):
        if project_loader is None:
            msg = "project_loader is required for path-based workflow definitions"
            raise WorkflowBuilderError(msg)
        project = project_loader(definition)
        return project, {}, _agent_handlers_for_project(
            project,
            registry_agents=registry_agents,
            client_agents=client_agents,
        )

    workflow_graph: WorkflowGraph | None = None
    if isinstance(definition, WorkflowBuilder):
        workflow_graph = definition.build()
    elif isinstance(definition, WorkflowGraph):
        workflow_graph = definition
    else:
        workflow_factory = definition.handler if isinstance(definition, WorkflowInfo) else None
        if workflow_factory is None and callable(definition):
            workflow_factory = getattr(definition, "_pylon_workflow", None)
            if isinstance(workflow_factory, WorkflowInfo):
                workflow_factory = workflow_factory.handler
        if workflow_factory is not None:
            produced = _invoke_workflow_factory(workflow_name, workflow_factory)
            if isinstance(produced, PylonProject):
                return produced, {}, _agent_handlers_for_project(
                    produced,
                    registry_agents=registry_agents,
                    client_agents=client_agents,
                )
            if isinstance(produced, WorkflowBuilder):
                workflow_graph = produced.build()
            else:
                workflow_graph = produced

    if workflow_graph is None:
        raise WorkflowBuilderError(
            "Workflow definition must be a PylonProject, WorkflowGraph, "
            "WorkflowBuilder, or @workflow factory"
        )

    return workflow_graph_to_project(
        workflow_graph,
        project_name=workflow_name,
        registry_agents=registry_agents,
        client_agents=client_agents,
    )
