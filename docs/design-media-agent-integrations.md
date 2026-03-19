# Design And Media Agent Integrations

## Goal

Enable Pylon agents to work with Figma, Google Stitch, and Kling AI using the integration primitives available today.

## Integration Strategy

- `Figma`: host-authenticated Claude MCP bridge first, then REST token helper, then browser automation fallback
- `Canva`: host-authenticated Claude MCP bridge
- `Stitch`: official Gemini CLI extension and Stitch MCP
- `Google Stitch`: browser automation via `agent-browser` as fallback
- `Kling AI`: browser automation via `agent-browser`

## Figma

Preferred options:

- Remote MCP: `https://mcp.figma.com/mcp`
- Desktop MCP: `http://127.0.0.1:3845/mcp` as fallback only

Repo-local probe:

```bash
export FIGMA_MCP_URL="https://mcp.figma.com/mcp"
python3 ui/scripts/claude_mcp_delegate.py status --server figma
python3 ui/scripts/claude_mcp_delegate.py run --server figma --prompt "Inspect this Figma link and summarize the main frames: https://www.figma.com/file/ABC123"
python3 ui/scripts/figma_mcp_probe.py initialize
python3 ui/scripts/figma_mcp_probe.py tools
```

Fallback option:

```bash
export FIGMA_ACCESS_TOKEN="..."
python3 ui/scripts/figma_rest.py me
```

## Canva

Use the host-authenticated Claude MCP bridge:

```bash
python3 ui/scripts/claude_mcp_delegate.py status --server canva
python3 ui/scripts/claude_mcp_delegate.py run --server canva --prompt "Use Canva to create a simple social card announcing the Pylon GTM control tower."
```

This depends on the host Claude Code session having `canva` configured and authenticated.

## Stitch

Preferred path uses the official Gemini CLI extension:

```bash
python3 ui/scripts/gemini_stitch_delegate.py status
python3 ui/scripts/gemini_stitch_delegate.py configure-api-key --api-key "$STITCH_API_KEY"
python3 ui/scripts/gemini_stitch_delegate.py run --prompt "What Stitch projects do I have?"
python3 ui/scripts/gemini_stitch_delegate.py run --prompt "Design a modern SaaS landing page for Pylon, focused on multi-agent operations."
```

Current official Stitch extension details observed locally:

- Extension repo: `https://github.com/gemini-cli-extensions/stitch`
- Installed extension: `Stitch 0.1.4`
- MCP endpoint: `https://stitch.googleapis.com/mcp`

Use browser automation only if the Gemini extension path is unavailable.

## Google Stitch

Use a saved browser session:

```bash
agent-browser --session-name stitch-google open https://stitch.withgoogle.com/
```

Stitch is best suited to concept generation and export to HTML/CSS or Figma.

## Kling AI

Use a saved browser session:

```bash
agent-browser --session-name kling-ai open https://app.klingai.com/global/
```

Treat references to `Killing AI` as `Kling AI` unless the request explicitly says otherwise.

## Seeded Agents

Recommended agents for these integrations:

- `design-integration-engineer`
- `creative-automation-producer`
- `ui-designer`
- `automation-engineer`
- `integration-engineer`
