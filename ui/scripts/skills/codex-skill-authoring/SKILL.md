---
name: codex-skill-authoring
description: Use when creating or updating repository-local Claude or Codex skills in ui/scripts/skills, especially for SKILL.md design, progressive disclosure, agents/openai.yaml metadata, naming, and reference routing.
metadata:
  category: meta
  risk: safe
  tags:
    - skills
    - codex
    - claude
    - authoring
---

# Codex Skill Authoring

Use this skill when the task is defining or refining a reusable skill package for this repository, not when answering a one-off prompt. It is optimized for creating skills under `ui/scripts/skills/` that match the conventions already used in this codebase.

## When to Use

- Creating a new skill folder in `ui/scripts/skills/`
- Rewriting an existing `SKILL.md` to improve triggering or workflow clarity
- Splitting a large skill into `references/` for progressive disclosure
- Adding or refreshing `agents/openai.yaml`
- Reviewing whether a task should be a skill, a script, or plain prompt guidance

## Reference Routing

- Read [references/skill-design-checklist.md](references/skill-design-checklist.md) when deciding metadata, folder contents, or how much detail belongs in `SKILL.md`.
- Read [references/repo-conventions.md](references/repo-conventions.md) when choosing placement, naming, or `agents/openai.yaml` values for this repository.

## Workflow

1. Confirm the job is reusable.
   Convert the request into a skill only when the workflow is likely to repeat or needs stable instructions, bundled references, or deterministic scripts.
2. Collect concrete examples first.
   Capture at least three example requests, expected outputs, and trigger phrases before writing the skill.
3. Choose the minimum structure.
   Start with `SKILL.md`. Add `references/` only for details that should load on demand. Add `scripts/` only when deterministic execution is meaningfully better than prose.
4. Write metadata for triggering.
   Make `name` short and hyphenated. Make `description` specific enough that the runtime can infer when to invoke the skill.
5. Keep `SKILL.md` lean.
   Put only overview, use conditions, workflow, output shape, heuristics, and anti-patterns in the main file. Move long examples, checklists, and variant-specific details to `references/`.
6. Add UI metadata.
   Create or refresh `agents/openai.yaml` with `display_name`, `short_description`, `default_prompt`, and `allow_implicit_invocation`.
7. Validate by inspection.
   Check frontmatter parse, file layout, naming, and that the skill can be understood without extra documentation files.

## Output Shape

- Skill scope: what the skill handles and what it does not
- Triggering guidance: phrases, contexts, and adjacent tasks
- File plan: `SKILL.md`, optional `references/`, optional `scripts/`, optional `assets/`
- Main workflow: ordered operator steps
- Validation notes: likely failure modes and missing inputs

## Heuristics

- Prefer one clear skill over a broad "do everything" meta skill.
- If a section is only relevant in one variant, move it to a reference file.
- If the same code would be rewritten repeatedly, create a script instead of embedding code blocks.
- The `description` drives invocation; optimize it for recall, not marketing tone.
- Do not add README-style files to explain the skill package.

## Anti-Patterns

- Writing a long tutorial into `SKILL.md` instead of routing to references
- Using vague descriptions such as "handles docs" or "helps with code"
- Adding scripts before confirming they are actually needed
- Mixing repository conventions, domain reference material, and workflow instructions in one file
- Creating a skill for a task that will only happen once
