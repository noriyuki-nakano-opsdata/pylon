"""Unit tests for OpenClawBridge."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from pylon.bridges.openclaw import OpenClawBridge


class TestOpenClawBridge:
    def test_openclaw_bridge_init(self) -> None:
        bridge = OpenClawBridge(
            base_url="http://example.com:18789",
            token="my-token",
        )
        assert bridge._base_url == "http://example.com:18789"
        assert bridge._token == "my-token"

    def test_openclaw_bridge_headers(self) -> None:
        bridge = OpenClawBridge(token="secret")
        headers = bridge._headers()
        assert headers["Authorization"] == "Bearer secret"
        assert headers["Content-Type"] == "application/json"

        bridge_no_token = OpenClawBridge()
        headers2 = bridge_no_token._headers()
        assert "Authorization" not in headers2

    @pytest.mark.asyncio
    async def test_openclaw_send_message(self) -> None:
        bridge = OpenClawBridge(token="tok")

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await bridge.send_message("general", "hello")
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_openclaw_health_check(self) -> None:
        bridge = OpenClawBridge()

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "healthy"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = await bridge.health_check()
            assert result == {"status": "healthy"}
