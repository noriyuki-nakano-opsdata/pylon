from __future__ import annotations

import json
import textwrap
from pathlib import Path

from pylon.dsl.parser import PylonProject
from pylon.providers.base import Response, TokenUsage
from pylon.runtime.execution import execute_project_sync
from pylon.runtime.llm import ProviderRegistry
from pylon.skills.adapters.registry import get_default_adapter_registry
from pylon.skills.catalog import SkillCatalog
from pylon.skills.compat import SkillCompatibilityLayer
from pylon.skills.runtime import SkillRuntime


class _ToolCallingProvider:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_name(self) -> str:
        return "fake"

    async def chat(self, messages, **kwargs):
        tool_messages = [message for message in messages if message.role == "tool"]
        if tool_messages:
            return Response(
                content=f"Final answer: {tool_messages[-1].content}",
                model=self._model_id,
                usage=TokenUsage(input_tokens=4, output_tokens=3),
            )
        return Response(
            content="",
            model=self._model_id,
            usage=TokenUsage(input_tokens=3, output_tokens=2),
            tool_calls=[
                {
                    "id": "tool_1",
                    "name": "echo-json",
                    "input": {"name": "pylon"},
                }
            ],
            finish_reason="tool_use",
        )


class _CapturingProvider:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self.system_messages: list[str] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_name(self) -> str:
        return "fake"

    async def chat(self, messages, **kwargs):
        self.system_messages.extend(
            str(message.content)
            for message in messages
            if message.role == "system"
        )
        return Response(
            content="ok",
            model=self._model_id,
            usage=TokenUsage(input_tokens=5, output_tokens=2),
        )


def _write_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "greeter"
    (skill_dir / "tools").mkdir(parents=True)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            id: greeter
            name: Greeter
            description: Adds a greeting tool.
            toolsets: [echo-json]
            ---

            You are a greeting specialist.
            """
        ),
        encoding="utf-8",
    )
    (skill_dir / "tools" / "echo-json.yaml").write_text(
        textwrap.dedent(
            """\
            id: echo-json
            name: Echo JSON
            kind: local-script
            description: Echo a greeting based on stdin JSON.
            entrypoint: scripts/echo.py
            args_schema:
              type: object
              properties:
                name:
                  type: string
              required: [name]
            """
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "echo.py").write_text(
        textwrap.dedent(
            """\
            import json
            import sys

            payload = json.load(sys.stdin)
            print(f"hello {payload['name']}")
            """
        ),
        encoding="utf-8",
    )


def _write_external_skill_repo(base_dir: Path, *, with_cli: bool = False) -> Path:
    repo_root = base_dir / "marketingskills-like"
    analytics_dir = repo_root / "skills" / "analytics-tracking"
    (analytics_dir / "references").mkdir(parents=True)
    (repo_root / "tools" / "integrations").mkdir(parents=True)
    if with_cli:
        (repo_root / "tools" / "clis").mkdir(parents=True)
    (repo_root / "VERSIONS.md").write_text("# Versions\n", encoding="utf-8")
    (repo_root / "tools" / "REGISTRY.md").write_text(
        "| Tool | Category | API | MCP | CLI | SDK | Guide |\n"
        "|---|---|---|---|---|---|---|\n"
        "| ga4 | Analytics | ✓ | ✓ | - | ✓ | [ga4.md](integrations/ga4.md) |\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "integrations" / "ga4.md").write_text(
        "# GA4\n\nUse GA4 for analytics tracking.\n",
        encoding="utf-8",
    )
    (analytics_dir / "SKILL.md").write_text(
        "---\n"
        "name: analytics-tracking\n"
        "description: Set up and audit analytics tracking.\n"
        "metadata:\n"
        "  version: 1.1.0\n"
        "---\n\n"
        "If `.agents/product-marketing-context.md` exists, read it before asking questions.\n",
        encoding="utf-8",
    )
    (analytics_dir / "references" / "event-library.md").write_text(
        "# Event Library\n\nTrack important events.\n",
        encoding="utf-8",
    )
    if with_cli:
        (repo_root / "tools" / "clis" / "ga4.js").write_text(
            "process.stdout.write('{\"ok\":true}')\n",
            encoding="utf-8",
        )
    return repo_root


def _write_basic_agent_skills_repo(base_dir: Path) -> Path:
    repo_root = base_dir / "basic-skills"
    skill_dir = repo_root / "skills" / "briefing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: briefing\n"
        "description: Prepare a short briefing.\n"
        "---\n\n"
        "Summarize the current situation.\n",
        encoding="utf-8",
    )
    return repo_root


def test_skill_catalog_loads_filesystem_skill_and_tool(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    catalog = SkillCatalog(skill_dirs=(str(tmp_path / "skills"),), refresh_ttl_seconds=0)

    skills = catalog.list_skills()

    assert [skill.id for skill in skills] == ["greeter"]
    assert skills[0].tools[0].id == "echo-json"
    assert skills[0].content == "You are a greeting specialist."


def test_default_adapter_registry_classifies_profiles(tmp_path: Path) -> None:
    registry = get_default_adapter_registry()

    marketing_repo = _write_external_skill_repo(tmp_path)
    source_format, profile = registry.classify(marketing_repo)
    assert source_format == "agent-skills-spec"
    assert profile == "marketingskills"

    basic_repo = _write_basic_agent_skills_repo(tmp_path)
    source_format, profile = registry.classify(basic_repo)
    assert source_format == "agent-skills-spec"
    assert profile == "agent-skills-basic"


def test_execute_project_sync_uses_skill_prompt_and_local_tool(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": "skill-runtime",
            "agents": {
                "assistant": {
                    "model": "fake/demo",
                    "role": "Default assistant role.",
                    "skills": ["greeter"],
                }
            },
            "workflow": {
                "nodes": {
                    "start": {
                        "agent": "assistant",
                        "next": "END",
                    }
                }
            },
        }
    )
    registry = ProviderRegistry({"fake": lambda model_id: _ToolCallingProvider(model_id)})
    runtime = SkillRuntime(
        SkillCatalog(skill_dirs=(str(tmp_path / "skills"),), refresh_ttl_seconds=0)
    )

    artifacts = execute_project_sync(
        project,
        input_data={"prompt": "Say hello"},
        workflow_id="skill-runtime",
        provider_registry=registry,
        skill_runtime=runtime,
    )

    assert artifacts.run.state["start_response"] == "Final answer: hello pylon"
    assert artifacts.run.state["last_model"] == "demo"
    node_event = artifacts.run.event_log[0]
    assert node_event["metrics"]["activated_skills"] == ["greeter"]
    assert node_event["metrics"]["activated_skill_aliases"] == ["greeter"]
    assert node_event["metrics"]["activated_skill_version_refs"] == ["greeter"]
    assert node_event["metrics"]["activated_tools"] == ["echo-json"]


def test_imported_agent_skill_loads_workspace_context_contract(tmp_path: Path, monkeypatch) -> None:
    repo_root = _write_external_skill_repo(tmp_path)
    import_root = tmp_path / "imports"
    monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
    compatibility = SkillCompatibilityLayer(import_root=import_root)
    compatibility.sync_source(
        compatibility.normalize_source_payload(
            {"location": str(repo_root), "kind": "local-dir"},
            tenant_id="default",
        )
    )
    workspace = tmp_path / "workspace"
    (workspace / ".agents").mkdir(parents=True)
    (workspace / ".agents" / "product-marketing-context.md").write_text(
        "# Product Marketing Context\n\nTarget audience: product teams.\n",
        encoding="utf-8",
    )
    project = PylonProject.model_validate(
        {
            "version": "1",
            "name": "compat-runtime",
            "agents": {
                "assistant": {
                    "model": "fake/demo",
                    "role": "Default assistant role.",
                    "skills": ["analytics-tracking"],
                }
            },
            "workflow": {"nodes": {"start": {"agent": "assistant", "next": "END"}}},
        }
    )
    provider = _CapturingProvider("demo")
    registry = ProviderRegistry({"fake": lambda model_id: provider})
    runtime = SkillRuntime(SkillCatalog(skill_dirs=(), refresh_ttl_seconds=0))

    artifacts = execute_project_sync(
        project,
        input_data={"prompt": "Audit our tracking", "workspace": str(workspace)},
        workflow_id="compat-runtime",
        provider_registry=registry,
        skill_runtime=runtime,
    )

    assert any("Target audience: product teams." in message for message in provider.system_messages)
    node_event = artifacts.run.event_log[0]
    assert node_event["metrics"]["activated_skill_aliases"] == ["analytics-tracking"]
    assert node_event["metrics"]["activated_skill_version_refs"][0].startswith(
        "marketingskills-like:analytics-tracking@"
    )
    assert node_event["metrics"]["loaded_skill_contexts"][0]["path"].endswith(
        ".agents/product-marketing-context.md"
    )


def test_sync_source_uses_single_checkout_and_persists_snapshot_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = _write_external_skill_repo(tmp_path)
    import_root = tmp_path / "imports"
    monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
    compatibility = SkillCompatibilityLayer(import_root=import_root)
    payload = compatibility.normalize_source_payload(
        {"location": str(repo_root), "kind": "local-dir"},
        tenant_id="default",
    )
    calls: list[str] = []
    original_prepare_checkout = compatibility._prepare_checkout

    def counted_prepare_checkout(source_payload: dict[str, str]) -> Path:
        calls.append(str(source_payload["id"]))
        return original_prepare_checkout(source_payload)

    monkeypatch.setattr(compatibility, "_prepare_checkout", counted_prepare_checkout)

    report = compatibility.sync_source(payload)

    assert calls == [str(payload["id"])]
    assert report["snapshot_id"]
    assert report["snapshot"]["snapshot_id"] == report["snapshot_id"]
    snapshot_path = (
        import_root
        / str(payload["id"])
        / "snapshots"
        / f"{report['snapshot_id']}.json"
    )
    assert snapshot_path.exists()
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_payload["source_id"] == str(payload["id"])
    assert snapshot_payload["revision"] == report["source_revision"]
    assert (import_root / str(payload["id"]) / "normalized" / "manifest.json").exists()
    staging_root = import_root / str(payload["id"]) / ".staging"
    assert staging_root.exists()
    assert list(staging_root.iterdir()) == []


def test_sync_source_keeps_manual_tool_candidates_pending_until_approved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = _write_external_skill_repo(tmp_path, with_cli=True)
    import_root = tmp_path / "imports"
    monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
    compatibility = SkillCompatibilityLayer(import_root=import_root)
    payload = compatibility.normalize_source_payload(
        {"location": str(repo_root), "kind": "local-dir"},
        tenant_id="default",
    )

    initial_report = compatibility.sync_source(payload)

    assert initial_report["promoted_tool_count"] == 0
    pending_candidates = compatibility.list_tool_candidates(str(payload["id"]))
    assert pending_candidates[0]["review"]["state"] == "pending"
    assert pending_candidates[0]["review"]["promoted"] is False
    skill_dir = import_root / str(payload["id"]) / "normalized" / "skills" / "analytics-tracking"
    assert not (skill_dir / "tools").exists()

    compatibility.set_tool_candidate_state(
        source_id=str(payload["id"]),
        candidate_id="analytics-tracking:ga4:cli",
        state="approved",
        note="verified local CLI binding",
    )
    approved_report = compatibility.sync_source(payload)

    approved_candidates = compatibility.list_tool_candidates(str(payload["id"]))
    assert approved_report["promoted_tool_count"] == 1
    assert approved_candidates[0]["review"]["state"] == "approved"
    assert approved_candidates[0]["review"]["promoted"] is True
    assert approved_candidates[0]["review"]["note"] == "verified local CLI binding"
    assert (skill_dir / "tools" / "ga4.yaml").exists()


def test_sync_source_does_not_promote_non_bindable_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = _write_external_skill_repo(tmp_path, with_cli=False)
    import_root = tmp_path / "imports"
    monkeypatch.setenv("PYLON_SKILL_IMPORT_ROOT", str(import_root))
    compatibility = SkillCompatibilityLayer(import_root=import_root)
    payload = compatibility.normalize_source_payload(
        {"location": str(repo_root), "kind": "local-dir"},
        tenant_id="default",
    )

    compatibility.sync_source(payload)
    compatibility.set_tool_candidate_state(
        source_id=str(payload["id"]),
        candidate_id="analytics-tracking:ga4:guide",
        state="approved",
        note="guide reviewed but not executable",
    )
    report = compatibility.sync_source(payload)

    candidates = compatibility.list_tool_candidates(str(payload["id"]))
    assert report["promoted_tool_count"] == 0
    assert candidates[0]["review"]["state"] == "approved"
    assert candidates[0]["review"]["bindable"] is False
    assert candidates[0]["review"]["promoted"] is False
    assert "not executable" in candidates[0]["review"]["promotion_blocked_reason"]
