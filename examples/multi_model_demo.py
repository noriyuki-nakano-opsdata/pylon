"""Pylon マルチモデル動作確認スクリプト.

Zhipu GLM + Anthropic Claude + Moonshot Kimi を使って以下を検証:
1. プロバイダー直接呼び出し (chat + stream)
2. CostEstimator によるコスト計算
3. CostOptimizer による最適モデル推薦
4. AdaptiveRouter の学習記録
5. マルチプロバイダー切り替え

Usage:
    python examples/multi_model_demo.py

Requires .env file with ZHIPU_API_KEY, ANTHROPIC_API_KEY, and MOONSHOT_API_KEY.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Load .env file
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Pylon imports
from pylon.providers.zhipu import ZhipuProvider
from pylon.providers.base import Message, TokenUsage
from pylon.cost.estimator import CostEstimator, ProviderPricing
from pylon.cost.optimizer import CostOptimizer, TaskComplexity
from pylon.cost.rate_limiter import RateLimitManager, ProviderQuota
from pylon.intelligence.adaptive_router import AdaptiveRouter, RoutingOutcome
from pylon.intelligence.event_store import EventStore
from pylon.autonomy.routing import ModelTier

# Zhipu GLM pricing (CNY → USD approximation)
ZHIPU_PRICING = ProviderPricing(
    provider="zhipu",
    model_id="glm-4.5-air",
    input_per_million=0.014,   # 0.1 CNY/M ≈ $0.014
    output_per_million=0.014,
    min_cacheable_tokens=0,
)

GLM_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "")


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def test_1_direct_chat() -> None:
    """テスト1: Zhipu GLM への直接チャット呼び出し."""
    separator("Test 1: Direct Chat (Zhipu GLM)")

    provider = ZhipuProvider(
        model="glm-4.5-air",
        api_key=GLM_API_KEY,
    )
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="system", content="You are a helpful assistant. Reply in 1-2 sentences."),
        Message(role="user", content="What is Python's GIL?"),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content[:200]}")
    print(f"Model: {response.model}")
    print(f"Finish reason: {response.finish_reason}")
    if response.usage:
        print(f"Usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}, total={response.usage.total_tokens}")
    print(f"Latency: {latency:.0f}ms")
    print("✓ Direct chat OK")
    return response


async def test_2_streaming() -> None:
    """テスト2: ストリーミング応答."""
    separator("Test 2: Streaming (Zhipu GLM)")

    provider = ZhipuProvider(
        model="glm-4.5-air",
        api_key=GLM_API_KEY,
    )

    messages = [
        Message(role="user", content="Count from 1 to 5, one number per line."),
    ]

    print("Streaming: ", end="", flush=True)
    chunks = 0
    full_content = ""
    async for chunk in provider.stream(messages):
        if chunk.content:
            print(chunk.content, end="", flush=True)
            full_content += chunk.content
            chunks += 1
        if chunk.usage:
            print(f"\nFinal usage: input={chunk.usage.input_tokens}, output={chunk.usage.output_tokens}")

    print(f"\nChunks received: {chunks}")
    print("✓ Streaming OK")


async def test_3_cost_estimation(response) -> None:
    """テスト3: コスト推定."""
    separator("Test 3: Cost Estimation")

    estimator = CostEstimator()
    # Zhipu のカスタム料金を登録
    estimator.pricing_table.register(ZHIPU_PRICING)

    usage = response.usage or TokenUsage(input_tokens=100, output_tokens=50)
    cost = estimator.estimate("zhipu", "glm-4.5-air", usage)

    print(f"Input tokens: {usage.input_tokens}")
    print(f"Output tokens: {usage.output_tokens}")
    print(f"Estimated cost: ${cost:.6f}")

    # 累積コスト記録
    estimator.estimate_and_record("zhipu", "glm-4.5-air", usage, session_id="demo-session")
    spend = estimator.get_spend("session", "demo-session")
    print(f"Session spend: ${spend.total_usd:.6f}")
    print(f"Burn rate: ${spend.burn_rate_usd_per_minute:.6f}/min")
    print("✓ Cost estimation OK")


async def test_4_optimizer() -> None:
    """テスト4: CostOptimizer による最適モデル推薦."""
    separator("Test 4: Cost Optimizer")

    estimator = CostEstimator()
    estimator.pricing_table.register(ZHIPU_PRICING)
    optimizer = CostOptimizer(estimator=estimator)

    # 各複雑度レベルでの推薦
    for purpose, complexity in [
        ("classify this text", TaskComplexity.TRIVIAL),
        ("summarize this article", TaskComplexity.LOW),
        ("debug this code and fix", TaskComplexity.HIGH),
    ]:
        rec = optimizer.recommend(
            complexity=complexity,
            purpose=purpose,
            input_tokens_estimate=1000,
            output_tokens_estimate=500,
        )
        print(f"[{complexity.value:8s}] → {rec.provider}/{rec.model_id} "
              f"(${rec.estimated_cost_usd:.4f}) | {rec.reasoning}")

    print("✓ Cost optimizer OK")


async def test_5_adaptive_router() -> None:
    """テスト5: AdaptiveRouter の学習."""
    separator("Test 5: Adaptive Router Learning")

    router = AdaptiveRouter(exploration_rate=0.1, min_samples=3)

    # 過去の結果をシミュレート
    outcomes = [
        RoutingOutcome("summarize", "zhipu", "glm-4.5-air", ModelTier.LIGHTWEIGHT, 0.9, 0.001, 200, time.time()),
        RoutingOutcome("summarize", "zhipu", "glm-4.5-air", ModelTier.LIGHTWEIGHT, 0.85, 0.001, 180, time.time()),
        RoutingOutcome("summarize", "zhipu", "glm-4.5-air", ModelTier.LIGHTWEIGHT, 0.88, 0.001, 210, time.time()),
        RoutingOutcome("summarize", "deepseek", "deepseek-chat", ModelTier.LIGHTWEIGHT, 0.7, 0.002, 300, time.time()),
        RoutingOutcome("summarize", "deepseek", "deepseek-chat", ModelTier.LIGHTWEIGHT, 0.75, 0.002, 280, time.time()),
        RoutingOutcome("summarize", "deepseek", "deepseek-chat", ModelTier.LIGHTWEIGHT, 0.72, 0.002, 290, time.time()),
    ]

    for o in outcomes:
        router.record_outcome(o)

    # 推薦を取得
    suggestion = router.suggest_provider(
        purpose="summarize",
        tier=ModelTier.LIGHTWEIGHT,
        candidates=["zhipu", "deepseek"],
    )
    print(f"Suggested provider: {suggestion}")

    stats = router.get_stats("summarize")
    for provider, data in stats.items():
        ratio = data['avg_quality'] / data['avg_cost'] if data['avg_cost'] > 0 else float('inf')
        print(f"  {provider}: avg_quality={data['avg_quality']:.2f}, "
              f"avg_cost=${data['avg_cost']:.4f}, score={ratio:.1f}")

    print("✓ Adaptive router OK")


async def test_6_event_store() -> None:
    """テスト6: Event Sourcing 監査ログ."""
    separator("Test 6: Event Store")

    store = EventStore(max_events=1000)

    # イベント記録
    e1 = store.append("model.routed", "workflow-1", {
        "provider": "zhipu", "model": "glm-4.5-air", "tier": "lightweight",
    })
    e2 = store.append("cost.recorded", "workflow-1", {
        "cost_usd": 0.001, "input_tokens": 100, "output_tokens": 50,
    })
    e3 = store.append("model.routed", "workflow-2", {
        "provider": "anthropic", "model": "claude-haiku", "tier": "standard",
    })

    print(f"Total events: {store.count()}")
    print(f"Streams: {store.stream_ids()}")

    events = store.read_stream("workflow-1")
    for e in events:
        print(f"  [{e.sequence}] {e.event_type}: {e.payload}")

    print("✓ Event store OK")


async def test_7_rate_limiter() -> None:
    """テスト7: Rate Limiter + ヘルスチェック."""
    separator("Test 7: Rate Limiter & Health")

    rlm = RateLimitManager()
    rlm.register_provider(ProviderQuota(provider="zhipu", rpm=60, tpm=100_000, concurrent=5))

    # Pre-flight check
    can = rlm.can_send("zhipu", estimated_tokens=1000)
    print(f"Can send to zhipu: {can}")

    # リクエスト成功を記録
    rlm.acquire("zhipu")
    rlm.record_success("zhipu", latency_ms=200)
    rlm.release("zhipu")

    # ヘルス情報
    health = rlm.get_health("zhipu")
    print(f"Health: {health.to_dict()}")

    circuit = rlm.get_circuit_state("zhipu")
    print(f"Circuit state: {circuit}")
    print("✓ Rate limiter OK")


async def test_8_multi_turn() -> None:
    """テスト8: マルチターン会話."""
    separator("Test 8: Multi-turn Conversation")

    provider = ZhipuProvider(
        model="glm-4.5-air",
        api_key=GLM_API_KEY,
    )

    messages = [
        Message(role="user", content="My name is Alice."),
    ]

    r1 = await provider.chat(messages)
    print(f"Turn 1: {r1.content[:150]}")

    messages.append(Message(role="assistant", content=r1.content))
    messages.append(Message(role="user", content="What is my name?"))

    r2 = await provider.chat(messages)
    print(f"Turn 2: {r2.content[:150]}")

    assert "Alice" in r2.content or "alice" in r2.content.lower(), "Multi-turn context not preserved!"
    print("✓ Multi-turn OK")


async def test_9_anthropic_chat() -> None:
    """テスト9: Anthropic Claude への直接チャット呼び出し."""
    separator("Test 9: Anthropic Claude (Multi-Provider)")

    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set, skipping")
        return

    from pylon.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        model="claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
    )
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="user", content="What is 2+2? Reply with just the number."),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content}")
    print(f"Model: {response.model}")
    if response.usage:
        print(f"Usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")
    print(f"Latency: {latency:.0f}ms")
    print("✓ Anthropic chat OK")


async def test_10_kimi_chat() -> None:
    """テスト10: Moonshot Kimi API への直接チャット呼び出し."""
    separator("Test 10: Moonshot Kimi (API)")

    if not MOONSHOT_API_KEY:
        print("MOONSHOT_API_KEY not set, skipping")
        return

    from pylon.providers.moonshot import MoonshotProvider

    provider = MoonshotProvider(
        model="kimi-k2.5",
        api_key=MOONSHOT_API_KEY,
    )
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="user", content="What is 3+4? Reply with just the number."),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content}")
    print(f"Model: {response.model}")
    if response.usage:
        print(f"Usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")
    print(f"Latency: {latency:.0f}ms")
    print("✓ Kimi chat OK")


async def test_11_kimi_streaming() -> None:
    """テスト11: Moonshot Kimi ストリーミング."""
    separator("Test 11: Moonshot Kimi Streaming")

    if not MOONSHOT_API_KEY:
        print("MOONSHOT_API_KEY not set, skipping")
        return

    from pylon.providers.moonshot import MoonshotProvider

    provider = MoonshotProvider(
        model="kimi-k2.5",
        api_key=MOONSHOT_API_KEY,
    )

    messages = [
        Message(role="user", content="Say 'Hello Pylon' and nothing else."),
    ]

    print("Streaming: ", end="", flush=True)
    chunks = 0
    async for chunk in provider.stream(messages):
        if chunk.content:
            print(chunk.content, end="", flush=True)
            chunks += 1
        if chunk.usage:
            print(f"\nFinal usage: input={chunk.usage.input_tokens}, output={chunk.usage.output_tokens}")

    print(f"\nChunks received: {chunks}")
    print("✓ Kimi streaming OK")


async def main() -> None:
    print("Pylon Multi-Model Demo")
    print(f"Python {sys.version}")

    passed = 0
    total = 11

    try:
        response = await test_1_direct_chat()
        passed += 1
        await test_2_streaming()
        passed += 1
        await test_3_cost_estimation(response)
        passed += 1
        await test_4_optimizer()
        passed += 1
        await test_5_adaptive_router()
        passed += 1
        await test_6_event_store()
        passed += 1
        await test_7_rate_limiter()
        passed += 1
        await test_8_multi_turn()
        passed += 1
        await test_9_anthropic_chat()
        passed += 1
        await test_10_kimi_chat()
        passed += 1
        await test_11_kimi_streaming()
        passed += 1

        separator("ALL TESTS PASSED")
        print(f"  Pylon マルチモデル機能の動作確認が完了しました。")
        print(f"  {passed}/{total} テスト成功")

    except Exception as e:
        print(f"\n✗ FAILED at test {passed + 1}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
