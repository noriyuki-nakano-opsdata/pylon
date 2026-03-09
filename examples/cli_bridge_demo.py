"""Pylon CLI Bridge マルチモデル動作確認スクリプト.

Claude Code / Gemini CLI / Kimi Code の各CLI Bridgeを経由して
Pylonのマルチモデル統合を検証する。

Usage:
    python examples/cli_bridge_demo.py
    python examples/cli_bridge_demo.py --only claude    # Claude Codeのみ
    python examples/cli_bridge_demo.py --only gemini    # Gemini CLIのみ
    python examples/cli_bridge_demo.py --only kimi      # Kimi Codeのみ

Requires: claude, gemini, kimi CLIs installed and authenticated.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import time

from pathlib import Path

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pylon.bridges.claude_code import ClaudeCodeBridge, ClaudeCodeProvider
from pylon.bridges.gemini_cli import GeminiCLIBridge, GeminiCLIProvider
from pylon.bridges.kimi_code import KimiCodeBridge, KimiCodeProvider
from pylon.providers.base import Message


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check_cli(name: str) -> bool:
    """Check if a CLI tool is available."""
    return shutil.which(name) is not None


async def test_claude_code() -> bool:
    """Claude Code CLI Bridge テスト."""
    separator("Claude Code CLI Bridge")

    if not check_cli("claude"):
        print("claude CLI not found, skipping")
        return False

    bridge = ClaudeCodeBridge(model="claude-sonnet-4-6", max_turns=1)
    provider = ClaudeCodeProvider(bridge, model="claude-sonnet-4-6")
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="user", content="What is 2+3? Reply with just the number, nothing else."),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content[:200]}")
    print(f"Model: {response.model}")
    if response.usage:
        print(f"Usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")
    print(f"Latency: {latency:.0f}ms")
    print("OK: Claude Code Bridge")
    return True


async def test_gemini_cli() -> bool:
    """Gemini CLI Bridge テスト."""
    separator("Gemini CLI Bridge")

    if not check_cli("gemini"):
        print("gemini CLI not found, skipping")
        return False

    bridge = GeminiCLIBridge(model="gemini-2.5-flash", yolo=True)
    provider = GeminiCLIProvider(bridge, model="gemini-2.5-flash")
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="user", content="What is 4+5? Reply with just the number, nothing else."),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content[:200]}")
    print(f"Model: {response.model}")
    print(f"Latency: {latency:.0f}ms")
    print("OK: Gemini CLI Bridge")
    return True


async def test_kimi_code() -> bool:
    """Kimi Code CLI Bridge テスト."""
    separator("Kimi Code CLI Bridge")

    if not check_cli("kimi"):
        print("kimi CLI not found, skipping")
        return False

    bridge = KimiCodeBridge(model="kimi-k2.5")
    provider = KimiCodeProvider(bridge, model="kimi-k2.5")
    print(f"Provider: {provider.provider_name} / {provider.model_id}")

    messages = [
        Message(role="user", content="What is 6+7? Reply with just the number, nothing else."),
    ]

    start = time.monotonic()
    response = await provider.chat(messages)
    latency = (time.monotonic() - start) * 1000

    print(f"Response: {response.content[:200]}")
    print(f"Model: {response.model}")
    print(f"Latency: {latency:.0f}ms")
    print("OK: Kimi Code Bridge")
    return True


async def test_multi_bridge_comparison() -> None:
    """全Bridge横断比較テスト."""
    separator("Multi-Bridge Comparison")

    prompt = "Explain what a Python decorator is in one sentence."
    results: list[tuple[str, str, float]] = []

    bridges = [
        ("claude-code", ClaudeCodeProvider(ClaudeCodeBridge(max_turns=1))),
        ("gemini-cli", GeminiCLIProvider(GeminiCLIBridge(model="gemini-2.5-flash"))),
        ("kimi-code", KimiCodeProvider(KimiCodeBridge())),
    ]

    for name, provider in bridges:
        if not check_cli(name.split("-")[0] if "-" in name else name):
            print(f"  {name}: CLI not found, skipped")
            continue

        start = time.monotonic()
        try:
            response = await provider.chat([Message(role="user", content=prompt)])
            latency = (time.monotonic() - start) * 1000
            content = response.content.strip()[:120]
            results.append((name, content, latency))
            print(f"  {name} ({latency:.0f}ms): {content}")
        except Exception as e:
            print(f"  {name}: FAILED - {e}")

    if results:
        print(f"\n  Compared {len(results)} bridges successfully")
    print("OK: Multi-Bridge Comparison")


async def main() -> None:
    print("Pylon CLI Bridge Demo")
    print(f"Python {sys.version}")

    # Parse --only flag
    only = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        if idx + 1 < len(sys.argv):
            only = sys.argv[idx + 1]

    # Check available CLIs
    print(f"\nCLI availability:")
    for cli in ["claude", "gemini", "kimi"]:
        status = "found" if check_cli(cli) else "not found"
        print(f"  {cli}: {status}")

    passed = 0
    failed = 0
    skipped = 0

    tests = [
        ("claude", test_claude_code),
        ("gemini", test_gemini_cli),
        ("kimi", test_kimi_code),
    ]

    for name, test_fn in tests:
        if only and name != only:
            continue
        try:
            ok = await test_fn()
            if ok:
                passed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"\nFAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    # Multi-bridge comparison (skip if --only)
    if not only:
        try:
            await test_multi_bridge_comparison()
            passed += 1
        except Exception as e:
            print(f"\nFAILED: {e}")
            failed += 1

    separator("RESULTS")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Skipped: {skipped}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
