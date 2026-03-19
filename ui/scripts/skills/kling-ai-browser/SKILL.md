---
name: kling-ai-browser
description: Browser automation skill for Kling AI image and video generation workflows. Use when Pylon agents need to generate visual assets, collect outputs, and download them from the Kling AI web app. If a request mentions Killing AI, treat it as Kling AI unless the user says otherwise.
allowed-tools:
  - Bash(agent-browser:*)
  - Bash(npx agent-browser:*)
---

# Kling AI Browser

Use this skill for Kling AI web workflows.

## When to Use

- Generating image or video assets from prompts
- Running short creative experiments and variant sweeps
- Downloading completed outputs into a local working directory

## Reference Routing

- Read [references/setup.md](references/setup.md) for session setup.

## Workflow

1. Reuse a saved authenticated browser session.
2. Open the global app at `https://app.klingai.com/global/`.
3. Snapshot before every major interaction.
4. Record prompt, aspect ratio, mode, and generation id if visible.
5. Wait for completion before downloading.

## Common Commands

```bash
agent-browser --session-name kling-ai open https://app.klingai.com/global/
agent-browser --session-name kling-ai wait --load networkidle
agent-browser --session-name kling-ai snapshot -i
```

## Output Shape

- Prompt used
- Mode used: image, video, or template
- Output identifiers if shown
- Download path or blocker
