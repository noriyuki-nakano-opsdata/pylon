"""Tests for multi-tenancy hardening."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from pylon.tenancy.config import (
    ConfigStore,
    TenantConfig,
    TenantLimits,
    TenantTier,
    get_global_feature_flags,
    resolve_feature_flags,
    resolve_policies,
    set_global_feature_flags,
    set_global_policies,
)
from pylon.tenancy.context import (
    TenantContext,
    TenantNotSetError,
    async_tenant_scope,
    clear_tenant,
    deserialize_tenant_context,
    get_tenant,
    require_tenant,
    serialize_tenant_context,
    set_tenant,
    tenant_scope,
)
from pylon.tenancy.isolation import (
    CrossTenantAccessError,
    IsolationLevel,
    ResourceType,
    TenantIsolation,
)
from pylon.tenancy.lifecycle import (
    Tenant,
    TenantAlreadyExistsError,
    TenantLifecycleManager,
    TenantNotFoundError,
    TenantStatus,
    TenantStatusError,
)
from pylon.tenancy.quota import (
    QuotaExceededError,
    QuotaManager,
    QuotaResource,
    TenantQuota,
)


# --- Context Propagation Tests ---


class TestTenantContext:
    def test_set_and_get_tenant(self) -> None:
        ctx = TenantContext(tenant_id="t1", tenant_name="Test")
        set_tenant(ctx)
        assert get_tenant() is ctx
        clear_tenant()

    def test_require_tenant_raises_when_not_set(self) -> None:
        clear_tenant()
        with pytest.raises(TenantNotSetError):
            require_tenant()

    def test_tenant_scope_context_manager(self) -> None:
        ctx = TenantContext(tenant_id="t1", tenant_name="Scoped")
        clear_tenant()
        with tenant_scope(ctx) as c:
            assert c.tenant_id == "t1"
            assert get_tenant() is ctx
        assert get_tenant() is None

    @pytest.mark.asyncio
    async def test_async_tenant_scope(self) -> None:
        ctx = TenantContext(tenant_id="t2", tenant_name="AsyncScoped")
        clear_tenant()
        async with async_tenant_scope(ctx) as c:
            assert c.tenant_id == "t2"
            assert get_tenant() is ctx
        assert get_tenant() is None

    def test_serialize_deserialize_context(self) -> None:
        ctx = TenantContext(
            tenant_id="t1",
            tenant_name="Serialized",
            tier=TenantTier.PRO,
            limits=TenantLimits(max_agents=50),
            metadata={"key": "value"},
        )
        serialized = serialize_tenant_context(ctx)
        restored = deserialize_tenant_context(serialized)
        assert restored.tenant_id == ctx.tenant_id
        assert restored.tenant_name == ctx.tenant_name
        assert restored.tier == ctx.tier
        assert restored.limits.max_agents == 50
        assert restored.metadata == {"key": "value"}

    def test_nested_tenant_scopes(self) -> None:
        ctx1 = TenantContext(tenant_id="outer")
        ctx2 = TenantContext(tenant_id="inner")
        clear_tenant()
        with tenant_scope(ctx1):
            assert get_tenant().tenant_id == "outer"
            with tenant_scope(ctx2):
                assert get_tenant().tenant_id == "inner"
            assert get_tenant().tenant_id == "outer"
        assert get_tenant() is None


# --- Data Isolation Tests ---


class TestTenantIsolation:
    def test_register_and_validate_own_resource(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.AGENT, "agent-1")
        assert iso.validate_access("t1", ResourceType.AGENT, "agent-1") is True

    def test_deny_cross_tenant_access(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.AGENT, "agent-1")
        assert iso.validate_access("t2", ResourceType.AGENT, "agent-1") is False

    def test_enforce_access_raises_on_violation(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.WORKFLOW, "wf-1")
        with pytest.raises(CrossTenantAccessError) as exc_info:
            iso.enforce_access("t2", ResourceType.WORKFLOW, "wf-1")
        assert exc_info.value.tenant_id == "t2"

    def test_cross_tenant_allowlist(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.MEMORY, "mem-1")
        iso.allow_cross_tenant("t2", ResourceType.MEMORY, "mem-1")
        assert iso.validate_access("t2", ResourceType.MEMORY, "mem-1") is True
        iso.revoke_cross_tenant("t2", ResourceType.MEMORY, "mem-1")
        assert iso.validate_access("t2", ResourceType.MEMORY, "mem-1") is False

    def test_enforce_isolation_injects_tenant_filter(self) -> None:
        iso = TenantIsolation(level=IsolationLevel.SCHEMA)
        query = {"select": "agents"}
        filtered = iso.enforce_isolation("t1", query)
        assert filtered["tenant_id"] == "t1"
        assert filtered["schema"] == "tenant_t1"

    def test_schema_prefix(self) -> None:
        iso = TenantIsolation()
        assert iso.get_schema_prefix("t1") == "tenant_t1"

    def test_detect_cross_tenant_access(self) -> None:
        iso = TenantIsolation()
        assert iso.detect_cross_tenant_access("t1", {"tenant_id": "t2"}) is True
        assert iso.detect_cross_tenant_access("t1", {"tenant_id": "t1"}) is False
        assert iso.detect_cross_tenant_access("t1", {"schema": "tenant_t2"}) is True
        assert iso.detect_cross_tenant_access("t1", {}) is False

    def test_audit_log_records_breaches(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.AGENT, "a1")
        with pytest.raises(CrossTenantAccessError):
            iso.enforce_access("t2", ResourceType.AGENT, "a1")
        breaches = iso.get_breach_log()
        assert len(breaches) == 1
        assert breaches[0].tenant_id == "t2"
        assert breaches[0].allowed is False

    def test_audit_log_records_allowed_access(self) -> None:
        iso = TenantIsolation()
        iso.register_resource("t1", ResourceType.AGENT, "a1")
        iso.enforce_access("t1", ResourceType.AGENT, "a1")
        log = iso.get_audit_log("t1")
        assert len(log) == 1
        assert log[0].allowed is True


# --- Quota Enforcement Tests ---


class TestQuotaManager:
    def test_set_and_check_quota(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=2))
        assert qm.check_quota("t1", QuotaResource.AGENTS) is True

    def test_quota_exceeded(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=1))
        qm.record_usage("t1", QuotaResource.AGENTS, 1)
        assert qm.check_quota("t1", QuotaResource.AGENTS) is False

    def test_enforce_quota_raises(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=1))
        qm.record_usage("t1", QuotaResource.AGENTS, 1)
        with pytest.raises(QuotaExceededError) as exc_info:
            qm.enforce_quota("t1", QuotaResource.AGENTS)
        assert exc_info.value.tenant_id == "t1"
        assert exc_info.value.resource == QuotaResource.AGENTS

    def test_release_usage(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=2))
        qm.record_usage("t1", QuotaResource.AGENTS, 2)
        assert qm.check_quota("t1", QuotaResource.AGENTS) is False
        qm.release_usage("t1", QuotaResource.AGENTS, 1)
        assert qm.check_quota("t1", QuotaResource.AGENTS) is True

    def test_generate_report(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=10, max_workflows=5))
        qm.record_usage("t1", QuotaResource.AGENTS, 5)
        qm.record_usage("t1", QuotaResource.WORKFLOWS, 5)
        report = qm.generate_report("t1")
        assert report.tenant_id == "t1"
        assert report.utilization["agents"] == 50.0
        assert "workflows" in report.exceeded

    def test_unlimited_quota(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_agents=-1))
        qm.record_usage("t1", QuotaResource.AGENTS, 1000)
        assert qm.check_quota("t1", QuotaResource.AGENTS) is True

    def test_cost_quota(self) -> None:
        qm = QuotaManager()
        qm.set_quota("t1", TenantQuota(max_cost_usd=10.0))
        qm.record_usage("t1", QuotaResource.COST_USD, 10.0)
        assert qm.check_quota("t1", QuotaResource.COST_USD) is False


# --- Tenant Lifecycle Tests ---


class TestTenantLifecycle:
    @pytest.mark.asyncio
    async def test_create_tenant(self) -> None:
        mgr = TenantLifecycleManager()
        tenant = await mgr.create_tenant("t1", "Test Tenant")
        assert tenant.tenant_id == "t1"
        assert tenant.name == "Test Tenant"
        assert tenant.status == TenantStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self) -> None:
        mgr = TenantLifecycleManager()
        await mgr.create_tenant("t1", "First")
        with pytest.raises(TenantAlreadyExistsError):
            await mgr.create_tenant("t1", "Second")

    @pytest.mark.asyncio
    async def test_suspend_and_resume(self) -> None:
        mgr = TenantLifecycleManager()
        await mgr.create_tenant("t1", "Test")
        tenant = await mgr.suspend_tenant("t1", reason="billing")
        assert tenant.status == TenantStatus.SUSPENDED
        assert tenant.suspended_reason == "billing"
        tenant = await mgr.resume_tenant("t1")
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.suspended_reason == ""

    @pytest.mark.asyncio
    async def test_delete_tenant_with_cleanup(self) -> None:
        mgr = TenantLifecycleManager()
        await mgr.create_tenant("t1", "Test")
        tenant = await mgr.delete_tenant("t1")
        assert tenant.status == TenantStatus.DELETED

    @pytest.mark.asyncio
    async def test_invalid_status_transition(self) -> None:
        mgr = TenantLifecycleManager()
        await mgr.create_tenant("t1", "Test")
        await mgr.delete_tenant("t1")
        with pytest.raises(TenantStatusError):
            await mgr.resume_tenant("t1")

    @pytest.mark.asyncio
    async def test_lifecycle_hooks(self) -> None:
        mgr = TenantLifecycleManager()
        events: list[str] = []
        mgr.register_hook("create", lambda tid, action, t: events.append(f"created:{tid}"))
        mgr.register_hook("suspend", lambda tid, action, t: events.append(f"suspended:{tid}"))
        await mgr.create_tenant("t1", "Hooked")
        await mgr.suspend_tenant("t1", "test")
        assert events == ["created:t1", "suspended:t1"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant(self) -> None:
        mgr = TenantLifecycleManager()
        with pytest.raises(TenantNotFoundError):
            mgr.get_tenant("nonexistent")

    @pytest.mark.asyncio
    async def test_list_tenants_by_status(self) -> None:
        mgr = TenantLifecycleManager()
        await mgr.create_tenant("t1", "Active")
        await mgr.create_tenant("t2", "ToBeSuspended")
        await mgr.suspend_tenant("t2", "reason")
        active = mgr.list_tenants(status=TenantStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].tenant_id == "t1"


# --- Config Feature Flags & Policy Tests ---


class TestTenantConfigEnhanced:
    def test_feature_flag_inheritance(self) -> None:
        set_global_feature_flags({"feature_a": True, "feature_b": False})
        config = TenantConfig(
            tenant_id="t1",
            feature_flags={"feature_b": True, "feature_c": True},
        )
        resolved = resolve_feature_flags(config)
        assert resolved["feature_a"] is True
        assert resolved["feature_b"] is True  # tenant overrides global
        assert resolved["feature_c"] is True
        # cleanup
        set_global_feature_flags({})

    def test_policy_override_inheritance(self) -> None:
        set_global_policies({"max_retries": 3, "timeout": 30})
        config = TenantConfig(
            tenant_id="t1",
            policy_overrides={"timeout": 60},
        )
        resolved = resolve_policies(config)
        assert resolved["max_retries"] == 3
        assert resolved["timeout"] == 60  # tenant overrides global
        # cleanup
        set_global_policies({})
