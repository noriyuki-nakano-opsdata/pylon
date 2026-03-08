from __future__ import annotations

from types import SimpleNamespace

import pytest

import pylon.providers.anthropic as anthropic_provider_module
from pylon.providers.anthropic import AnthropicProvider, _to_anthropic_messages
from pylon.providers.base import Message, TokenUsage


class _FakeAPIError(Exception):
    pass


class _FakeStream:
    def __init__(self, events):
        self._events = list(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _FakeMessagesAPI:
    def __init__(self, events):
        self._events = events
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            model=kwargs.get("model", "fake-model"),
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=1,
                cache_creation_input_tokens=2,
            ),
            content=[],
            stop_reason="stop",
        )

    def stream(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeStream(self._events)


class _FakeAsyncAnthropic:
    def __init__(self, messages_api):
        self.messages = messages_api


def test_to_anthropic_messages_combines_multiple_system_messages() -> None:
    system_prompt, api_messages = _to_anthropic_messages(
        [
            Message(role="system", content="You are precise."),
            Message(role="system", content="Cite sources."),
            Message(role="user", content="hello"),
        ]
    )

    assert system_prompt == "You are precise.\n\nCite sources."
    assert api_messages == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_stream_emits_tool_calls_usage_and_tools(monkeypatch) -> None:
    events = [
        SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(
                type="tool_use",
                id="tool_1",
                name="search",
                input={"query": "pylon"},
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="hello"),
        ),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="tool_use"),
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=1,
                cache_creation_input_tokens=2,
            ),
        ),
        SimpleNamespace(type="message_stop"),
    ]
    messages_api = _FakeMessagesAPI(events)
    fake_module = SimpleNamespace(
        APIError=_FakeAPIError,
        AsyncAnthropic=lambda api_key=None: _FakeAsyncAnthropic(messages_api),
    )
    monkeypatch.setattr(anthropic_provider_module, "anthropic", fake_module)

    provider = AnthropicProvider(model="claude-test")
    chunks = [
        chunk
        async for chunk in provider.stream(
            [Message(role="user", content="hello")],
            tools=[{"name": "search"}],
        )
    ]

    assert chunks[0].tool_calls == [{"id": "tool_1", "name": "search", "input": {"query": "pylon"}}]
    assert any(chunk.content == "hello" for chunk in chunks)
    usage_chunks = [chunk for chunk in chunks if chunk.usage is not None]
    assert usage_chunks[0].usage == TokenUsage(
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=1,
        cache_write_tokens=2,
    )
    assert messages_api.last_kwargs["tools"] == [{"name": "search"}]
