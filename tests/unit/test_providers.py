"""Tests for LLM provider abstraction and all 5 concrete providers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import pylon.providers.anthropic as anthropic_mod
import pylon.providers.bedrock as bedrock_mod
import pylon.providers.ollama as ollama_mod
import pylon.providers.openai as openai_mod
import pylon.providers.vertex as vertex_mod
from pylon.errors import ProviderError
from pylon.providers.anthropic import AnthropicProvider, _to_anthropic_messages
from pylon.providers.base import (
    Chunk,
    LLMProvider,
    Message,
    Response,
    TokenUsage,
)
from pylon.providers.bedrock import BedrockProvider, _to_bedrock_messages
from pylon.providers.ollama import OllamaProvider, _to_ollama_messages
from pylon.providers.openai import OpenAIProvider, _to_openai_messages
from pylon.providers.vertex import VertexProvider, _to_gemini_contents

# ---------------------------------------------------------------------------
# Base dataclass tests
# ---------------------------------------------------------------------------


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
    def test_protocol_check(self):
        assert hasattr(LLMProvider, "chat")
        assert hasattr(LLMProvider, "stream")


# ---------------------------------------------------------------------------
# Helper: fake SDK modules injected via monkeypatch
# ---------------------------------------------------------------------------


def _fake_anthropic_module():
    """Build a fake ``anthropic`` module namespace."""

    class _FakeAPIError(Exception):
        status_code = 400

    mod = SimpleNamespace(
        APIError=_FakeAPIError,
        AsyncAnthropic=MagicMock,
    )
    return mod, _FakeAPIError


def _fake_openai_module():
    class _FakeAPIError(Exception):
        status_code = 500

    mod = SimpleNamespace(
        APIError=_FakeAPIError,
        AsyncOpenAI=MagicMock,
    )
    return mod, _FakeAPIError


def _fake_httpx_module():
    class _FakeHTTPError(Exception):
        pass

    mod = SimpleNamespace(
        HTTPError=_FakeHTTPError,
        AsyncClient=MagicMock,
    )
    return mod, _FakeHTTPError


def _fake_boto3_module():
    mod = SimpleNamespace(
        Session=MagicMock,
    )
    return mod


def _fake_botocore_module():
    class _FakeClientError(Exception):
        def __init__(self):
            self.response = {"Error": {"Code": "ValidationException"}}
            super().__init__("boom")

    exceptions = SimpleNamespace(ClientError=_FakeClientError)
    mod = SimpleNamespace(exceptions=exceptions)
    return mod, _FakeClientError


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------


class TestAnthropicMessageConversion:
    def test_system_extracted(self):
        sys_prompt, msgs = _to_anthropic_messages([
            Message(role="system", content="Be concise."),
            Message(role="user", content="hi"),
        ])
        assert sys_prompt == "Be concise."
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_tool_result(self):
        _, msgs = _to_anthropic_messages([
            Message(role="tool", content="42", tool_call_id="t1"),
        ])
        assert msgs[0]["content"][0]["type"] == "tool_result"
        assert msgs[0]["content"][0]["tool_use_id"] == "t1"

    def test_no_system(self):
        sys_prompt, _ = _to_anthropic_messages([
            Message(role="user", content="hi"),
        ])
        assert sys_prompt is None


class TestAnthropicProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(anthropic_mod, "anthropic", None)
        with pytest.raises(ProviderError, match="anthropic package"):
            AnthropicProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_anthropic_module()
        monkeypatch.setattr(anthropic_mod, "anthropic", fake)
        p = AnthropicProvider(model="claude-test", api_key="k")
        assert p.model_id == "claude-test"
        assert p.provider_name == "anthropic"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_anthropic_module()
        mock_client = MagicMock()
        mock_create = AsyncMock(return_value=SimpleNamespace(
            model="claude-test",
            usage=SimpleNamespace(
                input_tokens=10, output_tokens=5,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
            content=[SimpleNamespace(type="text", text="Hello!")],
            stop_reason="end_turn",
        ))
        mock_client.messages.create = mock_create
        fake.AsyncAnthropic = lambda api_key=None: mock_client
        monkeypatch.setattr(anthropic_mod, "anthropic", fake)

        p = AnthropicProvider(model="claude-test", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.model == "claude-test"
        assert resp.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_chat_api_error(self, monkeypatch):
        fake, fake_error = _fake_anthropic_module()
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=fake_error("fail"))
        fake.AsyncAnthropic = lambda api_key=None: mock_client
        monkeypatch.setattr(anthropic_mod, "anthropic", fake)

        p = AnthropicProvider(model="claude-test", api_key="k")
        with pytest.raises(ProviderError, match="Anthropic API error"):
            await p.chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------


class TestOpenAIMessageConversion:
    def test_basic_roles(self):
        msgs = _to_openai_messages([
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ])
        assert msgs[0] == {"role": "system", "content": "sys"}
        assert msgs[1] == {"role": "user", "content": "hi"}

    def test_tool_message(self):
        msgs = _to_openai_messages([
            Message(role="tool", content="result", tool_call_id="tc1"),
        ])
        assert msgs[0]["tool_call_id"] == "tc1"

    def test_assistant_tool_calls(self):
        calls = [{"id": "c1", "type": "function", "function": {"name": "f"}}]
        msgs = _to_openai_messages([
            Message(role="assistant", content="", tool_calls=calls),
        ])
        assert msgs[0]["tool_calls"] == calls


class TestOpenAIProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(openai_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            OpenAIProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(openai_mod, "openai", fake)
        p = OpenAIProvider(model="gpt-4o", api_key="k")
        assert p.model_id == "gpt-4o"
        assert p.provider_name == "openai"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        mock_client = MagicMock()
        mock_create = AsyncMock(return_value=SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3),
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Hi!", tool_calls=None),
                finish_reason="stop",
            )],
        ))
        mock_client.chat.completions.create = mock_create
        fake.AsyncOpenAI = lambda api_key=None, base_url=None: mock_client
        monkeypatch.setattr(openai_mod, "openai", fake)

        p = OpenAIProvider(model="gpt-4o", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hi!"
        assert resp.usage.input_tokens == 8

    @pytest.mark.asyncio
    async def test_chat_api_error(self, monkeypatch):
        fake, fake_error = _fake_openai_module()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=fake_error("fail"),
        )
        fake.AsyncOpenAI = lambda api_key=None, base_url=None: mock_client
        monkeypatch.setattr(openai_mod, "openai", fake)

        p = OpenAIProvider(model="gpt-4o", api_key="k")
        with pytest.raises(ProviderError, match="OpenAI API error"):
            await p.chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------


class TestOllamaMessageConversion:
    def test_tool_mapped_to_user(self):
        msgs = _to_ollama_messages([
            Message(role="tool", content="42", tool_call_id="t1"),
        ])
        assert msgs[0]["role"] == "user"
        assert "[Tool Result]" in msgs[0]["content"]

    def test_regular_messages(self):
        msgs = _to_ollama_messages([
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ])
        assert msgs[0] == {"role": "system", "content": "sys"}


class TestOllamaProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(ollama_mod, "httpx", None)
        with pytest.raises(ProviderError, match="httpx package"):
            OllamaProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_httpx_module()
        monkeypatch.setattr(ollama_mod, "httpx", fake)
        p = OllamaProvider(model="llama3.1")
        assert p.model_id == "llama3.1"
        assert p.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_httpx_module()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "llama3.1",
            "message": {"content": "Hi!"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        fake.AsyncClient = lambda base_url=None, timeout=None: mock_client
        monkeypatch.setattr(ollama_mod, "httpx", fake)

        p = OllamaProvider(model="llama3.1")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hi!"
        assert resp.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_chat_http_error(self, monkeypatch):
        fake, fake_error = _fake_httpx_module()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=fake_error("fail"))
        fake.AsyncClient = lambda base_url=None, timeout=None: mock_client
        monkeypatch.setattr(ollama_mod, "httpx", fake)

        p = OllamaProvider(model="llama3.1")
        with pytest.raises(ProviderError, match="Ollama API error"):
            await p.chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Bedrock Provider
# ---------------------------------------------------------------------------


class TestBedrockMessageConversion:
    def test_system_extracted(self):
        sys_blocks, msgs = _to_bedrock_messages([
            Message(role="system", content="Be short."),
            Message(role="user", content="hi"),
        ])
        assert sys_blocks == [{"text": "Be short."}]
        assert msgs[0]["content"] == [{"text": "hi"}]

    def test_tool_result(self):
        _, msgs = _to_bedrock_messages([
            Message(role="tool", content="42", tool_call_id="t1"),
        ])
        assert "toolResult" in msgs[0]["content"][0]

    def test_no_system(self):
        sys_blocks, _ = _to_bedrock_messages([
            Message(role="user", content="hi"),
        ])
        assert sys_blocks is None


class TestBedrockProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(bedrock_mod, "boto3", None)
        with pytest.raises(ProviderError, match="boto3 package"):
            BedrockProvider()

    def test_properties(self, monkeypatch):
        fake_boto3 = _fake_boto3_module()
        fake_botocore, _ = _fake_botocore_module()
        mock_session = MagicMock()
        mock_session.client.return_value = MagicMock()
        fake_boto3.Session = lambda **kw: mock_session
        monkeypatch.setattr(bedrock_mod, "boto3", fake_boto3)
        monkeypatch.setattr(bedrock_mod, "botocore", fake_botocore)

        p = BedrockProvider(model="anthropic.claude-v2")
        assert p.model_id == "anthropic.claude-v2"
        assert p.provider_name == "bedrock"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake_boto3 = _fake_boto3_module()
        fake_botocore, _ = _fake_botocore_module()
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {"message": {"content": [{"text": "Hi!"}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "stopReason": "end_turn",
        }
        mock_session = MagicMock()
        mock_session.client.return_value = mock_bedrock
        fake_boto3.Session = lambda **kw: mock_session
        monkeypatch.setattr(bedrock_mod, "boto3", fake_boto3)
        monkeypatch.setattr(bedrock_mod, "botocore", fake_botocore)

        p = BedrockProvider(model="anthropic.claude-v2")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hi!"
        assert resp.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_chat_client_error(self, monkeypatch):
        fake_boto3 = _fake_boto3_module()
        fake_botocore, fake_error = _fake_botocore_module()
        mock_bedrock = MagicMock()
        mock_bedrock.converse.side_effect = fake_error()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_bedrock
        fake_boto3.Session = lambda **kw: mock_session
        monkeypatch.setattr(bedrock_mod, "boto3", fake_boto3)
        monkeypatch.setattr(bedrock_mod, "botocore", fake_botocore)

        p = BedrockProvider(model="anthropic.claude-v2")
        with pytest.raises(ProviderError, match="Bedrock API error"):
            await p.chat([Message(role="user", content="hi")])


# ---------------------------------------------------------------------------
# Vertex Provider
# ---------------------------------------------------------------------------


class TestGeminiMessageConversion:
    def test_system_extracted(self):
        sys_instr, contents = _to_gemini_contents([
            Message(role="system", content="Be brief."),
            Message(role="user", content="hi"),
        ])
        assert sys_instr == "Be brief."
        assert contents[0]["role"] == "user"

    def test_assistant_mapped_to_model(self):
        _, contents = _to_gemini_contents([
            Message(role="assistant", content="sure"),
        ])
        assert contents[0]["role"] == "model"

    def test_tool_mapped_to_user(self):
        _, contents = _to_gemini_contents([
            Message(role="tool", content="42", tool_call_id="t1"),
        ])
        assert contents[0]["role"] == "user"
        assert "[Tool Result]" in contents[0]["parts"][0]["text"]


class TestVertexProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(vertex_mod, "genai", None)
        with pytest.raises(ProviderError, match="google-genai package"):
            VertexProvider(api_key="k")

    def test_requires_key_or_project(self, monkeypatch):
        fake = SimpleNamespace(Client=MagicMock)
        monkeypatch.setattr(vertex_mod, "genai", fake)
        with pytest.raises(ProviderError, match="api_key or project"):
            VertexProvider()

    def test_properties(self, monkeypatch):
        fake = SimpleNamespace(Client=MagicMock)
        monkeypatch.setattr(vertex_mod, "genai", fake)
        p = VertexProvider(model="gemini-2.0-flash", api_key="k")
        assert p.model_id == "gemini-2.0-flash"
        assert p.provider_name == "google"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake = SimpleNamespace(Client=MagicMock)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(
                text="Hi!",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=10,
                    candidates_token_count=5,
                ),
            ),
        )
        fake.Client = lambda api_key=None: mock_client
        monkeypatch.setattr(vertex_mod, "genai", fake)

        p = VertexProvider(model="gemini-2.0-flash", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hi!"
        assert resp.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_chat_api_error(self, monkeypatch):
        fake = SimpleNamespace(Client=MagicMock)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("quota exceeded"),
        )
        fake.Client = lambda api_key=None: mock_client
        monkeypatch.setattr(vertex_mod, "genai", fake)

        p = VertexProvider(model="gemini-2.0-flash", api_key="k")
        with pytest.raises(ProviderError, match="Google API error"):
            await p.chat([Message(role="user", content="hi")])
