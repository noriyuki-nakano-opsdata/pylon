"""Tests for LLM provider abstraction."""


from pylon.providers.base import (
    Chunk,
    LLMProvider,
    Message,
    Response,
    TokenUsage,
)


class TestMessage:
    def test_basic_message(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_calls == []

    def test_system_message(self):
        msg = Message(role="system", content="You are helpful.")
        assert msg.role == "system"


class TestTokenUsage:
    def test_total(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_zero(self):
        usage = TokenUsage()
        assert usage.total_tokens == 0

    def test_with_cache(self):
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_write_tokens=10,
        )
        assert usage.total_tokens == 150
        assert usage.cache_read_tokens == 20


class TestResponse:
    def test_basic(self):
        resp = Response(content="Hello!", model="test-model")
        assert resp.content == "Hello!"
        assert resp.finish_reason == "stop"

    def test_with_tools(self):
        resp = Response(
            content="",
            model="test",
            tool_calls=[{"id": "1", "name": "search", "input": {}}],
        )
        assert len(resp.tool_calls) == 1


class TestChunk:
    def test_text_chunk(self):
        chunk = Chunk(content="Hi")
        assert chunk.content == "Hi"
        assert chunk.finish_reason is None

    def test_final_chunk(self):
        chunk = Chunk(finish_reason="stop")
        assert chunk.finish_reason == "stop"


class TestLLMProviderProtocol:
    """Verify the Protocol definition works as expected."""

    def test_protocol_check(self):
        # LLMProvider is a runtime_checkable Protocol
        assert hasattr(LLMProvider, "chat")
        assert hasattr(LLMProvider, "stream")
