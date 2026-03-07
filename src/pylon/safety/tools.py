"""Structured tool safety descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field

from pylon.types import TrustLevel


@dataclass(frozen=True)
class ToolDescriptor:
    """Local-policy tool descriptor used for dynamic safety checks."""

    name: str
    input_trust: TrustLevel = TrustLevel.TRUSTED
    reads_untrusted_input: bool = False
    accesses_secrets: bool = False
    writes_external: bool = False
    requires_approval: bool = False
    deterministic: bool = True
    secret_scopes: frozenset[str] = field(default_factory=frozenset)
    effect_scopes: frozenset[str] = field(default_factory=frozenset)
    network_egress_policy: str = "none"


_BUILTIN_TOOL_DESCRIPTORS: dict[str, ToolDescriptor] = {
    "vault-read": ToolDescriptor(
        name="vault-read",
        accesses_secrets=True,
        secret_scopes=frozenset({"vault"}),
    ),
    "secret-read": ToolDescriptor(
        name="secret-read",
        accesses_secrets=True,
        secret_scopes=frozenset({"secrets"}),
    ),
    "env-read": ToolDescriptor(
        name="env-read",
        accesses_secrets=True,
        secret_scopes=frozenset({"env"}),
    ),
    "github-pr-approve": ToolDescriptor(
        name="github-pr-approve",
        writes_external=True,
        effect_scopes=frozenset({"github.pr.approve"}),
    ),
    "github-pr-comment": ToolDescriptor(
        name="github-pr-comment",
        writes_external=True,
        effect_scopes=frozenset({"github.pr.comment"}),
    ),
    "github-pr-request-changes": ToolDescriptor(
        name="github-pr-request-changes",
        writes_external=True,
        effect_scopes=frozenset({"github.pr.request_changes"}),
    ),
    "git-push": ToolDescriptor(
        name="git-push",
        writes_external=True,
        effect_scopes=frozenset({"git.push"}),
    ),
    "db-write": ToolDescriptor(
        name="db-write",
        writes_external=True,
        effect_scopes=frozenset({"db.write"}),
    ),
    "api-call": ToolDescriptor(
        name="api-call",
        writes_external=True,
        effect_scopes=frozenset({"api.call"}),
        network_egress_policy="restricted",
    ),
}


def resolve_tool_descriptor(name: str) -> ToolDescriptor:
    """Resolve a structured tool descriptor from local policy defaults."""
    return _BUILTIN_TOOL_DESCRIPTORS.get(name, ToolDescriptor(name=name))
