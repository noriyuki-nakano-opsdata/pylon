"""Tests for A2A protocol (FR-09)."""

from __future__ import annotations

import pytest

from pylon.protocols.a2a.types import (
    A2AMessage,
    A2ATask,
    AgentCard,
    Artifact,
    Part,
    TaskState,
)
from pylon.protocols.a2a.server import A2AServer
from pylon.protocols.a2a.client import A2AClient
from pylon.protocols.a2a.card import AgentCardRegistry, generate_card
from pylon.protocols.mcp.types import JsonRpcRequest


class TestTaskStateLifecycle:
    def test_submitted_to_working(self) -> None:
        task = A2ATask()
        assert task.state == TaskState.SUBMITTED
        task.transition_to(TaskState.WORKING)
        assert task.state == TaskState.WORKING

    def test_working_to_completed(self) -> None:
        task = A2ATask(state=TaskState.WORKING)
        task.transition_to(TaskState.COMPLETED)
        assert task.state == TaskState.COMPLETED

    def test_working_to_failed(self) -> None:
        task = A2ATask(state=TaskState.WORKING)
        task.transition_to(TaskState.FAILED)
        assert task.state == TaskState.FAILED

    def test_working_to_canceled(self) -> None:
        task = A2ATask(state=TaskState.WORKING)
        task.transition_to(TaskState.CANCELED)
        assert task.state == TaskState.CANCELED

    def test_working_to_input_required(self) -> None:
        task = A2ATask(state=TaskState.WORKING)
        task.transition_to(TaskState.INPUT_REQUIRED)
        assert task.state == TaskState.INPUT_REQUIRED

    def test_input_required_to_working(self) -> None:
        task = A2ATask(state=TaskState.INPUT_REQUIRED)
        task.transition_to(TaskState.WORKING)
        assert task.state == TaskState.WORKING

    def test_invalid_transition_raises(self) -> None:
        task = A2ATask(state=TaskState.COMPLETED)
        with pytest.raises(ValueError, match="Invalid transition"):
            task.transition_to(TaskState.WORKING)

    def test_completed_is_terminal(self) -> None:
        assert not TaskState.COMPLETED.can_transition_to(TaskState.WORKING)
        assert not TaskState.COMPLETED.can_transition_to(TaskState.SUBMITTED)

    def test_failed_is_terminal(self) -> None:
        assert not TaskState.FAILED.can_transition_to(TaskState.WORKING)

    def test_canceled_is_terminal(self) -> None:
        assert not TaskState.CANCELED.can_transition_to(TaskState.WORKING)


class TestA2ATypes:
    def test_part_roundtrip(self) -> None:
        part = Part(type="text", content="hello")
        data = part.to_dict()
        restored = Part.from_dict(data)
        assert restored.type == "text"
        assert restored.content == "hello"

    def test_message_roundtrip(self) -> None:
        msg = A2AMessage(
            role="user",
            parts=[Part(type="text", content="do something")],
        )
        data = msg.to_dict()
        restored = A2AMessage.from_dict(data)
        assert restored.role == "user"
        assert len(restored.parts) == 1
        assert restored.parts[0].content == "do something"

    def test_artifact_roundtrip(self) -> None:
        artifact = Artifact(
            name="result",
            description="output",
            parts=[Part(type="data", content={"key": "value"})],
        )
        data = artifact.to_dict()
        restored = Artifact.from_dict(data)
        assert restored.name == "result"
        assert restored.parts[0].content == {"key": "value"}

    def test_task_roundtrip(self) -> None:
        task = A2ATask(
            id="task-1",
            messages=[A2AMessage(role="user", parts=[Part(type="text", content="hi")])],
        )
        data = task.to_dict()
        restored = A2ATask.from_dict(data)
        assert restored.id == "task-1"
        assert restored.state == TaskState.SUBMITTED
        assert len(restored.messages) == 1

    def test_agent_card_roundtrip(self) -> None:
        card = AgentCard(
            name="test-agent",
            url="http://localhost:8080",
            capabilities=["text"],
            skills=["summarize"],
        )
        data = card.to_dict()
        restored = AgentCard.from_dict(data)
        assert restored.name == "test-agent"
        assert "summarize" in restored.skills


class TestA2AServer:
    @pytest.fixture
    def server(self) -> A2AServer:
        return A2AServer()

    @pytest.fixture
    def server_with_allowlist(self) -> A2AServer:
        return A2AServer(allowed_peers={"agent-a", "agent-b"})

    def test_tasks_send(self, server: A2AServer) -> None:
        task = A2ATask(id="t-1", messages=[A2AMessage(role="user", parts=[Part(type="text", content="work")])])
        request = JsonRpcRequest(
            method="tasks/send",
            params={"task": task.to_dict()},
            id="1",
        )
        response = server.handle_request(request)
        assert response.error is None
        assert response.result["state"] == "working"
        assert response.result["id"] == "t-1"

    def test_tasks_get(self, server: A2AServer) -> None:
        task = A2ATask(id="t-2")
        send_req = JsonRpcRequest(method="tasks/send", params={"task": task.to_dict()}, id="1")
        server.handle_request(send_req)

        get_req = JsonRpcRequest(method="tasks/get", params={"task_id": "t-2"}, id="2")
        response = server.handle_request(get_req)
        assert response.error is None
        assert response.result["id"] == "t-2"
        assert response.result["state"] == "working"

    def test_tasks_get_not_found(self, server: A2AServer) -> None:
        request = JsonRpcRequest(method="tasks/get", params={"task_id": "nope"}, id="1")
        response = server.handle_request(request)
        assert response.error is not None
        assert "not found" in response.error.message.lower()

    def test_tasks_cancel(self, server: A2AServer) -> None:
        task = A2ATask(id="t-3")
        send_req = JsonRpcRequest(method="tasks/send", params={"task": task.to_dict()}, id="1")
        server.handle_request(send_req)

        cancel_req = JsonRpcRequest(method="tasks/cancel", params={"task_id": "t-3"}, id="2")
        response = server.handle_request(cancel_req)
        assert response.error is None
        assert response.result["state"] == "canceled"

    def test_tasks_cancel_already_completed(self, server: A2AServer) -> None:
        task = A2ATask(id="t-4")
        send_req = JsonRpcRequest(method="tasks/send", params={"task": task.to_dict()}, id="1")
        server.handle_request(send_req)
        # Manually complete
        server._tasks["t-4"].transition_to(TaskState.COMPLETED)

        cancel_req = JsonRpcRequest(method="tasks/cancel", params={"task_id": "t-4"}, id="2")
        response = server.handle_request(cancel_req)
        assert response.error is not None
        assert "cannot cancel" in response.error.message.lower()

    def test_unknown_method(self, server: A2AServer) -> None:
        request = JsonRpcRequest(method="tasks/unknown", id="1")
        response = server.handle_request(request)
        assert response.error is not None
        assert response.error.code == -32601

    def test_unknown_peer_rejected(self, server_with_allowlist: A2AServer) -> None:
        task = A2ATask(id="t-5")
        request = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "unknown-agent", "task": task.to_dict()},
            id="1",
        )
        response = server_with_allowlist.handle_request(request)
        assert response.error is not None
        assert "unknown peer" in response.error.message.lower()

    def test_allowed_peer_accepted(self, server_with_allowlist: A2AServer) -> None:
        task = A2ATask(id="t-6")
        request = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "agent-a", "task": task.to_dict()},
            id="1",
        )
        response = server_with_allowlist.handle_request(request)
        assert response.error is None
        assert response.result["state"] == "working"

    def test_add_peer(self, server_with_allowlist: A2AServer) -> None:
        assert not server_with_allowlist.is_peer_allowed("agent-c")
        server_with_allowlist.add_peer("agent-c")
        assert server_with_allowlist.is_peer_allowed("agent-c")


class TestAgentCard:
    def test_generate_card(self) -> None:
        card = generate_card(
            name="my-agent",
            url="http://localhost:9000",
            description="Test agent",
            capabilities=["text", "code"],
            skills=["summarize", "translate"],
        )
        assert card.name == "my-agent"
        assert card.url == "http://localhost:9000"
        assert "text" in card.capabilities
        assert "translate" in card.skills

    def test_generate_card_defaults(self) -> None:
        card = generate_card(name="minimal", url="http://localhost:8080")
        assert card.version == "0.1.0"
        assert card.authentication == "none"
        assert card.capabilities == []


class TestAgentCardRegistry:
    def test_register_and_lookup(self) -> None:
        registry = AgentCardRegistry()
        card = generate_card(name="peer-1", url="http://peer-1:8080")
        registry.register(card)

        assert registry.is_registered("peer-1")
        assert registry.get("peer-1") is card

    def test_unregister(self) -> None:
        registry = AgentCardRegistry()
        card = generate_card(name="peer-2", url="http://peer-2:8080")
        registry.register(card)
        registry.unregister("peer-2")

        assert not registry.is_registered("peer-2")
        assert registry.get("peer-2") is None

    def test_unknown_peer_not_registered(self) -> None:
        registry = AgentCardRegistry()
        assert not registry.is_registered("nope")
        assert registry.get("nope") is None

    def test_list_peers(self) -> None:
        registry = AgentCardRegistry()
        registry.register(generate_card(name="a", url="http://a:8080"))
        registry.register(generate_card(name="b", url="http://b:8080"))
        peers = registry.list_peers()
        assert len(peers) == 2
        names = {p.name for p in peers}
        assert names == {"a", "b"}

    def test_register_requires_name(self) -> None:
        registry = AgentCardRegistry()
        with pytest.raises(ValueError, match="must have a name"):
            registry.register(AgentCard())


class TestClientServerIntegration:
    def test_send_get_cancel_flow(self) -> None:
        server = A2AServer(allowed_peers={"test-client"})
        client = A2AClient(server, sender="test-client")

        # Send
        task = A2ATask(
            id="int-1",
            messages=[A2AMessage(role="user", parts=[Part(type="text", content="do work")])],
        )
        result = client.send_task(task)
        assert result.state == TaskState.WORKING
        assert result.id == "int-1"

        # Get
        fetched = client.get_task("int-1")
        assert fetched.state == TaskState.WORKING
        assert len(fetched.messages) == 1

        # Cancel
        canceled = client.cancel_task("int-1")
        assert canceled is True

        # Verify canceled
        fetched_again = client.get_task("int-1")
        assert fetched_again.state == TaskState.CANCELED

    def test_send_rejected_for_unknown_peer(self) -> None:
        server = A2AServer(allowed_peers={"allowed-agent"})
        client = A2AClient(server, sender="intruder")

        task = A2ATask(id="int-2")
        with pytest.raises(RuntimeError, match="Unknown peer"):
            client.send_task(task)

    def test_get_nonexistent_task(self) -> None:
        server = A2AServer()
        client = A2AClient(server, sender="test")

        with pytest.raises(RuntimeError, match="not found"):
            client.get_task("nope")

    def test_cancel_nonexistent_task(self) -> None:
        server = A2AServer()
        client = A2AClient(server, sender="test")

        result = client.cancel_task("nope")
        assert result is False
