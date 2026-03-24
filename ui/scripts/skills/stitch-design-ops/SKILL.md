---
name: stitch-design-ops
description: Stitch design generation skill for shell-enabled Pylon agents. Use when a Pylon agent needs the official Gemini CLI Stitch extension to generate UI screens from prompts, list Stitch projects, inspect screens, or download HTML and images from Stitch.
allowed-tools:
  - Bash(python3 ui/scripts/gemini_stitch_delegate.py:*)
---

# Stitch Design Ops

Use this skill when a shell-enabled Pylon agent needs to interact with Stitch through the official Gemini CLI extension.

## When to Use

- Generating UI screens from text prompts in Stitch
- Listing Stitch projects or retrieving project details
- Listing project screens
- Downloading Stitch-generated HTML or images
- Enhancing prompts before sending them to Stitch

## Workflow

1. Check configuration first.
   Run `python3 ui/scripts/gemini_stitch_delegate.py status`.
2. If config is missing, prefer API key auth.
   Use `python3 ui/scripts/gemini_stitch_delegate.py configure-api-key --api-key ...`.
3. Run Stitch through the official Gemini extension.
   Use `python3 ui/scripts/gemini_stitch_delegate.py run --prompt "..."`.
4. Keep prompts product-specific.
   Include device, audience, visual tone, and required sections or flows.
5. Return operator-ready output.
   Include any project IDs, screen IDs, or downloadable artifact links returned by Stitch.

## Common Commands

```bash
python3 ui/scripts/gemini_stitch_delegate.py status
python3 ui/scripts/gemini_stitch_delegate.py configure-api-key --api-key "$STITCH_API_KEY"
python3 ui/scripts/gemini_stitch_delegate.py run --prompt "What Stitch projects do I have?"
python3 ui/scripts/gemini_stitch_delegate.py run --prompt "Design a modern SaaS landing page for Pylon, focused on multi-agent operations."
```

## Notes

- This path uses the official Stitch Gemini CLI extension.
- Stitch currently relies on Gemini CLI auth plus Stitch extension auth configuration.
- Prefer Stitch for high-level UI generation and exportable screen artifacts.
