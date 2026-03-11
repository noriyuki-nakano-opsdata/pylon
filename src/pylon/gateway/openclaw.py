"""OpenClaw skill integration endpoint."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpenClawSkillRequest:
    """Incoming request from an OpenClaw skill invocation."""

    message: str
    context: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""


@dataclass
class OpenClawSkillResponse:
    """Response returned to OpenClaw after processing."""

    reply: str
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    model: str = ""


class OpenClawGateway:
    """Gateway for OpenClaw skill request handling.

    Bridges OpenClaw's skill protocol with internal chat processing.
    """

    def __init__(self, handler: Callable[..., Any] | None = None) -> None:
        self._handler = handler
        self._models: list[dict[str, Any]] = []

    def set_handler(self, handler: Callable[..., Any]) -> None:
        """Set the chat handler for processing skill requests."""
        self._handler = handler

    def register_model(self, model_info: dict[str, Any]) -> None:
        """Register an available model for the model list endpoint."""
        self._models.append(model_info)

    async def handle_skill_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process an OpenClaw skill request.

        Args:
            request: Raw request dict with 'message', 'context', 'session_id'.

        Returns:
            Response dict with 'reply', 'usage', 'cost', 'model'.
        """
        skill_req = OpenClawSkillRequest(
            message=request.get("message", ""),
            context=request.get("context", {}),
            session_id=request.get("session_id", ""),
        )

        if self._handler is None:
            return dataclasses.asdict(OpenClawSkillResponse(
                reply="No handler configured",
                model="none",
            ))

        import asyncio

        result = self._handler(skill_req)
        if asyncio.iscoroutine(result):
            result = await result

        if isinstance(result, OpenClawSkillResponse):
            return dataclasses.asdict(result)
        if isinstance(result, dict):
            return result
        return dataclasses.asdict(
            OpenClawSkillResponse(reply=str(result), model="unknown")
        )

    async def handle_model_list(self) -> list[dict[str, Any]]:
        """Return the list of available models."""
        return list(self._models)

    async def handle_health(self) -> dict[str, Any]:
        """Return health status of the gateway."""
        return {
            "status": "healthy",
            "handler_configured": self._handler is not None,
            "models_registered": len(self._models),
        }
