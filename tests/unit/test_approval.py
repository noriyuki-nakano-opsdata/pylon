"""Tests for approval workflow."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from pylon.approval.manager import (
    ApprovalAlreadyDecidedError,
    ApprovalManager,
    ApprovalNotFoundError,
)
from pylon.approval.store import ApprovalStore
from pylon.approval.types import ApprovalDecision, ApprovalRequest, ApprovalStatus
from pylon.repository.audit import AuditRepository
from pylon.types import AutonomyLevel


@pytest.fixture
def store() -> ApprovalStore:
    return ApprovalStore()


@pytest.fixture
def audit() -> AuditRepository:
    return AuditRepository(hmac_key=b"test-key-at-least-16b")


@pytest.fixture
def manager(store: ApprovalStore, audit: AuditRepository) -> ApprovalManager:
    return ApprovalManager(store, audit, timeout_seconds=300)


# --- Types ---


class TestApprovalStatus:
    def test_status_values(self) -> None:
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.EXPIRED.value == "expired"


class TestApprovalRequest:
    def test_default_fields(self) -> None:
        req = ApprovalRequest()
        assert req.id  # non-empty uuid
        assert req.status == ApprovalStatus.PENDING
        assert req.agent_id == ""
        assert req.context == {}
        assert req.expires_at is None

    def test_custom_fields(self) -> None:
        req = ApprovalRequest(
            agent_id="coder-1",
            action="deploy",
            autonomy_level=AutonomyLevel.A4,
            context={"env": "prod"},
        )
        assert req.agent_id == "coder-1"
        assert req.action == "deploy"
        assert req.autonomy_level == AutonomyLevel.A4
        assert req.context == {"env": "prod"}


class TestApprovalDecision:
    def test_default_fields(self) -> None:
        d = ApprovalDecision()
        assert d.approved is False
        assert d.decided_by == ""
        assert d.reason == ""


# --- Store ---


class TestApprovalStore:
    @pytest.mark.asyncio
    async def test_create_and_get(self, store: ApprovalStore) -> None:
        req = ApprovalRequest(agent_id="a1", action="run")
        await store.create(req)
        found = await store.get(req.id)
        assert found is not None
        assert found.agent_id == "a1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: ApprovalStore) -> None:
        assert await store.get("nope") is None

    @pytest.mark.asyncio
    async def test_update(self, store: ApprovalStore) -> None:
        req = ApprovalRequest(agent_id="a1", action="run")
        await store.create(req)
        req.status = ApprovalStatus.APPROVED
        await store.update(req)
        found = await store.get(req.id)
        assert found is not None
        assert found.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, store: ApprovalStore) -> None:
        r1 = ApprovalRequest(agent_id="a1", action="run")
        r2 = ApprovalRequest(agent_id="a2", action="deploy", status=ApprovalStatus.APPROVED)
        await store.create(r1)
        await store.create(r2)
        pending = await store.list(status=ApprovalStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == r1.id

    @pytest.mark.asyncio
    async def test_list_filter_by_agent_id(self, store: ApprovalStore) -> None:
        r1 = ApprovalRequest(agent_id="a1", action="run")
        r2 = ApprovalRequest(agent_id="a2", action="deploy")
        await store.create(r1)
        await store.create(r2)
        filtered = await store.list(agent_id="a1")
        assert len(filtered) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_action(self, store: ApprovalStore) -> None:
        r1 = ApprovalRequest(agent_id="a1", action="run")
        r2 = ApprovalRequest(agent_id="a2", action="deploy")
        await store.create(r1)
        await store.create(r2)
        filtered = await store.list(action="deploy")
        assert len(filtered) == 1
        assert filtered[0].action == "deploy"

    @pytest.mark.asyncio
    async def test_delete(self, store: ApprovalStore) -> None:
        req = ApprovalRequest(agent_id="a1", action="run")
        await store.create(req)
        assert await store.delete(req.id) is True
        assert await store.get(req.id) is None
        assert await store.delete(req.id) is False


# --- Manager ---


class TestApprovalManagerSubmit:
    @pytest.mark.asyncio
    async def test_submit_creates_request(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        assert req.agent_id == "agent-1"
        assert req.action == "deploy"
        assert req.status == ApprovalStatus.PENDING
        assert req.expires_at is not None

    @pytest.mark.asyncio
    async def test_submit_creates_audit_entry(
        self, manager: ApprovalManager, audit: AuditRepository
    ) -> None:
        await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        entries = await audit.list(event_type="approval.submitted")
        assert len(entries) == 1
        assert entries[0].actor == "agent-1"

    @pytest.mark.asyncio
    async def test_submit_with_context(self, manager: ApprovalManager) -> None:
        ctx = {"target": "production", "files": 3}
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A4, context=ctx)
        assert req.context == ctx


class TestApprovalManagerApprove:
    @pytest.mark.asyncio
    async def test_approve_flow(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        decision = await manager.approve(req.id, "admin", comment="looks good")
        assert decision.approved is True
        assert decision.decided_by == "admin"
        assert decision.reason == "looks good"
        updated = await manager.get_request(req.id)
        assert updated is not None
        assert updated.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_approve_audit_trail(
        self, manager: ApprovalManager, audit: AuditRepository
    ) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.approve(req.id, "admin")
        entries = await audit.list(event_type="approval.approved")
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_approve_nonexistent_raises(self, manager: ApprovalManager) -> None:
        with pytest.raises(ApprovalNotFoundError):
            await manager.approve("nonexistent", "admin")

    @pytest.mark.asyncio
    async def test_approve_already_approved_raises(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.approve(req.id, "admin")
        with pytest.raises(ApprovalAlreadyDecidedError):
            await manager.approve(req.id, "admin")


class TestApprovalManagerReject:
    @pytest.mark.asyncio
    async def test_reject_flow(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        decision = await manager.reject(req.id, "admin", reason="too risky")
        assert decision.approved is False
        assert decision.decided_by == "admin"
        assert decision.reason == "too risky"
        updated = await manager.get_request(req.id)
        assert updated is not None
        assert updated.status == ApprovalStatus.REJECTED

    @pytest.mark.asyncio
    async def test_reject_audit_trail(
        self, manager: ApprovalManager, audit: AuditRepository
    ) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.reject(req.id, "admin", reason="nope")
        entries = await audit.list(event_type="approval.rejected")
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_reject_already_rejected_raises(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.reject(req.id, "admin")
        with pytest.raises(ApprovalAlreadyDecidedError):
            await manager.reject(req.id, "admin")


class TestApprovalManagerTimeout:
    @pytest.mark.asyncio
    async def test_expired_request_not_in_pending(
        self, store: ApprovalStore, audit: AuditRepository
    ) -> None:
        mgr = ApprovalManager(store, audit, timeout_seconds=0)
        req = await mgr.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        # Force expiry by setting expires_at in the past
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.update(req)
        pending = await mgr.get_pending()
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_expired_request_creates_audit(
        self, store: ApprovalStore, audit: AuditRepository
    ) -> None:
        mgr = ApprovalManager(store, audit, timeout_seconds=0)
        req = await mgr.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.update(req)
        await mgr.get_pending()
        entries = await audit.list(event_type="approval.expired")
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_approve_expired_raises(
        self, store: ApprovalStore, audit: AuditRepository
    ) -> None:
        mgr = ApprovalManager(store, audit, timeout_seconds=0)
        req = await mgr.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.update(req)
        with pytest.raises(ApprovalAlreadyDecidedError, match="expired"):
            await mgr.approve(req.id, "admin")

    @pytest.mark.asyncio
    async def test_get_request_auto_expires(
        self, store: ApprovalStore, audit: AuditRepository
    ) -> None:
        mgr = ApprovalManager(store, audit, timeout_seconds=0)
        req = await mgr.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        req.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await store.update(req)
        result = await mgr.get_request(req.id)
        assert result is not None
        assert result.status == ApprovalStatus.EXPIRED


class TestApprovalManagerPending:
    @pytest.mark.asyncio
    async def test_pending_list_all(self, manager: ApprovalManager) -> None:
        await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.submit_request("agent-2", "build", AutonomyLevel.A4)
        pending = await manager.get_pending()
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_pending_filter_by_agent(self, manager: ApprovalManager) -> None:
        await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.submit_request("agent-2", "build", AutonomyLevel.A4)
        pending = await manager.get_pending(agent_id="agent-1")
        assert len(pending) == 1
        assert pending[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_approved_not_in_pending(self, manager: ApprovalManager) -> None:
        req = await manager.submit_request("agent-1", "deploy", AutonomyLevel.A3)
        await manager.approve(req.id, "admin")
        pending = await manager.get_pending()
        assert len(pending) == 0


class TestApprovalManagerConcurrent:
    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self, manager: ApprovalManager) -> None:
        reqs = await asyncio.gather(
            manager.submit_request("a1", "deploy", AutonomyLevel.A3),
            manager.submit_request("a2", "build", AutonomyLevel.A3),
            manager.submit_request("a3", "test", AutonomyLevel.A4),
        )
        assert len(reqs) == 3
        ids = {r.id for r in reqs}
        assert len(ids) == 3  # all unique

        pending = await manager.get_pending()
        assert len(pending) == 3

        # Approve one, reject one
        await manager.approve(reqs[0].id, "admin")
        await manager.reject(reqs[1].id, "admin", reason="no")
        pending = await manager.get_pending()
        assert len(pending) == 1
        assert pending[0].id == reqs[2].id
