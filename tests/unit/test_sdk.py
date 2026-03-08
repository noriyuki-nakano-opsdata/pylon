from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from pylon.dsl.parser import PylonProject
from pylon.sdk.builder import WorkflowBuilder, WorkflowBuilderError, WorkflowGraph
from pylon.sdk.client import (
    AgentHandle,
    PylonClient,
    PylonClientError,
    RunStatus,
    RunStopReason,
    WorkflowRun,
)
from pylon.sdk.config import SDKConfig
from pylon.sdk.decorators import (
    AgentRegistry,
    ToolRegistry,
    WorkflowRegistry,
    agent,
    tool,
    workflow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registries():
    """Ensure decorator registries are empty between tests."""
    AgentRegistry.clear()
    ToolRegistry.clear()
    WorkflowRegistry.clear()
    yield
    AgentRegistry.clear()
    ToolRegistry.clear()
    WorkflowRegistry.clear()


@pytest.fixture()
def client() -> PylonClient:
    return PylonClient()


def _workflow_project(name: str = "demo-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
        }
    )


def _limited_workflow_project(name: str = "limited-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "researcher": {"role": "research"},
                "writer": {"role": "write"},
            },
            "workflow": {
                "nodes": {
                    "start": {"agent": "researcher", "next": "finish"},
                    "finish": {"agent": "writer", "next": "END"},
                }
            },
            "goal": {
                "objective": "finish both steps",
                "constraints": {"max_iterations": 1},
            },
        }
    )


def _approval_project(name: str = "approval-project") -> PylonProject:
    return PylonProject.model_validate(
        {
            "version": "1",
            "name": name,
            "agents": {
                "reviewer": {"role": "review", "autonomy": "A4"},
            },
            "workflow": {
                "nodes": {
                    "review": {"agent": "reviewer", "next": "END"},
                }
            },
        }
    )


# ---------------------------------------------------------------------------
# SDKConfig tests
# ---------------------------------------------------------------------------


class TestSDKConfig:
    def test_defaults(self):
        cfg = SDKConfig()
        assert cfg.base_url == "http://localhost:8080"
        assert cfg.api_key is None
        assert cfg.timeout == 30
        assert cfg.max_retries == 3
        assert cfg.log_level == "INFO"

    def test_from_env(self):
        env = {
            "PYLON_BASE_URL": "http://custom:9090",
            "PYLON_API_KEY": "secret-key",
            "PYLON_TIMEOUT": "60",
            "PYLON_MAX_RETRIES": "5",
            "PYLON_LOG_LEVEL": "DEBUG",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = SDKConfig.from_env()
        assert cfg.base_url == "http://custom:9090"
        assert cfg.api_key == "secret-key"
        assert cfg.timeout == 60
        assert cfg.max_retries == 5
        assert cfg.log_level == "DEBUG"

    def test_from_env_partial(self):
        with mock.patch.dict(os.environ, {"PYLON_API_KEY": "k"}, clear=False):
            cfg = SDKConfig.from_env()
        assert cfg.api_key == "k"
        assert cfg.base_url == "http://localhost:8080"  # default preserved

    def test_from_file(self, tmp_path: Path):
        cfg_file = tmp_path / "pylon.yaml"
        cfg_file.write_text("base_url: http://file:1234\ntimeout: 10\n")
        cfg = SDKConfig.from_file(cfg_file)
        assert cfg.base_url == "http://file:1234"
        assert cfg.timeout == 10
        assert cfg.api_key is None  # default

    def test_from_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            SDKConfig.from_file("/nonexistent/pylon.yaml")

    def test_from_file_ignores_unknown_keys(self, tmp_path: Path):
        cfg_file = tmp_path / "pylon.yaml"
        cfg_file.write_text("base_url: http://x\nunknown_key: value\n")
        cfg = SDKConfig.from_file(cfg_file)
        assert cfg.base_url == "http://x"


# ---------------------------------------------------------------------------
# PylonClient tests
# ---------------------------------------------------------------------------


class TestPylonClientAgents:
    def test_create_agent(self, client: PylonClient):
        handle = client.create_agent("coder", role="dev", capabilities=["python"])
        assert isinstance(handle, AgentHandle)
        assert handle.name == "coder"
        assert handle.role == "dev"
        assert handle.capabilities == ["python"]

    def test_create_agent_duplicate(self, client: PylonClient):
        client.create_agent("a")
        with pytest.raises(PylonClientError, match="already exists"):
            client.create_agent("a")

    def test_list_agents_empty(self, client: PylonClient):
        assert client.list_agents() == []

    def test_list_agents(self, client: PylonClient):
        client.create_agent("a")
        client.create_agent("b")
        names = [a.name for a in client.list_agents()]
        assert "a" in names
        assert "b" in names

    def test_get_agent(self, client: PylonClient):
        client.create_agent("x", role="tester")
        handle = client.get_agent("x")
        assert handle.role == "tester"

    def test_get_agent_not_found(self, client: PylonClient):
        with pytest.raises(PylonClientError, match="not found"):
            client.get_agent("missing")

    def test_delete_agent(self, client: PylonClient):
        client.create_agent("d")
        client.delete_agent("d")
        assert client.list_agents() == []

    def test_delete_agent_not_found(self, client: PylonClient):
        with pytest.raises(PylonClientError, match="not found"):
            client.delete_agent("ghost")


class TestPylonClientWorkflows:
    def test_register_and_get_workflow_definition(self, client: PylonClient):
        project = _workflow_project("echo-project")
        client.register_project("echo", project)
        registered = client.get_workflow("echo")
        assert registered.name == "echo-project"

    def test_list_workflows_returns_registered_metadata(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        client.register_project("review", _workflow_project("review-project"))
        workflows = client.list_workflows()
        assert {workflow["id"] for workflow in workflows} == {"echo", "review"}
        assert {workflow["project_name"] for workflow in workflows} == {
            "echo-project",
            "review-project",
        }

    def test_delete_workflow_definition(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        client.delete_workflow("echo")
        with pytest.raises(PylonClientError, match="not found"):
            client.get_workflow("echo")

    def test_run_workflow_uses_canonical_graph_runtime(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        result = client.run_workflow("echo", input_data={"msg": "hi"})
        assert result.status == RunStatus.COMPLETED
        assert result.output is None

    def test_run_callable_with_handler(self, client: PylonClient):
        client.register_callable("upper", lambda data: data.upper())
        result = client.run_callable("upper", input_data="hello")
        assert result.output == "HELLO"

    def test_run_callable_handler_error(self, client: PylonClient):
        client.register_callable("bad", lambda _: 1 / 0)
        result = client.run_callable("bad", input_data=None)
        assert result.status == RunStatus.FAILED
        assert result.error == "Internal execution error"
        assert result.stop_reason == RunStopReason.WORKFLOW_ERROR

    def test_get_run(self, client: PylonClient):
        client.register_project("w", _workflow_project("workflow-w"))
        result = client.run_workflow("w")
        run = client.get_run(result.run_id)
        assert isinstance(run, WorkflowRun)
        assert run.workflow_id == "w"
        assert run.workflow_name == "w"
        assert run.project_name == "workflow-w"
        assert run.runtime_metrics is not None
        assert run.runtime_metrics["iterations"] == 2
        assert isinstance(run.event_log, list)
        assert run.state_version == 2
        assert run.state_hash
        assert run.goal is None
        assert run.policy_resolution is None
        assert run.approval_summary is not None
        assert run.approval_summary["pending"] is False
        assert run.execution_summary is not None
        assert run.execution_summary["node_sequence"] == ["start", "finish"]
        assert run.execution_summary["total_events"] == 2
        assert run.execution_summary["critical_path"] == [
            {"node_id": "start", "attempt_id": 1, "loop_iteration": 1},
            {"node_id": "finish", "attempt_id": 1, "loop_iteration": 1},
        ]
        assert run.execution_summary["decision_points"][0] == {
            "type": "edge_decision",
            "source_node": "start",
            "edges": [
                {
                    "edge_key": "start:0",
                    "edge_index": 0,
                    "status": "taken",
                    "target": "finish",
                    "condition": None,
                    "decision_source": "default",
                    "reason": "default edge selected",
                }
            ],
        }

    def test_run_workflow_exposes_runtime_metadata(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        result = client.run_workflow("echo", input_data={"msg": "hi"})
        run = client.get_run(result.run_id)
        assert run.state["msg"] == "hi"
        assert run.state["start_done"] is True
        assert run.state["finish_done"] is True
        assert run.runtime_metrics is not None
        assert run.runtime_metrics["token_usage"]["total_tokens"] == 0
        assert run.event_log[0]["node_id"] == "start"
        assert run.execution_summary is not None
        assert run.execution_summary["last_node"] == "finish"
        assert run.execution_summary["pending_approval"] is False
        assert run.execution_summary["critical_path"] == [
            {"node_id": "start", "attempt_id": 1, "loop_iteration": 1},
            {"node_id": "finish", "attempt_id": 1, "loop_iteration": 1},
        ]

    def test_register_workflow_rejects_plain_callable(self, client: PylonClient):
        with pytest.raises(PylonClientError, match="register_callable"):
            client.register_workflow("upper", lambda data: data.upper())

    def test_register_workflow_accepts_builder_graph_and_node_handlers(self, client: PylonClient):
        graph = (
            WorkflowBuilder("builder-flow")
            .add_node(
                "start",
                agent="builder_agent",
                handler=lambda state: {"message": state["msg"]},
            )
            .add_node("finish", agent="builder_agent")
            .add_edge("start", "finish")
            .set_entry("start")
            .build()
        )
        client.register_workflow("builder", graph)

        result = client.run_workflow("builder", input_data={"msg": "hello"})
        run = client.get_run(result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.state["message"] == "hello"
        assert run.state["finish_done"] is True

    def test_register_workflow_accepts_builder_instance(self, client: PylonClient):
        builder = (
            WorkflowBuilder("builder-flow")
            .add_node("start", agent="builder_agent", handler=lambda state: {"x": 1})
            .add_node("finish", agent="builder_agent")
            .add_edge("start", "finish")
            .set_entry("start")
        )
        client.register_workflow("builder", builder)

        result = client.run_workflow("builder")
        run = client.get_run(result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.state["x"] == 1
        assert run.state["finish_done"] is True

    def test_register_workflow_accepts_decorated_workflow_factory(self, client: PylonClient):
        @agent(name="researcher", role="research")
        def researcher(state):
            return {"topic": str(state["topic"]).upper()}

        @agent(name="writer", role="write")
        def writer(state):
            return {"summary": f"summary:{state['topic']}"}

        @workflow(name="pipeline")
        def define(builder):
            builder.add_node("research", agent="researcher")
            builder.add_node("write", agent="writer")
            builder.add_edge("research", "write")
            builder.set_entry("research")

        client.register_workflow("pipeline", define)
        result = client.run_workflow("pipeline", input_data={"topic": "agents"})
        run = client.get_run(result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.state["topic"] == "AGENTS"
        assert run.state["summary"] == "summary:AGENTS"

    def test_register_workflow_factory_returning_project_keeps_agent_handlers(
        self,
        client: PylonClient,
    ):
        @agent(name="researcher", role="research")
        def researcher(state):
            return {"topic": str(state["topic"]).upper()}

        @workflow(name="pipeline")
        def define():
            return PylonProject.model_validate(
                {
                    "version": "1",
                    "name": "pipeline-project",
                    "agents": {"researcher": {"role": "research"}},
                    "workflow": {
                        "nodes": {
                            "research": {"agent": "researcher", "next": "END"},
                        }
                    },
                }
            )

        client.register_workflow("pipeline", define)
        result = client.run_workflow("pipeline", input_data={"topic": "agents"})
        run = client.get_run(result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.state["topic"] == "AGENTS"

    def test_register_workflow_rejects_callable_conditions_for_canonical_runtime(
        self,
        client: PylonClient,
    ):
        graph = (
            WorkflowBuilder("conditional")
            .add_node("start", agent="a")
            .add_node("finish", agent="a")
            .add_edge("start", "finish", condition=lambda state: bool(state))
            .set_entry("start")
            .build()
        )
        with pytest.raises(WorkflowBuilderError, match="Callable edge conditions"):
            client.register_workflow("conditional", graph)

    def test_resume_run_continues_paused_workflow(self, client: PylonClient):
        client.register_project("limited", _limited_workflow_project())
        result = client.run_workflow("limited", input_data={"task": "x"})
        paused = client.get_run(result.run_id)
        assert paused.status == RunStatus.PAUSED
        assert paused.suspension_reason == RunStopReason.LIMIT_EXCEEDED

        resumed = client.resume_run(result.run_id)
        assert resumed.status == RunStatus.PAUSED
        assert resumed.suspension_reason == RunStopReason.LIMIT_EXCEEDED
        assert resumed.state["finish_done"] is True
        assert resumed.state["task"] == "x"

    def test_resume_run_rejects_input_mismatch(self, client: PylonClient):
        client.register_project("limited", _limited_workflow_project())
        result = client.run_workflow("limited", input_data={"task": "x"})
        with pytest.raises(PylonClientError, match="resume input_data must match"):
            client.resume_run(result.run_id, input_data={"task": "y"})

    def test_approve_request_resumes_waiting_run(self, client: PylonClient):
        client.register_project("approval", _approval_project())
        result = client.run_workflow("approval")
        waiting = client.get_run(result.run_id)
        assert waiting.status == RunStatus.WAITING_APPROVAL
        assert waiting.approval_request_id is not None

        completed = client.approve_request(waiting.approval_request_id, reason="looks good")
        assert completed.status == RunStatus.COMPLETED
        assert completed.approval_summary is not None
        assert completed.approval_summary["approved_request_ids"] == [
            waiting.approval_request_id
        ]

    def test_reject_request_cancels_waiting_run(self, client: PylonClient):
        client.register_project("approval", _approval_project())
        result = client.run_workflow("approval")
        waiting = client.get_run(result.run_id)

        cancelled = client.reject_request(waiting.approval_request_id, reason="no")
        assert cancelled.status == RunStatus.CANCELLED
        assert cancelled.stop_reason == RunStopReason.APPROVAL_DENIED
        assert cancelled.active_approval is None

    def test_replay_checkpoint_returns_replay_payload(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        result = client.run_workflow("echo", input_data={"msg": "hi"})
        run = client.get_run(result.run_id)

        replay = client.replay_checkpoint(run.checkpoint_ids[-1])
        assert replay["view_kind"] == "replay"
        assert replay["source_run"] == result.run_id
        assert replay["state_hash"]

    def test_replay_intermediate_checkpoint_uses_reconstructed_status(self, client: PylonClient):
        client.register_project("echo", _workflow_project("echo-project"))
        result = client.run_workflow("echo", input_data={"msg": "hi"})
        run = client.get_run(result.run_id)

        replay = client.replay_checkpoint(run.checkpoint_ids[0])
        assert replay["view_kind"] == "replay"
        assert replay["status"] == RunStatus.RUNNING.value
        assert replay["stop_reason"] == RunStopReason.NONE.value
        assert replay["execution_summary"]["node_sequence"] == ["start"]

    def test_delete_callable(self, client: PylonClient):
        client.register_callable("upper", lambda data: data.upper())
        client.delete_callable("upper")
        with pytest.raises(PylonClientError, match="not found"):
            client.run_callable("upper", input_data="hello")

    def test_get_run_not_found(self, client: PylonClient):
        with pytest.raises(PylonClientError, match="not found"):
            client.get_run("no-such-id")

    def test_client_with_config(self):
        cfg = SDKConfig(base_url="http://test:1111", api_key="abc")
        c = PylonClient(config=cfg)
        assert c.config.base_url == "http://test:1111"
        assert c.config.api_key == "abc"


# ---------------------------------------------------------------------------
# Decorator tests
# ---------------------------------------------------------------------------


class TestDecorators:
    def test_agent_registers(self):
        @agent(name="coder", role="dev", tools=["git"])
        def handle(data):
            return data

        agents = AgentRegistry.get_agents()
        assert "coder" in agents
        assert agents["coder"].role == "dev"
        assert agents["coder"].tools == ["git"]

    def test_agent_handler_callable(self):
        @agent(name="echo", role="echo")
        def handle(data):
            return data

        assert handle("test") == "test"

    def test_tool_registers(self):
        @tool(name="search", description="Search the web")
        def do_search(q):
            return q

        tools = ToolRegistry.get_tools()
        assert "search" in tools
        assert tools["search"].description == "Search the web"

    def test_tool_handler_callable(self):
        @tool(name="add", description="Add numbers")
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_workflow_registers(self):
        @workflow(name="pipeline")
        def define(builder):
            pass

        workflows = WorkflowRegistry.get_workflows()
        assert "pipeline" in workflows

    def test_multiple_agents(self):
        @agent(name="a1")
        def h1(d):
            return d

        @agent(name="a2")
        def h2(d):
            return d

        assert len(AgentRegistry.get_agents()) == 2

    def test_clear_registries(self):
        @agent(name="temp")
        def h(d):
            return d

        AgentRegistry.clear()
        assert len(AgentRegistry.get_agents()) == 0


# ---------------------------------------------------------------------------
# WorkflowBuilder tests
# ---------------------------------------------------------------------------


class TestWorkflowBuilder:
    def test_basic_build(self):
        graph = (
            WorkflowBuilder("simple")
            .add_node("start", agent="researcher")
            .add_node("end", agent="writer")
            .add_edge("start", "end")
            .set_entry("start")
            .build()
        )
        assert isinstance(graph, WorkflowGraph)
        assert graph.name == "simple"
        assert graph.entry_point == "start"
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1

    def test_fluent_chaining_returns_self(self):
        b = WorkflowBuilder("chain")
        assert b.add_node("n", agent="a") is b
        assert b.add_edge("n", "n") is b
        assert b.set_entry("n") is b

    def test_build_no_entry_raises(self):
        b = WorkflowBuilder("no_entry").add_node("n", agent="a")
        with pytest.raises(WorkflowBuilderError, match="No entry point"):
            b.build()

    def test_build_invalid_entry_raises(self):
        b = WorkflowBuilder("bad_entry").add_node("a", agent="x").set_entry("missing")
        with pytest.raises(WorkflowBuilderError, match="does not match any node"):
            b.build()

    def test_build_invalid_edge_source_raises(self):
        b = (
            WorkflowBuilder("bad_src")
            .add_node("a", agent="x")
            .add_edge("missing", "a")
            .set_entry("a")
        )
        with pytest.raises(WorkflowBuilderError, match="source.*does not match"):
            b.build()

    def test_build_invalid_edge_target_raises(self):
        b = (
            WorkflowBuilder("bad_tgt")
            .add_node("a", agent="x")
            .add_edge("a", "missing")
            .set_entry("a")
        )
        with pytest.raises(WorkflowBuilderError, match="target.*does not match"):
            b.build()

    def test_duplicate_node_raises(self):
        b = WorkflowBuilder("dup").add_node("a", agent="x")
        with pytest.raises(WorkflowBuilderError, match="Duplicate"):
            b.add_node("a", agent="y")

    def test_conditional_edge(self):
        def cond(result):
            return result.get("ok")

        graph = (
            WorkflowBuilder("cond")
            .add_node("a", agent="x")
            .add_node("b", agent="y")
            .add_edge("a", "b", condition=cond)
            .set_entry("a")
            .build()
        )
        assert graph.edges[0].condition is cond

    def test_to_dict(self):
        graph = (
            WorkflowBuilder("dict_test")
            .add_node("n1", agent="a1")
            .set_entry("n1")
            .build()
        )
        d = graph.to_dict()
        assert d["name"] == "dict_test"
        assert d["entry_point"] == "n1"
        assert "n1" in d["nodes"]

    def test_node_with_handler(self):
        def fn(data):
            return data

        graph = (
            WorkflowBuilder("handler")
            .add_node("n", agent="a", handler=fn)
            .set_entry("n")
            .build()
        )
        assert graph.nodes["n"].handler is fn
