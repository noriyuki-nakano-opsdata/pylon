"""Adaptive cost optimizer for multi-model routing.

Analyzes task complexity, recommends cheapest provider meeting quality
thresholds, enforces cost ceilings, and paces budgets across workflow steps.

Integration point: called by ModelRouter before route selection to inject
cost-aware constraints into the routing decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pylon.autonomy.routing import CacheStrategy, ModelTier
from pylon.cost.estimator import CostEstimator, ModelPricingTable, ProviderPricing


class TaskComplexity(StrEnum):
    """Estimated task complexity driving model selection."""

    TRIVIAL = "trivial"        # Classification, extraction, formatting
    LOW = "low"                # Simple Q&A, summarization
    MEDIUM = "medium"          # Multi-step reasoning, code generation
    HIGH = "high"              # Complex analysis, planning, novel synthesis
    CRITICAL = "critical"      # Safety-critical, requires premium models


# Mapping from complexity to minimum acceptable tier.
_COMPLEXITY_TO_MIN_TIER: dict[TaskComplexity, ModelTier] = {
    TaskComplexity.TRIVIAL: ModelTier.LIGHTWEIGHT,
    TaskComplexity.LOW: ModelTier.LIGHTWEIGHT,
    TaskComplexity.MEDIUM: ModelTier.STANDARD,
    TaskComplexity.HIGH: ModelTier.STANDARD,
    TaskComplexity.CRITICAL: ModelTier.PREMIUM,
}

_TIER_RANK: dict[ModelTier, int] = {
    ModelTier.LIGHTWEIGHT: 0,
    ModelTier.STANDARD: 1,
    ModelTier.PREMIUM: 2,
}

# Heuristic tier assignment for known models (used when profiles lack tier info).
# Model IDs MUST match DEFAULT_MODEL_PROFILES in pylon.autonomy.routing.
_MODEL_TIER_HINTS: dict[str, ModelTier] = {
    "deepseek-chat": ModelTier.LIGHTWEIGHT,
    "llama-3.3-70b-versatile": ModelTier.LIGHTWEIGHT,
    "gemini-2.0-flash": ModelTier.LIGHTWEIGHT,
    "mistral-small-3.2": ModelTier.LIGHTWEIGHT,
    "gpt-4o-mini": ModelTier.LIGHTWEIGHT,
    "gpt-4o": ModelTier.STANDARD,
    "claude-haiku": ModelTier.LIGHTWEIGHT,
    "claude-sonnet": ModelTier.STANDARD,
    "claude-opus": ModelTier.PREMIUM,
    "gemini-2.5-pro": ModelTier.STANDARD,
    "o3": ModelTier.PREMIUM,
    "deepseek-reasoner": ModelTier.STANDARD,
    "mistral-large-3": ModelTier.STANDARD,
}


@dataclass(frozen=True)
class CostCeiling:
    """Maximum cost allowed for a single request or a full workflow.

    When per_request_usd is exceeded, the optimizer forces a tier downgrade
    or rejects the request. When workflow_usd is exceeded, subsequent
    requests are blocked.
    """

    per_request_usd: float = 0.50
    workflow_usd: float = 10.0


@dataclass(frozen=True)
class QualityFloor:
    """Minimum quality constraints that prevent excessive cost cutting.

    min_tier: the optimizer will never select a model below this tier.
    require_tool_support: if True, only models with tool calling are eligible.
    """

    min_tier: ModelTier = ModelTier.LIGHTWEIGHT
    require_tool_support: bool = False


@dataclass(frozen=True)
class CacheSavingsEstimate:
    """Projected savings from applying a cache strategy."""

    strategy: CacheStrategy
    estimated_saving_usd: float
    cache_eligible_tokens: int
    saving_percentage: float


@dataclass(frozen=True)
class OptimizationRecommendation:
    """Output of the optimizer: which provider/model to use and why."""

    provider: str
    model_id: str
    tier: ModelTier
    estimated_cost_usd: float
    reasoning: str
    cache_strategy: CacheStrategy = CacheStrategy.NONE
    cache_savings: CacheSavingsEstimate | None = None
    budget_pacing: BudgetPacing | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "model_id": self.model_id,
            "tier": self.tier.value,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "reasoning": self.reasoning,
            "cache_strategy": self.cache_strategy.value,
        }
        if self.cache_savings:
            result["cache_savings"] = {
                "strategy": self.cache_savings.strategy.value,
                "estimated_saving_usd": round(
                    self.cache_savings.estimated_saving_usd, 6,
                ),
                "saving_percentage": round(
                    self.cache_savings.saving_percentage, 2,
                ),
            }
        if self.budget_pacing:
            result["budget_pacing"] = self.budget_pacing.to_dict()
        return result


@dataclass(frozen=True)
class BudgetPacing:
    """Budget pacing: spread budget evenly across expected workflow steps."""

    total_budget_usd: float
    spent_usd: float
    remaining_usd: float
    total_steps: int
    completed_steps: int
    per_step_budget_usd: float
    on_pace: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_budget_usd": round(self.total_budget_usd, 6),
            "spent_usd": round(self.spent_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "per_step_budget_usd": round(self.per_step_budget_usd, 6),
            "on_pace": self.on_pace,
        }


class CostOptimizer:
    """Recommends the cheapest model that meets quality and budget constraints.

    Usage:
        optimizer = CostOptimizer(estimator=cost_estimator)
        rec = optimizer.recommend(
            complexity=TaskComplexity.LOW,
            input_tokens_estimate=2000,
            output_tokens_estimate=500,
            available_providers={"anthropic", "openai", "deepseek"},
        )
        # rec.provider, rec.model_id, rec.estimated_cost_usd

    Integration with ModelRouter:
        The router should call optimizer.recommend() to get the cheapest
        viable option, then use the returned provider/model_id in its
        ModelRouteDecision. The router's existing _select_tier() can be
        replaced by optimizer.classify_complexity() for richer analysis.
    """

    def __init__(
        self,
        estimator: CostEstimator | None = None,
        ceiling: CostCeiling | None = None,
        floor: QualityFloor | None = None,
        pricing_table: ModelPricingTable | None = None,
    ) -> None:
        self._estimator = estimator or CostEstimator()
        self._ceiling = ceiling or CostCeiling()
        self._floor = floor or QualityFloor()
        self._pricing = pricing_table or self._estimator.pricing_table

    @property
    def ceiling(self) -> CostCeiling:
        return self._ceiling

    @property
    def floor(self) -> QualityFloor:
        return self._floor

    def classify_complexity(
        self,
        *,
        purpose: str = "",
        input_tokens_estimate: int = 0,
        requires_tools: bool = False,
        quality_sensitive: bool = False,
    ) -> TaskComplexity:
        """Heuristic complexity classification based on request characteristics.

        This replaces hard-coded tier logic in ModelRouter._select_tier() with
        a richer signal that the optimizer uses to enforce quality floors.
        """
        if quality_sensitive:
            return TaskComplexity.CRITICAL

        purpose_lower = purpose.lower()
        trivial_keywords = {"classify", "extract", "format", "parse", "label"}
        if any(kw in purpose_lower for kw in trivial_keywords):
            return TaskComplexity.TRIVIAL

        high_keywords = {"plan", "architect", "debug", "analyze", "design"}
        if any(kw in purpose_lower for kw in high_keywords):
            return TaskComplexity.HIGH

        if requires_tools and input_tokens_estimate > 4000:
            return TaskComplexity.MEDIUM

        if input_tokens_estimate > 8000:
            return TaskComplexity.MEDIUM

        if requires_tools:
            return TaskComplexity.LOW

        return TaskComplexity.LOW

    def recommend(
        self,
        *,
        complexity: TaskComplexity | None = None,
        purpose: str = "",
        input_tokens_estimate: int = 1000,
        output_tokens_estimate: int = 500,
        available_providers: set[str] | None = None,
        requires_tools: bool = False,
        quality_sensitive: bool = False,
        cacheable_prefix_tokens: int = 0,
        is_batch: bool = False,
        workflow_id: str = "",
        workflow_budget_usd: float = 0.0,
        workflow_total_steps: int = 1,
        workflow_completed_steps: int = 0,
    ) -> OptimizationRecommendation:
        """Find the cheapest model meeting quality and budget constraints.

        Args:
            complexity: Pre-classified complexity. If None, auto-classified.
            purpose: Task purpose string for auto-classification.
            input_tokens_estimate: Expected input token count.
            output_tokens_estimate: Expected output token count.
            available_providers: Restrict to these providers (None = all known).
            requires_tools: Whether tool calling is required.
            quality_sensitive: Force premium tier.
            cacheable_prefix_tokens: Number of tokens in cacheable prefix.
            is_batch: Whether batch API can be used.
            workflow_id: For budget pacing tracking.
            workflow_budget_usd: Total workflow budget (0 = unlimited).
            workflow_total_steps: Expected total steps in workflow.
            workflow_completed_steps: Steps already completed.

        Returns:
            OptimizationRecommendation with selected model and cost estimate.

        Raises:
            ValueError: If no model satisfies all constraints.
        """
        if complexity is None:
            complexity = self.classify_complexity(
                purpose=purpose,
                input_tokens_estimate=input_tokens_estimate,
                requires_tools=requires_tools,
                quality_sensitive=quality_sensitive,
            )

        min_tier = max(
            _COMPLEXITY_TO_MIN_TIER[complexity],
            self._floor.min_tier,
            key=lambda t: _TIER_RANK[t],
        )

        candidates = self._pricing.cheapest_for_tier(
            providers=available_providers,
        )

        # Filter by tier and tool support.
        eligible: list[ProviderPricing] = []
        for candidate in candidates:
            tier = _MODEL_TIER_HINTS.get(candidate.model_id, ModelTier.STANDARD)
            if _TIER_RANK[tier] < _TIER_RANK[min_tier]:
                continue
            if self._floor.require_tool_support or requires_tools:
                # Cannot verify tool support from pricing alone; assume
                # standard+ tiers support tools.
                if _TIER_RANK[tier] < _TIER_RANK[ModelTier.STANDARD]:
                    continue
            eligible.append(candidate)

        if not eligible:
            raise ValueError(
                f"No model satisfies constraints: min_tier={min_tier.value}, "
                f"providers={available_providers}"
            )

        # Score by estimated cost (cheapest first).
        from pylon.providers.base import TokenUsage

        scored: list[tuple[float, ProviderPricing, CacheSavingsEstimate | None]] = []
        for pricing in eligible:
            cache_savings = self._estimate_cache_savings(
                pricing, input_tokens_estimate, cacheable_prefix_tokens,
            )
            cache_read = min(cacheable_prefix_tokens, input_tokens_estimate)
            effective_input = input_tokens_estimate - cache_read

            usage = TokenUsage(
                input_tokens=effective_input,
                output_tokens=output_tokens_estimate,
                cache_read_tokens=cache_read if cache_savings else 0,
                cache_write_tokens=0,
            )
            cost = self._estimator.estimate(
                pricing.provider, pricing.model_id, usage,
                is_batch=is_batch,
            )

            # Enforce per-request ceiling.
            if cost > self._ceiling.per_request_usd:
                continue

            scored.append((cost, pricing, cache_savings))

        if not scored:
            raise ValueError(
                f"All eligible models exceed per-request ceiling "
                f"${self._ceiling.per_request_usd}"
            )

        scored.sort(key=lambda t: t[0])
        best_cost, best_pricing, best_cache = scored[0]

        # Budget pacing.
        pacing: BudgetPacing | None = None
        if workflow_budget_usd > 0 and workflow_id:
            spent = self._estimator.get_spend("workflow", workflow_id).total_usd
            remaining = max(0.0, workflow_budget_usd - spent)
            remaining_steps = max(1, workflow_total_steps - workflow_completed_steps)
            per_step = remaining / remaining_steps
            pacing = BudgetPacing(
                total_budget_usd=workflow_budget_usd,
                spent_usd=spent,
                remaining_usd=remaining,
                total_steps=workflow_total_steps,
                completed_steps=workflow_completed_steps,
                per_step_budget_usd=per_step,
                on_pace=best_cost <= per_step,
            )

            # If over budget, try cheaper option.
            if best_cost > per_step and len(scored) > 1:
                for alt_cost, alt_pricing, alt_cache in scored:
                    if alt_cost <= per_step:
                        best_cost, best_pricing, best_cache = (
                            alt_cost, alt_pricing, alt_cache,
                        )
                        pacing = BudgetPacing(
                            total_budget_usd=workflow_budget_usd,
                            spent_usd=spent,
                            remaining_usd=remaining,
                            total_steps=workflow_total_steps,
                            completed_steps=workflow_completed_steps,
                            per_step_budget_usd=per_step,
                            on_pace=True,
                        )
                        break

        tier = _MODEL_TIER_HINTS.get(best_pricing.model_id, ModelTier.STANDARD)

        cache_strategy = CacheStrategy.NONE
        if best_cache and best_cache.estimated_saving_usd > 0:
            cache_strategy = best_cache.strategy

        reasons: list[str] = [
            f"complexity={complexity.value}",
            f"cheapest at ${best_cost:.4f}",
        ]
        if cache_strategy != CacheStrategy.NONE:
            reasons.append(
                f"cache saves ${best_cache.estimated_saving_usd:.4f}"  # type: ignore[union-attr]
            )
        if pacing and not pacing.on_pace:
            reasons.append("OVER BUDGET PACE")

        return OptimizationRecommendation(
            provider=best_pricing.provider,
            model_id=best_pricing.model_id,
            tier=tier,
            estimated_cost_usd=best_cost,
            reasoning="; ".join(reasons),
            cache_strategy=cache_strategy,
            cache_savings=best_cache,
            budget_pacing=pacing,
        )

    def _estimate_cache_savings(
        self,
        pricing: ProviderPricing,
        input_tokens: int,
        cacheable_prefix_tokens: int,
    ) -> CacheSavingsEstimate | None:
        """Project how much caching would save for a given pricing entry."""
        if cacheable_prefix_tokens <= 0:
            return None
        if pricing.cached_input_per_million <= 0:
            return None
        if pricing.min_cacheable_tokens > cacheable_prefix_tokens:
            return None

        cached_tokens = min(cacheable_prefix_tokens, input_tokens)
        full_cost = (cached_tokens * pricing.input_per_million) / 1_000_000
        cached_cost = (cached_tokens * pricing.cached_input_per_million) / 1_000_000
        saving = full_cost - cached_cost

        if saving <= 0:
            return None

        strategy = CacheStrategy.NONE
        if pricing.provider == "anthropic":
            strategy = CacheStrategy.EXPLICIT
        elif pricing.provider in {"openai", "google"}:
            strategy = CacheStrategy.PREFIX
        elif pricing.provider == "deepseek":
            strategy = CacheStrategy.PREFIX  # Auto-caching

        saving_pct = (saving / full_cost * 100) if full_cost > 0 else 0.0

        return CacheSavingsEstimate(
            strategy=strategy,
            estimated_saving_usd=saving,
            cache_eligible_tokens=cached_tokens,
            saving_percentage=saving_pct,
        )
