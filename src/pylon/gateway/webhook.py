"""Webhook reception framework with HMAC verification."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class WebhookRequest:
    """Incoming webhook request."""

    source: str
    event_type: str
    payload: bytes
    signature: str = ""
    timestamp: int | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class WebhookResponse:
    """Webhook processing response."""

    accepted: bool
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    error: str | None = None


@runtime_checkable
class WebhookHandler(Protocol):
    """Protocol for webhook event handlers."""

    async def handle(self, request: WebhookRequest) -> WebhookResponse: ...


class WebhookVerifier:
    """Verifies webhook authenticity via HMAC-SHA256 and timestamp checks."""

    @staticmethod
    def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
        """Verify HMAC-SHA256 signature of the payload.

        Args:
            payload: Raw request body bytes.
            signature: Hex-encoded HMAC signature to verify against.
            secret: Shared secret key for HMAC computation.

        Returns:
            True if the signature matches.
        """
        expected = hmac.HMAC(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def verify_timestamp(timestamp: int, tolerance_seconds: int = 300) -> bool:
        """Check that the timestamp is within the tolerance window.

        Prevents replay attacks by rejecting requests with stale timestamps.

        Args:
            timestamp: Unix epoch timestamp from the request.
            tolerance_seconds: Maximum age in seconds (default 300).

        Returns:
            True if the timestamp is within the tolerance window.
        """
        now = int(time.time())
        return abs(now - timestamp) <= tolerance_seconds


class WebhookReceiver:
    """Receives, verifies, and routes webhook requests to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], WebhookHandler] = {}
        self._secret_store: dict[str, str] = {}
        self._verifier = WebhookVerifier()

    def register_handler(
        self,
        source: str,
        event_type: str,
        handler: WebhookHandler,
    ) -> None:
        """Register a handler for a specific source and event type.

        Args:
            source: Webhook source identifier (e.g. "github", "stripe").
            event_type: Event type string (e.g. "push", "payment.completed").
            handler: Handler implementing the WebhookHandler protocol.
        """
        self._handlers[(source, event_type)] = handler

    def set_secret(self, source: str, secret: str) -> None:
        """Set the HMAC secret for a webhook source.

        Args:
            source: Webhook source identifier.
            secret: Shared secret for HMAC verification.
        """
        self._secret_store[source] = secret

    async def handle(self, request: WebhookRequest) -> WebhookResponse:
        """Verify and route a webhook request.

        Performs HMAC verification (if a secret is configured for the source),
        timestamp validation, and dispatches to the registered handler.

        Args:
            request: The incoming webhook request.

        Returns:
            WebhookResponse indicating acceptance or rejection.
        """
        # Verify HMAC if a secret is configured
        secret = self._secret_store.get(request.source)
        if secret:
            if not request.signature:
                return WebhookResponse(
                    accepted=False,
                    error="Missing signature",
                )
            if not self._verifier.verify_hmac(
                request.payload, request.signature, secret,
            ):
                return WebhookResponse(
                    accepted=False,
                    error="Invalid signature",
                )

        # Verify timestamp if provided
        if request.timestamp is not None:
            if not self._verifier.verify_timestamp(request.timestamp):
                return WebhookResponse(
                    accepted=False,
                    error="Timestamp out of tolerance",
                )

        # Route to handler
        handler = self._handlers.get((request.source, request.event_type))
        if handler is None:
            return WebhookResponse(
                accepted=False,
                error=f"No handler for {request.source}:{request.event_type}",
            )

        return await handler.handle(request)
