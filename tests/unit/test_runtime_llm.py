from __future__ import annotations

from dataclasses import dataclass

import pytest

from pylon.autonomy.routing import ModelProfile, ModelRouter, ModelRouteRequest, ModelTier
from pylon.cost.fallback_engine import (
    FallbackChainConfig,
    FallbackEngine,
    FallbackTarget,
    ProviderCallError,
)
from pylon.dsl.parser import PylonProject
from pylon.providers.base import Message, Response, TokenUsage
from pylon.runtime import LLMRuntime, ModelPricing, ProviderRegistry, execute_project_sync
from pylon.runtime.context import ContextManager, ContextWindowConfig
from pylon.runtime.llm import estimate_message_tokens, messages_from_input


@dataclass
class FakeProvider:
    model: str
    provider_name: str = "fake"
    last_kwargs: dict[str, object] | None = None

    @property
    def model_id(self) -> str:
        return self.model

    async def chat(self, messages: list[Message], **kwargs: object) -> Response:
        self.last_kwargs = kwargs
        content = "|".join(message.content for message in messages)
        return Response(
            content=f"echo:{content}",
            model=str(kwargs.get("model", self.model)),
            usage=TokenUsage(input_tokens=120, output_tokens=30),
        )

    async def stream(self, messages: list[Message], **kwargs: object):  # pragma: no cover
        del messages, kwargs
        if False:
            yield None


@dataclass
class FailingProvider(FakeProvider):
    status_code: int = 503
    call_count: int = 0

    async def chat(self, messages: list[Message], **kwargs: object) -> Response:
        del messages, kwargs
        self.call_count += 1
        raise ProviderCallError(
            "provider unavailable",
            status_code=self.status_code,
            provider=self.provider_name,
            model_id=self.model,
        )


def test_message_helpers() -> None:
    assert estimate_message_tokens([Message(role="user", content="hello world")]) >= 1
    parsed = messages_from_input([{"role": "user", "content": "hi"}])
    assert parsed[0].content == "hi"
    assert messages_from_input("hello")[0].content == "hello"


def test_message_helpers_reject_invalid_type() -> None:
    with pytest.raises(ValueError):
        messages_from_input({"role": "user"})


def test_context_manager_compacts_long_inputs() -> None:
    manager = ContextManager(
        ContextWindowConfig(max_input_tokens=20, keep_last_messages=2, summary_char_limit=200)
    )
    prepared = manager.prepare(
        [
            Message(role="system", content="You are precise."),
            Message(role="user", content="A" * 400),
            Message(role="assistant", content="B" * 400),
            Message(role="user", content="C" * 400),
        ]
    )

    assert prepared.was_compacted is True
    assert prepared.prepared_input_tokens < prepared.original_input_tokens
    assert any(
        message.content.startswith("Compacted prior context:")
        for message in prepared.messages
    )


def test_context_window_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        ContextWindowConfig(keep_last_messages=0)


@pytest.mark.asyncio
async def test_llm_runtime_routes_and_estimates_cost() -> None:
    provider = FakeProvider("fake-standard")
    registry = ProviderRegistry({"fake": lambda _model_id: provider})
    router = ModelRouter(
        profiles=(
            ModelProfile(provider_name="fake", model_id="fake-standard", tier=ModelTier.STANDARD),
        )
    )
    runtime = LLMRuntime(
        router=router,
        pricing={
            ("fake", "fake-standard"): ModelPricing(
                input_per_million=10.0,
                output_per_million=20.0,
            )
        },
    )

    result = await runtime.chat(
        registry=registry,
        request=ModelRouteRequest(
            purpose="unit-test",
            input_tokens_estimate=100,
            requires_tools=True,
        ),
        messages=[Message(role="user", content="hello")],
    )

    assert result.route.provider_name == "fake"
    assert result.response.content == "echo:hello"
    assert result.estimated_cost_usd > 0
    assert provider.last_kwargs is not None
    assert provider.last_kwargs["cache_strategy"] == "none"
    assert provider.last_kwargs["context_compacted"] is False


@pytest.mark.asyncio
async def test_llm_runtime_route_falls_back_to_preferred_model_on_available_provider() -> None:
    provider = FakeProvider("fallback-model")
    registry = ProviderRegistry({"fake": lambda _model_id: provider})
    router = ModelRouter(
        profiles=(
            ModelProfile(
                provider_name="missing",
                model_id="missing-model",
                tier=ModelTier.STANDARD,
            ),
        )
    )
    runtime = LLMRuntime(router=router)

    result = await runtime.chat(
        registry=registry,
        request=ModelRouteRequest(purpose="unit-test", input_tokens_estimate=10),
        messages=[Message(role="user", content="hello")],
        preferred_model="fallback-model",
    )

    assert result.route.provider_name == "fake"
    assert result.route.model_id == "fallback-model"


@pytest.mark.asyncio
async def test_llm_runtime_falls_back_to_available_profile_before_cross_provider_model_id() -> None:
    provider = FakeProvider("google-standard", provider_name="google")
    registry = ProviderRegistry(
        {
            "google": lambda _model_id: provider,
            "fake": lambda _model_id: FakeProvider("other"),
        }
    )
    router = ModelRouter(
        profiles=(
            ModelProfile(
                provider_name="missing",
                model_id="missing-model",
                tier=ModelTier.STANDARD,
            ),
            ModelProfile(
                provider_name="google",
                model_id="google-standard",
                tier=ModelTier.STANDARD,
            ),
        )
    )
    runtime = LLMRuntime(router=router)

    result = await runtime.chat(
        registry=registry,
        request=ModelRouteRequest(purpose="unit-test", input_tokens_estimate=10),
        messages=[Message(role="user", content="hello")],
        preferred_model="preferred-only",
    )

    assert result.route.provider_name == "google"
    assert result.route.model_id == "google-standard"


@pytest.mark.asyncio
async def test_llm_runtime_uses_selected_route_as_fallback_primary_and_records_effective_route() -> None:
    primary = FailingProvider("primary-model", provider_name="fake")
    secondary = FakeProvider("secondary-model", provider_name="backup")
    registry = ProviderRegistry(
        {
            "fake": lambda _model_id: primary,
            "backup": lambda _model_id: secondary,
        }
    )
    router = ModelRouter(
        profiles=(
            ModelProfile(
                provider_name="fake",
                model_id="primary-model",
                tier=ModelTier.STANDARD,
            ),
        )
    )
    fallback_engine = FallbackEngine(
        chains={
            ModelTier.STANDARD: FallbackChainConfig(
                primary_provider="unused",
                primary_model="unused-model",
                primary_tier=ModelTier.STANDARD,
                same_tier=(
                    FallbackTarget("backup", "secondary-model", ModelTier.STANDARD),
                ),
                max_attempts=2,
            )
        }
    )
    runtime = LLMRuntime(
        router=router,
        fallback_engine=fallback_engine,
        pricing={
            ("backup", "secondary-model"): ModelPricing(
                input_per_million=10.0,
                output_per_million=20.0,
            )
        },
    )

    result = await runtime.chat(
        registry=registry,
        request=ModelRouteRequest(purpose="unit-test", input_tokens_estimate=100),
        messages=[Message(role="user", content="hello")],
    )

    assert primary.call_count == 1
    assert result.route.provider_name == "backup"
    assert result.route.model_id == "secondary-model"
    assert result.context["requested_route"]["provider_name"] == "fake"
    assert result.context["fallback"]["final_provider"] == "backup"
    assert result.estimated_cost_usd > 0


def test_execute_project_sync_records_model_route_and_usage() -> None:
    provider = FakeProvider("fake-standard")
    registry = ProviderRegistry({"fake": lambda _model_id: provider})
    router = ModelRouter(
        profiles=(
            ModelProfile(provider_name="fake", model_id="fake-standard", tier=ModelTier.STANDARD),
        )
    )
    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": "runtime-llm",
            "agents": {
                "worker": {
                    "role": "assistant",
                    "autonomy": "A2",
                    "model": "fake/fake-standard",
                }
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "step1": {
                        "agent": "worker",
                        "loop_metadata": {
                            "cacheable_prefix": True,
                            "static_instruction": "You are precise and brief.",
                        },
                        "next": "END",
                    }
                },
            },
        }
    )

    artifacts = execute_project_sync(
        project,
        input_data={"prompt": "hello world"},
        provider_registry=registry,
        model_router=router,
    )

    event = artifacts.run.event_log[0]
    assert artifacts.run.state["last_response"].endswith("hello world")
    assert event["llm_events"][0]["provider"] == "fake"
    assert event["metrics"]["model_route"]["provider_name"] == "fake"
    assert artifacts.run.state["runtime_metrics"]["token_usage"]["total_tokens"] == 150
    assert event["metrics"]["context"]["cacheable_prefix"] is True


def test_execute_project_sync_compacts_long_prompt_context() -> None:
    provider = FakeProvider("fake-standard")
    registry = ProviderRegistry({"fake": lambda _model_id: provider})
    router = ModelRouter(
        profiles=(
            ModelProfile(provider_name="fake", model_id="fake-standard", tier=ModelTier.STANDARD),
        )
    )
    runtime = LLMRuntime(
        router=router,
        context_manager=ContextManager(
            ContextWindowConfig(max_input_tokens=40, keep_last_messages=2, summary_char_limit=200)
        ),
    )
    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": "runtime-llm-compact",
            "agents": {
                "worker": {
                    "role": "assistant",
                    "autonomy": "A2",
                    "model": "fake/fake-standard",
                }
            },
            "workflow": {
                "type": "graph",
                "nodes": {
                    "step1": {
                        "agent": "worker",
                        "loop_metadata": {"static_instruction": "You are concise."},
                        "next": "END",
                    }
                },
            },
        }
    )

    artifacts = execute_project_sync(
        project,
        input_data={
            "messages": [
                {"role": "user", "content": "A" * 400},
                {"role": "assistant", "content": "B" * 400},
                {"role": "user", "content": "C" * 400},
            ]
        },
        provider_registry=registry,
        model_router=router,
        llm_runtime=runtime,
    )

    event = artifacts.run.event_log[0]
    assert event["metrics"]["context"]["compacted"] is True
    assert provider.last_kwargs is not None
    assert provider.last_kwargs["context_compacted"] is True
    assert (
        provider.last_kwargs["prepared_input_tokens"]
        < provider.last_kwargs["original_input_tokens"]
    )


def test_execute_project_sync_rejects_invalid_policy_level() -> None:
    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": "bad-policy",
            "agents": {"worker": {"role": "assistant"}},
            "workflow": {"type": "graph", "nodes": {"step1": {"agent": "worker", "next": "END"}}},
        }
    )
    project.policy.require_approval_above = "AX"

    with pytest.raises(ValueError, match="Invalid require_approval_above"):
        execute_project_sync(project)
