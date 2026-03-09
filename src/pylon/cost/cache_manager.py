"""Prompt cache manager for multi-provider cache optimization.

Detects cacheable prefixes (system prompts, few-shot examples, tool
definitions), selects provider-appropriate caching strategies, tracks
cache hit rates, and pins cached prefixes to the same deployment for
load-balanced setups (LiteLLM pattern).
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pylon.autonomy.routing import CacheStrategy
from pylon.providers.base import Message, TokenUsage


@dataclass(frozen=True)
class CacheBreakpoint:
    """Optimal position in a message list to inject cache_control markers.

    For Anthropic: inject {"type": "ephemeral"} cache_control at this index.
    For OpenAI/DeepSeek: ensure prefix up to this index exceeds min tokens.
    For Gemini: use context caching API for content up to this index.
    """

    message_index: int
    token_count: int
    content_hash: str
    strategy: CacheStrategy


@dataclass
class CacheHitStats:
    """Tracks cache performance per provider/model pair."""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0
    last_hit_at: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a fraction [0.0, 1.0]."""
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": round(self.hit_rate, 4),
            "tokens_saved": self.tokens_saved,
            "cost_saved_usd": round(self.cost_saved_usd, 6),
        }


@dataclass(frozen=True)
class PrefixPin:
    """Binds a cached prefix hash to a specific deployment for affinity routing.

    When load-balancing across multiple deployments of the same provider,
    requests with the same prefix should be pinned to the same backend
    to maximize cache reuse (LiteLLM sticky routing pattern).
    """

    content_hash: str
    provider: str
    deployment_id: str
    pinned_at: float
    ttl_seconds: float = 3600.0

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.pinned_at > self.ttl_seconds


class CacheManager:
    """Manages prompt caching across providers with strategy auto-selection.

    Usage:
        cache_mgr = CacheManager()

        # Before sending to provider:
        breakpoints = cache_mgr.detect_breakpoints(messages, provider="anthropic")
        messages = cache_mgr.apply_cache_markers(messages, breakpoints, provider="anthropic")

        # After receiving response:
        cache_mgr.record_hit(provider, model_id, usage)

        # For load-balanced setups:
        deployment = cache_mgr.get_pinned_deployment(prefix_hash, provider)

    Integration with LLMRuntime:
        Insert between context preparation and provider.chat(). The runtime
        should call detect_breakpoints() and apply_cache_markers() before
        forwarding messages to the provider.
    """

    def __init__(
        self,
        min_prefix_tokens: int = 256,
        default_pin_ttl: float = 3600.0,
    ) -> None:
        self._min_prefix_tokens = min_prefix_tokens
        self._default_pin_ttl = default_pin_ttl
        self._lock = threading.Lock()
        # (provider, model_id) -> CacheHitStats
        self._stats: dict[tuple[str, str], CacheHitStats] = {}
        # content_hash -> PrefixPin
        self._pins: dict[str, PrefixPin] = {}

    def detect_breakpoints(
        self,
        messages: list[Message],
        provider: str,
        *,
        estimate_tokens_fn: Any = None,
    ) -> list[CacheBreakpoint]:
        """Identify optimal cache breakpoints in a message list.

        Scans for system prompts, consecutive few-shot examples, and tool
        definition blocks. Returns breakpoints sorted by token count descending
        (largest cacheable prefix first).

        Args:
            messages: The message list to analyze.
            provider: Provider name to select strategy.
            estimate_tokens_fn: Optional token estimator (defaults to char/4).

        Returns:
            List of CacheBreakpoint, empty if no cacheable content found.
        """
        if not messages:
            return []

        if estimate_tokens_fn is None:
            estimate_tokens_fn = _cheap_token_estimate

        strategy = self._strategy_for_provider(provider)
        if strategy == CacheStrategy.NONE:
            return []

        breakpoints: list[CacheBreakpoint] = []
        running_tokens = 0
        running_content: list[str] = []

        for i, msg in enumerate(messages):
            tokens = estimate_tokens_fn(msg.content)
            running_tokens += tokens
            running_content.append(msg.content)

            # System messages are always good breakpoints.
            if msg.role == "system":
                content_hash = _hash_content(running_content)
                breakpoints.append(CacheBreakpoint(
                    message_index=i,
                    token_count=running_tokens,
                    content_hash=content_hash,
                    strategy=strategy,
                ))
                continue

            # Few-shot example boundaries (user/assistant pairs).
            if (
                msg.role == "assistant"
                and i > 0
                and messages[i - 1].role == "user"
                and i + 1 < len(messages)
            ):
                content_hash = _hash_content(running_content)
                breakpoints.append(CacheBreakpoint(
                    message_index=i,
                    token_count=running_tokens,
                    content_hash=content_hash,
                    strategy=strategy,
                ))

        # Filter by minimum token threshold.
        min_tokens = self._provider_min_tokens(provider)
        breakpoints = [
            bp for bp in breakpoints
            if bp.token_count >= min_tokens
        ]

        # Sort by token count descending: prefer largest cacheable prefix.
        breakpoints.sort(key=lambda bp: bp.token_count, reverse=True)
        return breakpoints

    def apply_cache_markers(
        self,
        messages: list[Message],
        breakpoints: list[CacheBreakpoint],
        provider: str,
    ) -> list[dict[str, Any]]:
        """Apply provider-specific cache markers to messages.

        Returns provider-native message dicts (not Pylon Message objects)
        with cache control annotations inserted.

        For Anthropic: injects cache_control: {type: "ephemeral"} on the
        content block at the breakpoint index.

        For OpenAI/DeepSeek: returns messages unchanged (caching is automatic
        when prefix exceeds minimum token count).

        For Gemini: annotates with caching metadata for the context caching API.

        Args:
            messages: Original Pylon messages.
            breakpoints: Breakpoints from detect_breakpoints().
            provider: Provider name.

        Returns:
            List of provider-native message dicts.
        """
        if not breakpoints:
            return [_msg_to_dict(m) for m in messages]

        bp_indices = {bp.message_index for bp in breakpoints}
        result: list[dict[str, Any]] = []

        for i, msg in enumerate(messages):
            entry = _msg_to_dict(msg)
            if i in bp_indices and provider == "anthropic":
                # Anthropic explicit caching: wrap content in block with
                # cache_control marker.
                entry["content"] = [
                    {
                        "type": "text",
                        "text": msg.content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            elif i in bp_indices and provider == "google":
                entry["_pylon_cache_hint"] = True
            result.append(entry)

        return result

    def record_hit(
        self,
        provider: str,
        model_id: str,
        usage: TokenUsage,
        *,
        uncached_input_rate: float = 0.0,
        cached_input_rate: float = 0.0,
    ) -> None:
        """Record cache hit/miss statistics from a provider response.

        Call after every LLM response. If cache_read_tokens > 0, it's a hit.

        Args:
            provider: Provider name.
            model_id: Model identifier.
            usage: Token usage from the response.
            uncached_input_rate: $/M for uncached input (for cost savings calc).
            cached_input_rate: $/M for cached input.
        """
        with self._lock:
            key = (provider, model_id)
            stats = self._stats.setdefault(key, CacheHitStats())
            stats.total_requests += 1

            if usage.cache_read_tokens > 0:
                stats.cache_hits += 1
                stats.tokens_saved += usage.cache_read_tokens
                stats.last_hit_at = time.monotonic()

                if uncached_input_rate > 0 and cached_input_rate >= 0:
                    saving = (
                        usage.cache_read_tokens
                        * (uncached_input_rate - cached_input_rate)
                        / 1_000_000
                    )
                    stats.cost_saved_usd += max(0.0, saving)
            else:
                stats.cache_misses += 1

    def get_stats(self, provider: str, model_id: str) -> CacheHitStats:
        """Retrieve cache hit statistics for a provider/model pair."""
        with self._lock:
            return self._stats.get(
                (provider, model_id), CacheHitStats(),
            )

    def get_all_stats(self) -> dict[str, CacheHitStats]:
        """Retrieve all cache stats keyed by "provider/model"."""
        with self._lock:
            return {
                f"{k[0]}/{k[1]}": v
                for k, v in self._stats.items()
            }

    def pin_deployment(
        self,
        content_hash: str,
        provider: str,
        deployment_id: str,
        ttl_seconds: float | None = None,
    ) -> PrefixPin:
        """Pin a cached prefix to a specific deployment for affinity routing.

        Args:
            content_hash: Hash of the cacheable prefix content.
            provider: Provider name.
            deployment_id: Deployment/backend identifier.
            ttl_seconds: Time-to-live for the pin (default: 1 hour).

        Returns:
            The created PrefixPin.
        """
        pin = PrefixPin(
            content_hash=content_hash,
            provider=provider,
            deployment_id=deployment_id,
            pinned_at=time.monotonic(),
            ttl_seconds=ttl_seconds or self._default_pin_ttl,
        )
        with self._lock:
            self._pins[content_hash] = pin
        return pin

    def get_pinned_deployment(
        self,
        content_hash: str,
        provider: str,
    ) -> str | None:
        """Look up the pinned deployment for a prefix hash.

        Returns None if no pin exists or the pin has expired.
        """
        with self._lock:
            pin = self._pins.get(content_hash)
        if pin is None:
            return None
        if pin.provider != provider:
            return None
        if pin.expired:
            with self._lock:
                self._pins.pop(content_hash, None)
            return None
        return pin.deployment_id

    def _strategy_for_provider(self, provider: str) -> CacheStrategy:
        """Select the appropriate cache strategy for a provider."""
        if provider == "anthropic":
            return CacheStrategy.EXPLICIT
        if provider in {"openai", "deepseek"}:
            return CacheStrategy.PREFIX
        if provider == "google":
            return CacheStrategy.PREFIX
        # Providers without caching support.
        return CacheStrategy.NONE

    def _provider_min_tokens(self, provider: str) -> int:
        """Minimum cacheable prefix length per provider."""
        provider_minimums = {
            "openai": 1024,
            "anthropic": 256,
            "deepseek": 0,
            "google": 0,
        }
        return provider_minimums.get(provider, self._min_prefix_tokens)


def _cheap_token_estimate(text: str) -> int:
    """Rough token estimate without tiktoken dependency."""
    if not text:
        return 0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + int(non_ascii / 1.5))


def _hash_content(parts: list[str]) -> str:
    """Deterministic hash of concatenated content parts."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
    return h.hexdigest()[:16]


def _msg_to_dict(msg: Message) -> dict[str, Any]:
    """Convert a Pylon Message to a plain dict."""
    d: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = msg.tool_calls
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    return d
