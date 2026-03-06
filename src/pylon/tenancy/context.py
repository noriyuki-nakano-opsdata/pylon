"""Tenant context propagation via contextvars."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Generator

from pylon.tenancy.config import TenantLimits, TenantTier


@dataclass
class TenantContext:
    tenant_id: str = ""
    tenant_name: str = ""
    tier: TenantTier = TenantTier.FREE
    limits: TenantLimits = field(default_factory=TenantLimits)
    metadata: dict[str, Any] = field(default_factory=dict)


_current_tenant: ContextVar[TenantContext | None] = ContextVar(
    "current_tenant", default=None
)


class TenantNotSetError(RuntimeError):
    """Raised when tenant context is required but not set."""


def set_tenant(ctx: TenantContext) -> None:
    _current_tenant.set(ctx)


def get_tenant() -> TenantContext | None:
    return _current_tenant.get()


def require_tenant() -> TenantContext:
    ctx = _current_tenant.get()
    if ctx is None:
        raise TenantNotSetError("Tenant context is not set")
    return ctx


def clear_tenant() -> None:
    _current_tenant.set(None)


@contextmanager
def tenant_scope(ctx: TenantContext) -> Generator[TenantContext, None, None]:
    token = _current_tenant.set(ctx)
    try:
        yield ctx
    finally:
        _current_tenant.reset(token)
