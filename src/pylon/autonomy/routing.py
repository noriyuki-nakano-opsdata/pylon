"""Model routing helpers for cost-aware bounded autonomy."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ModelTier(enum.StrEnum):
    """Coarse capability and cost class used for routing."""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    PREMIUM = "premium"


class CacheStrategy(enum.StrEnum):
    """Cache strategy selected by the router."""

    NONE = "none"
    PREFIX = "prefix"
    EXPLICIT = "explicit"
    BATCH = "batch"


@dataclass(frozen=True)
class ModelProfile:
    """Static model metadata used by the router."""

    provider_name: str
    model_id: str
    tier: ModelTier
    supports_tools: bool = True
    prompt_caching: bool = False
    batch_api: bool = False


@dataclass(frozen=True)
class ModelRouteRequest:
    """Routing request produced by higher-level autonomy logic."""

    purpose: str
    input_tokens_estimate: int
    requires_tools: bool = False
    latency_sensitive: bool = False
    quality_sensitive: bool = False
    cacheable_prefix: bool = False
    batch_eligible: bool = False
    remaining_budget_usd: float | None = None


@dataclass(frozen=True)
class ModelRouteDecision:
    """Selected provider/model pair plus routing rationale."""

    provider_name: str
    model_id: str
    tier: ModelTier
    reasoning: str
    cache_strategy: CacheStrategy = CacheStrategy.NONE
    batch_eligible: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "model_id": self.model_id,
            "tier": self.tier.value,
            "reasoning": self.reasoning,
            "cache_strategy": self.cache_strategy.value,
            "batch_eligible": self.batch_eligible,
        }


DEFAULT_MODEL_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        provider_name="anthropic",
        model_id="claude-haiku",
        tier=ModelTier.LIGHTWEIGHT,
        supports_tools=True,
        prompt_caching=True,
        batch_api=True,
    ),
    ModelProfile(
        provider_name="anthropic",
        model_id="claude-sonnet",
        tier=ModelTier.STANDARD,
        supports_tools=True,
        prompt_caching=True,
        batch_api=True,
    ),
    ModelProfile(
        provider_name="anthropic",
        model_id="claude-opus",
        tier=ModelTier.PREMIUM,
        supports_tools=True,
        prompt_caching=True,
        batch_api=True,
    ),
)


class ModelRouter:
    """Simple heuristic router for provider/model selection."""

    def __init__(self, profiles: tuple[ModelProfile, ...] = DEFAULT_MODEL_PROFILES) -> None:
        if not profiles:
            raise ValueError("ModelRouter requires at least one model profile")
        self._profiles = profiles

    def route(self, request: ModelRouteRequest) -> ModelRouteDecision:
        target_tier = self._select_tier(request)
        profile = self._select_profile(target_tier, request.requires_tools)
        if profile is None:
            raise ValueError("No model profile available for request")

        cache_strategy = self._select_cache_strategy(profile, request)
        reasoning = self._build_reasoning(request, profile.tier, cache_strategy)
        return ModelRouteDecision(
            provider_name=profile.provider_name,
            model_id=profile.model_id,
            tier=profile.tier,
            reasoning=reasoning,
            cache_strategy=cache_strategy,
            batch_eligible=(cache_strategy == CacheStrategy.BATCH),
        )

    def route_for_available_providers(
        self,
        request: ModelRouteRequest,
        available_providers: set[str],
    ) -> ModelRouteDecision:
        target_tier = self._select_tier(request)
        profile = self._select_profile(
            target_tier,
            request.requires_tools,
            allowed_providers=available_providers,
        )
        if profile is None:
            profile = self._select_nearest_available_profile(
                target_tier,
                request.requires_tools,
                available_providers,
            )
        if profile is None:
            raise ValueError("No model profile available for available providers")

        cache_strategy = self._select_cache_strategy(profile, request)
        reasoning = self._build_reasoning(request, profile.tier, cache_strategy)
        return ModelRouteDecision(
            provider_name=profile.provider_name,
            model_id=profile.model_id,
            tier=profile.tier,
            reasoning=reasoning,
            cache_strategy=cache_strategy,
            batch_eligible=(cache_strategy == CacheStrategy.BATCH),
        )

    def _select_tier(self, request: ModelRouteRequest) -> ModelTier:
        if request.quality_sensitive:
            tier = ModelTier.PREMIUM
        elif request.requires_tools or request.input_tokens_estimate >= 8000:
            tier = ModelTier.STANDARD
        elif request.latency_sensitive:
            tier = (
                ModelTier.LIGHTWEIGHT
                if request.input_tokens_estimate <= 2000
                else ModelTier.STANDARD
            )
        else:
            tier = ModelTier.LIGHTWEIGHT

        budget = request.remaining_budget_usd
        if budget is not None and budget < 0.10 and tier == ModelTier.PREMIUM:
            tier = ModelTier.STANDARD
        if budget is not None and budget < 0.03 and tier in {
            ModelTier.PREMIUM,
            ModelTier.STANDARD,
        }:
            tier = ModelTier.LIGHTWEIGHT
        return tier

    def _select_profile(
        self,
        tier: ModelTier,
        requires_tools: bool,
        *,
        allowed_providers: set[str] | None = None,
    ) -> ModelProfile | None:
        def eligible(profile: ModelProfile) -> bool:
            return (
                ((not requires_tools) or profile.supports_tools)
                and (
                    allowed_providers is None
                    or profile.provider_name in allowed_providers
                )
            )

        fallback_order: tuple[ModelTier, ...]
        if tier == ModelTier.PREMIUM:
            fallback_order = (
                ModelTier.PREMIUM,
                ModelTier.STANDARD,
                ModelTier.LIGHTWEIGHT,
            )
        elif tier == ModelTier.STANDARD:
            fallback_order = (ModelTier.STANDARD, ModelTier.LIGHTWEIGHT)
        else:
            fallback_order = (ModelTier.LIGHTWEIGHT,)

        for candidate_tier in fallback_order:
            for profile in self._profiles:
                if profile.tier == candidate_tier and eligible(profile):
                    return profile
        return None

    def _select_nearest_available_profile(
        self,
        target_tier: ModelTier,
        requires_tools: bool,
        allowed_providers: set[str],
    ) -> ModelProfile | None:
        tier_rank = {
            ModelTier.LIGHTWEIGHT: 0,
            ModelTier.STANDARD: 1,
            ModelTier.PREMIUM: 2,
        }

        def eligible(profile: ModelProfile) -> bool:
            return (
                profile.provider_name in allowed_providers
                and ((not requires_tools) or profile.supports_tools)
            )

        candidates = [profile for profile in self._profiles if eligible(profile)]
        if not candidates:
            return None
        target_rank = tier_rank[target_tier]
        return min(
            candidates,
            key=lambda profile: (
                abs(tier_rank[profile.tier] - target_rank),
                tier_rank[profile.tier],
            ),
        )

    def _select_cache_strategy(
        self,
        profile: ModelProfile,
        request: ModelRouteRequest,
    ) -> CacheStrategy:
        if request.batch_eligible and profile.batch_api and not request.latency_sensitive:
            return CacheStrategy.BATCH
        if not request.cacheable_prefix or not profile.prompt_caching:
            return CacheStrategy.NONE
        if profile.provider_name in {"openai", "google"}:
            return CacheStrategy.PREFIX
        return CacheStrategy.EXPLICIT

    def _build_reasoning(
        self,
        request: ModelRouteRequest,
        tier: ModelTier,
        cache_strategy: CacheStrategy,
    ) -> str:
        reasons: list[str] = [f"selected {tier.value} tier for purpose '{request.purpose}'"]
        if request.quality_sensitive:
            reasons.append("quality sensitivity requested")
        if request.requires_tools:
            reasons.append("tool support required")
        if request.remaining_budget_usd is not None:
            reasons.append(f"remaining budget ${request.remaining_budget_usd:.2f}")
        if cache_strategy != CacheStrategy.NONE:
            reasons.append(f"cache strategy {cache_strategy.value}")
        return "; ".join(reasons)
