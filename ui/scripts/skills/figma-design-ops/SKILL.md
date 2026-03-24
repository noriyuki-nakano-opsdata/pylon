---
name: figma-design-ops
description: Figma design handoff and automation skill for shell-enabled or browser-enabled Pylon agents. Use for Figma Dev Mode MCP setup, REST API inspection with FIGMA_ACCESS_TOKEN, design asset export, frame inspection, and browser-driven design review workflows.
allowed-tools:
  - Bash(python3 ui/scripts/claude_mcp_delegate.py:*)
  - Bash(python3 ui/scripts/figma_rest.py:*)
  - Bash(python3 ui/scripts/figma_mcp_probe.py:*)
  - Bash(agent-browser:*)
  - Bash(npx agent-browser:*)
---

# Figma Design Ops

Use this skill when a Pylon agent needs to work with Figma files, frames, assets, or design handoff workflows.

## When to Use

- Inspecting a Figma file from a file key or node URL
- Exporting node images or assets for implementation
- Reviewing comments and handoff metadata
- Setting up or using the official Figma MCP server
- Browser automation inside Figma when REST coverage is insufficient

## Reference Routing

- Read [references/setup.md](references/setup.md) for auth options and MCP endpoints.

## Workflow

1. For Pylon agents, prefer the host-authenticated Claude MCP bridge first.
2. Run `python3 ui/scripts/claude_mcp_delegate.py status --server figma`.
3. If the host `figma` MCP server is connected, use `python3 ui/scripts/claude_mcp_delegate.py run --server figma --prompt '...'`.
4. Otherwise, use `python3 ui/scripts/figma_rest.py` with `FIGMA_ACCESS_TOKEN` for file reads, nodes, images, and comments.
5. Use `agent-browser` only for actions not covered by the REST helper, such as Dev Mode navigation, manual review, or UI-only workflows.
6. For remote MCP, pass full Figma file or node links. Remote MCP is link-based and does not support desktop-style current-selection context.
7. Keep requests narrow. Prefer file keys, node ids, and specific export ranges over whole-file dumps.
8. For asset export, use the REST helper with `images --download-dir` before falling back to browser downloads.

## Common Commands

```bash
export FIGMA_ACCESS_TOKEN="..."
export FIGMA_MCP_URL="https://mcp.figma.com/mcp"

python3 ui/scripts/claude_mcp_delegate.py status --server figma
python3 ui/scripts/claude_mcp_delegate.py run --server figma --prompt "Inspect this Figma URL and summarize the main frames: https://www.figma.com/file/ABC123"
python3 ui/scripts/figma_mcp_probe.py initialize
python3 ui/scripts/figma_mcp_probe.py tools
python3 ui/scripts/figma_rest.py me
python3 ui/scripts/figma_rest.py file --file-key ABC123
python3 ui/scripts/figma_rest.py nodes --file-key ABC123 --node-ids 1:2,3:4
python3 ui/scripts/figma_rest.py images --file-key ABC123 --node-ids 1:2 --format png --download-dir ./tmp/figma-assets
python3 ui/scripts/figma_rest.py comments --file-key ABC123

agent-browser --session-name figma open https://www.figma.com/file/ABC123
agent-browser --session-name figma wait --load networkidle
agent-browser --session-name figma snapshot -i
```

## Output Shape

- Auth path used: remote MCP, REST token, or browser session
- Target file or node ids
- Commands run
- Result summary: exported assets, comments, or blocker

## Anti-Patterns

- Scraping Figma UI when the REST helper can do the job
- Whole-file exports when only one frame is needed
- Running browser automation without a saved session for authenticated pages
