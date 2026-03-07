"""Tests for kill switch."""

from pylon.safety.kill_switch import KillSwitch


class TestKillSwitch:
    def test_activate_and_is_active(self):
        ks = KillSwitch()
        assert not ks.is_active("agent:123")

        ks.activate("agent:123", reason="misbehaving", issued_by="admin")
        assert ks.is_active("agent:123")

    def test_deactivate(self):
        ks = KillSwitch()
        ks.activate("agent:123", reason="test", issued_by="admin")
        assert ks.is_active("agent:123")

        event = ks.deactivate("agent:123")
        assert event is not None
        assert event.scope == "agent:123"
        assert not ks.is_active("agent:123")

    def test_deactivate_nonexistent_returns_none(self):
        ks = KillSwitch()
        assert ks.deactivate("agent:999") is None

    def test_global_blocks_all_scopes(self):
        ks = KillSwitch()
        ks.activate("global", reason="emergency", issued_by="admin")
        assert ks.is_active("global")
        assert ks.is_active("agent:123")
        assert ks.is_active("workflow:456")
        assert ks.is_active("tenant:abc")

    def test_scope_isolation(self):
        ks = KillSwitch()
        ks.activate("agent:1", reason="test", issued_by="admin")
        assert ks.is_active("agent:1")
        assert not ks.is_active("agent:2")
        assert not ks.is_active("workflow:1")

    def test_get_active_scopes(self):
        ks = KillSwitch()
        ks.activate("agent:1", reason="a", issued_by="admin")
        ks.activate("workflow:2", reason="b", issued_by="admin")
        scopes = ks.get_active_scopes()
        assert "agent:1" in scopes
        assert "workflow:2" in scopes
        assert len(scopes) == 2

    def test_get_event(self):
        ks = KillSwitch()
        ks.activate("agent:1", reason="bad behavior", issued_by="ops")
        event = ks.get_event("agent:1")
        assert event is not None
        assert event.reason == "bad behavior"
        assert event.issued_by == "ops"

    def test_get_event_nonexistent(self):
        ks = KillSwitch()
        assert ks.get_event("agent:999") is None

    def test_activate_returns_event(self):
        ks = KillSwitch()
        event = ks.activate("global", reason="drill", issued_by="sre")
        assert event.scope == "global"
        assert event.reason == "drill"
        assert event.issued_by == "sre"

    def test_tenant_scope_blocks_child_agents(self):
        """Activating tenant kill switch should block all agents under that tenant."""
        ks = KillSwitch()
        ks.activate("tenant:acme", reason="breach", issued_by="admin")
        assert ks.is_active("tenant:acme")
        assert ks.is_active("tenant:acme/agent:a1")
        assert ks.is_active("tenant:acme/workflow:w1")
        # Other tenants should not be affected
        assert not ks.is_active("tenant:other/agent:a1")
        assert not ks.is_active("tenant:other")
