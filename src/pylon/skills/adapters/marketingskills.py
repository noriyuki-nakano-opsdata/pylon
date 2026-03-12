"""Profile adapter for marketingskills-like repositories."""

from __future__ import annotations

from pathlib import Path

from pylon.skills.adapters.agent_skills_basic import AgentSkillsBasicAdapter
from pylon.skills.adapters.base import tool_registry_index
from pylon.skills.import_types import ContextContract, ToolCandidate


class MarketingskillsAdapter(AgentSkillsBasicAdapter):
    profile_name = "marketingskills"
    priority = 100

    def matches_repository(self, root: Path) -> bool:
        return (
            (root / "skills").is_dir()
            and any((root / "skills").glob("*/SKILL.md"))
            and (root / "tools" / "REGISTRY.md").exists()
            and (root / "VERSIONS.md").exists()
        )

    def build_context_contracts(self, *, skill_id: str, body: str) -> list[ContextContract]:
        contracts: list[ContextContract] = []
        mentions_context = (
            ".agents/product-marketing-context.md" in body
            or ".claude/product-marketing-context.md" in body
        )
        if skill_id == "product-marketing-context" or mentions_context:
            contracts.append(
                ContextContract(
                    contract_id=f"{skill_id}:product-marketing-context",
                    skill_id=skill_id,
                    path_patterns=(
                        ".agents/product-marketing-context.md",
                        ".claude/product-marketing-context.md",
                    ),
                    mode="read-write" if skill_id == "product-marketing-context" else "read",
                    required=False,
                    description="Shared product marketing context used by marketing skills.",
                    discovery_hint="Read the shared product marketing context before asking repeated foundation questions.",
                    max_chars=5000,
                )
            )
        inherited = super().build_context_contracts(skill_id=skill_id, body=body)
        deduped: dict[str, ContextContract] = {}
        for contract in [*contracts, *inherited]:
            if "product-marketing-context.md" in " ".join(contract.path_patterns) and contract.contract_id != f"{skill_id}:product-marketing-context":
                continue
            deduped[contract.contract_id] = contract
        return list(deduped.values())

    def build_tool_candidates(self, *, source_root: Path, skill_id: str) -> list[ToolCandidate]:
        candidates: list[ToolCandidate] = []
        registry_index = tool_registry_index(source_root / "tools" / "REGISTRY.md")
        for tool_id in self._tool_map().get(skill_id, ()):
            registry_row = registry_index.get(tool_id, {})
            guide_path = source_root / "tools" / "integrations" / f"{tool_id}.md"
            cli_path = source_root / "tools" / "clis" / f"{tool_id}.js"
            if cli_path.exists():
                candidates.append(
                    ToolCandidate(
                        candidate_id=f"{skill_id}:{tool_id}:cli",
                        skill_id=skill_id,
                        origin_path=str(cli_path.relative_to(source_root)),
                        adapter_kind="repo-cli",
                        proposed_tool_id=tool_id,
                        confidence=0.95,
                        descriptor_payload={
                            "id": tool_id,
                            "name": tool_id,
                            "kind": "local-script",
                            "description": str(registry_row.get("Category", "Repo CLI tool")).strip() or "Repo CLI tool",
                            "entrypoint": f"scripts/{tool_id}.js",
                            "args_schema": {"type": "object", "properties": {}},
                            "approval_class": "manual",
                            "sandbox": "inherit",
                            "read_only": False,
                        },
                        review_required=True,
                    )
                )
            elif guide_path.exists():
                candidates.append(
                    self.guide_candidate(
                        source_root=source_root,
                        skill_id=skill_id,
                        tool_id=tool_id,
                        guide_path=guide_path,
                    )
                )
        return candidates

    @staticmethod
    def _tool_map() -> dict[str, tuple[str, ...]]:
        return {
            "analytics-tracking": ("ga4", "mixpanel", "segment", "google-search-console"),
            "paid-ads": ("google-ads", "meta-ads", "linkedin-ads", "tiktok-ads"),
            "email-sequence": ("customer-io", "mailchimp", "resend", "sendgrid"),
            "referral-program": ("rewardful", "tolt", "mention-me", "partnerstack"),
            "revops": ("hubspot", "salesforce", "apollo", "zoominfo"),
            "ad-creative": ("meta-ads", "google-ads", "linkedin-ads", "tiktok-ads"),
            "seo-audit": ("google-search-console", "semrush", "ahrefs", "dataforseo"),
            "social-content": ("buffer",),
            "pricing-strategy": ("stripe", "paddle"),
        }
