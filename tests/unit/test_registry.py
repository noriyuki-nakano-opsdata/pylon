"""Tests for tool and skill registries."""

from __future__ import annotations

import pytest

from pylon.control_plane.registry.skills import SkillDefinition, SkillRegistry, SkillRegistryError
from pylon.control_plane.registry.tools import ToolDefinition, ToolRegistry, ToolRegistryError, tool
from pylon.types import TrustLevel

# --- Fixtures ---


async def _noop(**kwargs):
    return {"ok": True}


def make_tool(name: str, trust: TrustLevel = TrustLevel.UNTRUSTED) -> ToolDefinition:
    return ToolDefinition(name=name, description=f"{name} tool", handler=_noop, trust_level=trust)


# --- ToolRegistry Tests ---


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        t = make_tool("read-pr")
        reg.register(t)
        assert reg.get("read-pr") is t

    def test_get_missing_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_register_duplicate_raises(self):
        reg = ToolRegistry()
        reg.register(make_tool("t1"))
        with pytest.raises(ToolRegistryError):
            reg.register(make_tool("t1"))

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(make_tool("a", TrustLevel.TRUSTED))
        reg.register(make_tool("b", TrustLevel.UNTRUSTED))
        assert len(reg.list()) == 2

    def test_list_filter_by_trust_level(self):
        reg = ToolRegistry()
        reg.register(make_tool("trusted-tool", TrustLevel.TRUSTED))
        reg.register(make_tool("untrusted-tool", TrustLevel.UNTRUSTED))
        reg.register(make_tool("internal-tool", TrustLevel.INTERNAL))

        trusted = reg.list(trust_level=TrustLevel.TRUSTED)
        assert len(trusted) == 1
        assert trusted[0].name == "trusted-tool"

        untrusted = reg.list(trust_level=TrustLevel.UNTRUSTED)
        assert len(untrusted) == 1
        assert untrusted[0].name == "untrusted-tool"

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(make_tool("t"))
        reg.unregister("t")
        assert reg.get("t") is None

    def test_unregister_missing_raises(self):
        reg = ToolRegistry()
        with pytest.raises(ToolRegistryError):
            reg.unregister("nonexistent")

    def test_discover_returns_all(self):
        reg = ToolRegistry()
        reg.register(make_tool("a"))
        reg.register(make_tool("b"))
        assert len(reg.discover()) == 2


class TestToolDecorator:
    def test_decorator_creates_tool_definition(self):
        @tool(name="github-pr-read", description="Read PR details", trust_level="untrusted")
        async def read_pr(pr_number: int):
            return {"pr": pr_number}

        defn = read_pr._tool_definition
        assert isinstance(defn, ToolDefinition)
        assert defn.name == "github-pr-read"
        assert defn.trust_level == TrustLevel.UNTRUSTED

    def test_decorator_with_parameters(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}

        @tool(name="get-issue", description="Get issue", trust_level="internal", parameters=schema)
        async def get_issue(issue_id: int):
            return {}

        defn = get_issue._tool_definition
        assert defn.parameters == schema
        assert defn.trust_level == TrustLevel.INTERNAL

    def test_decorated_function_still_callable(self):
        @tool(name="test", description="test")
        async def my_fn():
            return 42

        # The function itself is still the original coroutine function
        import asyncio
        result = asyncio.run(my_fn())
        assert result == 42


# --- SkillRegistry Tests ---


class TestSkillRegistry:
    def test_register_and_get(self):
        tool_reg = ToolRegistry()
        skill_reg = SkillRegistry(tool_reg)
        skill = SkillDefinition(name="pr-review", version="1.0", tools=[], description="PR review")
        skill_reg.register(skill)
        assert skill_reg.get("pr-review") is skill

    def test_get_missing_returns_none(self):
        skill_reg = SkillRegistry(ToolRegistry())
        assert skill_reg.get("nonexistent") is None

    def test_register_duplicate_raises(self):
        skill_reg = SkillRegistry(ToolRegistry())
        skill_reg.register(SkillDefinition(name="s1", version="1.0"))
        with pytest.raises(SkillRegistryError):
            skill_reg.register(SkillDefinition(name="s1", version="2.0"))

    def test_resolve_dependencies(self):
        tool_reg = ToolRegistry()
        t1 = make_tool("read-pr")
        t2 = make_tool("write-comment")
        tool_reg.register(t1)
        tool_reg.register(t2)

        skill_reg = SkillRegistry(tool_reg)
        skill = SkillDefinition(
            name="pr-review", version="1.0", tools=["read-pr", "write-comment"]
        )
        skill_reg.register(skill)

        deps = skill_reg.resolve_dependencies("pr-review")
        assert len(deps) == 2
        assert deps[0] is t1
        assert deps[1] is t2

    def test_resolve_missing_skill_raises(self):
        skill_reg = SkillRegistry(ToolRegistry())
        with pytest.raises(SkillRegistryError):
            skill_reg.resolve_dependencies("nonexistent")

    def test_resolve_missing_tool_raises(self):
        tool_reg = ToolRegistry()
        skill_reg = SkillRegistry(tool_reg)
        skill = SkillDefinition(name="s1", version="1.0", tools=["missing-tool"])
        skill_reg.register(skill)
        with pytest.raises(SkillRegistryError, match="missing-tool"):
            skill_reg.resolve_dependencies("s1")

    def test_list(self):
        skill_reg = SkillRegistry(ToolRegistry())
        skill_reg.register(SkillDefinition(name="a", version="1.0"))
        skill_reg.register(SkillDefinition(name="b", version="1.0"))
        assert len(skill_reg.list()) == 2
