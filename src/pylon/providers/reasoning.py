"""Reasoning/thinking output normalization across LLM providers.

Each provider has a different format for reasoning/thinking output.
This module provides a unified interface to extract and manage
reasoning data across multi-turn conversations.

Provider-specific rules:
- Anthropic: thinking blocks with signatures, MUST re-send in multi-turn
- OpenAI: reasoning items in Responses API, no re-send needed
- DeepSeek: reasoning_content field, MUST NOT re-send (400 error)
- Zhipu/Moonshot: reasoning_content field, MUST NOT re-send
- Gemini: thought signatures, MUST return signatures in next turn
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, Protocol

from pylon.providers.base import Message, ReasoningOutput


class ReasoningHandler(Protocol):
    """Protocol for provider-specific reasoning extraction."""

    def extract(self, raw_response: dict[str, Any]) -> ReasoningOutput | None:
        """Extract reasoning from a raw API response dict."""
        ...

    def prepare_messages(
        self,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        """Prepare messages for multi-turn, handling reasoning data appropriately."""
        ...


class AnthropicReasoningHandler:
    """Handle Anthropic thinking blocks with signatures.

    Anthropic returns thinking content blocks alongside text blocks.
    In multi-turn conversations, thinking blocks with their signatures
    MUST be re-sent in assistant messages to maintain conversation state.
    """

    def extract(self, raw_response: dict[str, Any]) -> ReasoningOutput | None:
        content_blocks = raw_response.get("content", [])
        thinking_parts: list[str] = []
        signature_blocks: list[dict[str, Any]] = []
        reasoning_tokens = 0

        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking", "")
                if text:
                    thinking_parts.append(text)
                signature = block.get("signature")
                signature_blocks.append({
                    "type": "thinking",
                    "thinking": text,
                    "signature": signature,
                })

        if not thinking_parts:
            return None

        usage = raw_response.get("usage", {})
        if isinstance(usage, dict):
            reasoning_tokens = usage.get("reasoning_tokens", 0)

        return ReasoningOutput(
            content="\n\n".join(thinking_parts),
            tokens=reasoning_tokens,
            redacted_for_resend=signature_blocks,
        )

    def prepare_messages(
        self,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        if not reasoning_history:
            return messages

        # Build a lookup: index reasoning outputs to re-insert into
        # assistant messages in order.
        result = list(messages)
        reasoning_iter = iter(reasoning_history)

        prepared: list[Message] = []
        for msg in result:
            if msg.role == "assistant":
                reasoning = next(reasoning_iter, None)
                if reasoning and reasoning.redacted_for_resend:
                    # Build content blocks: thinking blocks first, then text.
                    # The provider layer detects list-type content and uses it
                    # directly as structured blocks in the Anthropic API call.
                    content_blocks: list[dict[str, Any]] = list(
                        reasoning.redacted_for_resend
                    )
                    content_blocks.append({"type": "text", "text": msg.content})
                    prepared.append(replace(
                        msg,
                        content_blocks=content_blocks,
                    ))
                    continue
            prepared.append(msg)

        return prepared


class DeepSeekReasoningHandler:
    """Handle DeepSeek/Zhipu/Moonshot reasoning_content field.

    These providers expose reasoning via a `reasoning_content` field
    on the response message. This data MUST NOT be re-sent in
    multi-turn conversations (causes 400 error).
    """

    def extract(self, raw_response: dict[str, Any]) -> ReasoningOutput | None:
        choices = raw_response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        reasoning_content = message.get("reasoning_content")
        if not reasoning_content:
            return None

        usage = raw_response.get("usage", {})
        reasoning_tokens = 0
        if isinstance(usage, dict):
            reasoning_tokens = usage.get("reasoning_tokens", 0) or usage.get(
                "completion_tokens_details", {}
            ).get("reasoning_tokens", 0)

        return ReasoningOutput(
            content=reasoning_content,
            tokens=reasoning_tokens,
            redacted_for_resend=None,  # Must not re-send
        )

    def prepare_messages(
        self,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        # Strip any reasoning data — must not re-send.
        # Messages are plain text so nothing to strip in the base case.
        # Return a copy to avoid mutating the original.
        return [copy.copy(msg) for msg in messages]


class OpenAIReasoningHandler:
    """Handle OpenAI reasoning (Responses API / o-series models).

    OpenAI manages reasoning state server-side. No client-side
    re-send is needed. Reasoning effort is controlled via the
    `reasoning_effort` parameter.
    """

    def extract(self, raw_response: dict[str, Any]) -> ReasoningOutput | None:
        # Responses API format: look for reasoning summary
        choices = raw_response.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            # o-series models may include reasoning in the response
            reasoning = message.get("reasoning")
            if reasoning:
                usage = raw_response.get("usage", {})
                detail = usage.get("completion_tokens_details", {})
                return ReasoningOutput(
                    content=reasoning,
                    tokens=detail.get("reasoning_tokens", 0)
                    if isinstance(detail, dict)
                    else 0,
                )

        # Also check for reasoning items in Responses API format
        reasoning_items = raw_response.get("reasoning", [])
        if reasoning_items and isinstance(reasoning_items, list):
            texts = [
                item.get("text", "")
                for item in reasoning_items
                if isinstance(item, dict)
            ]
            combined = "\n\n".join(t for t in texts if t)
            if combined:
                return ReasoningOutput(content=combined)

        return None

    def prepare_messages(
        self,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        # No modification needed — server manages state.
        return messages


class GeminiReasoningHandler:
    """Handle Gemini/Vertex thought signatures.

    Gemini returns thought summaries with signatures that MUST be
    returned in the next turn. Failure to include signatures
    results in a 400 error.
    """

    def extract(self, raw_response: dict[str, Any]) -> ReasoningOutput | None:
        candidates = raw_response.get("candidates", [])
        if not candidates:
            return None

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        thought_parts: list[str] = []
        thought_signatures: list[dict[str, Any]] = []

        for part in parts:
            if isinstance(part, dict) and part.get("thought"):
                text = part.get("text", "")
                if text:
                    thought_parts.append(text)
                thought_signatures.append(part)

        if not thought_parts:
            return None

        usage = raw_response.get("usageMetadata", {})
        reasoning_tokens = 0
        if isinstance(usage, dict):
            reasoning_tokens = usage.get("thoughtsTokenCount", 0)

        return ReasoningOutput(
            content="\n\n".join(thought_parts),
            tokens=reasoning_tokens,
            redacted_for_resend=thought_signatures,
        )

    def prepare_messages(
        self,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        if not reasoning_history:
            return messages

        # For Gemini, thought signatures must be included in the next turn.
        # Attach redacted thought signatures to assistant messages so the
        # Gemini API can validate conversation continuity.
        result = list(messages)
        reasoning_iter = iter(reasoning_history)

        prepared: list[Message] = []
        for msg in result:
            if msg.role == "assistant":
                reasoning = next(reasoning_iter, None)
                if reasoning and reasoning.redacted_for_resend:
                    signature_text = " ".join(
                        f"[thought_signature: {part.get('text', '')[:50]}]"
                        for part in reasoning.redacted_for_resend
                        if isinstance(part, dict) and part.get("thought")
                    )
                    if signature_text:
                        prepared.append(replace(
                            msg,
                            content=f"{signature_text}\n{msg.content}",
                        ))
                        continue
            prepared.append(msg)

        return prepared


class ReasoningNormalizer:
    """Normalize reasoning output across providers.

    Provides a unified interface to extract reasoning data from
    raw API responses and prepare messages for multi-turn
    conversations with provider-specific handling rules.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ReasoningHandler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["anthropic"] = AnthropicReasoningHandler()
        self._handlers["deepseek"] = DeepSeekReasoningHandler()
        self._handlers["moonshot"] = DeepSeekReasoningHandler()  # Same format
        self._handlers["zhipu"] = DeepSeekReasoningHandler()  # Same format
        self._handlers["openai"] = OpenAIReasoningHandler()
        self._handlers["google"] = GeminiReasoningHandler()
        self._handlers["vertex"] = GeminiReasoningHandler()  # Same as google

    def register(self, provider_name: str, handler: ReasoningHandler) -> None:
        """Register a custom reasoning handler for a provider."""
        self._handlers[provider_name] = handler

    def extract(
        self, provider_name: str, raw_response: dict[str, Any]
    ) -> ReasoningOutput | None:
        """Extract reasoning from raw response.

        Returns None if no handler registered or no reasoning found.
        """
        handler = self._handlers.get(provider_name)
        if handler is None:
            return None
        return handler.extract(raw_response)

    def prepare_for_resend(
        self,
        provider_name: str,
        messages: list[Message],
        reasoning_history: list[ReasoningOutput],
    ) -> list[Message]:
        """Prepare messages for multi-turn conversation.

        Applies provider-specific reasoning rules:
        - Anthropic: Re-insert thinking blocks with signatures
        - DeepSeek/Zhipu/Moonshot: Strip reasoning data
        - OpenAI: No modification
        - Gemini/Vertex: Return thought signatures
        """
        handler = self._handlers.get(provider_name)
        if handler is None:
            return messages
        return handler.prepare_messages(messages, reasoning_history)
