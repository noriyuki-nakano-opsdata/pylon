"""Approval workflow manager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pylon.approval.store import ApprovalStore
from pylon.approval.types import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    compute_approval_binding_hash,
)
from pylon.errors import PolicyViolationError, PylonError
from pylon.repository.audit import AuditRepository
from pylon.types import AutonomyLevel


class ApprovalNotFoundError(PylonError):
    code = "APPROVAL_NOT_FOUND"
    status_code = 404


class ApprovalAlreadyDecidedError(PylonError):
    code = "APPROVAL_ALREADY_DECIDED"
    status_code = 409


class ApprovalBindingMismatchError(PolicyViolationError):
    code = "APPROVAL_BINDING_MISMATCH"
    status_code = 409


class ApprovalManager:
    """Manages the approval workflow for A3+ autonomy actions.

    Handles submission, approval, rejection, timeout/expiry,
    and audit trail integration.
    """

    def __init__(
        self,
        store: ApprovalStore,
        audit: AuditRepository,
        *,
        timeout_seconds: int = 300,
    ) -> None:
        self._store = store
        self._audit = audit
        self._timeout_seconds = timeout_seconds

    async def submit_request(
        self,
        agent_id: str,
        action: str,
        autonomy_level: AutonomyLevel,
        context: dict[str, Any] | None = None,
        *,
        plan: Any | None = None,
        effect_envelope: Any | None = None,
    ) -> ApprovalRequest:
        now = datetime.now(UTC)
        request = ApprovalRequest(
            agent_id=agent_id,
            action=action,
            autonomy_level=autonomy_level,
            context=context or {},
            plan_hash=compute_approval_binding_hash(plan) if plan is not None else "",
            effect_hash=(
                compute_approval_binding_hash(effect_envelope)
                if effect_envelope is not None
                else ""
            ),
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=self._timeout_seconds),
        )
        await self._store.create(request)
        await self._audit.append(
            event_type="approval.submitted",
            actor=agent_id,
            action=action,
            details={
                "request_id": request.id,
                "autonomy_level": autonomy_level.name,
                "context": context or {},
                "plan_hash": request.plan_hash,
                "effect_hash": request.effect_hash,
            },
        )
        return request

    async def approve(
        self,
        request_id: str,
        approved_by: str,
        comment: str = "",
    ) -> ApprovalDecision:
        request = await self._get_valid_pending(request_id)
        request.status = ApprovalStatus.APPROVED
        await self._store.update(request)

        decision = ApprovalDecision(
            request_id=request_id,
            approved=True,
            decided_by=approved_by,
            reason=comment,
        )
        await self._audit.append(
            event_type="approval.approved",
            actor=approved_by,
            action=request.action,
            details={"request_id": request_id, "comment": comment},
        )
        return decision

    async def reject(
        self,
        request_id: str,
        rejected_by: str,
        reason: str = "",
    ) -> ApprovalDecision:
        request = await self._get_valid_pending(request_id)
        request.status = ApprovalStatus.REJECTED
        await self._store.update(request)

        decision = ApprovalDecision(
            request_id=request_id,
            approved=False,
            decided_by=rejected_by,
            reason=reason,
        )
        await self._audit.append(
            event_type="approval.rejected",
            actor=rejected_by,
            action=request.action,
            details={"request_id": request_id, "reason": reason},
        )
        return decision

    async def get_pending(
        self,
        agent_id: str | None = None,
    ) -> list[ApprovalRequest]:
        """Get pending requests, expiring any that have timed out."""
        pending = await self._store.list(
            status=ApprovalStatus.PENDING,
            agent_id=agent_id,
        )
        now = datetime.now(UTC)
        still_pending: list[ApprovalRequest] = []
        for req in pending:
            if req.expires_at and now >= req.expires_at:
                await self._expire_request(req)
            else:
                still_pending.append(req)
        return still_pending

    async def get_request(self, request_id: str) -> ApprovalRequest | None:
        request = await self._store.get(request_id)
        if request and request.status == ApprovalStatus.PENDING:
            if request.expires_at and datetime.now(UTC) >= request.expires_at:
                await self._expire_request(request)
        return request

    async def validate_binding(
        self,
        request_id: str,
        *,
        plan: Any | None = None,
        effect_envelope: Any | None = None,
    ) -> ApprovalRequest:
        """Validate that an approved request still matches its bound scope."""
        request = await self._store.get(request_id)
        if request is None:
            raise ApprovalNotFoundError(
                f"Approval request not found: {request_id}",
                details={"request_id": request_id},
            )
        if request.status != ApprovalStatus.APPROVED:
            raise ApprovalAlreadyDecidedError(
                f"Approval request is not approved: {request_id}",
                details={"request_id": request_id, "status": request.status.value},
            )

        if request.expires_at and datetime.now(UTC) >= request.expires_at:
            await self._expire_request(request)
            raise ApprovalAlreadyDecidedError(
                f"Approval request has expired: {request_id}",
                details={"request_id": request_id, "status": ApprovalStatus.EXPIRED.value},
            )

        supplied_plan_hash = compute_approval_binding_hash(plan) if plan is not None else ""
        supplied_effect_hash = (
            compute_approval_binding_hash(effect_envelope)
            if effect_envelope is not None
            else ""
        )
        if request.plan_hash and request.plan_hash != supplied_plan_hash:
            raise ApprovalBindingMismatchError(
                "Approval invalidated by plan drift",
                details={
                    "request_id": request_id,
                    "expected_plan_hash": request.plan_hash,
                    "actual_plan_hash": supplied_plan_hash,
                },
            )
        if request.effect_hash and request.effect_hash != supplied_effect_hash:
            raise ApprovalBindingMismatchError(
                "Approval invalidated by effect scope drift",
                details={
                    "request_id": request_id,
                    "expected_effect_hash": request.effect_hash,
                    "actual_effect_hash": supplied_effect_hash,
                },
            )
        return request

    async def _get_valid_pending(self, request_id: str) -> ApprovalRequest:
        request = await self._store.get(request_id)
        if request is None:
            raise ApprovalNotFoundError(
                f"Approval request not found: {request_id}",
                details={"request_id": request_id},
            )
        # Check expiry first
        if request.status == ApprovalStatus.PENDING and request.expires_at:
            if datetime.now(UTC) >= request.expires_at:
                await self._expire_request(request)
                raise ApprovalAlreadyDecidedError(
                    f"Approval request expired: {request_id}",
                    details={"request_id": request_id, "status": "expired"},
                )
        if request.status != ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecidedError(
                f"Approval request already {request.status.value}: {request_id}",
                details={"request_id": request_id, "status": request.status.value},
            )
        return request

    async def _expire_request(self, request: ApprovalRequest) -> None:
        request.status = ApprovalStatus.EXPIRED
        await self._store.update(request)
        await self._audit.append(
            event_type="approval.expired",
            actor="system",
            action=request.action,
            details={
                "request_id": request.id,
                "agent_id": request.agent_id,
            },
        )
