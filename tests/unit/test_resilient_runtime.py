"""Tests for ResilientLLMRuntime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylon.autonomy.routing import (
    CacheStrategy,
    ModelRouteDecision,
    ModelRouteRequest,
    ModelTier,
)
from pylon.cost.estimator import CostEstimator
from pylon.cost.optimizer import CostOptimizer, TaskComplexity
from pylon.providers.base import Message, Response, TokenUsage
from pylon.providers.health import ProviderHealthTracker
from pylon.runtime.llm import LLMRuntime, ProviderRegistry, RoutedChatResult
from pylon.runtime.resilient import ResilientChatResult, ResilientLLMRuntime


def _make_route(
    provider: str = "anthropic",
    model: str = "claude-haiku",
) -> ModelRouteDecision:
    return ModelRouteDecision(
        provider_name=provider,
        model_id=model,
        tier=ModelTier.STANDARD,
        reasoning="test",
        cache_strategy=CacheStrategy.NONE,
        batch_eligible=False,
    )


def _make_response(content: str = "hello") -> Response:
    return Response(
        content=content,
        model="claude-haiku",
        usage=TokenUsage(input_tokens=100, output_tokens=50),
    )


def _make_routed_result(
    provider: str = "anthropic",
    model: str = "claude-haiku",
) -> RoutedChatResult:
    return RoutedChatResult(
        response=_make_response(),
        route=_make_route(provider, model),
        estimated_cost_usd=0.001,
        context={"compacted": False},
    )


def _make_request() -> ModelRouteRequest:
    return ModelRouteRequest(
        purpose="test task",
        input_tokens_estimate=1000,
    )


@pytest.fixture
def mock_runtime() -> MagicMock:
    rt = MagicMock(spec=LLMRuntime)
    rt.chat = AsyncMock(return_value=_make_routed_result())
    return rt


@pytest.fixture
def mock_registry() -> MagicMock:
    return MagicMock(spec=ProviderRegistry)


@pytest.fixture
def mock_health() -> MagicMock:
    h = MagicMock(spec=ProviderHealthTracker)
    h.available_providers.return_value = {"anthropic", "openai"}
    return h


@pytest.fixture
def mock_optimizer() -> MagicMock:
    opt = MagicMock(spec=CostOptimizer)
    opt.classify_complexity.return_value = TaskComplexity.LOW
    return opt


@pytest.fixture
def mock_estimator() -> MagicMock:
    est = MagicMock(spec=CostEstimator)
    est.remaining_budget.return_value = 5.0
    est.estimate_and_record.return_value = 0.002
    return est


@pytest.mark.asyncio
async def test_basic_chat_delegates_to_runtime(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(mock_runtime)
    result = await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
    )
    assert isinstance(result, ResilientChatResult)
    assert result.response.content == "hello"
    assert result.was_fallback is False
    assert result.fallback_attempts == 1
    mock_runtime.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_records_health_on_success(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
    mock_health: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(mock_runtime, health_tracker=mock_health)
    await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
    )
    mock_health.record_success.assert_called_once_with(
        "anthropic", "claude-haiku",
    )


@pytest.mark.asyncio
async def test_optimizer_classifies_complexity(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
    mock_optimizer: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(
        mock_runtime, cost_optimizer=mock_optimizer,
    )
    result = await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
    )
    mock_optimizer.classify_complexity.assert_called_once()
    assert "complexity=low" in result.optimization_reasoning


@pytest.mark.asyncio
async def test_estimator_records_spend(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
    mock_estimator: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(
        mock_runtime, cost_estimator=mock_estimator,
    )
    result = await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
        session_id="s1",
        workflow_id="w1",
        agent_id="a1",
    )
    mock_estimator.estimate_and_record.assert_called_once()
    assert result.estimated_cost_usd == 0.002


@pytest.mark.asyncio
async def test_budget_adjustment_with_optimizer_and_estimator(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
    mock_optimizer: MagicMock,
    mock_estimator: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(
        mock_runtime,
        cost_optimizer=mock_optimizer,
        cost_estimator=mock_estimator,
    )
    await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
        workflow_id="w1",
        workflow_budget_usd=10.0,
    )
    mock_estimator.remaining_budget.assert_called_once_with(
        "workflow", "w1", 10.0,
    )
    # The effective request passed to runtime should have remaining_budget_usd
    call_kwargs = mock_runtime.chat.call_args.kwargs
    effective_req = call_kwargs["request"]
    assert effective_req.remaining_budget_usd == 5.0


@pytest.mark.asyncio
async def test_no_optimizer_passes_request_through(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(mock_runtime)
    req = _make_request()
    await resilient.chat(
        registry=mock_registry,
        request=req,
        messages=[Message(role="user", content="hi")],
    )
    call_kwargs = mock_runtime.chat.call_args.kwargs
    assert call_kwargs["request"] is req


@pytest.mark.asyncio
async def test_no_estimator_uses_runtime_cost(
    mock_runtime: MagicMock,
    mock_registry: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(mock_runtime)
    result = await resilient.chat(
        registry=mock_registry,
        request=_make_request(),
        messages=[Message(role="user", content="hi")],
    )
    assert result.estimated_cost_usd == 0.001  # from RoutedChatResult


@pytest.mark.asyncio
async def test_properties_expose_internals(
    mock_runtime: MagicMock,
    mock_health: MagicMock,
) -> None:
    resilient = ResilientLLMRuntime(
        mock_runtime, health_tracker=mock_health,
    )
    assert resilient.runtime is mock_runtime
    assert resilient.health_tracker is mock_health
