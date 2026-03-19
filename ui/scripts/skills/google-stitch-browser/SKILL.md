---
name: google-stitch-browser
description: Browser automation skill for Google Stitch at stitch.withgoogle.com. Use when Pylon agents need to prompt Stitch, iterate on generated UI, export HTML or CSS, or hand designs off to Figma.
allowed-tools:
  - Bash(agent-browser:*)
  - Bash(npx agent-browser:*)
---

# Google Stitch Browser

Use this skill for Google Stitch workflows driven through the web UI.

## When to Use

- Generating UI from prompts or reference images in Stitch
- Iterating on themes, layout, and variants
- Exporting HTML/CSS output
- Exporting or handing work off to Figma

## Reference Routing

- Read [references/setup.md](references/setup.md) for session setup and export expectations.

## Workflow

1. Reuse a saved authenticated browser session when available.
2. Open `https://stitch.withgoogle.com/`.
3. Snapshot the page and work from element refs.
4. Keep prompts explicit: platform, layout, visual style, CTA hierarchy, responsive intent.
5. After generation, capture both the output and the export path chosen.

## Common Commands

```bash
agent-browser --session-name stitch-google open https://stitch.withgoogle.com/
agent-browser --session-name stitch-google wait --load networkidle
agent-browser --session-name stitch-google snapshot -i
```

## Output Shape

- Prompt used
- Generated concept summary
- Export action taken: HTML/CSS or Figma
- Download path or blocker
