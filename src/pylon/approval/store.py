"""In-memory store for approval requests."""

from __future__ import annotations

from pylon.approval.types import ApprovalRequest, ApprovalStatus


class ApprovalStore:
    """In-memory CRUD store for approval requests."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    async def create(self, request: ApprovalRequest) -> ApprovalRequest:
        self._requests[request.id] = request
        return request

    async def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    async def update(self, request: ApprovalRequest) -> ApprovalRequest:
        self._requests[request.id] = request
        return request

    async def list(
        self,
        *,
        status: ApprovalStatus | None = None,
        agent_id: str | None = None,
        action: str | None = None,
    ) -> list[ApprovalRequest]:
        results = list(self._requests.values())
        if status is not None:
            results = [r for r in results if r.status == status]
        if agent_id is not None:
            results = [r for r in results if r.agent_id == agent_id]
        if action is not None:
            results = [r for r in results if r.action == action]
        return results

    async def delete(self, request_id: str) -> bool:
        return self._requests.pop(request_id, None) is not None
