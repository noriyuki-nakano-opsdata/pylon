"""Channel adapter abstraction layer for messaging integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class ChannelMessage:
    """Normalized message from any messaging channel."""

    channel: str
    sender_id: str
    content: str
    thread_id: str | None = None
    attachments: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Protocol for channel adapters (Slack, Discord, etc.)."""

    @property
    def channel_name(self) -> str:
        """Unique name for this channel adapter."""
        ...

    async def receive(self) -> ChannelMessage:
        """Receive the next message from the channel."""
        ...

    async def send(self, message: ChannelMessage) -> None:
        """Send a message to the channel."""
        ...

    async def health_check(self) -> bool:
        """Check whether the channel connection is healthy."""
        ...


class ChannelRouter:
    """Routes messages between channel adapters and a central handler.

    Adapters are registered by channel name. Incoming messages are passed
    to the configured handler, and the response is returned.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._handler: Callable[[ChannelMessage], Any] | None = None

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter.

        Args:
            adapter: An object implementing the ChannelAdapter protocol.
        """
        self._adapters[adapter.channel_name] = adapter

    def set_handler(self, handler: Callable[[ChannelMessage], Any]) -> None:
        """Set the handler for incoming messages.

        Args:
            handler: A callable (sync or async) that processes a ChannelMessage
                     and returns a response string.
        """
        self._handler = handler

    async def route(self, message: ChannelMessage) -> str:
        """Route a message through the handler and return the response.

        Args:
            message: The incoming channel message.

        Returns:
            Response text from the handler.

        Raises:
            RuntimeError: If no handler is configured.
            KeyError: If no adapter is registered for the message channel.
        """
        if message.channel not in self._adapters:
            raise KeyError(f"No adapter registered for channel: {message.channel}")

        if self._handler is None:
            raise RuntimeError("No handler configured")

        import asyncio
        result = self._handler(message)
        if asyncio.iscoroutine(result):
            result = await result

        return str(result)

    def get_adapter(self, channel_name: str) -> ChannelAdapter | None:
        """Look up a registered adapter by channel name."""
        return self._adapters.get(channel_name)
