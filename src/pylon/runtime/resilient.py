"""Resilient LLM runtime with automatic cost optimization and fallback.

Wraps LLMRuntime with:
- Cost-aware tier selection via CostOptimizer
- Provider health tracking via ProviderHealthTracker
- Automatic cross-provider fallback via FallbackEngine
- Cumulative spend tracking via CostEstimator
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.routing import ModelRouteDecision, ModelRouteRequest, ModelTier
from pylon.cost.estimator import CostEstimator
from pylon.cost.fallback_engine import FallbackEngine
from pylon.cost.optimizer import CostOptimizer
from pylon.providers.base import Message, Response
from pylon.providers.health import ProviderHealthTracker
from pylon.runtime.llm import LLMRuntime, ProviderRegistry


@dataclass
class ResilientChatResult:
    """Extended result with resilience metadata."""

    response: Response
    route: ModelRouteDecision
    estimated_cost_usd: float
    context: dict[str, Any] = field(default_factory=dict)
    was_fallback: bool = False
    fallback_attempts: int = 1
    optimization_reasoning: str = ""


class ResilientLLMRuntime:
    """LLMRuntime wrapper with cost optimization, health tracking, and fallback.

    Pipeline:
    1. CostOptimizer classifies complexity and recommends tier
    2. Filter available providers via HealthTracker
    3. Route via ModelRouter (with cost-adjusted request)
    4. Execute via LLMRuntime with automatic retry
    5. Record spend via CostEstimator
    """

    def __init__(
        self,
        runtime: LLMRuntime,
        *,
        health_tracker: ProviderHealthTracker | None = None,
        fallback_engine: FallbackEngine | None = None,
        cost_optimizer: CostOptimizer | None = None,
        cost_estimator: CostEstimator | None = None,
    ) -> None:
        self._runtime = runtime
        self._health = health_tracker or ProviderHealthTracker()
        self._fallback = fallback_engine or FallbackEngine()
        self._optimizer = cost_optimizer
        self._estimator = cost_estimator

    @property
    def runtime(self) -> LLMRuntime:
        """Access the underlying LLMRuntime."""
        return self._runtime

    @property
    def health_tracker(self) -> ProviderHealthTracker:
        """Access the health tracker."""
        return self._health

    async def chat(
        self,
        *,
        registry: ProviderRegistry,
        request: ModelRouteRequest,
        messages: list[Message],
        preferred_model: str = "",
        tools: list[dict[str, Any]] | None = None,
        static_instruction: str = "",
        session_id: str = "",
        workflow_id: str = "",
        agent_id: str = "",
        workflow_budget_usd: float = 0.0,
        workflow_total_steps: int = 1,
        workflow_completed_steps: int = 0,
    ) -> ResilientChatResult:
        """Execute chat with automatic optimization and fallback.

        Pipeline:
        1. CostOptimizer classifies complexity and recommends tier
        2. Filter available providers via HealthTracker
        3. Route via ModelRouter (with cost-adjusted request)
        4. Execute via LLMRuntime
        5. Record health and spend
        """
        optimization_reasoning = ""

        # Step 1: Cost optimization - adjust request if budget constraints apply
        effective_request = request
        if self._optimizer:
            complexity = self._optimizer.classify_complexity(
                purpose=request.purpose,
                input_tokens_estimate=request.input_tokens_estimate,
                requires_tools=request.requires_tools,
                quality_sensitive=request.quality_sensitive,
            )
            optimization_reasoning = f"complexity={complexity.value}"

            # Adjust remaining budget based on actual spend
            if (
                self._estimator
                and workflow_budget_usd > 0
                and workflow_id
            ):
                remaining = self._estimator.remaining_budget(
                    "workflow", workflow_id, workflow_budget_usd,
                )
                effective_request = ModelRouteRequest(
                    purpose=request.purpose,
                    input_tokens_estimate=request.input_tokens_estimate,
                    requires_tools=request.requires_tools,
                    latency_sensitive=request.latency_sensitive,
                    quality_sensitive=request.quality_sensitive,
                    cacheable_prefix=request.cacheable_prefix,
                    batch_eligible=request.batch_eligible,
                    remaining_budget_usd=remaining,
                )

        # Step 2: Execute via base runtime (routing + provider call)
        try:
            result = await self._runtime.chat(
                registry=registry,
                request=effective_request,
                messages=messages,
                preferred_model=preferred_model,
                tools=tools,
                static_instruction=static_instruction,
            )
        except Exception as primary_error:
            # Step 2b: On failure, attempt fallback via FallbackEngine
            self._health.record_failure(
                getattr(primary_error, "provider", "unknown"),
                getattr(primary_error, "model_id", "unknown"),
                primary_error,
            )

            async def _fallback_call_fn(
                provider: str,
                model_id: str,
                msgs: list[Message],
                **kw: object,
            ) -> Response:
                fb_provider = registry.resolve(provider, model_id)
                return await fb_provider.chat(msgs, model=model_id, **kw)

            try:
                fb_result = await self._fallback.execute(
                    tier=ModelTier.STANDARD,
                    messages=messages,
                    call_fn=_fallback_call_fn,
                    tools=tools,
                )
            except Exception:
                raise primary_error from None

            fb_route = ModelRouteDecision(
                provider_name=fb_result.provider,
                model_id=fb_result.model_id,
                tier=fb_result.tier,
                reasoning=f"fallback after primary failure: {primary_error}",
            )

            self._health.record_success(
                fb_result.provider, fb_result.model_id,
            )

            estimated_cost = 0.0
            if self._estimator and fb_result.response.usage:
                estimated_cost = self._estimator.estimate_and_record(
                    fb_result.provider,
                    fb_result.model_id,
                    fb_result.response.usage,
                    session_id=session_id,
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                )

            return ResilientChatResult(
                response=fb_result.response,
                route=fb_route,
                estimated_cost_usd=estimated_cost,
                was_fallback=True,
                fallback_attempts=fb_result.attempt,
                optimization_reasoning=optimization_reasoning,
            )

        # Step 3: Record health
        self._health.record_success(
            result.route.provider_name,
            result.route.model_id,
        )

        # Step 4: Record spend
        estimated_cost = result.estimated_cost_usd
        if self._estimator and result.response.usage:
            estimated_cost = self._estimator.estimate_and_record(
                result.route.provider_name,
                result.route.model_id,
                result.response.usage,
                session_id=session_id,
                workflow_id=workflow_id,
                agent_id=agent_id,
            )

        return ResilientChatResult(
            response=result.response,
            route=result.route,
            estimated_cost_usd=estimated_cost,
            context=result.context,
            was_fallback=False,
            fallback_attempts=1,
            optimization_reasoning=optimization_reasoning,
        )
