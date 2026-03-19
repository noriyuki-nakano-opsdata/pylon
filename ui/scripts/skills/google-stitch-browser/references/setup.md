# Setup

Google Stitch currently works best for Pylon through browser automation.

## Session Setup

Use a persistent browser session:

```bash
agent-browser --session-name stitch-google open https://stitch.withgoogle.com/
```

Log in once, then reuse the saved session for future runs.

## Practical Notes

- Stitch can generate UI from prompts or reference images
- Stitch can export to HTML/CSS or Figma
- Prefer downloading exports into a known working directory per run
