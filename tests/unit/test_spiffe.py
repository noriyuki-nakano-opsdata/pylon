"""Tests for SPIFFE/SPIRE workload identity."""

import time

import pytest

from pylon.identity.spiffe import (
    SVID,
    SpiffeId,
    SpireRegistrationEntry,
    SVIDType,
    WorkloadIdentityManager,
)


class TestSpiffeId:
    def test_uri_property(self):
        sid = SpiffeId(trust_domain="pylon.cluster1", path="/tenant/t1/agent/a1")
        assert sid.uri == "spiffe://pylon.cluster1/tenant/t1/agent/a1"

    def test_from_uri(self):
        sid = SpiffeId.from_uri("spiffe://pylon.cluster1/tenant/t1/agent/a1")
        assert sid.trust_domain == "pylon.cluster1"
        assert sid.path == "/tenant/t1/agent/a1"

    def test_from_uri_no_path(self):
        sid = SpiffeId.from_uri("spiffe://pylon.cluster1")
        assert sid.trust_domain == "pylon.cluster1"
        assert sid.path == "/"

    def test_from_uri_invalid_scheme(self):
        with pytest.raises(ValueError, match="Invalid SPIFFE URI"):
            SpiffeId.from_uri("https://example.com")

    def test_for_tenant(self):
        sid = SpiffeId.for_tenant("cluster1", "t1")
        assert sid.trust_domain == "pylon.cluster1"
        assert sid.path == "/tenant/t1"
        assert sid.uri == "spiffe://pylon.cluster1/tenant/t1"

    def test_for_agent(self):
        sid = SpiffeId.for_agent("cluster1", "t1", "a1")
        assert sid.trust_domain == "pylon.cluster1"
        assert sid.path == "/tenant/t1/agent/a1"

    def test_roundtrip(self):
        original = SpiffeId.for_agent("cluster1", "t1", "a1")
        parsed = SpiffeId.from_uri(original.uri)
        assert parsed.trust_domain == original.trust_domain
        assert parsed.path == original.path


class TestSVID:
    def test_not_expired(self):
        now = time.time()
        svid = SVID(
            spiffe_id=SpiffeId.for_agent("c1", "t1", "a1"),
            svid_type=SVIDType.X509,
            issued_at=now,
            expires_at=now + 3600,
        )
        assert svid.is_expired is False

    def test_expired(self):
        now = time.time()
        svid = SVID(
            spiffe_id=SpiffeId.for_agent("c1", "t1", "a1"),
            svid_type=SVIDType.X509,
            issued_at=now - 7200,
            expires_at=now - 3600,
        )
        assert svid.is_expired is True

    def test_svid_types(self):
        assert SVIDType.X509.value == "x509"
        assert SVIDType.JWT.value == "jwt"

    def test_default_ttl(self):
        now = time.time()
        svid = SVID(
            spiffe_id=SpiffeId.for_agent("c1", "t1", "a1"),
            svid_type=SVIDType.JWT,
            issued_at=now,
            expires_at=now + 3600,
        )
        assert svid.ttl_seconds == 3600


class TestSpireRegistrationEntry:
    def test_fields(self):
        sid = SpiffeId.for_agent("c1", "t1", "a1")
        parent = SpiffeId.for_tenant("c1", "t1")
        entry = SpireRegistrationEntry(
            entry_id="e1",
            spiffe_id=sid,
            parent_id=parent,
            selectors=[{"type": "k8s_psat", "value": "ns:openclaw"}],
            ttl=7200,
        )
        assert entry.entry_id == "e1"
        assert entry.spiffe_id.uri == sid.uri
        assert entry.parent_id.uri == parent.uri
        assert entry.ttl == 7200
        assert len(entry.selectors) == 1

    def test_default_ttl(self):
        entry = SpireRegistrationEntry(
            entry_id="e1",
            spiffe_id=SpiffeId.for_agent("c1", "t1", "a1"),
            parent_id=SpiffeId.for_tenant("c1", "t1"),
        )
        assert entry.ttl == 3600


class TestWorkloadIdentityManager:
    def test_create_registration(self):
        mgr = WorkloadIdentityManager()
        entry = mgr.create_registration("t1", "a1")
        assert entry.entry_id.startswith("entry-")
        assert "/tenant/t1/agent/a1" in entry.spiffe_id.path
        assert "/tenant/t1" in entry.parent_id.path
        assert len(entry.selectors) == 1

    def test_create_registration_custom_selectors(self):
        mgr = WorkloadIdentityManager()
        selectors = [{"type": "unix", "value": "uid:1000"}]
        entry = mgr.create_registration("t1", "a1", selectors=selectors)
        assert entry.selectors == selectors

    def test_get_svid(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        svid = mgr.get_svid(sid)
        assert svid.spiffe_id.uri == sid.uri
        assert svid.svid_type == SVIDType.X509
        assert svid.is_expired is False

    def test_get_svid_cached(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        svid1 = mgr.get_svid(sid)
        svid2 = mgr.get_svid(sid)
        assert svid1.issued_at == svid2.issued_at

    def test_get_svid_jwt_type(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        svid = mgr.get_svid(sid, svid_type=SVIDType.JWT)
        assert svid.svid_type == SVIDType.JWT

    def test_validate_svid_valid(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        svid = mgr.get_svid(sid)
        assert mgr.validate_svid(svid) is True

    def test_validate_svid_expired(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        now = time.time()
        svid = SVID(
            spiffe_id=sid,
            svid_type=SVIDType.X509,
            issued_at=now - 7200,
            expires_at=now - 3600,
        )
        mgr._svids[sid.uri] = svid
        assert mgr.validate_svid(svid) is False

    def test_validate_svid_unknown(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "unknown")
        now = time.time()
        svid = SVID(
            spiffe_id=sid,
            svid_type=SVIDType.X509,
            issued_at=now,
            expires_at=now + 3600,
        )
        assert mgr.validate_svid(svid) is False

    def test_rotate_svid(self):
        mgr = WorkloadIdentityManager()
        sid = SpiffeId.for_agent("pylon.cluster1", "t1", "a1")
        original = mgr.get_svid(sid)
        rotated = mgr.rotate_svid(original)
        assert rotated.spiffe_id.uri == original.spiffe_id.uri
        assert rotated.issued_at >= original.issued_at
        assert mgr.validate_svid(rotated) is True
        assert mgr.validate_svid(original) is False

    def test_list_entries(self):
        mgr = WorkloadIdentityManager()
        mgr.create_registration("t1", "a1")
        mgr.create_registration("t1", "a2")
        mgr.create_registration("t2", "a3")
        entries = mgr.list_entries("t1")
        assert len(entries) == 2
        assert all("/tenant/t1/" in e.spiffe_id.path for e in entries)

    def test_list_entries_empty(self):
        mgr = WorkloadIdentityManager()
        assert mgr.list_entries("t99") == []

    def test_delete_entry(self):
        mgr = WorkloadIdentityManager()
        entry = mgr.create_registration("t1", "a1")
        assert mgr.delete_entry(entry.entry_id) is True
        assert mgr.list_entries("t1") == []

    def test_delete_entry_nonexistent(self):
        mgr = WorkloadIdentityManager()
        assert mgr.delete_entry("no-such-entry") is False
