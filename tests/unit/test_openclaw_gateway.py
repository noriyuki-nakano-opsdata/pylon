"""Tests for OpenClaw skill integration gateway."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from pylon.gateway.openclaw import (
    OpenClawGateway,
    OpenClawSkillRequest,
    OpenClawSkillResponse,
)


class TestSkillRequestParsing:
    @pytest.mark.asyncio
    async def test_skill_request_parsing(self):
        gateway = OpenClawGateway()

        async def handler(req: OpenClawSkillRequest) -> OpenClawSkillResponse:
            assert req.message == "hello"
            assert req.context == {"key": "val"}
            assert req.session_id == "s1"
            return OpenClawSkillResponse(
                reply="hi", usage={"tokens": 10}, cost=0.001, model="test"
            )

        gateway.set_handler(handler)

        result = await gateway.handle_skill_request({
            "message": "hello",
            "context": {"key": "val"},
            "session_id": "s1",
        })
        assert result["reply"] == "hi"
        assert result["cost"] == 0.001
        assert result["model"] == "test"


class TestSkillResponseFormat:
    @pytest.mark.asyncio
    async def test_skill_response_format(self):
        """Handler returning a plain string is wrapped into a response dict."""
        gateway = OpenClawGateway(handler=lambda req: "plain text")

        result = await gateway.handle_skill_request({
            "message": "test",
        })
        assert result["reply"] == "plain text"
        assert "model" in result

        # No handler returns default message
        gw2 = OpenClawGateway()
        result2 = await gw2.handle_skill_request({"message": "x"})
        assert result2["reply"] == "No handler configured"


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check(self):
        gw = OpenClawGateway(handler=lambda r: "ok")
        gw.register_model({"id": "m1", "name": "Model 1"})

        result = await gw.handle_health()
        assert result["status"] == "healthy"
        assert result["handler_configured"] is True
        assert result["models_registered"] == 1

        gw2 = OpenClawGateway()
        result2 = await gw2.handle_health()
        assert result2["handler_configured"] is False
        assert result2["models_registered"] == 0


class TestModelList:
    @pytest.mark.asyncio
    async def test_model_list(self):
        gw = OpenClawGateway()
        assert await gw.handle_model_list() == []

        gw.register_model({"id": "claude", "provider": "anthropic"})
        gw.register_model({"id": "gpt-4", "provider": "openai"})

        models = await gw.handle_model_list()
        assert len(models) == 2
        assert models[0]["id"] == "claude"
        assert models[1]["provider"] == "openai"
