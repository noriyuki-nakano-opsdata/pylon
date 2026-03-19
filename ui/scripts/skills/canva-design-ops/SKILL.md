---
name: canva-design-ops
description: Canva AI Connector skill for shell-enabled Pylon agents. Use when a Pylon agent needs Canva through the host-authenticated Claude MCP server for design creation, editing, search, or workspace-aware content operations.
allowed-tools:
  - Bash(python3 ui/scripts/claude_mcp_delegate.py:*)
---

# Canva Design Ops

Use this skill when a shell-enabled Pylon agent needs Canva access and the host machine has Canva MCP configured in Claude Code.

## When to Use

- Creating or updating Canva designs through the AI Connector
- Searching Canva workspace content from an agent
- Generating presentations, social assets, or branded layouts in Canva
- Summarizing or retrieving Canva content without direct browser work

## Workflow

1. Check host MCP status first.
   Run `python3 ui/scripts/claude_mcp_delegate.py status --server canva`.
2. If status is `Needs authentication`, stop and ask the operator to finish Canva auth in Claude Code.
3. Use the host-authenticated bridge for real work.
   Run `python3 ui/scripts/claude_mcp_delegate.py run --server canva --prompt '...'`.
4. Keep prompts explicit.
   Include the target design type, audience, content blocks, and any brand constraints.
5. Return operator-ready outcomes.
   Summarize what Canva object was created or updated, and include any links or IDs returned by Claude.

## Common Commands

```bash
python3 ui/scripts/claude_mcp_delegate.py status --server canva
python3 ui/scripts/claude_mcp_delegate.py run --server canva --prompt "Use Canva to draft a 5-slide product overview deck for Pylon."
```

## Notes

- This path depends on the host Claude Code session having a connected `canva` MCP server.
- Prefer Canva MCP over browser automation for native Canva tasks.
