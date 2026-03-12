"""Runtime resolution for skill-backed prompts and tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from pylon.sdk.decorators import ToolRegistry as SDKToolRegistry
from pylon.skills.catalog import SkillCatalog, get_default_skill_catalog
from pylon.skills.models import (
    EffectiveSkillSet,
    ResolvedSkillTool,
    SkillActivation,
    SkillRecord,
    SkillToolSpec,
)
from pylon.skills.prompting import build_skill_prompt_prefix


def skill_record_from_mapping(skill_id: str, payload: dict[str, Any]) -> SkillRecord:
    """Normalize a legacy skill payload into a SkillRecord."""
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return SkillRecord(
        id=str(payload.get("id", skill_id)),
        alias=str(payload.get("alias", payload.get("id", skill_id))),
        skill_key=str(payload.get("skill_key", payload.get("alias", payload.get("id", skill_id)))),
        name=str(payload.get("name", skill_id)),
        version=str(payload.get("version", "0.0.1")),
        description=str(payload.get("description", "")),
        content=str(payload.get("content", payload.get("content_preview", ""))),
        content_preview=str(payload.get("content_preview", payload.get("description", "")))[:240],
        category=str(payload.get("category", "other")),
        risk=str(payload.get("risk", "unknown")),
        source=str(payload.get("source", "local")),
        source_kind=str(payload.get("source_kind", "control_plane")),
        tags=tuple(str(tag) for tag in tags if str(tag).strip()),
        path=str(payload.get("path", "")),
        installed_at=str(payload.get("installed_at", "")),
        has_scripts=bool(payload.get("has_scripts", False)),
        dependencies=tuple(str(item) for item in payload.get("dependencies", []) if str(item).strip()) if isinstance(payload.get("dependencies"), list) else (),
        toolsets=tuple(str(item) for item in payload.get("toolsets", []) if str(item).strip()) if isinstance(payload.get("toolsets"), list) else (),
        tools=tuple(),
        prompt_priority=int(payload.get("prompt_priority", 50) or 50),
        trust_class=str(payload.get("trust_class", "internal")),
        approval_class=str(payload.get("approval_class", "auto")),
        max_prompt_chars=int(payload.get("max_prompt_chars", 5000) or 5000),
        digest=str(payload.get("digest", "")),
        references=tuple(str(item) for item in payload.get("references", []) if str(item).strip()) if isinstance(payload.get("references"), list) else (),
        context_contracts=tuple(
            dict(item) for item in payload.get("context_contracts", []) if isinstance(item, dict)
        ) if isinstance(payload.get("context_contracts"), list) else (),
        source_id=str(payload.get("source_id", "")),
        source_revision=str(payload.get("source_revision", "")),
        source_format=str(payload.get("source_format", "")),
    )


class SkillRuntime:
    """Resolves effective skills and executable tools for an agent run."""

    def __init__(self, catalog: SkillCatalog | None = None) -> None:
        self._catalog = catalog or get_default_skill_catalog()

    def effective_catalog(
        self,
        *,
        tenant_id: str | None = None,
        control_plane_skills: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, SkillRecord]:
        merged = {
            skill.id: skill
            for skill in self._catalog.list_skills(tenant_id=tenant_id)
        }
        for skill_id, payload in (control_plane_skills or {}).items():
            merged.setdefault(str(skill_id), skill_record_from_mapping(str(skill_id), dict(payload)))
        return merged

    def rescan(self, *, tenant_id: str | None = None) -> dict[str, int]:
        return self._catalog.rescan(tenant_id=tenant_id)

    def resolve_effective_skill_set(
        self,
        *,
        tenant_id: str | None = None,
        assigned_skill_ids: list[str] | tuple[str, ...] = (),
        explicit_skill_ids: list[str] | tuple[str, ...] = (),
        control_plane_skills: dict[str, dict[str, Any]] | None = None,
        workspace: str | Path | None = None,
    ) -> EffectiveSkillSet:
        catalog = self.effective_catalog(
            tenant_id=tenant_id,
            control_plane_skills=control_plane_skills,
        )
        ordered_ids = _dedupe_strings([
            *[str(item) for item in explicit_skill_ids if str(item).strip()],
            *[str(item) for item in assigned_skill_ids if str(item).strip()],
        ])
        activations: list[SkillActivation] = []
        seen: set[str] = set()
        for skill_id in ordered_ids:
            resolved_skill_id = _resolve_catalog_identifier(catalog, skill_id)
            if resolved_skill_id is None:
                continue
            self._activate_skill(
                resolved_skill_id,
                catalog=catalog,
                activations=activations,
                seen=seen,
                workspace=workspace,
            )
        prompt_prefix = build_skill_prompt_prefix(tuple(activations))
        available_tools: list[ResolvedSkillTool] = []
        unavailable_tools: list[ResolvedSkillTool] = []
        for activation in activations:
            for tool in activation.resolved_tools:
                if tool.available:
                    available_tools.append(tool)
                else:
                    unavailable_tools.append(tool)
        loaded_contexts, context_warnings = _resolve_context_contracts(
            activations,
            workspace=workspace,
        )
        return EffectiveSkillSet(
            activations=tuple(activations),
            prompt_prefix=prompt_prefix,
            available_tools=tuple(_dedupe_tools(available_tools)),
            unavailable_tools=tuple(unavailable_tools),
            loaded_contexts=tuple(loaded_contexts),
            context_warnings=tuple(context_warnings),
        )

    def augment_instruction(
        self,
        base_instruction: str,
        *,
        tenant_id: str | None = None,
        assigned_skill_ids: list[str] | tuple[str, ...] = (),
        explicit_skill_ids: list[str] | tuple[str, ...] = (),
        control_plane_skills: dict[str, dict[str, Any]] | None = None,
        workspace: str | Path | None = None,
    ) -> tuple[str, EffectiveSkillSet]:
        effective = self.resolve_effective_skill_set(
            tenant_id=tenant_id,
            assigned_skill_ids=assigned_skill_ids,
            explicit_skill_ids=explicit_skill_ids,
            control_plane_skills=control_plane_skills,
            workspace=workspace,
        )
        context_prefix = _build_context_prompt_prefix(effective.loaded_contexts)
        prompt_sections = [
            section
            for section in (effective.prompt_prefix, context_prefix)
            if str(section).strip()
        ]
        combined_prefix = "\n\n".join(prompt_sections).strip()
        if not combined_prefix:
            return base_instruction, effective
        if base_instruction.strip():
            return f"{combined_prefix}\n\n---\n\n{base_instruction.strip()}", effective
        return combined_prefix, effective

    def _activate_skill(
        self,
        skill_id: str,
        *,
        catalog: dict[str, SkillRecord],
        activations: list[SkillActivation],
        seen: set[str],
        workspace: str | Path | None,
    ) -> None:
        if skill_id in seen:
            return
        seen.add(skill_id)
        skill = catalog.get(skill_id)
        if skill is None:
            return
        for dependency in skill.dependencies:
            resolved_dependency = _resolve_catalog_identifier(
                catalog,
                dependency,
                preferred_source_id=skill.source_id,
            )
            if resolved_dependency is None:
                continue
            self._activate_skill(
                resolved_dependency,
                catalog=catalog,
                activations=activations,
                seen=seen,
                workspace=workspace,
            )
        resolved_tools = tuple(
            self._resolve_tool(tool, skill=skill, workspace=workspace)
            for tool in skill.tools
        )
        activations.append(SkillActivation(skill=skill, resolved_tools=resolved_tools))

    def _resolve_tool(
        self,
        tool: SkillToolSpec,
        *,
        skill: SkillRecord,
        workspace: str | Path | None,
    ) -> ResolvedSkillTool:
        if tool.approval_class not in {"auto", ""}:
            return ResolvedSkillTool(
                spec=tool,
                skill_id=skill.id,
                unavailable_reason=f"approval class '{tool.approval_class}' is not auto-executable",
            )
        if tool.kind == "platform-ref":
            tool_info = SDKToolRegistry.get(tool.id)
            if tool_info is None:
                return ResolvedSkillTool(
                    spec=tool,
                    skill_id=skill.id,
                    unavailable_reason="platform tool is not registered",
                )
            return ResolvedSkillTool(
                spec=replace(
                    tool,
                    description=tool.description or tool_info.description,
                ),
                skill_id=skill.id,
                executor=_sdk_tool_executor(tool_info.handler),
            )
        if tool.kind != "local-script":
            return ResolvedSkillTool(
                spec=tool,
                skill_id=skill.id,
                unavailable_reason=f"unsupported tool kind: {tool.kind}",
            )
        skill_root = Path(skill.path).expanduser().resolve()
        try:
            entrypoint = (skill_root / tool.entrypoint).resolve(strict=True)
        except FileNotFoundError:
            return ResolvedSkillTool(
                spec=tool,
                skill_id=skill.id,
                unavailable_reason="local tool entrypoint not found",
            )
        if skill_root not in entrypoint.parents and entrypoint != skill_root:
            return ResolvedSkillTool(
                spec=tool,
                skill_id=skill.id,
                unavailable_reason="entrypoint escapes skill package root",
            )
        return ResolvedSkillTool(
            spec=tool,
            skill_id=skill.id,
            executor=_local_script_executor(
                tool=tool,
                entrypoint=entrypoint,
                workspace=workspace,
                skill_id=skill.id,
            ),
        )


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _resolve_catalog_identifier(
    catalog: dict[str, SkillRecord],
    identifier: str,
    *,
    preferred_source_id: str = "",
) -> str | None:
    trimmed = str(identifier).strip()
    if not trimmed:
        return None
    if trimmed in catalog:
        return trimmed
    alias_matches = [
        skill.id
        for skill in catalog.values()
        if skill.effective_alias == trimmed or skill.effective_skill_key == trimmed
    ]
    if preferred_source_id:
        preferred_matches = [
            skill_id
            for skill_id in alias_matches
            if catalog[skill_id].source_id == preferred_source_id
        ]
        if len(preferred_matches) == 1:
            return preferred_matches[0]
    if len(alias_matches) == 1:
        return alias_matches[0]
    return None


def _dedupe_tools(values: list[ResolvedSkillTool]) -> list[ResolvedSkillTool]:
    result: list[ResolvedSkillTool] = []
    seen: set[str] = set()
    for value in values:
        if value.name in seen:
            continue
        seen.add(value.name)
        result.append(value)
    return result


def _resolve_context_contracts(
    activations: list[SkillActivation],
    *,
    workspace: str | Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if workspace is None:
        return [], []
    root = Path(workspace).expanduser().resolve()
    loaded: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_paths: set[str] = set()
    for activation in activations:
        for contract in activation.skill.context_contracts:
            patterns = contract.get("path_patterns", [])
            if not isinstance(patterns, list):
                continue
            matched = None
            for pattern in patterns:
                candidate = (root / str(pattern)).resolve()
                if candidate.exists() and candidate.is_file():
                    matched = candidate
                    break
            if matched is None:
                if bool(contract.get("required", False)):
                    warnings.append(
                        f"missing context contract for skill '{activation.skill.id}': {patterns}"
                    )
                continue
            resolved_key = str(matched)
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            max_chars = int(contract.get("max_chars", 4000) or 4000)
            content = matched.read_text(encoding="utf-8")[:max_chars].strip()
            if not content:
                continue
            loaded.append(
                {
                    "skill_id": activation.skill.id,
                    "contract_id": str(contract.get("contract_id", "")),
                    "path": str(matched),
                    "content": content,
                }
            )
    return loaded, warnings


def _build_context_prompt_prefix(values: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    if not values:
        return ""
    sections = ["You also have the following workspace context files available."]
    for item in values:
        sections.extend(
            [
                "",
                f"=== Context File: {item.get('path', '')} ===",
                str(item.get("content", "")).strip(),
            ]
        )
    return "\n".join(sections).strip()


def _sdk_tool_executor(handler: Any):
    async def execute(payload: dict[str, Any]) -> str:
        result = _invoke_callable(handler, payload)
        if inspect.isawaitable(result):
            result = await result
        return str(result)

    return execute


def _invoke_callable(handler: Any, payload: dict[str, Any]) -> Any:
    signature = inspect.signature(handler)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if not positional:
        return handler()
    if len(positional) == 1:
        return handler(payload)
    return handler(**payload)


def _local_script_executor(
    *,
    tool: SkillToolSpec,
    entrypoint: Path,
    workspace: str | Path | None,
    skill_id: str,
):
    async def execute(payload: dict[str, Any]) -> str:
        cwd = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
        if not cwd.exists():
            cwd.mkdir(parents=True, exist_ok=True)
        if entrypoint.suffix == ".py":
            command = [sys.executable, str(entrypoint)]
        elif entrypoint.suffix == ".js":
            command = ["node", str(entrypoint)]
        elif entrypoint.suffix == ".sh":
            command = ["bash", str(entrypoint)]
        else:
            command = [str(entrypoint)]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "PYLON_SKILL_ID": skill_id,
                "PYLON_TOOL_ID": tool.id,
                "PYLON_TOOL_ARGS_JSON": json.dumps(payload, ensure_ascii=False),
                "PYLON_WORKSPACE": str(cwd),
            },
        )
        stdin = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin),
                timeout=max(int(tool.timeout_seconds or 30), 1),
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Tool '{tool.id}' timed out") from exc
        if process.returncode:
            raise RuntimeError(
                stderr.decode("utf-8", errors="replace").strip()
                or stdout.decode("utf-8", errors="replace").strip()
                or f"Tool '{tool.id}' exited with status {process.returncode}"
            )
        return stdout.decode("utf-8", errors="replace").strip()

    return execute


_DEFAULT_RUNTIME: SkillRuntime | None = None


def get_default_skill_runtime() -> SkillRuntime:
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is None:
        _DEFAULT_RUNTIME = SkillRuntime()
    return _DEFAULT_RUNTIME
