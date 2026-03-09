"""Tests for fallback engine."""

from __future__ import annotations

import pytest

from pylon.autonomy.routing import ModelTier
from pylon.cost.fallback_engine import (
    FallbackChainConfig,
    FallbackEngine,
    FallbackTarget,
    ProviderCallError,
)
from pylon.cost.rate_limiter import ProviderQuota, RateLimitManager
from pylon.providers.base import Response, TokenUsage


def _make_response(provider: str, model: str) -> Response:
    return Response(
        content=f"response from {provider}/{model}",
        model=model,
        usage=TokenUsage(input_tokens=100, output_tokens=50),
    )


@pytest.fixture
def rlm() -> RateLimitManager:
    mgr = RateLimitManager()
    mgr.register_provider(ProviderQuota(provider="primary", rpm=100, tpm=100_000))
    mgr.register_provider(ProviderQuota(provider="secondary", rpm=100, tpm=100_000))
    mgr.register_provider(ProviderQuota(provider="tertiary", rpm=100, tpm=100_000))
    return mgr


@pytest.fixture
def chain_config() -> FallbackChainConfig:
    return FallbackChainConfig(
        primary_provider="primary",
        primary_model="model-a",
        primary_tier=ModelTier.STANDARD,
        same_tier=(
            FallbackTarget("secondary", "model-b", ModelTier.STANDARD),
        ),
        downgrade=(
            FallbackTarget("tertiary", "model-c", ModelTier.LIGHTWEIGHT),
        ),
        max_attempts=3,
    )


class TestFallbackEngine:
    @pytest.mark.asyncio
    async def test_primary_succeeds(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
        )

        async def call_fn(provider, model, messages, **kw):
            return _make_response(provider, model)

        result = await engine.execute(
            tier=ModelTier.STANDARD,
            messages=[],
            call_fn=call_fn,
        )
        assert result.provider == "primary"
        assert result.attempt == 1
        assert result.was_fallback is False

    @pytest.mark.asyncio
    async def test_fallback_on_server_error(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
        )
        call_count = 0

        async def call_fn(provider, model, messages, **kw):
            nonlocal call_count
            call_count += 1
            if provider == "primary":
                raise ProviderCallError(
                    "server error", status_code=500,
                    provider=provider, model_id=model,
                )
            return _make_response(provider, model)

        result = await engine.execute(
            tier=ModelTier.STANDARD,
            messages=[],
            call_fn=call_fn,
        )
        assert result.provider == "secondary"
        assert result.attempt == 2
        assert result.was_fallback is True
        assert len(result.events) == 1

    @pytest.mark.asyncio
    async def test_no_fallback_on_client_error(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
        )

        async def call_fn(provider, model, messages, **kw):
            raise ProviderCallError(
                "bad request", status_code=400,
                provider=provider, model_id=model,
            )

        with pytest.raises(ProviderCallError) as exc_info:
            await engine.execute(
                tier=ModelTier.STANDARD,
                messages=[],
                call_fn=call_fn,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_all_fallbacks_exhausted(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
        )

        async def call_fn(provider, model, messages, **kw):
            raise ProviderCallError(
                "server error", status_code=502,
                provider=provider, model_id=model,
            )

        with pytest.raises(ProviderCallError):
            await engine.execute(
                tier=ModelTier.STANDARD,
                messages=[],
                call_fn=call_fn,
            )

    @pytest.mark.asyncio
    async def test_fallback_on_429(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
        )

        async def call_fn(provider, model, messages, **kw):
            if provider == "primary":
                raise ProviderCallError(
                    "rate limited", status_code=429,
                    provider=provider, model_id=model,
                )
            return _make_response(provider, model)

        result = await engine.execute(
            tier=ModelTier.STANDARD,
            messages=[],
            call_fn=call_fn,
        )
        assert result.provider == "secondary"

    @pytest.mark.asyncio
    async def test_fallback_events_logged(
        self, rlm: RateLimitManager, chain_config: FallbackChainConfig,
    ) -> None:
        events_received: list = []
        engine = FallbackEngine(
            rate_limiter=rlm,
            chains={ModelTier.STANDARD: chain_config},
            on_fallback=lambda e: events_received.append(e),
        )

        async def call_fn(provider, model, messages, **kw):
            if provider == "primary":
                raise ProviderCallError(
                    "error", status_code=503,
                    provider=provider, model_id=model,
                )
            return _make_response(provider, model)

        await engine.execute(
            tier=ModelTier.STANDARD,
            messages=[],
            call_fn=call_fn,
        )
        assert len(events_received) == 1
        assert events_received[0].from_provider == "primary"
        assert events_received[0].to_provider == "secondary"
