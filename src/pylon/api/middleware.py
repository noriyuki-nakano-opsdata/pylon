"""API middleware: authentication, tenant isolation, rate limiting, security headers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets as _secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pylon.api.server import HandlerFunc, Request, Response

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class AuthPrincipal:
    """Authenticated principal projected from a bearer token."""

    subject: str
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()
    token_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "tenant_id": self.tenant_id,
            "scopes": list(self.scopes),
            "token_id": self.token_id,
            "claims": dict(self.claims),
        }


@dataclass(frozen=True)
class ServiceToken:
    """Static service-token definition used by reference auth backends."""

    token: str
    subject: str
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()
    token_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: str | dict[str, Any]) -> ServiceToken:
        if isinstance(value, str):
            token_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
            return cls(
                token=value,
                subject=f"token:{token_hash}",
                token_id=token_hash,
            )
        scopes = value.get("scopes", ())
        tenant_id = value.get("tenant_id")
        token_id = value.get("token_id")
        return cls(
            token=str(value["token"]),
            subject=str(value.get("subject") or value.get("principal_id") or "service-token"),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            scopes=tuple(str(scope) for scope in scopes),
            token_id=str(token_id) if token_id is not None else None,
            claims=dict(value.get("claims", {})),
        )

    def to_principal(self) -> AuthPrincipal:
        return AuthPrincipal(
            subject=self.subject,
            tenant_id=self.tenant_id,
            scopes=self.scopes,
            token_id=self.token_id,
            claims=dict(self.claims),
        )


class TokenVerificationError(ValueError):
    """Raised when a bearer token cannot be verified."""


@runtime_checkable
class TokenVerifier(Protocol):
    """Adapter interface for bearer token verification."""

    def verify(self, token: str) -> AuthPrincipal: ...


class InMemoryTokenVerifier(TokenVerifier):
    """Reference verifier backed by an in-memory token registry."""

    def __init__(self, tokens: Sequence[ServiceToken] | None = None) -> None:
        self._tokens: list[ServiceToken] = list(tokens or ())

    @classmethod
    def from_plain_tokens(cls, tokens: Sequence[str] | set[str]) -> InMemoryTokenVerifier:
        return cls([ServiceToken.from_value(token) for token in tokens])

    def add_token(
        self,
        token: str,
        *,
        subject: str | None = None,
        tenant_id: str | None = None,
        scopes: Sequence[str] = (),
        token_id: str | None = None,
        claims: dict[str, Any] | None = None,
    ) -> None:
        self._tokens.append(ServiceToken(
            token=token,
            subject=subject or f"token:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]}",
            tenant_id=tenant_id,
            scopes=tuple(str(scope) for scope in scopes),
            token_id=token_id,
            claims=dict(claims or {}),
        ))

    def verify(self, token: str) -> AuthPrincipal:
        for entry in self._tokens:
            if _secrets.compare_digest(token, entry.token):
                return entry.to_principal()
        raise TokenVerificationError("Invalid token")


class JsonFileTokenVerifier(TokenVerifier):
    """Reference verifier backed by a JSON file of service tokens."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"Token registry not found: {self._path}")
        # Validate file shape eagerly so misconfiguration fails fast.
        self._load_tokens()

    def _load_tokens(self) -> list[ServiceToken]:
        with self._path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        values = raw.get("tokens", raw) if isinstance(raw, dict) else raw
        if not isinstance(values, list):
            raise ValueError("Token registry must be a list or {'tokens': [...]} mapping")
        return [ServiceToken.from_value(item) for item in values]

    def verify(self, token: str) -> AuthPrincipal:
        return InMemoryTokenVerifier(self._load_tokens()).verify(token)


def _decode_jwt_part(part: str) -> dict[str, Any]:
    padded = part + "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


class JWTTokenVerifier(TokenVerifier):
    """HS256 JWT verifier for API bearer-token authentication."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str | None = None,
        audience: Sequence[str] = (),
        tenant_claim: str = "tenant_id",
        subject_claim: str = "sub",
        scopes_claim: str = "scope",
        leeway_seconds: float = 0.0,
    ) -> None:
        if not secret:
            raise ValueError("JWTTokenVerifier requires a non-empty secret")
        self._secret = secret
        self._issuer = issuer
        self._audience = tuple(str(item) for item in audience)
        self._tenant_claim = tenant_claim
        self._subject_claim = subject_claim
        self._scopes_claim = scopes_claim
        self._leeway_seconds = float(leeway_seconds)

    def _verify_signature(self, header_b64: str, payload_b64: str, signature_b64: str) -> None:
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(
            self._secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        padded = signature_b64 + "=" * (-len(signature_b64) % 4)
        try:
            provided_sig = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:  # pragma: no cover - defensive
            raise TokenVerificationError("Invalid token signature encoding") from exc
        if not hmac.compare_digest(provided_sig, expected_sig):
            raise TokenVerificationError("Invalid token signature")

    def _validate_claims(self, payload: dict[str, Any], now: float) -> None:
        if self._issuer is not None and payload.get("iss") != self._issuer:
            raise TokenVerificationError("Invalid token issuer")

        if self._audience:
            token_aud = payload.get("aud")
            if isinstance(token_aud, str):
                token_audiences = {token_aud}
            elif isinstance(token_aud, Sequence):
                token_audiences = {str(item) for item in token_aud}
            else:
                token_audiences = set()
            if not token_audiences.intersection(self._audience):
                raise TokenVerificationError("Invalid token audience")

        exp = payload.get("exp")
        if exp is not None and float(exp) + self._leeway_seconds < now:
            raise TokenVerificationError("Token has expired")

        nbf = payload.get("nbf")
        if nbf is not None and float(nbf) - self._leeway_seconds > now:
            raise TokenVerificationError("Token not yet valid")

        iat = payload.get("iat")
        if iat is not None and float(iat) - self._leeway_seconds > now:
            raise TokenVerificationError("Token issued in the future")

    def _extract_scopes(self, payload: dict[str, Any]) -> tuple[str, ...]:
        scopes_value = payload.get(self._scopes_claim, ())
        if isinstance(scopes_value, str):
            return tuple(scope for scope in scopes_value.split(" ") if scope)
        if isinstance(scopes_value, Sequence):
            return tuple(str(scope) for scope in scopes_value)
        return ()

    def verify(self, token: str) -> AuthPrincipal:
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenVerificationError("Invalid JWT structure")
        header = _decode_jwt_part(parts[0])
        payload = _decode_jwt_part(parts[1])
        if header.get("alg") != "HS256":
            raise TokenVerificationError("Unsupported JWT algorithm")
        self._verify_signature(parts[0], parts[1], parts[2])
        self._validate_claims(payload, now=time.time())

        subject = payload.get(self._subject_claim)
        if not subject:
            raise TokenVerificationError("JWT subject claim is required")

        tenant_value = payload.get(self._tenant_claim)
        tenant_id = str(tenant_value) if tenant_value is not None else None
        token_id = payload.get("jti")
        return AuthPrincipal(
            subject=str(subject),
            tenant_id=tenant_id,
            scopes=self._extract_scopes(payload),
            token_id=str(token_id) if token_id is not None else None,
            claims=dict(payload),
        )


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of a rate-limit consume attempt."""

    allowed: bool
    remaining_tokens: float
    retry_after_seconds: float = 0.0


@runtime_checkable
class RateLimitStore(Protocol):
    """Adapter interface for token-bucket persistence."""

    def consume(
        self,
        bucket_key: str,
        *,
        capacity: int,
        refill_rate: float,
        now: float,
    ) -> RateLimitDecision: ...


@dataclass
class _TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float
    refill_rate: float
    last_refill: float = 0.0

    def consume(self, now: float) -> RateLimitDecision:
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return RateLimitDecision(
                allowed=True,
                remaining_tokens=self.tokens,
                retry_after_seconds=0.0,
            )
        deficit = 1.0 - self.tokens
        retry_after = deficit / self.refill_rate if self.refill_rate > 0 else 1.0
        return RateLimitDecision(
            allowed=False,
            remaining_tokens=self.tokens,
            retry_after_seconds=max(retry_after, 0.0),
        )


class InMemoryRateLimitStore(RateLimitStore):
    """Thread-safe in-memory token-bucket store."""

    def __init__(self) -> None:
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()

    def consume(
        self,
        bucket_key: str,
        *,
        capacity: int,
        refill_rate: float,
        now: float,
    ) -> RateLimitDecision:
        with self._lock:
            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _TokenBucket(
                    capacity=capacity,
                    tokens=float(capacity),
                    refill_rate=refill_rate,
                    last_refill=now,
                )
                self._buckets[bucket_key] = bucket
            return bucket.consume(now)


class SQLiteRateLimitStore(RateLimitStore):
    """SQLite-backed token-bucket store shared across processes."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), isolation_level=None, timeout=30.0)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_limit_buckets (
                    bucket_key TEXT PRIMARY KEY,
                    tokens REAL NOT NULL,
                    last_refill REAL NOT NULL
                )
                """
            )

    def consume(
        self,
        bucket_key: str,
        *,
        capacity: int,
        refill_rate: float,
        now: float,
    ) -> RateLimitDecision:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT tokens, last_refill FROM rate_limit_buckets WHERE bucket_key = ?",
                (bucket_key,),
            ).fetchone()
            if row is None:
                bucket = _TokenBucket(
                    capacity=capacity,
                    tokens=float(capacity),
                    refill_rate=refill_rate,
                    last_refill=now,
                )
            else:
                bucket = _TokenBucket(
                    capacity=capacity,
                    tokens=float(row[0]),
                    refill_rate=refill_rate,
                    last_refill=float(row[1]),
                )
            decision = bucket.consume(now)
            conn.execute(
                """
                INSERT INTO rate_limit_buckets(bucket_key, tokens, last_refill)
                VALUES(?, ?, ?)
                ON CONFLICT(bucket_key)
                DO UPDATE SET tokens = excluded.tokens, last_refill = excluded.last_refill
                """,
                (bucket_key, bucket.tokens, bucket.last_refill),
            )
            conn.commit()
            return decision


class AuthMiddleware:
    """Bearer token authentication middleware."""

    def __init__(
        self,
        valid_tokens: set[str] | None = None,
        *,
        verifier: TokenVerifier | None = None,
    ) -> None:
        if verifier is not None and valid_tokens is not None:
            raise ValueError("Specify either valid_tokens or verifier, not both")
        self._verifier = verifier or InMemoryTokenVerifier.from_plain_tokens(valid_tokens or set())

    def add_token(
        self,
        token: str,
        *,
        subject: str | None = None,
        tenant_id: str | None = None,
        scopes: Sequence[str] = (),
        token_id: str | None = None,
        claims: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(self._verifier, InMemoryTokenVerifier):
            raise TypeError("add_token() is only supported for InMemoryTokenVerifier")
        self._verifier.add_token(
            token,
            subject=subject,
            tenant_id=tenant_id,
            scopes=scopes,
            token_id=token_id,
            claims=claims,
        )

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        if request.path == "/health":
            return next_handler(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return Response(
                status_code=401,
                body={"error": "Missing or invalid Authorization header"},
            )

        token = auth[7:]
        try:
            principal = self._verifier.verify(token)
        except TokenVerificationError:
            return Response(status_code=401, body={"error": "Invalid token"})

        request.context["authenticated"] = True
        request.context["token_hash"] = hashlib.sha256(token.encode()).hexdigest()[:16]
        request.context["auth_principal"] = principal
        request.context["auth_principal_claims"] = principal.to_dict()
        return next_handler(request)


class TenantMiddleware:
    """Extracts tenant context from header and/or authenticated principal."""

    def __init__(self, *, require_tenant: bool = True) -> None:
        self._require = require_tenant

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        if request.path == "/health":
            return next_handler(request)

        header_tenant_id = request.headers.get("x-tenant-id", "")
        principal = request.context.get("auth_principal")
        principal_tenant = (
            principal.tenant_id
            if isinstance(principal, AuthPrincipal) and principal.tenant_id
            else None
        )

        if header_tenant_id and not _TENANT_ID_RE.match(header_tenant_id):
            return Response(
                status_code=400,
                body={"error": "Invalid tenant ID format"},
            )
        if principal_tenant and not _TENANT_ID_RE.match(principal_tenant):
            return Response(
                status_code=401,
                body={"error": "Authenticated token carries an invalid tenant binding"},
            )
        if header_tenant_id and principal_tenant and header_tenant_id != principal_tenant:
            return Response(
                status_code=403,
                body={"error": "Authenticated principal is not authorized for requested tenant"},
            )

        effective_id = header_tenant_id or principal_tenant or ""
        if not effective_id:
            if self._require:
                return Response(status_code=400, body={"error": "X-Tenant-ID header is required"})
            effective_id = "default"

        request.context["tenant_id"] = effective_id
        request.context["tenant_source"] = (
            "header"
            if header_tenant_id
            else ("principal" if principal_tenant else "default")
        )
        request.context["tenant_bound"] = bool(principal_tenant)
        return next_handler(request)


class RateLimitMiddleware:
    """Per-tenant token bucket rate limiter."""

    def __init__(
        self,
        *,
        requests_per_second: float = 10.0,
        burst: int = 20,
        store: RateLimitStore | None = None,
    ) -> None:
        self._rps = requests_per_second
        self._burst = burst
        self._store = store or InMemoryRateLimitStore()

    def _resolve_bucket_key(self, request: Request) -> str:
        tenant_id = request.context.get("tenant_id")
        if tenant_id:
            return f"tenant:{tenant_id}"
        principal = request.context.get("auth_principal")
        if isinstance(principal, AuthPrincipal):
            return f"subject:{principal.subject}"
        return "default"

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        now = time.monotonic()
        decision = self._store.consume(
            self._resolve_bucket_key(request),
            capacity=self._burst,
            refill_rate=self._rps,
            now=now,
        )
        if not decision.allowed:
            retry_after = max(1, int(decision.retry_after_seconds) or 1)
            return Response(
                status_code=429,
                body={"error": "Rate limit exceeded"},
                headers={
                    "content-type": "application/json",
                    "retry-after": str(retry_after),
                },
            )

        response = next_handler(request)
        response.headers.setdefault("x-ratelimit-limit", str(self._burst))
        response.headers.setdefault(
            "x-ratelimit-remaining",
            str(max(0, int(decision.remaining_tokens))),
        )
        return response


class RequestContextMiddleware:
    """Inject request/correlation IDs and echo them on the response."""

    def __init__(
        self,
        *,
        request_id_header: str = "x-request-id",
        correlation_id_header: str = "x-correlation-id",
    ) -> None:
        self._request_id_header = request_id_header.lower()
        self._correlation_id_header = correlation_id_header.lower()

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        request_id = request.headers.get(self._request_id_header) or uuid.uuid4().hex
        correlation_id = request.headers.get(self._correlation_id_header) or request_id
        request.context.setdefault("request_id", request_id)
        request.context.setdefault("correlation_id", correlation_id)
        request.context.setdefault("request_started_at", time.time())

        response = next_handler(request)
        response.headers.setdefault(self._request_id_header, request_id)
        response.headers.setdefault(self._correlation_id_header, correlation_id)
        return response


_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'",
    "x-xss-protection": "0",
}


class SecurityHeadersMiddleware:
    """Injects standard security response headers."""

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        response = next_handler(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class MiddlewareChain:
    """Convenience builder for chaining multiple middlewares."""

    def __init__(self) -> None:
        self._middlewares: list[Any] = []

    def add(self, middleware: Any) -> MiddlewareChain:
        self._middlewares.append(middleware)
        return self

    @property
    def middlewares(self) -> list[Any]:
        return list(self._middlewares)
