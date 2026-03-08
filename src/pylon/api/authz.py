"""Authorization helpers for API route scope enforcement."""

from __future__ import annotations

from collections.abc import Sequence

from pylon.api.middleware import AuthPrincipal
from pylon.api.server import Request, Response


def _scope_matches(granted: str, required: str) -> bool:
    if granted == "*" or granted == required:
        return True
    granted_namespace, granted_sep, granted_action = granted.partition(":")
    required_namespace, required_sep, _required_action = required.partition(":")
    return (
        bool(granted_sep)
        and bool(required_sep)
        and granted_namespace == required_namespace
        and granted_action == "*"
    )


def has_required_scopes(
    principal: AuthPrincipal,
    *,
    any_of: Sequence[str] = (),
    all_of: Sequence[str] = (),
) -> bool:
    scopes = tuple(str(scope) for scope in principal.scopes)
    if any_of:
        if not any(
            any(_scope_matches(granted, required) for granted in scopes)
            for required in any_of
        ):
            return False
    if all_of:
        for required in all_of:
            if not any(_scope_matches(granted, required) for granted in scopes):
                return False
    return True


def require_scopes(
    request: Request,
    *,
    any_of: Sequence[str] = (),
    all_of: Sequence[str] = (),
) -> Response | None:
    """Enforce scopes for authenticated principals.

    If authentication is disabled and no principal is present, authorization is
    skipped to preserve the local/reference deployment mode.
    """

    principal = request.context.get("auth_principal")
    if not isinstance(principal, AuthPrincipal):
        return None
    if has_required_scopes(principal, any_of=any_of, all_of=all_of):
        return None
    required_scopes = [*all_of]
    if any_of:
        required_scopes.extend(scope for scope in any_of if scope not in required_scopes)
    return Response(
        status_code=403,
        body={
            "error": "Insufficient scope",
            "required_scopes": required_scopes,
            "principal_scopes": list(principal.scopes),
        },
    )
