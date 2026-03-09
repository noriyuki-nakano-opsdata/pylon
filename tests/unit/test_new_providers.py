"""Tests for 7 new OpenAI-compatible LLM providers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import pylon.providers.deepseek as deepseek_mod
import pylon.providers.groq as groq_mod
import pylon.providers.mistral as mistral_mod
import pylon.providers.moonshot as moonshot_mod
import pylon.providers.together as together_mod
import pylon.providers.xai as xai_mod
import pylon.providers.zhipu as zhipu_mod
from pylon.errors import ProviderError
from pylon.providers.base import Message
from pylon.providers.deepseek import DeepSeekProvider
from pylon.providers.groq import GroqProvider
from pylon.providers.mistral import MistralProvider, _normalize_tool_choice
from pylon.providers.moonshot import MoonshotProvider
from pylon.providers.together import TogetherProvider
from pylon.providers.xai import XAIProvider
from pylon.providers.zhipu import ZhipuProvider


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fake_openai_module():
    """Build a fake ``openai`` module namespace."""

    class _FakeAPIError(Exception):
        status_code = 500

    mod = SimpleNamespace(
        APIError=_FakeAPIError,
        AsyncOpenAI=MagicMock,
    )
    return mod, _FakeAPIError


def _mock_chat_result(
    model: str = "test-model",
    content: str = "Hello!",
    prompt_tokens: int = 8,
    completion_tokens: int = 3,
    reasoning_content: str | None = None,
    prompt_cache_hit_tokens: int = 0,
):
    """Build a fake OpenAI chat completion result."""
    message_attrs = {"content": content, "tool_calls": None}
    if reasoning_content is not None:
        message_attrs["reasoning_content"] = reasoning_content
    message = SimpleNamespace(**message_attrs)

    usage_attrs = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if prompt_cache_hit_tokens:
        usage_attrs["prompt_cache_hit_tokens"] = prompt_cache_hit_tokens
    usage = SimpleNamespace(**usage_attrs)

    return SimpleNamespace(
        model=model,
        usage=usage,
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
    )


def _setup_provider(monkeypatch, mod, fake_mod, mock_result=None):
    """Patch module-level openai and wire up a mock client."""
    mock_client = MagicMock()
    if mock_result is not None:
        mock_client.chat.completions.create = AsyncMock(return_value=mock_result)
    fake_mod.AsyncOpenAI = lambda api_key=None, base_url=None: mock_client
    monkeypatch.setattr(mod, "openai", fake_mod)
    return mock_client


# ---------------------------------------------------------------------------
# DeepSeek Provider
# ---------------------------------------------------------------------------


class TestDeepSeekProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(deepseek_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            DeepSeekProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(deepseek_mod, "openai", fake)
        p = DeepSeekProvider(model="deepseek-chat", api_key="k")
        assert p.model_id == "deepseek-chat"
        assert p.provider_name == "deepseek"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="deepseek-chat")
        _setup_provider(monkeypatch, deepseek_mod, fake, result)

        p = DeepSeekProvider(model="deepseek-chat", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.usage.input_tokens == 8
        assert resp.reasoning is None

    @pytest.mark.asyncio
    async def test_reasoning_extraction(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(
            model="deepseek-reasoner",
            reasoning_content="Let me think step by step...",
        )
        _setup_provider(monkeypatch, deepseek_mod, fake, result)

        p = DeepSeekProvider(model="deepseek-reasoner", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.reasoning is not None
        assert resp.reasoning.content == "Let me think step by step..."

    @pytest.mark.asyncio
    async def test_cache_token_extraction(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(
            model="deepseek-chat",
            prompt_cache_hit_tokens=50,
        )
        _setup_provider(monkeypatch, deepseek_mod, fake, result)

        p = DeepSeekProvider(model="deepseek-chat", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.usage.cache_read_tokens == 50


# ---------------------------------------------------------------------------
# Groq Provider
# ---------------------------------------------------------------------------


class TestGroqProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(groq_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            GroqProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(groq_mod, "openai", fake)
        p = GroqProvider(model="llama-3.3-70b-versatile", api_key="k")
        assert p.model_id == "llama-3.3-70b-versatile"
        assert p.provider_name == "groq"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="llama-3.3-70b-versatile")
        _setup_provider(monkeypatch, groq_mod, fake, result)

        p = GroqProvider(model="llama-3.3-70b-versatile", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.usage.input_tokens == 8


# ---------------------------------------------------------------------------
# Mistral Provider
# ---------------------------------------------------------------------------


class TestMistralProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(mistral_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            MistralProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(mistral_mod, "openai", fake)
        p = MistralProvider(model="mistral-small-latest", api_key="k")
        assert p.model_id == "mistral-small-latest"
        assert p.provider_name == "mistral"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="mistral-small-latest")
        _setup_provider(monkeypatch, mistral_mod, fake, result)

        p = MistralProvider(model="mistral-small-latest", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.usage.input_tokens == 8

    def test_tool_choice_any_maps_to_required(self):
        assert _normalize_tool_choice("any") == "required"
        assert _normalize_tool_choice("auto") == "auto"
        assert _normalize_tool_choice(None) is None


# ---------------------------------------------------------------------------
# xAI Provider
# ---------------------------------------------------------------------------


class TestXAIProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(xai_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            XAIProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(xai_mod, "openai", fake)
        p = XAIProvider(model="grok-4", api_key="k")
        assert p.model_id == "grok-4"
        assert p.provider_name == "xai"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="grok-4")
        _setup_provider(monkeypatch, xai_mod, fake, result)

        p = XAIProvider(model="grok-4", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.reasoning is None

    @pytest.mark.asyncio
    async def test_reasoning_extraction(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(
            model="grok-4",
            reasoning_content="Analyzing the question...",
        )
        _setup_provider(monkeypatch, xai_mod, fake, result)

        p = XAIProvider(model="grok-4", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.reasoning is not None
        assert resp.reasoning.content == "Analyzing the question..."


# ---------------------------------------------------------------------------
# Together Provider
# ---------------------------------------------------------------------------


class TestTogetherProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(together_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            TogetherProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(together_mod, "openai", fake)
        p = TogetherProvider(api_key="k")
        assert p.model_id == "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
        assert p.provider_name == "together"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo")
        _setup_provider(monkeypatch, together_mod, fake, result)

        p = TogetherProvider(api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.usage.input_tokens == 8


# ---------------------------------------------------------------------------
# Moonshot Provider
# ---------------------------------------------------------------------------


class TestMoonshotProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(moonshot_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            MoonshotProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(moonshot_mod, "openai", fake)
        p = MoonshotProvider(model="kimi-k2.5", api_key="k")
        assert p.model_id == "kimi-k2.5"
        assert p.provider_name == "moonshot"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="kimi-k2.5")
        _setup_provider(monkeypatch, moonshot_mod, fake, result)

        p = MoonshotProvider(model="kimi-k2.5", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.reasoning is None

    @pytest.mark.asyncio
    async def test_reasoning_extraction(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(
            model="kimi-k2.5",
            reasoning_content="Thinking about this...",
        )
        _setup_provider(monkeypatch, moonshot_mod, fake, result)

        p = MoonshotProvider(model="kimi-k2.5", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.reasoning is not None
        assert resp.reasoning.content == "Thinking about this..."


# ---------------------------------------------------------------------------
# Zhipu Provider
# ---------------------------------------------------------------------------


class TestZhipuProvider:
    def test_import_error(self, monkeypatch):
        monkeypatch.setattr(zhipu_mod, "openai", None)
        with pytest.raises(ProviderError, match="openai package"):
            ZhipuProvider()

    def test_properties(self, monkeypatch):
        fake, _ = _fake_openai_module()
        monkeypatch.setattr(zhipu_mod, "openai", fake)
        p = ZhipuProvider(model="glm-5", api_key="k")
        assert p.model_id == "glm-5"
        assert p.provider_name == "zhipu"

    @pytest.mark.asyncio
    async def test_chat_happy_path(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(model="glm-5")
        _setup_provider(monkeypatch, zhipu_mod, fake, result)

        p = ZhipuProvider(model="glm-5", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.content == "Hello!"
        assert resp.reasoning is None

    @pytest.mark.asyncio
    async def test_reasoning_extraction(self, monkeypatch):
        fake, _ = _fake_openai_module()
        result = _mock_chat_result(
            model="glm-5",
            reasoning_content="Let me reason through this...",
        )
        _setup_provider(monkeypatch, zhipu_mod, fake, result)

        p = ZhipuProvider(model="glm-5", api_key="k")
        resp = await p.chat([Message(role="user", content="hi")])
        assert resp.reasoning is not None
        assert resp.reasoning.content == "Let me reason through this..."
