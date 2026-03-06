"""Tests for multi-tenancy module."""

from __future__ import annotations

import base64
import json
import unittest

from pylon.tenancy import (
    ConfigStore,
    CrossTenantAccessError,
    HeaderTenantResolver,
    IsolationLevel,
    ResourceType,
    TenantConfig,
    TenantContext,
    TenantDirectory,
    TenantIsolation,
    TenantLimits,
    TenantMiddleware,
    TenantNotFoundError,
    TenantNotSetError,
    TenantTier,
    TIER_DEFAULTS,
    TokenTenantResolver,
    clear_tenant,
    get_tenant,
    get_tier_defaults,
    require_tenant,
    set_tenant,
    tenant_scope,
)


def _make_ctx(tenant_id: str = "t1", tier: TenantTier = TenantTier.FREE) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name=f"Tenant {tenant_id}",
        tier=tier,
        limits=get_tier_defaults(tier),
    )


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


# --- Context ---

class TestTenantContext(unittest.TestCase):
    def tearDown(self):
        clear_tenant()

    def test_default_not_set(self):
        self.assertIsNone(get_tenant())

    def test_set_and_get(self):
        ctx = _make_ctx()
        set_tenant(ctx)
        self.assertEqual(get_tenant().tenant_id, "t1")

    def test_require_when_set(self):
        ctx = _make_ctx()
        set_tenant(ctx)
        result = require_tenant()
        self.assertEqual(result.tenant_id, "t1")

    def test_require_when_not_set(self):
        with self.assertRaises(TenantNotSetError):
            require_tenant()

    def test_clear(self):
        set_tenant(_make_ctx())
        clear_tenant()
        self.assertIsNone(get_tenant())

    def test_scope_sets_and_restores(self):
        outer = _make_ctx("outer")
        set_tenant(outer)
        inner = _make_ctx("inner")
        with tenant_scope(inner) as ctx:
            self.assertEqual(ctx.tenant_id, "inner")
            self.assertEqual(get_tenant().tenant_id, "inner")
        self.assertEqual(get_tenant().tenant_id, "outer")

    def test_scope_restores_none(self):
        with tenant_scope(_make_ctx("scoped")):
            self.assertEqual(get_tenant().tenant_id, "scoped")
        self.assertIsNone(get_tenant())

    def test_nested_scopes(self):
        with tenant_scope(_make_ctx("level1")):
            self.assertEqual(get_tenant().tenant_id, "level1")
            with tenant_scope(_make_ctx("level2")):
                self.assertEqual(get_tenant().tenant_id, "level2")
                with tenant_scope(_make_ctx("level3")):
                    self.assertEqual(get_tenant().tenant_id, "level3")
                self.assertEqual(get_tenant().tenant_id, "level2")
            self.assertEqual(get_tenant().tenant_id, "level1")
        self.assertIsNone(get_tenant())

    def test_context_metadata(self):
        ctx = TenantContext(tenant_id="m1", metadata={"region": "us-west"})
        self.assertEqual(ctx.metadata["region"], "us-west")

    def test_context_tier_default(self):
        ctx = TenantContext()
        self.assertEqual(ctx.tier, TenantTier.FREE)


# --- Isolation ---

class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.iso = TenantIsolation(level=IsolationLevel.SCHEMA)

    def test_unregistered_resource_accessible(self):
        self.assertTrue(
            self.iso.validate_access("t1", ResourceType.AGENT, "unknown-agent")
        )

    def test_owner_can_access(self):
        self.iso.register_resource("t1", ResourceType.AGENT, "agent-1")
        self.assertTrue(self.iso.validate_access("t1", ResourceType.AGENT, "agent-1"))

    def test_non_owner_denied(self):
        self.iso.register_resource("t1", ResourceType.AGENT, "agent-1")
        self.assertFalse(self.iso.validate_access("t2", ResourceType.AGENT, "agent-1"))

    def test_enforce_raises(self):
        self.iso.register_resource("t1", ResourceType.WORKFLOW, "wf-1")
        with self.assertRaises(CrossTenantAccessError) as cm:
            self.iso.enforce_access("t2", ResourceType.WORKFLOW, "wf-1")
        self.assertEqual(cm.exception.tenant_id, "t2")

    def test_cross_tenant_allowlist(self):
        self.iso.register_resource("t1", ResourceType.MEMORY, "mem-shared")
        self.iso.allow_cross_tenant("t2", ResourceType.MEMORY, "mem-shared")
        self.assertTrue(self.iso.validate_access("t2", ResourceType.MEMORY, "mem-shared"))

    def test_revoke_cross_tenant(self):
        self.iso.register_resource("t1", ResourceType.MEMORY, "mem-shared")
        self.iso.allow_cross_tenant("t2", ResourceType.MEMORY, "mem-shared")
        self.iso.revoke_cross_tenant("t2", ResourceType.MEMORY, "mem-shared")
        self.assertFalse(self.iso.validate_access("t2", ResourceType.MEMORY, "mem-shared"))

    def test_enforce_isolation_schema(self):
        result = self.iso.enforce_isolation("t1", {"select": "*", "from": "agents"})
        self.assertEqual(result["tenant_id"], "t1")
        self.assertEqual(result["schema"], "tenant_t1")

    def test_enforce_isolation_database(self):
        iso_db = TenantIsolation(level=IsolationLevel.DATABASE)
        result = iso_db.enforce_isolation("t1", {"select": "*"})
        self.assertEqual(result["database"], "db_t1")

    def test_enforce_isolation_shared(self):
        iso_shared = TenantIsolation(level=IsolationLevel.SHARED)
        result = iso_shared.enforce_isolation("t1", {"select": "*"})
        self.assertEqual(result["tenant_id"], "t1")
        self.assertNotIn("schema", result)
        self.assertNotIn("database", result)

    def test_all_resource_types(self):
        for rt in ResourceType:
            self.iso.register_resource("owner", rt, f"{rt.value}-1")
            self.assertTrue(self.iso.validate_access("owner", rt, f"{rt.value}-1"))
            self.assertFalse(self.iso.validate_access("other", rt, f"{rt.value}-1"))


# --- Middleware ---

class TestTenantMiddleware(unittest.TestCase):
    def setUp(self):
        self.directory = TenantDirectory()
        self.directory.register(_make_ctx("tenant-a"))
        self.directory.register(_make_ctx("tenant-b", TenantTier.PRO))
        self.header_resolver = HeaderTenantResolver(self.directory)
        self.token_resolver = TokenTenantResolver(self.directory)
        self.middleware = TenantMiddleware(
            header_resolver=self.header_resolver,
            token_resolver=self.token_resolver,
        )

    def test_resolve_from_header(self):
        ctx = self.middleware.resolve_tenant({"X-Tenant-ID": "tenant-a"})
        self.assertEqual(ctx.tenant_id, "tenant-a")

    def test_resolve_from_lowercase_header(self):
        ctx = self.middleware.resolve_tenant({"x-tenant-id": "tenant-b"})
        self.assertEqual(ctx.tenant_id, "tenant-b")
        self.assertEqual(ctx.tier, TenantTier.PRO)

    def test_resolve_from_token(self):
        token = _make_jwt({"tenant_id": "tenant-a", "sub": "user1"})
        ctx = self.middleware.resolve_tenant({"Authorization": f"Bearer {token}"})
        self.assertEqual(ctx.tenant_id, "tenant-a")

    def test_resolve_unknown_tenant(self):
        with self.assertRaises(TenantNotFoundError):
            self.middleware.resolve_tenant({"X-Tenant-ID": "unknown"})

    def test_resolve_no_identifier(self):
        with self.assertRaises(TenantNotFoundError):
            self.middleware.resolve_tenant({})

    def test_resolve_invalid_token(self):
        with self.assertRaises(TenantNotFoundError):
            self.middleware.resolve_tenant({"Authorization": "Bearer bad-token"})

    def test_header_takes_priority_over_token(self):
        token = _make_jwt({"tenant_id": "tenant-b"})
        ctx = self.middleware.resolve_tenant({
            "X-Tenant-ID": "tenant-a",
            "Authorization": f"Bearer {token}",
        })
        self.assertEqual(ctx.tenant_id, "tenant-a")


class TestTenantDirectory(unittest.TestCase):
    def test_register_and_lookup(self):
        d = TenantDirectory()
        ctx = _make_ctx("dir-1")
        d.register(ctx)
        self.assertEqual(d.lookup("dir-1").tenant_id, "dir-1")

    def test_lookup_missing(self):
        d = TenantDirectory()
        self.assertIsNone(d.lookup("missing"))

    def test_remove(self):
        d = TenantDirectory()
        d.register(_make_ctx("rm-1"))
        self.assertTrue(d.remove("rm-1"))
        self.assertIsNone(d.lookup("rm-1"))

    def test_remove_missing(self):
        d = TenantDirectory()
        self.assertFalse(d.remove("missing"))

    def test_list_tenants(self):
        d = TenantDirectory()
        d.register(_make_ctx("a"))
        d.register(_make_ctx("b"))
        ids = {t.tenant_id for t in d.list_tenants()}
        self.assertEqual(ids, {"a", "b"})


# --- Config ---

class TestTenantConfig(unittest.TestCase):
    def test_tier_defaults_free(self):
        limits = get_tier_defaults(TenantTier.FREE)
        self.assertEqual(limits.max_agents, 5)
        self.assertEqual(limits.max_workflows, 10)

    def test_tier_defaults_pro(self):
        limits = get_tier_defaults(TenantTier.PRO)
        self.assertEqual(limits.max_agents, 50)
        self.assertEqual(limits.max_workflows, 100)

    def test_tier_defaults_enterprise(self):
        limits = get_tier_defaults(TenantTier.ENTERPRISE)
        self.assertEqual(limits.max_agents, -1)
        self.assertEqual(limits.max_api_calls_per_hour, -1)

    def test_config_store_crud(self):
        store = ConfigStore()
        cfg = TenantConfig(tier=TenantTier.PRO, limits=get_tier_defaults(TenantTier.PRO))
        store.set_config("t1", cfg)

        retrieved = store.get_config("t1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.tenant_id, "t1")
        self.assertEqual(retrieved.tier, TenantTier.PRO)

    def test_config_store_get_missing(self):
        store = ConfigStore()
        self.assertIsNone(store.get_config("missing"))

    def test_config_store_delete(self):
        store = ConfigStore()
        store.set_config("t1", TenantConfig())
        self.assertTrue(store.delete_config("t1"))
        self.assertIsNone(store.get_config("t1"))

    def test_config_store_delete_missing(self):
        store = ConfigStore()
        self.assertFalse(store.delete_config("missing"))

    def test_config_store_list(self):
        store = ConfigStore()
        store.set_config("a", TenantConfig(tier=TenantTier.FREE))
        store.set_config("b", TenantConfig(tier=TenantTier.PRO))
        configs = store.list_configs()
        self.assertEqual(len(configs), 2)

    def test_config_store_overwrite(self):
        store = ConfigStore()
        store.set_config("t1", TenantConfig(tier=TenantTier.FREE))
        store.set_config("t1", TenantConfig(tier=TenantTier.ENTERPRISE))
        self.assertEqual(store.get_config("t1").tier, TenantTier.ENTERPRISE)


# --- Protocol compliance ---

class TestTenantResolverProtocol(unittest.TestCase):
    def test_header_resolver_is_protocol_compliant(self):
        from pylon.tenancy import TenantResolver
        d = TenantDirectory()
        r = HeaderTenantResolver(d)
        self.assertIsInstance(r, TenantResolver)

    def test_token_resolver_is_protocol_compliant(self):
        from pylon.tenancy import TenantResolver
        d = TenantDirectory()
        r = TokenTenantResolver(d)
        self.assertIsInstance(r, TenantResolver)


if __name__ == "__main__":
    unittest.main()
