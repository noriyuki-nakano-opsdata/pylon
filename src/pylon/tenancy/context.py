"""Enhanced tenant context propagation via contextvars."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncGenerator, Generator

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


@asynccontextmanager
async def async_tenant_scope(ctx: TenantContext) -> AsyncGenerator[TenantContext, None]:
    token = _current_tenant.set(ctx)
    try:
        yield ctx
    finally:
        _current_tenant.reset(token)


async def run_in_tenant_context(ctx: TenantContext, coro: Any) -> Any:
    """Run a coroutine with tenant context propagated across async tasks."""
    context = copy_context()
    context.run(_current_tenant.set, ctx)

    async def _wrapper() -> Any:
        return await coro

    loop = asyncio.get_running_loop()
    task = loop.create_task(_wrapper(), context=context)
    return await task


def serialize_tenant_context(ctx: TenantContext) -> str:
    """Serialize tenant context for NATS messages."""
    data = {
        "tenant_id": ctx.tenant_id,
        "tenant_name": ctx.tenant_name,
        "tier": ctx.tier.value,
        "limits": {
            "max_agents": ctx.limits.max_agents,
            "max_workflows": ctx.limits.max_workflows,
            "max_memory_mb": ctx.limits.max_memory_mb,
            "max_api_calls_per_hour": ctx.limits.max_api_calls_per_hour,
        },
        "metadata": ctx.metadata,
    }
    return json.dumps(data)


def deserialize_tenant_context(data: str) -> TenantContext:
    """Deserialize tenant context from NATS messages."""
    parsed = json.loads(data)
    return TenantContext(
        tenant_id=parsed["tenant_id"],
        tenant_name=parsed["tenant_name"],
        tier=TenantTier(parsed["tier"]),
        limits=TenantLimits(**parsed["limits"]),
        metadata=parsed.get("metadata", {}),
    )
