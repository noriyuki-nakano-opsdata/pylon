# Setup

## Preferred Path: Official Figma Remote MCP

Figma provides both:

- desktop MCP server at `http://127.0.0.1:3845/mcp`
- remote MCP server at `https://mcp.figma.com/mcp`

For this repo, prefer the remote server.

Use MCP when the host client can attach to external MCP servers.

For shell verification inside this repo:

```bash
export FIGMA_MCP_URL="https://mcp.figma.com/mcp"
python3 ui/scripts/claude_mcp_delegate.py status --server figma
python3 ui/scripts/figma_mcp_probe.py initialize
python3 ui/scripts/figma_mcp_probe.py tools
```

Expected behavior:

- Remote MCP may return `401 Unauthorized` unless the host client completes the official auth flow.
- Remote MCP is link-based. Pass a copied Figma file URL or node URL in prompts instead of relying on current desktop selection.
- For Pylon agent usage, route through `python3 ui/scripts/claude_mcp_delegate.py run --server figma --prompt '...'` so the agent can reuse the host-authenticated Claude MCP session.

## REST Token Fallback

For shell-enabled Pylon agents, the practical fallback is a Figma personal access token.

1. Generate a personal access token in Figma Settings > Security
2. Export:

```bash
export FIGMA_ACCESS_TOKEN="..."
```

3. Use the helper:

```bash
python3 ui/scripts/figma_rest.py file --file-key ABC123
```

## Browser Session Fallback

Use browser automation for UI-only tasks.

```bash
agent-browser --session-name figma open https://www.figma.com/
```

Log in once and reuse the saved session.

## Decision Rule

- Use MCP first when available
- Prefer remote MCP over desktop MCP
- Use REST token for file, node, image, and comment reads
- Use browser automation for Dev Mode UI navigation, manual review, or unsupported interactions
