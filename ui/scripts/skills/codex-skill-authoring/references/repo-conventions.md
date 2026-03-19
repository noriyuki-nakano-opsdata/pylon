# Repository Conventions

Use this reference when creating or updating a skill in this repository.

## Placement

- Store repository-local skills under `ui/scripts/skills/<skill-name>/`.
- Name the folder exactly after the skill `name`.

## Typical File Set

```text
ui/scripts/skills/<skill-name>/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── ...
```

Not every skill needs `references/`, `scripts/`, or `assets/`. Add them only when justified by the workflow.

## Existing Style

The local skills in this repository generally use:

- short YAML frontmatter
- concise sections with flat bullet lists
- an explicit `When to Use` section
- a deterministic `Workflow` section
- optional `agents/openai.yaml` with implicit invocation enabled

## agents/openai.yaml Pattern

```yaml
interface:
  display_name: "Skill Display Name"
  short_description: "Brief operator-facing summary"
  default_prompt: "Use $skill-name to ..."
policy:
  allow_implicit_invocation: true
```

Keep these values short and directly aligned with the `SKILL.md` description.

## Practical Authoring Pattern

1. Start with the smallest viable `SKILL.md`.
2. Split heavy detail into `references/`.
3. Add `agents/openai.yaml`.
4. Re-read the description and ask whether it would trigger for the real user phrasing.
5. Verify the skill is discoverable by filesystem scan and does not rely on hidden setup.
