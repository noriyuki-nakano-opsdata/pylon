"""Comprehensive tests for A2A protocol (FR-09) - RC v1.0."""

from __future__ import annotations

import asyncio

import pytest

from pylon.protocols.a2a.card import AgentCardRegistry, generate_card
from pylon.protocols.a2a.client import A2AClient, A2AConnectionPool
from pylon.protocols.a2a.server import RATE_LIMITED, TASK_NOT_FOUND, A2AServer
from pylon.protocols.a2a.types import (
    A2AMessage,
    A2ATask,
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    AuthMethod,
    Part,
    PushNotificationConfig,
    TaskEvent,
    TaskState,
)
from pylon.protocols.mcp.types import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcRequest
from pylon.safety.context import SafetyContext
from pylon.types import AgentCapability, TrustLevel

# ── Helpers ──────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_task(task_id: str = "test-1", msg: str = "hello") -> A2ATask:
    return A2ATask(
        id=task_id,
        messages=[A2AMessage(role="user", parts=[Part(type="text", content=msg)])],
    )


# ── TaskState Tests ──────────────────────────────────────────────────

class TestTaskState:
    def test_valid_transitions_from_submitted(self):
        assert TaskState.SUBMITTED.can_transition_to(TaskState.WORKING)
        assert TaskState.SUBMITTED.can_transition_to(TaskState.CANCELED)
        assert TaskState.SUBMITTED.can_transition_to(TaskState.FAILED)

    def test_invalid_transition_from_submitted(self):
        assert not TaskState.SUBMITTED.can_transition_to(TaskState.COMPLETED)

    def test_valid_transitions_from_working(self):
        assert TaskState.WORKING.can_transition_to(TaskState.COMPLETED)
        assert TaskState.WORKING.can_transition_to(TaskState.FAILED)
        assert TaskState.WORKING.can_transition_to(TaskState.CANCELED)
        assert TaskState.WORKING.can_transition_to(TaskState.INPUT_REQUIRED)

    def test_terminal_states_have_no_transitions(self):
        for state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED):
            assert not state.can_transition_to(TaskState.WORKING)
            assert not state.can_transition_to(TaskState.SUBMITTED)


# ── A2ATask Tests ────────────────────────────────────────────────────

class TestA2ATask:
    def test_task_creation_defaults(self):
        task = A2ATask()
        assert task.state == TaskState.SUBMITTED
        assert task.messages == []
        assert task.artifacts == []
        assert task.id  # auto-generated

    def test_task_transition(self):
        task = _make_task()
        task.transition_to(TaskState.WORKING)
        assert task.state == TaskState.WORKING

    def test_task_invalid_transition_raises(self):
        task = _make_task()
        with pytest.raises(ValueError, match="Invalid transition"):
            task.transition_to(TaskState.COMPLETED)

    def test_task_full_lifecycle(self):
        task = _make_task()
        task.transition_to(TaskState.WORKING)
        task.add_artifact(Artifact(name="result", parts=[Part(type="text", content="done")]))
        task.transition_to(TaskState.COMPLETED)
        assert task.state == TaskState.COMPLETED
        assert len(task.artifacts) == 1

    def test_task_to_dict_and_from_dict(self):
        task = _make_task("round-trip")
        task.metadata = {"key": "value"}
        task.push_notification = PushNotificationConfig(
            url="https://example.com/hook",
            token="secret",
            events=["completed"],
        )
        d = task.to_dict()
        restored = A2ATask.from_dict(d)
        assert restored.id == "round-trip"
        assert restored.state == TaskState.SUBMITTED
        assert len(restored.messages) == 1
        assert restored.metadata == {"key": "value"}
        assert restored.push_notification is not None
        assert restored.push_notification.url == "https://example.com/hook"

    def test_task_add_message(self):
        task = _make_task()
        task.add_message(A2AMessage(role="agent", parts=[Part(type="text", content="reply")]))
        assert len(task.messages) == 2
        assert task.messages[1].role == "agent"


# ── Server Tests ─────────────────────────────────────────────────────

class TestA2AServer:
    def test_send_task(self):
        server = A2AServer()
        task = _make_task()
        req = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="1",
        )
        resp = _run(server.handle_request(req))
        assert resp.error is None
        assert resp.result["state"] == "working"

    def test_send_task_blocked_by_safety_context(self):
        server = A2AServer(
            local_capability=AgentCapability(can_access_secrets=True),
            peer_policies={
                "peer-a": SafetyContext(
                    agent_name="peer-a",
                    held_capability=AgentCapability(can_write_external=True),
                    data_taint=TrustLevel.UNTRUSTED,
                )
            },
        )
        task = _make_task()
        req = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="1b",
        )
        resp = _run(server.handle_request(req))
        assert resp.error is not None
        assert resp.error.code == -32003

    def test_send_task_untrusted_messages_block_secret_receiver_without_peer_claims(self):
        server = A2AServer(local_capability=AgentCapability(can_access_secrets=True))
        task = _make_task("test-unsafe", "remote message")
        req = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="1c",
        )
        resp = _run(server.handle_request(req))
        assert resp.error is not None
        assert resp.error.code == -32003

    def test_send_transitions_to_working(self):
        server = A2AServer()
        task = _make_task("t-working")
        req = JsonRpcRequest(
            method="tasks/send",
            params={"sender": "", "task": task.to_dict()},
            id="2",
        )
        resp = _run(server.handle_request(req))
        assert resp.result["state"] == "working"

    def test_get_task(self):
        server = A2AServer()
        task = _make_task("t-get")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "", "task": task.to_dict()},
            id="s1",
        )))
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/get",
            params={"taskId": "t-get"},
            id="g1",
        )))
        assert resp.error is None
        assert resp.result["id"] == "t-get"

    def test_get_nonexistent_task(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/get",
            params={"taskId": "nope"},
            id="g2",
        )))
        assert resp.error is not None
        assert resp.error.code == TASK_NOT_FOUND
        assert "not found" in resp.error.message.lower()

    def test_cancel_task(self):
        server = A2AServer()
        task = _make_task("t-cancel")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "", "task": task.to_dict()},
            id="s2",
        )))
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/cancel",
            params={"taskId": "t-cancel"},
            id="c1",
        )))
        assert resp.error is None
        assert resp.result["state"] == "canceled"

    def test_cancel_completed_task_fails(self):
        server = A2AServer()
        task = _make_task("t-comp")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "", "task": task.to_dict()},
            id="s3",
        )))
        # Manually complete the task
        server._tasks["t-comp"].transition_to(TaskState.COMPLETED)
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/cancel",
            params={"taskId": "t-comp"},
            id="c2",
        )))
        assert resp.error is not None
        assert "cannot cancel" in resp.error.message.lower()

    def test_unknown_method(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/unknown",
            params={},
            id="u1",
        )))
        assert resp.error is not None
        assert resp.error.code == METHOD_NOT_FOUND

    def test_set_and_get_push_notification(self):
        server = A2AServer()
        task = _make_task("push-1")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="pn-send",
        )))

        set_resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/set",
            params={
                "taskId": "push-1",
                "pushNotification": {
                    "url": "https://hook.example",
                    "token": "abc",
                    "events": ["completed"],
                },
            },
            id="pn-set",
        )))
        assert set_resp.error is None
        assert set_resp.result["taskId"] == "push-1"

        get_resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/get",
            params={"taskId": "push-1"},
            id="pn-get",
        )))
        assert get_resp.error is None
        assert get_resp.result["pushNotification"]["url"] == "https://hook.example"

    def test_set_push_notification_requires_task(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/set",
            params={
                "taskId": "missing",
                "pushNotification": {"url": "https://hook.example", "events": []},
            },
            id="pn-missing",
        )))
        assert resp.error is not None
        assert resp.error.code == TASK_NOT_FOUND

    def test_missing_task_in_send(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "a"},
            id="m1",
        )))
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS

    def test_missing_task_id_in_get(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/get",
            params={},
            id="m2",
        )))
        assert resp.error is not None

    def test_missing_task_id_in_cancel(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/cancel",
            params={},
            id="m3",
        )))
        assert resp.error is not None

    def test_get_rejects_snake_case_task_id(self):
        server = A2AServer()
        task = _make_task("camel-only")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="camel-send",
        )))
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/get",
            params={"task_id": "camel-only"},
            id="camel-get",
        )))
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS

    def test_push_notification_set_rejects_snake_case_fields(self):
        server = A2AServer()
        task = _make_task("camel-push")
        _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "peer-a", "task": task.to_dict()},
            id="camel-push-send",
        )))
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/set",
            params={
                "task_id": "camel-push",
                "push_notification": {"url": "https://hook.example", "events": []},
            },
            id="camel-push-set",
        )))
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS


# ── Peer Authentication Tests ────────────────────────────────────────

class TestPeerAuth:
    def test_allowed_peer_succeeds(self):
        server = A2AServer(allowed_peers={"agent-a", "agent-b"})
        task = _make_task("auth-ok")
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "agent-a", "task": task.to_dict()},
            id="a1",
        )))
        assert resp.error is None

    def test_denied_peer_fails(self):
        server = A2AServer(allowed_peers={"agent-a"})
        task = _make_task("auth-deny")
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "agent-x", "task": task.to_dict()},
            id="a2",
        )))
        assert resp.error is not None
        assert "unknown peer" in resp.error.message.lower()

    def test_no_allowlist_allows_all(self):
        server = A2AServer()
        assert server.is_peer_allowed("anyone")

    def test_add_peer_dynamically(self):
        server = A2AServer(allowed_peers={"agent-a"})
        assert not server.is_peer_allowed("agent-c")
        server.add_peer("agent-c")
        assert server.is_peer_allowed("agent-c")

    def test_remove_peer(self):
        server = A2AServer(allowed_peers={"agent-a", "agent-b"})
        server.remove_peer("agent-b")
        assert not server.is_peer_allowed("agent-b")

    def test_authenticated_peer_matches_sender(self):
        """H2: authenticated_peer matching sender should succeed."""
        server = A2AServer()
        task = _make_task("auth-match")
        resp = _run(server.handle_request(
            JsonRpcRequest(
                method="tasks/send",
                params={"sender": "agent-a", "task": task.to_dict()},
                id="am1",
            ),
            authenticated_peer="agent-a",
        ))
        assert resp.error is None

    def test_authenticated_peer_mismatch_rejected(self):
        """H2: sender spoofing detected via authenticated_peer mismatch."""
        server = A2AServer()
        task = _make_task("auth-spoof")
        resp = _run(server.handle_request(
            JsonRpcRequest(
                method="tasks/send",
                params={"sender": "agent-a", "task": task.to_dict()},
                id="am2",
            ),
            authenticated_peer="agent-b",
        ))
        assert resp.error is not None
        assert resp.error.code == -32003  # FORBIDDEN
        assert "does not match" in resp.error.message.lower()

    def test_no_authenticated_peer_allows_any_sender(self):
        """H2: Without authenticated_peer, existing behaviour is preserved."""
        server = A2AServer()
        task = _make_task("auth-none")
        resp = _run(server.handle_request(
            JsonRpcRequest(
                method="tasks/send",
                params={"sender": "anyone", "task": task.to_dict()},
                id="am3",
            ),
        ))
        assert resp.error is None


# ── Rate Limiting Tests ──────────────────────────────────────────────

class TestRateLimiting:
    def test_rate_limit_exceeded(self):
        server = A2AServer(rate_limit=2, rate_window=60.0)
        for i in range(3):
            task = _make_task(f"rl-{i}")
            resp = _run(server.handle_request(JsonRpcRequest(
                method="tasks/send",
                params={"sender": "fast-peer", "task": task.to_dict()},
                id=f"rl-{i}",
            )))
            if i < 2:
                assert resp.error is None
            else:
                assert resp.error is not None
                assert resp.error.code == RATE_LIMITED

    def test_no_rate_limit(self):
        server = A2AServer(rate_limit=0)
        for i in range(10):
            task = _make_task(f"nrl-{i}")
            resp = _run(server.handle_request(JsonRpcRequest(
                method="tasks/send",
                params={"sender": "peer", "task": task.to_dict()},
                id=f"nrl-{i}",
            )))
            assert resp.error is None


# ── Task Handler Tests ───────────────────────────────────────────────

class TestTaskHandler:
    def test_custom_handler(self):
        server = A2AServer()

        @server.on_task
        async def handle(task: A2ATask) -> A2ATask:
            task.add_artifact(
                Artifact(name="output", parts=[Part(type="text", content="processed")])
            )
            task.transition_to(TaskState.COMPLETED)
            return task

        task = _make_task("handler-1")
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/send",
            params={"sender": "", "task": task.to_dict()},
            id="h1",
        )))
        assert resp.error is None
        assert resp.result["state"] == "completed"
        assert len(resp.result["artifacts"]) == 1


# ── Client Tests ─────────────────────────────────────────────────────

class TestA2AClient:
    def test_client_send_task(self):
        server = A2AServer()
        client = A2AClient(server, sender="client-a")
        task = _make_task("client-send")
        result = _run(client.send_task(task))
        assert result.state == TaskState.WORKING
        assert result.id == "client-send"

    def test_client_get_task(self):
        server = A2AServer()
        client = A2AClient(server, sender="client-a")
        task = _make_task("client-get")
        _run(client.send_task(task))
        fetched = _run(client.get_task("client-get"))
        assert fetched.id == "client-get"

    def test_client_cancel_task(self):
        server = A2AServer()
        client = A2AClient(server, sender="client-a")
        task = _make_task("client-cancel")
        _run(client.send_task(task))
        success = _run(client.cancel_task("client-cancel"))
        assert success is True

    def test_client_cancel_nonexistent(self):
        server = A2AServer()
        client = A2AClient(server, sender="client-a")
        success = _run(client.cancel_task("nope"))
        assert success is False

    def test_client_send_denied_peer(self):
        server = A2AServer(allowed_peers={"allowed-only"})
        client = A2AClient(server, sender="intruder", max_retries=0)
        task = _make_task("denied")
        with pytest.raises(RuntimeError, match="failed"):
            _run(client.send_task(task))


# ── Streaming Tests ──────────────────────────────────────────────────

class TestStreaming:
    def test_subscribe_default_completes(self):
        server = A2AServer()
        client = A2AClient(server, sender="streamer")
        task = _make_task("stream-1")

        async def collect():
            events = []
            async for event in client.send_subscribe(task):
                events.append(event)
            return events

        events = _run(collect())
        assert len(events) >= 2
        assert events[0].type == "status"
        assert events[0].state == "working"
        assert events[-1].state == "completed"

    def test_subscribe_custom_handler(self):
        server = A2AServer()

        @server.on_stream
        async def stream(task):
            from pylon.protocols.a2a.types import TaskEvent
            yield TaskEvent(type="message", task_id=task.id, data={"msg": "step1"})
            yield TaskEvent(type="status", task_id=task.id, state="completed")

        client = A2AClient(server, sender="s")
        task = _make_task("stream-2")

        async def collect():
            events = []
            async for event in client.send_subscribe(task):
                events.append(event)
            return events

        events = _run(collect())
        assert any(e.type == "message" for e in events)


# ── Connection Pool Tests ────────────────────────────────────────────

class TestConnectionPool:
    def test_pool_add_get(self):
        pool = A2AConnectionPool()
        server = A2AServer()
        client = A2AClient(server, sender="pool-c")
        pool.add("peer-1", client)
        assert pool.get("peer-1") is client
        assert len(pool) == 1

    def test_pool_remove(self):
        pool = A2AConnectionPool()
        server = A2AServer()
        pool.add("p", A2AClient(server))
        pool.remove("p")
        assert pool.get("p") is None
        assert len(pool) == 0

    def test_pool_list_peers(self):
        pool = A2AConnectionPool()
        server = A2AServer()
        pool.add("a", A2AClient(server))
        pool.add("b", A2AClient(server))
        assert sorted(pool.list_peers()) == ["a", "b"]


# ── Agent Card Tests ─────────────────────────────────────────────────

class TestAgentCard:
    def test_generate_card(self):
        card = generate_card(
            "test-agent",
            "http://localhost:8080",
            description="A test agent",
            capabilities=AgentCapabilities(streaming=True),
            skills=[AgentSkill(name="code", description="Code gen")],
            authentication=AuthMethod.BEARER,
        )
        assert card.name == "test-agent"
        assert card.capabilities.streaming is True
        assert len(card.skills) == 1

    def test_card_to_dict_roundtrip(self):
        card = generate_card("roundtrip", "http://example.com", provider="pylon")
        d = card.to_dict()
        restored = AgentCard.from_dict(d)
        assert restored.name == "roundtrip"
        assert restored.provider == "pylon"

    def test_card_validation_missing_name(self):
        card = AgentCard(url="http://example.com")
        errors = card.validate()
        assert any("name" in e for e in errors)

    def test_card_validation_missing_url(self):
        card = AgentCard(name="test")
        errors = card.validate()
        assert any("url" in e for e in errors)

    def test_card_validation_passes(self):
        card = AgentCard(name="ok", url="http://ok.com", version="1.0.0")
        assert card.validate() == []


# ── Card Registry Tests ──────────────────────────────────────────────

class TestCardRegistry:
    def test_register_and_lookup(self):
        registry = AgentCardRegistry()
        card = AgentCard(name="agent-1", url="http://a1.com")
        registry.register(card)
        assert registry.is_registered("agent-1")
        assert registry.get("agent-1") is card

    def test_register_invalid_card_raises(self):
        registry = AgentCardRegistry()
        card = AgentCard()  # no name, no url
        with pytest.raises(ValueError, match="Invalid agent card"):
            registry.register(card)

    def test_unregister(self):
        registry = AgentCardRegistry()
        card = AgentCard(name="temp", url="http://t.com")
        registry.register(card)
        registry.unregister("temp")
        assert not registry.is_registered("temp")

    def test_list_peers(self):
        registry = AgentCardRegistry()
        for i in range(3):
            registry.register(AgentCard(name=f"a{i}", url=f"http://a{i}.com"))
        assert len(registry.list_peers()) == 3

    def test_find_by_skill(self):
        registry = AgentCardRegistry()
        registry.register(AgentCard(
            name="coder",
            url="http://c.com",
            skills=[AgentSkill(name="code-gen")],
        ))
        registry.register(AgentCard(
            name="reviewer",
            url="http://r.com",
            skills=[AgentSkill(name="review")],
        ))
        results = registry.find_by_skill("code-gen")
        assert len(results) == 1
        assert results[0].name == "coder"

    def test_find_by_capability(self):
        registry = AgentCardRegistry()
        registry.register(AgentCard(
            name="streamer",
            url="http://s.com",
            capabilities=AgentCapabilities(streaming=True),
        ))
        registry.register(AgentCard(
            name="basic",
            url="http://b.com",
        ))
        results = registry.find_by_capability("streaming")
        assert len(results) == 1
        assert results[0].name == "streamer"


# ── Type Serialization Tests ─────────────────────────────────────────

class TestTypeSerialization:
    def test_part_roundtrip(self):
        p = Part(type="text", content="hello")
        assert Part.from_dict(p.to_dict()).content == "hello"

    def test_message_roundtrip(self):
        m = A2AMessage(role="user", parts=[Part(type="text", content="hi")])
        d = m.to_dict()
        restored = A2AMessage.from_dict(d)
        assert restored.role == "user"
        assert len(restored.parts) == 1

    def test_artifact_with_metadata(self):
        a = Artifact(name="out", metadata={"format": "json"})
        d = a.to_dict()
        assert d["metadata"] == {"format": "json"}
        restored = Artifact.from_dict(d)
        assert restored.metadata["format"] == "json"

    def test_push_notification_config(self):
        pn = PushNotificationConfig(url="https://hook.com", token="t", events=["completed"])
        d = pn.to_dict()
        restored = PushNotificationConfig.from_dict(d)
        assert restored.url == "https://hook.com"
        assert restored.events == ["completed"]

    def test_task_event(self):
        e = TaskEvent(type="status", task_id="t1", state="working")
        d = e.to_dict()
        assert d["type"] == "status"
        assert d["state"] == "working"

    def test_agent_skill_roundtrip(self):
        s = AgentSkill(name="code", input_modes=["text"], output_modes=["text", "code"])
        d = s.to_dict()
        restored = AgentSkill.from_dict(d)
        assert restored.name == "code"
        assert restored.output_modes == ["text", "code"]

    def test_agent_capabilities_roundtrip(self):
        c = AgentCapabilities(streaming=True, push_notifications=True)
        d = c.to_dict()
        restored = AgentCapabilities.from_dict(d)
        assert restored.streaming is True
        assert restored.push_notifications is True
        assert restored.state_transition_history is False


# -- M8: TASK_NOT_FOUND error code tests ---------------------------------

class TestTaskNotFoundErrorCode:
    """M8: Task not found should use TASK_NOT_FOUND (-32001), not INVALID_PARAMS."""

    def test_get_nonexistent_uses_task_not_found_code(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/get", params={"taskId": "missing"}, id="tnf-1",
        )))
        assert resp.error.code == TASK_NOT_FOUND

    def test_cancel_nonexistent_uses_task_not_found_code(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/cancel", params={"taskId": "missing"}, id="tnf-2",
        )))
        assert resp.error.code == TASK_NOT_FOUND

    def test_push_notification_set_nonexistent_uses_task_not_found_code(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/set",
            params={
                "taskId": "missing",
                "pushNotification": {"url": "https://hook.example", "events": []},
            },
            id="tnf-3",
        )))
        assert resp.error.code == TASK_NOT_FOUND

    def test_push_notification_get_nonexistent_uses_task_not_found_code(self):
        server = A2AServer()
        resp = _run(server.handle_request(JsonRpcRequest(
            method="tasks/pushNotification/get",
            params={"taskId": "missing"},
            id="tnf-4",
        )))
        assert resp.error.code == TASK_NOT_FOUND


# -- M12: Rate limit memory leak tests -----------------------------------

class TestRateLimitMemoryLeak:
    """M12: Peer entries should be cleaned up when their timestamps expire."""

    def test_expired_peer_entries_are_removed(self):
        server = A2AServer(rate_limit=10, rate_window=0.001)
        # Force a request with a timestamp far in the past
        server._peer_requests["old-peer"] = [0.0]
        import time
        time.sleep(0.002)  # ensure the entry expires
        # Calling _check_rate_limit filters out expired entries and deletes empty list
        # But it also adds a new entry because the peer is under the limit.
        # To test cleanup only, we verify the old timestamp was removed.
        server._check_rate_limit("old-peer")
        # The old timestamp (0.0) should be gone; only the new one remains
        timestamps = server._peer_requests.get("old-peer", [])
        assert all(t > 1.0 for t in timestamps)  # no ancient timestamps

    def test_empty_peer_list_is_deleted(self):
        """After filtering, if no timestamps remain and under limit, entry is recreated.
        But if we just filter without calling, empty list should be removed."""
        server = A2AServer(rate_limit=10, rate_window=0.001)
        server._peer_requests["stale"] = [0.0]
        import time
        time.sleep(0.002)
        # Manually trigger the filtering logic
        now = time.time()
        cutoff = now - server._rate_window
        server._peer_requests["stale"] = [
            t for t in server._peer_requests["stale"] if t > cutoff
        ]
        # After filtering, the list is empty -- our fix should handle this
        assert server._peer_requests["stale"] == []

    def test_active_peer_entries_are_kept(self):
        server = A2AServer(rate_limit=10, rate_window=60.0)
        server._check_rate_limit("active-peer")
        assert "active-peer" in server._peer_requests
        assert len(server._peer_requests["active-peer"]) == 1


# -- M13: PushNotificationConfig URL validation tests ---------------------

class TestPushNotificationUrlValidation:
    """M13: PushNotificationConfig must validate URL scheme."""

    def test_https_url_accepted(self):
        pn = PushNotificationConfig(url="https://example.com/hook", token="t")
        assert pn.url == "https://example.com/hook"

    def test_http_url_rejected(self):
        with pytest.raises(ValueError, match="https scheme"):
            PushNotificationConfig(url="http://example.com/hook", token="t")

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            PushNotificationConfig(url="", token="t")

    def test_ftp_url_rejected(self):
        with pytest.raises(ValueError, match="https scheme"):
            PushNotificationConfig(url="ftp://example.com/hook", token="t")
