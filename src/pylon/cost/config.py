"""Configuration loader for cost compression subsystem.

Parses the `cost` section of pylon.yaml into typed dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.routing import ModelTier
from pylon.cost.estimator import Currency, ProviderPricing
from pylon.cost.fallback_engine import FallbackChainConfig, FallbackTarget
from pylon.cost.optimizer import CostCeiling, QualityFloor
from pylon.cost.rate_limiter import ProviderQuota


@dataclass(frozen=True)
class CostConfig:
    """Top-level cost configuration parsed from pylon.yaml.

    Example YAML structure:

    cost:
      currency: USD
      ceiling:
        per_request_usd: 0.50
        workflow_usd: 10.0
      quality_floor:
        min_tier: lightweight
        require_tool_support: false
      budget_pacing:
        enabled: true
      providers:
        anthropic:
          rpm: 60
          tpm: 100000
          concurrent: 10
          models:
            claude-haiku:
              input_per_million: 1.00
              output_per_million: 5.00
              cached_input_per_million: 0.10
              cache_write_per_million: 1.25
              batch_discount: 0.50
        openai:
          rpm: 500
          tpm: 200000
          concurrent: 20
          models:
            gpt-4o-mini:
              input_per_million: 0.15
              output_per_million: 0.60
              cached_input_per_million: 0.025
              min_cacheable_tokens: 1024
      fallback:
        max_attempts: 3
        chains:
          standard:
            primary: anthropic/claude-sonnet
            same_tier:
              - openai/gpt-4o
            downgrade:
              - deepseek/deepseek-chat
      circuit_breaker:
        failure_threshold: 5
        success_threshold: 2
        timeout_seconds: 30.0
    """

    currency: Currency = Currency.USD
    ceiling: CostCeiling = field(default_factory=CostCeiling)
    quality_floor: QualityFloor = field(default_factory=QualityFloor)
    budget_pacing_enabled: bool = True
    provider_quotas: tuple[ProviderQuota, ...] = ()
    provider_pricing: tuple[ProviderPricing, ...] = ()
    fallback_chains: dict[ModelTier, FallbackChainConfig] = field(
        default_factory=dict,
    )
    circuit_failure_threshold: int = 5
    circuit_success_threshold: int = 2
    circuit_timeout_seconds: float = 30.0


def parse_cost_config(raw: dict[str, Any]) -> CostConfig:
    """Parse a cost configuration dict (from YAML) into CostConfig.

    Args:
        raw: The "cost" section of pylon.yaml.

    Returns:
        Validated CostConfig instance.
    """
    currency = Currency(raw.get("currency", "USD").upper())

    ceiling_raw = raw.get("ceiling", {})
    ceiling = CostCeiling(
        per_request_usd=float(ceiling_raw.get("per_request_usd", 0.50)),
        workflow_usd=float(ceiling_raw.get("workflow_usd", 10.0)),
    )

    floor_raw = raw.get("quality_floor", {})
    min_tier_str = floor_raw.get("min_tier", "lightweight")
    min_tier = ModelTier(min_tier_str)
    quality_floor = QualityFloor(
        min_tier=min_tier,
        require_tool_support=bool(floor_raw.get("require_tool_support", False)),
    )

    pacing_raw = raw.get("budget_pacing", {})
    budget_pacing = bool(pacing_raw.get("enabled", True))

    providers_raw = raw.get("providers", {})
    quotas: list[ProviderQuota] = []
    pricings: list[ProviderPricing] = []

    for provider_name, provider_cfg in providers_raw.items():
        quotas.append(ProviderQuota(
            provider=provider_name,
            rpm=int(provider_cfg.get("rpm", 60)),
            tpm=int(provider_cfg.get("tpm", 100_000)),
            concurrent=int(provider_cfg.get("concurrent", 10)),
        ))
        for model_id, model_cfg in provider_cfg.get("models", {}).items():
            pricings.append(ProviderPricing(
                provider=provider_name,
                model_id=model_id,
                input_per_million=float(model_cfg.get("input_per_million", 0)),
                output_per_million=float(model_cfg.get("output_per_million", 0)),
                cached_input_per_million=float(
                    model_cfg.get("cached_input_per_million", 0),
                ),
                cache_write_per_million=float(
                    model_cfg.get("cache_write_per_million", 0),
                ),
                reasoning_per_million=(
                    float(model_cfg["reasoning_per_million"])
                    if "reasoning_per_million" in model_cfg
                    else None
                ),
                batch_discount=float(model_cfg.get("batch_discount", 0)),
                min_cacheable_tokens=int(
                    model_cfg.get("min_cacheable_tokens", 0),
                ),
            ))

    fallback_raw = raw.get("fallback", {})
    max_attempts = int(fallback_raw.get("max_attempts", 3))
    chains: dict[ModelTier, FallbackChainConfig] = {}
    for tier_str, chain_cfg in fallback_raw.get("chains", {}).items():
        tier = ModelTier(tier_str)
        primary_ref = chain_cfg.get("primary", "")
        primary_provider, primary_model = _parse_ref(primary_ref)
        same_tier_targets = tuple(
            _parse_fallback_target(ref, tier)
            for ref in chain_cfg.get("same_tier", [])
        )
        downgrade_targets = tuple(
            _parse_fallback_target(
                ref,
                _lower_tier(tier),
            )
            for ref in chain_cfg.get("downgrade", [])
        )
        chains[tier] = FallbackChainConfig(
            primary_provider=primary_provider,
            primary_model=primary_model,
            primary_tier=tier,
            same_tier=same_tier_targets,
            downgrade=downgrade_targets,
            max_attempts=max_attempts,
        )

    cb_raw = raw.get("circuit_breaker", {})

    return CostConfig(
        currency=currency,
        ceiling=ceiling,
        quality_floor=quality_floor,
        budget_pacing_enabled=budget_pacing,
        provider_quotas=tuple(quotas),
        provider_pricing=tuple(pricings),
        fallback_chains=chains,
        circuit_failure_threshold=int(cb_raw.get("failure_threshold", 5)),
        circuit_success_threshold=int(cb_raw.get("success_threshold", 2)),
        circuit_timeout_seconds=float(cb_raw.get("timeout_seconds", 30.0)),
    )


def _parse_ref(ref: str) -> tuple[str, str]:
    """Parse a 'provider/model' reference string."""
    if "/" not in ref:
        return ref, ""
    provider, model = ref.split("/", 1)
    return provider, model


def _parse_fallback_target(ref: str, tier: ModelTier) -> FallbackTarget:
    """Parse a fallback target reference string."""
    provider, model = _parse_ref(ref)
    return FallbackTarget(provider=provider, model_id=model, tier=tier)


def _lower_tier(tier: ModelTier) -> ModelTier:
    """Return one tier lower, clamped at LIGHTWEIGHT."""
    if tier == ModelTier.PREMIUM:
        return ModelTier.STANDARD
    return ModelTier.LIGHTWEIGHT
