"""Tests for channel adapter abstraction."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, PropertyMock

import pytest

from pylon.gateway.channels import ChannelAdapter, ChannelMessage, ChannelRouter


class TestChannelMessageCreation:
    def test_channel_message_creation(self):
        msg = ChannelMessage(
            channel="slack",
            sender_id="U123",
            content="hello",
        )
        assert msg.channel == "slack"
        assert msg.sender_id == "U123"
        assert msg.content == "hello"
        assert msg.thread_id is None
        assert msg.attachments == []
        assert msg.metadata == {}

        msg2 = ChannelMessage(
            channel="discord",
            sender_id="D456",
            content="hi",
            thread_id="T789",
            attachments=[{"url": "file.png"}],
            metadata={"guild": "test"},
        )
        assert msg2.thread_id == "T789"
        assert len(msg2.attachments) == 1
        assert msg2.metadata["guild"] == "test"


class TestChannelRouterRegister:
    def test_channel_router_register(self):
        router = ChannelRouter()
        adapter = AsyncMock(spec=ChannelAdapter)
        type(adapter).channel_name = PropertyMock(return_value="slack")

        router.register_adapter(adapter)
        assert router.get_adapter("slack") is adapter
        assert router.get_adapter("discord") is None


class TestChannelRouterRoute:
    @pytest.mark.asyncio
    async def test_channel_router_route(self):
        router = ChannelRouter()
        adapter = AsyncMock(spec=ChannelAdapter)
        type(adapter).channel_name = PropertyMock(return_value="slack")
        router.register_adapter(adapter)

        async def handler(msg: ChannelMessage) -> str:
            return f"echo: {msg.content}"

        router.set_handler(handler)

        msg = ChannelMessage(channel="slack", sender_id="U1", content="test")
        result = await router.route(msg)
        assert result == "echo: test"

        # Missing channel raises KeyError
        msg2 = ChannelMessage(channel="unknown", sender_id="U1", content="x")
        with pytest.raises(KeyError, match="unknown"):
            await router.route(msg2)

        # No handler raises RuntimeError
        router2 = ChannelRouter()
        router2.register_adapter(adapter)
        msg3 = ChannelMessage(channel="slack", sender_id="U1", content="x")
        with pytest.raises(RuntimeError, match="No handler"):
            await router2.route(msg3)


class TestChannelAdapterProtocol:
    def test_channel_adapter_protocol(self):
        """Verify that a class implementing all methods satisfies the protocol."""

        class MockAdapter:
            @property
            def channel_name(self) -> str:
                return "test"

            async def receive(self) -> ChannelMessage:
                return ChannelMessage(channel="test", sender_id="u", content="m")

            async def send(self, message: ChannelMessage) -> None:
                pass

            async def health_check(self) -> bool:
                return True

        adapter = MockAdapter()
        assert isinstance(adapter, ChannelAdapter)
