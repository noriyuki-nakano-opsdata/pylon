"""Tests for webhook reception and HMAC verification."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from unittest.mock import AsyncMock

import pytest

from pylon.gateway.webhook import (
    WebhookReceiver,
    WebhookRequest,
    WebhookResponse,
    WebhookVerifier,
)


class TestHMACVerification:
    def test_hmac_verification_valid(self):
        payload = b'{"event":"push"}'
        secret = "test-secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert WebhookVerifier.verify_hmac(payload, sig, secret) is True

    def test_hmac_verification_invalid(self):
        payload = b'{"event":"push"}'
        secret = "test-secret"
        assert WebhookVerifier.verify_hmac(payload, "bad-signature", secret) is False


class TestTimestampVerification:
    def test_timestamp_verification_valid(self):
        now = int(time.time())
        assert WebhookVerifier.verify_timestamp(now) is True
        assert WebhookVerifier.verify_timestamp(now - 100) is True

    def test_timestamp_verification_expired(self):
        old = int(time.time()) - 600
        assert WebhookVerifier.verify_timestamp(old) is False
        assert WebhookVerifier.verify_timestamp(old, tolerance_seconds=60) is False


class TestWebhookReceiverRouting:
    @pytest.mark.asyncio
    async def test_webhook_receiver_routing(self):
        receiver = WebhookReceiver()

        mock_handler = AsyncMock()
        mock_handler.handle = AsyncMock(
            return_value=WebhookResponse(accepted=True, request_id="abc")
        )

        receiver.register_handler("github", "push", mock_handler)

        request = WebhookRequest(
            source="github",
            event_type="push",
            payload=b'{"ref":"main"}',
        )

        result = await receiver.handle(request)
        assert result.accepted is True
        assert result.request_id == "abc"
        mock_handler.handle.assert_called_once_with(request)

        # Unknown source/event returns error
        unknown_req = WebhookRequest(
            source="unknown",
            event_type="ping",
            payload=b"",
        )
        result2 = await receiver.handle(unknown_req)
        assert result2.accepted is False
        assert "No handler" in (result2.error or "")
