"""Tenant resolution middleware."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Protocol, runtime_checkable

from pylon.tenancy.context import TenantContext


class TenantNotFoundError(LookupError):
    """Raised when a tenant cannot be resolved."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Tenant not found: {identifier}")


@runtime_checkable
class TenantResolver(Protocol):
    def resolve(self, identifier: str) -> TenantContext: ...


class TenantDirectory:
    """In-memory tenant directory for lookups."""

    def __init__(self) -> None:
        self._tenants: dict[str, TenantContext] = {}

    def register(self, ctx: TenantContext) -> None:
        self._tenants[ctx.tenant_id] = ctx

    def lookup(self, tenant_id: str) -> TenantContext | None:
        return self._tenants.get(tenant_id)

    def remove(self, tenant_id: str) -> bool:
        if tenant_id in self._tenants:
            del self._tenants[tenant_id]
            return True
        return False

    def list_tenants(self) -> list[TenantContext]:
        return list(self._tenants.values())


class HeaderTenantResolver:
    """Resolves tenant from X-Tenant-ID header."""

    def __init__(self, directory: TenantDirectory) -> None:
        self._directory = directory

    def resolve(self, identifier: str) -> TenantContext:
        ctx = self._directory.lookup(identifier)
        if ctx is None:
            raise TenantNotFoundError(identifier)
        return ctx


_logger = logging.getLogger(__name__)


class TokenTenantResolver:
    """Resolves tenant from JWT-like token (base64-encoded JSON payload).

    When ``secret`` is provided, the JWT signature (HS256) is verified
    before trusting the payload.  Without a secret the resolver falls
    back to the legacy unsigned behaviour but emits a warning.
    """

    def __init__(
        self,
        directory: TenantDirectory,
        secret: str | None = None,
    ) -> None:
        self._directory = directory
        self._secret = secret
        if secret is None:
            _logger.warning(
                "TokenTenantResolver: no secret configured; "
                "JWT signatures will NOT be verified."
            )

    def _verify_signature(self, token: str) -> None:
        """Verify HS256 JWT signature. Raises TenantNotFoundError on failure."""
        parts = token.split(".")
        if len(parts) != 3:
            raise TenantNotFoundError("invalid token: expected 3 parts for signed JWT")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        sig_b64 = parts[2]
        # Add padding
        padding = 4 - len(sig_b64) % 4
        if padding != 4:
            sig_b64 += "=" * padding
        provided_sig = base64.urlsafe_b64decode(sig_b64)
        expected_sig = hmac.new(
            self._secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(provided_sig, expected_sig):
            raise TenantNotFoundError("invalid token: signature verification failed")

    def resolve(self, token: str) -> TenantContext:
        # Verify signature if secret is configured
        if self._secret is not None:
            self._verify_signature(token)

        try:
            parts = token.split(".")
            if len(parts) < 2:
                raise ValueError("Invalid token format")
            # Decode payload (part[1]), add padding
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            tenant_id = payload.get("tenant_id", "")
        except TenantNotFoundError:
            raise
        except Exception as exc:
            raise TenantNotFoundError(f"invalid token: {exc}") from exc

        if not tenant_id:
            raise TenantNotFoundError("no tenant_id in token")

        ctx = self._directory.lookup(tenant_id)
        if ctx is None:
            raise TenantNotFoundError(tenant_id)
        return ctx


class TenantMiddleware:
    """Request-level tenant resolution."""

    def __init__(
        self,
        header_resolver: HeaderTenantResolver | None = None,
        token_resolver: TokenTenantResolver | None = None,
    ) -> None:
        self._header_resolver = header_resolver
        self._token_resolver = token_resolver

    def resolve_tenant(self, request_headers: dict[str, str]) -> TenantContext:
        # Try X-Tenant-ID header first
        tenant_id = request_headers.get("X-Tenant-ID") or request_headers.get("x-tenant-id")
        if tenant_id and self._header_resolver:
            return self._header_resolver.resolve(tenant_id)

        # Try Authorization header with Bearer token
        auth = request_headers.get("Authorization") or request_headers.get("authorization")
        if auth and self._token_resolver:
            token = auth.removeprefix("Bearer ").strip()
            return self._token_resolver.resolve(token)

        raise TenantNotFoundError("no tenant identifier in request")
