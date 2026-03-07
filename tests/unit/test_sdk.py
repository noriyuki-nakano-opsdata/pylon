from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from pylon.sdk.builder import WorkflowBuilder, WorkflowBuilderError, WorkflowGraph
from pylon.sdk.client import (
    AgentHandle,
    PylonClient,
    PylonClientError,
    RunStatus,
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
    def test_run_workflow_no_handler(self, client: PylonClient):
        result = client.run_workflow("echo", input_data={"msg": "hi"})
        assert result.status == RunStatus.COMPLETED
        assert result.output == {"msg": "hi"}

    def test_run_workflow_with_handler(self, client: PylonClient):
        client.register_workflow("upper", lambda data: data.upper())
        result = client.run_workflow("upper", input_data="hello")
        assert result.output == "HELLO"

    def test_run_workflow_handler_error(self, client: PylonClient):
        client.register_workflow("bad", lambda _: 1 / 0)
        result = client.run_workflow("bad", input_data=None)
        assert result.status == RunStatus.FAILED
        assert "division by zero" in result.error

    def test_get_run(self, client: PylonClient):
        result = client.run_workflow("w")
        run = client.get_run(result.run_id)
        assert isinstance(run, WorkflowRun)
        assert run.workflow_name == "w"

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
