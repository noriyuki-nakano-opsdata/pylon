# Skill Design Checklist

Use this reference when deciding whether to create a skill and how to shape its contents.

## Before Creating the Skill

- Confirm the task is reusable, fragile, or domain-specific enough to justify a skill.
- Gather at least three concrete example prompts.
- Identify what output the agent should produce each time.
- Identify whether deterministic scripts are required or whether prose instructions are sufficient.

## Frontmatter Rules

- `name`: lowercase letters, digits, and hyphens only
- `description`: explicit about task type, scope, and invocation cues
- Keep top-level metadata minimal.
- Put extra classification fields under `metadata` unless the runtime explicitly expects them at top level.

## What Belongs in SKILL.md

- Overview
- When to use
- Reference routing
- Workflow
- Output shape
- Heuristics
- Anti-patterns

Keep it concise. If a section becomes long or highly variant-specific, move it into `references/`.

## When to Add references/

- Large domain-specific rules
- Detailed examples or templates
- Variant-specific guidance
- Checklists that are useful only for some requests

Every reference file should be linked directly from `SKILL.md`.

## When to Add scripts/

- A task needs deterministic execution
- The same code would otherwise be rewritten often
- The script is simpler and safer than prose instructions

Do not add scripts only because code is possible.

## Validation Questions

- Would the skill trigger correctly from its `description` alone?
- Can a reader understand the core workflow from `SKILL.md` without opening every reference file?
- Are references one hop away from `SKILL.md` rather than nested several levels deep?
- Does the folder avoid extra docs such as `README.md` or process notes?
- Is the structure smaller than the initial instinct suggested?
