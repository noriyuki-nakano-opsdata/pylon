"""Typed models for filesystem-backed agent skills."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


ToolExecutor = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class SkillHandle:
    """Stable source-scoped identity for a logical skill."""

    source_id: str = ""
    skill_key: str = ""

    @property
    def canonical_id(self) -> str:
        if self.source_id and self.skill_key:
            return f"{self.source_id}:{self.skill_key}"
        return self.skill_key

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "skill_key": self.skill_key,
            "canonical_id": self.canonical_id,
        }


@dataclass(frozen=True)
class SkillVersionRef:
    """Immutable revision-scoped identity for execution and audit."""

    source_id: str = ""
    skill_key: str = ""
    revision: str = ""

    @property
    def canonical_ref(self) -> str:
        handle = SkillHandle(
            source_id=self.source_id,
            skill_key=self.skill_key,
        ).canonical_id
        if handle and self.revision:
            return f"{handle}@{self.revision}"
        return handle

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "skill_key": self.skill_key,
            "revision": self.revision,
            "canonical_ref": self.canonical_ref,
        }


@dataclass(frozen=True)
class SkillToolSpec:
    """Tool declaration attached to a skill package."""

    id: str
    name: str
    kind: str = "platform-ref"
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    entrypoint: str = ""
    timeout_seconds: int = 30
    read_only: bool = True
    sandbox: str = "inherit"
    trust_class: str = "internal"
    approval_class: str = "auto"
    resource_limits: dict[str, Any] = field(default_factory=dict)

    def provider_tool(self) -> dict[str, Any]:
        """Return a provider-agnostic function tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": self.description or self.name,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass(frozen=True)
class SkillRecord:
    """Normalized skill content loaded from the filesystem or control plane."""

    id: str
    name: str
    alias: str = ""
    skill_key: str = ""
    version: str = "0.0.1"
    description: str = ""
    content: str = ""
    content_preview: str = ""
    category: str = "other"
    risk: str = "unknown"
    source: str = "local"
    source_kind: str = "filesystem"
    tags: tuple[str, ...] = ()
    path: str = ""
    installed_at: str = ""
    has_scripts: bool = False
    dependencies: tuple[str, ...] = ()
    toolsets: tuple[str, ...] = ()
    tools: tuple[SkillToolSpec, ...] = ()
    prompt_priority: int = 50
    trust_class: str = "internal"
    approval_class: str = "auto"
    max_prompt_chars: int = 5000
    digest: str = ""
    references: tuple[str, ...] = ()
    context_contracts: tuple[dict[str, Any], ...] = ()
    source_id: str = ""
    source_revision: str = ""
    source_format: str = ""

    @property
    def effective_alias(self) -> str:
        return self.alias or self.skill_key or self.id

    @property
    def effective_skill_key(self) -> str:
        return self.skill_key or self.alias or self.id

    @property
    def handle(self) -> SkillHandle:
        return SkillHandle(
            source_id=self.source_id,
            skill_key=self.effective_skill_key,
        )

    @property
    def version_ref(self) -> SkillVersionRef:
        return SkillVersionRef(
            source_id=self.source_id,
            skill_key=self.effective_skill_key,
            revision=self.source_revision,
        )

    def to_payload(self, *, include_content: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "alias": self.effective_alias,
            "skill_key": self.effective_skill_key,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "risk": self.risk,
            "source": self.source,
            "source_kind": self.source_kind,
            "tags": list(self.tags),
            "path": self.path,
            "has_scripts": self.has_scripts,
            "content_preview": self.content_preview,
            "installed_at": self.installed_at,
            "dependencies": list(self.dependencies),
            "toolsets": list(self.toolsets),
            "digest": self.digest,
            "references": list(self.references),
            "context_contracts": [dict(item) for item in self.context_contracts],
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_format": self.source_format,
            "handle": self.handle.to_payload(),
            "version_ref": self.version_ref.to_payload(),
        }
        if self.tools:
            payload["tools"] = [
                {
                    "id": tool.id,
                    "name": tool.name,
                    "kind": tool.kind,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "entrypoint": tool.entrypoint,
                    "read_only": tool.read_only,
                    "approval_class": tool.approval_class,
                }
                for tool in self.tools
            ]
        if include_content:
            payload["content"] = self.content
        return payload


@dataclass(frozen=True)
class ResolvedSkillTool:
    """Executable tool exposed to a run after policy checks."""

    spec: SkillToolSpec
    skill_id: str
    executor: ToolExecutor | None = None
    unavailable_reason: str = ""

    @property
    def name(self) -> str:
        return self.spec.id

    @property
    def available(self) -> bool:
        return self.executor is not None and not self.unavailable_reason

    def provider_tool(self) -> dict[str, Any]:
        return self.spec.provider_tool()


@dataclass(frozen=True)
class SkillActivation:
    """Skill activation attached to a single run."""

    skill: SkillRecord
    resolved_tools: tuple[ResolvedSkillTool, ...] = ()


@dataclass(frozen=True)
class EffectiveSkillSet:
    """Resolved skill prompt and tools for a single agent execution."""

    activations: tuple[SkillActivation, ...] = ()
    prompt_prefix: str = ""
    available_tools: tuple[ResolvedSkillTool, ...] = ()
    unavailable_tools: tuple[ResolvedSkillTool, ...] = ()
    loaded_contexts: tuple[dict[str, Any], ...] = ()
    context_warnings: tuple[str, ...] = ()

    @property
    def skill_ids(self) -> list[str]:
        return [activation.skill.id for activation in self.activations]

    @property
    def skill_aliases(self) -> list[str]:
        return [activation.skill.effective_alias for activation in self.activations]

    @property
    def skill_version_refs(self) -> list[str]:
        return [
            activation.skill.version_ref.canonical_ref or activation.skill.id
            for activation in self.activations
        ]
