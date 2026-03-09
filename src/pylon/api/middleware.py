"""API middleware: authentication, tenant isolation, rate limiting, security headers."""

from __future__ import annotations

import base64
import enum
import hashlib
import hmac
import json
import logging
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
from urllib import request as urllib_request

from pylon.api.server import HandlerFunc, Request, Response
from pylon.observability.exporters import ExporterProtocol
from pylon.observability.logging import StructuredLogger
from pylon.observability.metrics import MetricsCollector
from pylon.observability.tracing import SpanStatus, Tracer

logger = logging.getLogger(__name__)

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LIVENESS_BYPASS_PATHS = frozenset({"/health", "/ready"})
_TENANT_BYPASS_PATHS = frozenset({"/health", "/ready", "/metrics"})


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


def _decode_jwt_bytes(part: str) -> bytes:
    padded = part + "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _validate_jwt_claims(
    payload: dict[str, Any],
    *,
    issuer: str | None,
    audience: Sequence[str],
    leeway_seconds: float,
    now: float,
) -> None:
    if issuer is not None and payload.get("iss") != issuer:
        raise TokenVerificationError("Invalid token issuer")

    if audience:
        token_aud = payload.get("aud")
        if isinstance(token_aud, str):
            token_audiences = {token_aud}
        elif isinstance(token_aud, Sequence):
            token_audiences = {str(item) for item in token_aud}
        else:
            token_audiences = set()
        if not token_audiences.intersection(audience):
            raise TokenVerificationError("Invalid token audience")

    exp = payload.get("exp")
    if exp is not None and float(exp) + leeway_seconds < now:
        raise TokenVerificationError("Token has expired")

    nbf = payload.get("nbf")
    if nbf is not None and float(nbf) - leeway_seconds > now:
        raise TokenVerificationError("Token not yet valid")

    iat = payload.get("iat")
    if iat is not None and float(iat) - leeway_seconds > now:
        raise TokenVerificationError("Token issued in the future")


def _extract_jwt_scopes(payload: dict[str, Any], scopes_claim: str) -> tuple[str, ...]:
    scopes_value = payload.get(scopes_claim, ())
    if isinstance(scopes_value, str):
        return tuple(scope for scope in scopes_value.split(" ") if scope)
    if isinstance(scopes_value, Sequence):
        return tuple(str(scope) for scope in scopes_value)
    return ()


def _build_jwt_principal(
    payload: dict[str, Any],
    *,
    tenant_claim: str,
    subject_claim: str,
    scopes_claim: str,
) -> AuthPrincipal:
    subject = payload.get(subject_claim)
    if not subject:
        raise TokenVerificationError("JWT subject claim is required")
    tenant_value = payload.get(tenant_claim)
    tenant_id = str(tenant_value) if tenant_value is not None else None
    token_id = payload.get("jti")
    return AuthPrincipal(
        subject=str(subject),
        tenant_id=tenant_id,
        scopes=_extract_jwt_scopes(payload, scopes_claim),
        token_id=str(token_id) if token_id is not None else None,
        claims=dict(payload),
    )


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

    def verify(self, token: str) -> AuthPrincipal:
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenVerificationError("Invalid JWT structure")
        header = _decode_jwt_part(parts[0])
        payload = _decode_jwt_part(parts[1])
        if header.get("alg") != "HS256":
            raise TokenVerificationError("Unsupported JWT algorithm")
        self._verify_signature(parts[0], parts[1], parts[2])
        _validate_jwt_claims(
            payload,
            issuer=self._issuer,
            audience=self._audience,
            leeway_seconds=self._leeway_seconds,
            now=time.time(),
        )
        return _build_jwt_principal(
            payload,
            tenant_claim=self._tenant_claim,
            subject_claim=self._subject_claim,
            scopes_claim=self._scopes_claim,
        )


class JWKSTokenVerifier(TokenVerifier):
    """RS256/RS384/RS512 JWT verifier backed by a JWKS document."""

    def __init__(
        self,
        *,
        jwks: dict[str, Any] | str | Path | None = None,
        oidc_discovery: str | Path | None = None,
        issuer: str | None = None,
        audience: Sequence[str] = (),
        tenant_claim: str = "tenant_id",
        subject_claim: str = "sub",
        scopes_claim: str = "scope",
        leeway_seconds: float = 0.0,
        cache_ttl_seconds: float = 300.0,
        allow_insecure_http: bool = False,
    ) -> None:
        if (jwks is None) == (oidc_discovery is None):
            raise ValueError("Specify exactly one of jwks or oidc_discovery")
        self._jwks = jwks
        self._oidc_discovery = oidc_discovery
        self._issuer = issuer
        self._audience = tuple(str(item) for item in audience)
        self._tenant_claim = tenant_claim
        self._subject_claim = subject_claim
        self._scopes_claim = scopes_claim
        self._leeway_seconds = float(leeway_seconds)
        self._cache_ttl_seconds = max(float(cache_ttl_seconds), 0.0)
        self._allow_insecure_http = bool(allow_insecure_http)
        self._cached_jwks: dict[str, Any] | None = None
        self._cached_metadata: dict[str, Any] | None = None
        self._cached_at: float = 0.0

    def _validate_source_policy(self, source: str | Path, *, label: str) -> None:
        source_str = str(source)
        if source_str.startswith("http://") and not self._allow_insecure_http:
            raise TokenVerificationError(
                f"{label} must use https unless allow_insecure_http=true"
            )

    def _load_json_document(
        self,
        source: str | Path,
        *,
        label: str,
    ) -> dict[str, Any]:
        source_str = str(source)
        self._validate_source_policy(source_str, label=label)
        if source_str.startswith(("http://", "https://")):
            with urllib_request.urlopen(source_str, timeout=10.0) as response:  # noqa: S310
                payload = json.load(response)
        else:
            with Path(source_str).open(encoding="utf-8") as fh:
                payload = json.load(fh)
        if not isinstance(payload, dict):
            raise TokenVerificationError(f"{label} document must be a JSON object")
        return payload

    def _load_oidc_metadata(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if self._oidc_discovery is None:
            raise TokenVerificationError("OIDC discovery source is not configured")
        now = time.time()
        if (
            not force_refresh
            and self._cached_metadata is not None
            and (now - self._cached_at) < self._cache_ttl_seconds
        ):
            return dict(self._cached_metadata)
        payload = self._load_json_document(self._oidc_discovery, label="OIDC discovery")
        self._cached_metadata = dict(payload)
        self._cached_at = now
        return dict(payload)

    def _resolve_issuer(self, metadata: dict[str, Any] | None) -> str | None:
        metadata_issuer = None
        if isinstance(metadata, dict):
            raw_issuer = metadata.get("issuer")
            metadata_issuer = str(raw_issuer) if raw_issuer is not None else None
        if (
            self._issuer is not None
            and metadata_issuer is not None
            and self._issuer != metadata_issuer
        ):
            raise TokenVerificationError("OIDC discovery issuer does not match configured issuer")
        return self._issuer or metadata_issuer

    def _load_jwks(self, *, force_refresh: bool = False) -> tuple[dict[str, Any], str | None]:
        if isinstance(self._jwks, dict):
            payload = dict(self._jwks)
            self._validate_jwks_document(payload)
            return payload, self._issuer
        now = time.time()
        if (
            not force_refresh
            and self._cached_jwks is not None
            and (now - self._cached_at) < self._cache_ttl_seconds
        ):
            return dict(self._cached_jwks), self._resolve_issuer(self._cached_metadata)
        metadata: dict[str, Any] | None = None
        if self._oidc_discovery is not None:
            metadata = self._load_oidc_metadata(force_refresh=force_refresh)
            jwks_uri = metadata.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not jwks_uri:
                raise TokenVerificationError("OIDC discovery document is missing jwks_uri")
            payload = self._load_json_document(jwks_uri, label="JWKS")
        else:
            assert self._jwks is not None
            payload = self._load_json_document(self._jwks, label="JWKS")
        self._validate_jwks_document(payload)
        self._cached_jwks = dict(payload)
        if force_refresh or metadata is None:
            self._cached_at = now
        resolved_issuer = self._resolve_issuer(metadata)
        return dict(payload), resolved_issuer

    def _supports_refresh(self) -> bool:
        return not isinstance(self._jwks, dict)

    def _validate_jwks_document(self, jwks: dict[str, Any]) -> None:
        keys = jwks.get("keys", ())
        if not isinstance(keys, list) or not keys:
            raise TokenVerificationError("JWKS document does not contain any keys")

    def _invalidate_cache(self) -> None:
        self._cached_jwks = None
        self._cached_metadata = None
        self._cached_at = 0.0

    def _is_refreshable_failure(self, exc: TokenVerificationError) -> bool:
        message = str(exc)
        return message in {
            "JWT signing key not found in JWKS",
            "Invalid token signature",
        }

    def _verify_with_keyset(
        self,
        header: dict[str, Any],
        header_b64: str,
        payload_b64: str,
        signature_b64: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        jwks, resolved_issuer = self._load_jwks(force_refresh=force_refresh)
        jwk = self._select_jwk(header, jwks)
        self._verify_signature(header, header_b64, payload_b64, signature_b64, jwk)
        return jwks, resolved_issuer

    def _verify_signature_with_refresh(
        self,
        header: dict[str, Any],
        header_b64: str,
        payload_b64: str,
        signature_b64: str,
    ) -> str | None:
        try:
            _jwks, resolved_issuer = self._verify_with_keyset(
                header,
                header_b64,
                payload_b64,
                signature_b64,
            )
            return resolved_issuer
        except TokenVerificationError as exc:
            if not self._supports_refresh() or not self._is_refreshable_failure(exc):
                raise
            self._invalidate_cache()
            try:
                _jwks, resolved_issuer = self._verify_with_keyset(
                    header,
                    header_b64,
                    payload_b64,
                    signature_b64,
                    force_refresh=True,
                )
                return resolved_issuer
            except TokenVerificationError as refresh_exc:
                if str(exc) == "JWT signing key not found in JWKS":
                    raise TokenVerificationError(
                        "JWT signing key not found after JWKS refresh"
                    ) from refresh_exc
                if str(exc) == "Invalid token signature":
                    raise TokenVerificationError(
                        "Invalid token signature after JWKS refresh"
                    ) from refresh_exc
                raise

    def _select_jwk(self, header: dict[str, Any], jwks: dict[str, Any]) -> dict[str, Any]:
        keys = jwks.get("keys", ())
        if not isinstance(keys, list) or not keys:
            raise TokenVerificationError("JWKS document does not contain any keys")
        kid = header.get("kid")
        if kid:
            for key in keys:
                if isinstance(key, dict) and key.get("kid") == kid:
                    return key
            raise TokenVerificationError("JWT signing key not found in JWKS")
        if len(keys) == 1 and isinstance(keys[0], dict):
            return keys[0]
        raise TokenVerificationError("JWT header is missing kid for multi-key JWKS")

    def _verify_signature(
        self,
        header: dict[str, Any],
        header_b64: str,
        payload_b64: str,
        signature_b64: str,
        jwk: dict[str, Any],
    ) -> None:
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise TokenVerificationError(
                "JWKSTokenVerifier requires the 'cryptography' package"
            ) from exc
        if jwk.get("kty") != "RSA":
            raise TokenVerificationError("JWKS verifier supports only RSA keys")
        algorithm = str(header.get("alg", ""))
        hash_map = {
            "RS256": hashes.SHA256,
            "RS384": hashes.SHA384,
            "RS512": hashes.SHA512,
        }
        hash_cls = hash_map.get(algorithm)
        if hash_cls is None:
            raise TokenVerificationError("Unsupported JWKS JWT algorithm")
        modulus_b64 = jwk.get("n")
        exponent_b64 = jwk.get("e")
        if not isinstance(modulus_b64, str) or not isinstance(exponent_b64, str):
            raise TokenVerificationError("JWKS RSA key must include 'n' and 'e'")
        modulus = int.from_bytes(_decode_jwt_bytes(modulus_b64), "big")
        exponent = int.from_bytes(_decode_jwt_bytes(exponent_b64), "big")
        public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = _decode_jwt_bytes(signature_b64)
        try:
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hash_cls())
        except Exception as exc:  # pragma: no cover - cryptography error surface
            raise TokenVerificationError("Invalid token signature") from exc

    def verify(self, token: str) -> AuthPrincipal:
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenVerificationError("Invalid JWT structure")
        header = _decode_jwt_part(parts[0])
        payload = _decode_jwt_part(parts[1])
        resolved_issuer = self._verify_signature_with_refresh(
            header,
            parts[0],
            parts[1],
            parts[2],
        )
        _validate_jwt_claims(
            payload,
            issuer=resolved_issuer,
            audience=self._audience,
            leeway_seconds=self._leeway_seconds,
            now=time.time(),
        )
        return _build_jwt_principal(
            payload,
            tenant_claim=self._tenant_claim,
            subject_claim=self._subject_claim,
            scopes_claim=self._scopes_claim,
        )

    def prime(self) -> None:
        """Eagerly validate source reachability and trust bootstrap."""
        self._load_jwks(force_refresh=True)


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of a rate-limit consume attempt."""

    allowed: bool
    remaining_tokens: float
    retry_after_seconds: float = 0.0


class RateLimitBucketScope(enum.StrEnum):
    TENANT = "tenant"
    SUBJECT = "subject"
    TOKEN = "token"
    TENANT_SUBJECT = "tenant_subject"
    GLOBAL = "global"


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


class RedisRateLimitStore(RateLimitStore):
    """Redis-backed token-bucket store shared across processes or hosts."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: Any | None = None,
        key_prefix: str = "pylon:rate_limit",
        max_retries: int = 5,
    ) -> None:
        if client is None and not url:
            raise ValueError("RedisRateLimitStore requires either url or client")
        self._client = client or self._build_client(url)
        self._key_prefix = key_prefix.rstrip(":")
        self._max_retries = max(int(max_retries), 1)
        self._watch_error = self._resolve_watch_error()

    def _build_client(self, url: str | None) -> Any:
        assert url is not None
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "RedisRateLimitStore requires the 'redis' package"
            ) from exc
        return redis.Redis.from_url(url, decode_responses=True)

    def _resolve_watch_error(self) -> type[Exception]:
        try:
            import redis
        except ImportError:  # pragma: no cover - dependency guard
            return RuntimeError
        return redis.WatchError

    def _bucket_key(self, bucket_key: str) -> str:
        return f"{self._key_prefix}:{bucket_key}"

    def consume(
        self,
        bucket_key: str,
        *,
        capacity: int,
        refill_rate: float,
        now: float,
    ) -> RateLimitDecision:
        redis_key = self._bucket_key(bucket_key)
        for _attempt in range(self._max_retries):
            pipe = self._client.pipeline()
            try:
                pipe.watch(redis_key)
                row = pipe.hgetall(redis_key) or {}
                if row:
                    bucket = _TokenBucket(
                        capacity=capacity,
                        tokens=float(row.get("tokens", capacity)),
                        refill_rate=refill_rate,
                        last_refill=float(row.get("last_refill", now)),
                    )
                else:
                    bucket = _TokenBucket(
                        capacity=capacity,
                        tokens=float(capacity),
                        refill_rate=refill_rate,
                        last_refill=now,
                    )
                decision = bucket.consume(now)
                pipe.multi()
                pipe.hset(
                    redis_key,
                    mapping={
                        "tokens": bucket.tokens,
                        "last_refill": bucket.last_refill,
                    },
                )
                pipe.execute()
                return decision
            except self._watch_error:
                continue
            finally:
                pipe.reset()
        raise RuntimeError("Failed to update Redis rate-limit bucket after retries")


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
        if request.path in _LIVENESS_BYPASS_PATHS:
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
        if request.path in _TENANT_BYPASS_PATHS:
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
    """Configurable token-bucket rate limiter."""

    def __init__(
        self,
        *,
        requests_per_second: float = 10.0,
        burst: int = 20,
        store: RateLimitStore | None = None,
        bucket_scope: RateLimitBucketScope | str = RateLimitBucketScope.TENANT,
    ) -> None:
        self._rps = requests_per_second
        self._burst = burst
        self._store = store or InMemoryRateLimitStore()
        self._bucket_scope = (
            bucket_scope
            if isinstance(bucket_scope, RateLimitBucketScope)
            else RateLimitBucketScope(str(bucket_scope))
        )

    def _resolve_bucket_key(self, request: Request) -> str:
        tenant_id = request.context.get("tenant_id")
        principal = request.context.get("auth_principal")
        token_hash = request.context.get("token_hash")
        subject = principal.subject if isinstance(principal, AuthPrincipal) else None

        if self._bucket_scope is RateLimitBucketScope.GLOBAL:
            return "global"
        if self._bucket_scope is RateLimitBucketScope.TOKEN:
            if token_hash:
                return f"token:{token_hash}"
            if subject:
                return f"subject:{subject}"
            if tenant_id:
                return f"tenant:{tenant_id}"
            return "default"
        if self._bucket_scope is RateLimitBucketScope.SUBJECT:
            if subject:
                return f"subject:{subject}"
            if tenant_id:
                return f"tenant:{tenant_id}"
            return "default"
        if self._bucket_scope is RateLimitBucketScope.TENANT_SUBJECT:
            if tenant_id and subject:
                return f"tenant_subject:{tenant_id}:{subject}"
            if tenant_id:
                return f"tenant:{tenant_id}"
            if subject:
                return f"subject:{subject}"
            return "default"
        if tenant_id:
            return f"tenant:{tenant_id}"
        if subject:
            return f"subject:{subject}"
        return "default"

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        if request.path in _TENANT_BYPASS_PATHS:
            return next_handler(request)
        now = time.time()
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
        response.headers.setdefault("x-ratelimit-scope", self._bucket_scope.value)
        return response


class RequestTelemetryMiddleware:
    """Collect low-cardinality API request metrics and trace spans."""

    def __init__(
        self,
        *,
        metrics: MetricsCollector,
        tracer: Tracer | None = None,
        logger: StructuredLogger | None = None,
        exporters: Sequence[ExporterProtocol] = (),
    ) -> None:
        self._metrics = metrics
        self._tracer = tracer
        self._logger = logger
        self._exporters = tuple(exporters)
        self._lock = threading.Lock()
        self._in_flight = 0

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        if request.path in _TENANT_BYPASS_PATHS:
            return next_handler(request)

        method = request.method.upper()
        route = str(request.context.get("route_template") or request.path)
        request_id = str(request.context.get("request_id", ""))
        correlation_id = str(request.context.get("correlation_id", ""))
        base_labels = {"method": method, "route": route}
        started_at = time.time()
        self._adjust_in_flight(delta=1)
        span = None
        if self._tracer is not None:
            span = self._tracer.start_span(
                "api.request",
                attributes={
                    "http.method": method,
                    "http.route": route,
                    "request.id": request_id,
                    "correlation.id": correlation_id,
                },
            )
            request.context["trace_id"] = span.trace_id
        try:
            response = next_handler(request)
        except Exception as exc:
            elapsed = time.time() - started_at
            error_labels = {**base_labels, "status_class": "5xx"}
            self._metrics.counter("api_request_count", 1, labels=error_labels)
            self._metrics.counter("api_request_error_count", 1, labels=error_labels)
            self._metrics.histogram(
                "api_request_duration_seconds",
                elapsed,
                labels=error_labels,
            )
            self._adjust_in_flight(delta=-1)
            if span is not None:
                span.set_attribute("http.status_code", 500)
                span.set_attribute("error.type", exc.__class__.__name__)
                span.add_event("exception", {"message": str(exc)})
                try:
                    self._tracer.end_span(span.span_id, status=SpanStatus.ERROR)
                    self._export_current_snapshot(span)
                except Exception:
                    logger.warning(
                        "instrumentation failure in end_span/export",
                        exc_info=True,
                    )
            if self._logger is not None:
                self._logger.error(
                    "api request failed",
                    method=method,
                    route=route,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=str(request.context.get("trace_id", "")),
                    error_type=exc.__class__.__name__,
                )
            raise

        elapsed = time.time() - started_at
        status_code = int(response.status_code)
        result_labels = {**base_labels, "status_class": f"{status_code // 100}xx"}
        self._metrics.counter("api_request_count", 1, labels=result_labels)
        self._metrics.histogram(
            "api_request_duration_seconds",
            elapsed,
            labels=result_labels,
        )
        if status_code >= 500:
            self._metrics.counter("api_request_error_count", 1, labels=result_labels)
        self._adjust_in_flight(delta=-1)
        if span is not None:
            span.set_attribute("http.status_code", status_code)
            tenant_id = request.context.get("tenant_id")
            if tenant_id:
                span.set_attribute("tenant.id", str(tenant_id))
            try:
                self._tracer.end_span(
                    span.span_id,
                    status=SpanStatus.ERROR if status_code >= 500 else SpanStatus.OK,
                )
                self._export_current_snapshot(span)
            except Exception:
                logger.warning(
                    "instrumentation failure in end_span/export",
                    exc_info=True,
                )
        if self._logger is not None:
            self._logger.info(
                "api request completed",
                method=method,
                route=route,
                status_code=status_code,
                request_id=request_id,
                correlation_id=correlation_id,
                trace_id=str(request.context.get("trace_id", "")),
            )
        return response

    def _export_current_snapshot(self, span: Any) -> None:
        snapshot = self._metrics.get_metrics()
        for exporter in self._exporters:
            exporter.export_metrics(snapshot)
            exporter.export_span(span)

    def _adjust_in_flight(self, *, delta: int) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight + delta)
            current = float(self._in_flight)
        self._metrics.gauge("api_requests_in_flight", current)


class RequestContextMiddleware:
    """Inject request/correlation IDs and echo them on the response."""

    def __init__(
        self,
        *,
        request_id_header: str = "x-request-id",
        correlation_id_header: str = "x-correlation-id",
        trace_id_header: str = "x-trace-id",
    ) -> None:
        self._request_id_header = request_id_header.lower()
        self._correlation_id_header = correlation_id_header.lower()
        self._trace_id_header = trace_id_header.lower()

    def __call__(self, request: Request, next_handler: HandlerFunc) -> Response:
        request_id = request.headers.get(self._request_id_header) or uuid.uuid4().hex
        correlation_id = request.headers.get(self._correlation_id_header) or request_id
        request.context.setdefault("request_id", request_id)
        request.context.setdefault("correlation_id", correlation_id)
        request.context.setdefault("request_started_at", time.time())

        response = next_handler(request)
        response.headers.setdefault(self._request_id_header, request_id)
        response.headers.setdefault(self._correlation_id_header, correlation_id)
        trace_id = request.context.get("trace_id")
        if trace_id:
            response.headers.setdefault(self._trace_id_header, str(trace_id))
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
