"""OAuth 2.1 + PKCE authentication for MCP with scoped access control."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

# Scope hierarchy: admin > write > read
SCOPE_HIERARCHY: dict[str, list[str]] = {
    "admin": [
        "tools:read", "tools:call",
        "resources:read", "resources:write", "resources:subscribe",
        "prompts:read", "prompts:execute",
        "sampling:create",
    ],
    "write": [
        "tools:read", "tools:call",
        "resources:read", "resources:write",
        "prompts:read", "prompts:execute",
        "sampling:create",
    ],
    "read": [
        "tools:read",
        "resources:read",
        "prompts:read",
    ],
}

ALL_SCOPES = [
    "tools:read", "tools:call",
    "resources:read", "resources:write", "resources:subscribe",
    "prompts:read", "prompts:execute",
    "sampling:create",
]

# Map MCP methods to required scopes
METHOD_SCOPES: dict[str, str] = {
    "tools/list": "tools:read",
    "tools/call": "tools:call",
    "resources/list": "resources:read",
    "resources/read": "resources:read",
    "resources/subscribe": "resources:subscribe",
    "resources/templates/list": "resources:read",
    "prompts/list": "prompts:read",
    "prompts/get": "prompts:execute",
    "sampling/createMessage": "sampling:create",
}


def expand_scopes(scopes: list[str]) -> set[str]:
    """Expand hierarchical scopes into their constituent permissions."""
    result: set[str] = set()
    for scope in scopes:
        if scope in SCOPE_HIERARCHY:
            result.update(SCOPE_HIERARCHY[scope])
        else:
            result.add(scope)
    return result


def check_scope(required: str, granted: list[str]) -> bool:
    """Check if the required scope is covered by the granted scopes."""
    expanded = expand_scopes(granted)
    return required in expanded


@dataclass
class OAuthClientConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)


@dataclass
class PKCEChallenge:
    code_verifier: str = ""
    code_challenge: str = ""
    code_challenge_method: str = "S256"

    @staticmethod
    def generate() -> PKCEChallenge:
        verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return PKCEChallenge(
            code_verifier=verifier,
            code_challenge=challenge,
            code_challenge_method="S256",
        )

    def verify(self, verifier: str) -> bool:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(expected, self.code_challenge)


@dataclass
class AuthorizationCode:
    code: str = ""
    client_id: str = ""
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)
    code_challenge: str = ""
    code_challenge_method: str = "S256"
    created_at: float = field(default_factory=time.time)
    expires_in: int = 300


@dataclass
class TokenResponse:
    access_token: str = ""
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str = ""
    scope: str = ""


@dataclass
class OAuthServerConfig:
    issuer: str = ""
    authorization_endpoint: str = "/oauth/authorize"
    token_endpoint: str = "/oauth/token"
    registration_endpoint: str | None = None
    scopes_supported: list[str] = field(default_factory=lambda: list(ALL_SCOPES))
    response_types_supported: list[str] = field(default_factory=lambda: ["code"])
    grant_types_supported: list[str] = field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )
    code_challenge_methods_supported: list[str] = field(default_factory=lambda: ["S256"])
    dcr_enabled: bool = False


class OAuthProvider:
    """OAuth 2.1 + PKCE provider with scope-based access control."""

    def __init__(self, config: OAuthServerConfig | None = None) -> None:
        self.config = config or OAuthServerConfig()
        self._clients: dict[str, OAuthClientConfig] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._refresh_tokens: dict[str, str] = {}

    def register_client(self, client: OAuthClientConfig) -> None:
        self._clients[client.client_id] = client

    def get_client(self, client_id: str) -> OAuthClientConfig | None:
        return self._clients.get(client_id)

    def create_authorization_code(
        self,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str = "S256",
    ) -> str | None:
        client = self._clients.get(client_id)
        if client is None:
            return None
        if code_challenge_method != "S256":
            return None
        if client.redirect_uri and client.redirect_uri != redirect_uri:
            return None

        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
        return code

    def exchange_code(
        self,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenResponse | None:
        auth_code = self._auth_codes.pop(code, None)
        if auth_code is None:
            return None
        if auth_code.client_id != client_id:
            return None
        if auth_code.redirect_uri != redirect_uri:
            return None
        if time.time() - auth_code.created_at > auth_code.expires_in:
            return None

        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        if not secrets.compare_digest(expected, auth_code.code_challenge):
            return None

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        scope = " ".join(auth_code.scopes)

        self._tokens[access_token] = {
            "client_id": client_id,
            "scopes": auth_code.scopes,
            "created_at": time.time(),
            "expires_in": 3600,
        }
        self._refresh_tokens[refresh_token] = access_token

        return TokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh_token,
            scope=scope,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResponse | None:
        old_access = self._refresh_tokens.pop(refresh_token, None)
        if old_access is None:
            return None

        old_meta = self._tokens.pop(old_access, None)
        if old_meta is None:
            return None

        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)

        self._tokens[new_access] = {
            "client_id": old_meta["client_id"],
            "scopes": old_meta["scopes"],
            "created_at": time.time(),
            "expires_in": 3600,
        }
        self._refresh_tokens[new_refresh] = new_access

        return TokenResponse(
            access_token=new_access,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=new_refresh,
            scope=" ".join(old_meta["scopes"]),
        )

    def validate_token(self, access_token: str) -> dict[str, Any] | None:
        meta = self._tokens.get(access_token)
        if meta is None:
            return None
        if time.time() - meta["created_at"] > meta["expires_in"]:
            del self._tokens[access_token]
            return None
        return meta

    def validate_token_scope(
        self, access_token: str, required_scope: str
    ) -> dict[str, Any] | None:
        """Validate token and check that it has the required scope."""
        meta = self.validate_token(access_token)
        if meta is None:
            return None
        if not check_scope(required_scope, meta["scopes"]):
            return None
        return meta

    def revoke_token(self, access_token: str) -> bool:
        if access_token in self._tokens:
            del self._tokens[access_token]
            to_remove = [k for k, v in self._refresh_tokens.items() if v == access_token]
            for k in to_remove:
                del self._refresh_tokens[k]
            return True
        return False

    def dynamic_client_registration(
        self, redirect_uris: list[str], scope: str = ""
    ) -> OAuthClientConfig | None:
        if not self.config.dcr_enabled:
            return None
        client_id = secrets.token_urlsafe(16)
        client_secret = secrets.token_urlsafe(32)
        scopes = scope.split() if scope else []
        # Validate requested scopes against server-supported scopes
        if scopes and self.config.scopes_supported:
            allowed = set(self.config.scopes_supported) | set(SCOPE_HIERARCHY.keys())
            invalid = set(scopes) - allowed
            if invalid:
                return None
        client = OAuthClientConfig(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uris[0] if redirect_uris else "",
            scopes=scopes,
        )
        self._clients[client_id] = client
        return client
