# Agent Skills Runtime Design

## Goal

Add first-class Agent Skills to pylon so that:

- skills are loaded dynamically from the filesystem
- skills can contribute both instructions and executable tools
- assigned skills are actually applied during agent execution
- the same behavior holds across generic runtime execution, lifecycle handlers, and queued runs

This design treats a skill as a **capability bundle**:

- instruction layer: domain-specific guidance injected into the system prompt
- tool layer: additional tools or tool aliases exposed to the agent at runtime
- policy layer: trust, approval, sandbox, and resource constraints attached to the skill

## Design Principles

- Compatible by default: a directory that only contains `SKILL.md` loads as a prompt-only skill.
- Explicit tool semantics: executable tools require descriptors, not filename guessing.
- No hidden privilege escalation: a skill can narrow permissions, but never widen them beyond agent and tenant policy.
- Single resolution model: the same effective skill set must be computed for all execution modes.
- Filesystem is source of truth for dynamic skills: control-plane persistence is not the primary registry for file-backed skills.
- Human-readable packages: operators can understand a skill package from disk without reverse-engineering code.

## Non-Goals

- Remote package distribution or marketplace protocols
- Arbitrary shell execution without descriptor and policy checks
- Allowing a skill to silently replace platform safety policy

## Current Constraints In Pylon

- Skills API is currently a compatibility surface over `RouteStore.skills`, not a real dynamic catalog.
- Generic workflow runtime already has a single `static_instruction` injection point for provider-backed nodes.
- Lifecycle custom handlers bypass that generic runtime path and call provider-backed helpers directly.
- Queued mode does not execute generic LLM nodes when no custom handler exists, so behavior diverges today.
- DSL agent definitions do not currently include `skills`.

Relevant code:

- `src/pylon/api/routes.py`
- `src/pylon/runtime/execution.py`
- `src/pylon/lifecycle/orchestrator.py`
- `src/pylon/control_plane/workflow_service.py`
- `src/pylon/dsl/parser.py`
- `src/pylon/types.py`

## Skill Package Format

### Directory Layout

```text
<skill-id>/
  SKILL.md
  tools/
    <tool-id>.yaml
  scripts/
    <entrypoints>
  assets/
    <optional references>
```

### `SKILL.md`

`SKILL.md` remains mandatory. It contains YAML frontmatter and a Markdown body.

Example:

```md
---
id: api-design
name: API Design
version: 1.2.0
description: Design and critique external-facing APIs.
tags: [backend, api, contracts]
category: development
trust_class: internal
approval_class: review
prompt_priority: 50
dependencies: [schema-review]
toolsets: [openapi-lint, schema-diff]
max_prompt_chars: 5000
---

You are operating as an API design specialist.

Prefer explicit contracts, backward-compatible changes, typed error envelopes,
and migration notes when introducing new fields or endpoints.
```

### Tool Descriptor

Executable tools are declared under `tools/*.yaml`.

Example:

```yaml
id: openapi-lint
name: OpenAPI Lint
kind: local-script
description: Validate and lint OpenAPI files in the current workspace.
entrypoint: scripts/openapi_lint.py
args_schema:
  type: object
  properties:
    path:
      type: string
      description: Relative path to the OpenAPI file.
  required: [path]
timeout_seconds: 20
read_only: true
sandbox: inherit
trust_class: internal
approval_class: auto
resource_limits:
  max_output_bytes: 65536
  max_cpu_seconds: 10
```

Rules:

- `SKILL.md` without `tools/*.yaml` is valid and prompt-only.
- `tools/*.yaml` without `SKILL.md` is invalid.
- `toolsets` in `SKILL.md` must reference descriptor IDs or existing platform tool IDs.
- local script tools must use explicit descriptors; scripts are never auto-exposed solely because they exist.

## Runtime Model

### Core Concepts

- `SkillRecord`: normalized metadata and content loaded from disk or control-plane
- `ToolBinding`: either an existing platform tool reference or a file-backed local tool definition
- `SkillActivation`: a resolved skill for one run, with instructions, tools, and effective policy
- `EffectiveSkillSet`: the final merged result attached to an agent execution

### Resolution Order

For a given `tenant_id`, `agent_id`, and run:

1. load tenant-local file skills
2. load shared file skills
3. overlay control-plane skills
4. overlay generated built-ins such as lifecycle catalog entries when needed
5. resolve the agent's assigned skills
6. union any run-scoped explicit skills such as lifecycle `selected_skills`
7. expand dependencies
8. apply policy intersection
9. build final prompt prefix and tool exposure list

Conflict rule:

- later layers override metadata
- instruction bodies are not concatenated on collision; the winning skill ID is singular
- collisions are logged with source and digest

### Policy Intersection

A skill can request capabilities but cannot elevate beyond:

- agent sandbox
- tenant safety policy
- run approval policy
- platform tool allowlist

Effective permissions are the intersection of:

- agent base tools
- skill-declared tools
- tenant allowed tools
- trust and approval constraints

If a skill references a tool that cannot be admitted, the skill still loads but that tool is marked unavailable in runtime metadata.

## Filesystem Loading

### Directories

Initial directories:

- `~/.codex/skills`
- `~/.claude/skills`
- `.pylon/skills`
- `.pylon/tenants/{tenant_id}/skills`

### Refresh Strategy

Do not introduce a hard dependency on `watchdog` in the first implementation.

Use a catalog service with:

- directory snapshot hash based on path, mtime, and size
- `refresh_if_stale()` guard with a short TTL
- explicit `scan` API to force rescan

This yields dynamic behavior without a resident watcher thread. A later optimization may add event-based watch support behind a config flag.

## New Modules

### `src/pylon/skills/models.py`

Add typed models:

- `SkillRecord`
- `ToolBinding`
- `SkillPolicy`
- `SkillActivation`
- `EffectiveSkillSet`

### `src/pylon/skills/catalog.py`

Responsibilities:

- scan configured directories
- parse `SKILL.md`
- parse tool descriptors
- compute digests
- cache and refresh snapshots
- expose `list()`, `get()`, `rescan()`, `get_tool_bindings()`

### `src/pylon/skills/prompting.py`

Responsibilities:

- order skills by `prompt_priority`
- trim prompt bodies to configured limits
- compose deterministic skill prompt prefix
- emit prompt metadata for traces and tests

### `src/pylon/skills/runtime.py`

Responsibilities:

- resolve an agent's effective skill set for a run
- map tool bindings to platform tool definitions
- produce:
  - `static_instruction` augmentation
  - effective tool exposure
  - runtime metadata

## Integration Points

### 1. API Layer

Change `src/pylon/api/routes.py` to use a `SkillCatalogService` instead of reading `s.skills` directly for file-backed skills.

Routes:

- `GET /api/v1/skills`
  - returns effective catalog metadata
- `GET /api/v1/skills/{id}`
  - returns full content and tool descriptors
- `POST /api/v1/skills/scan`
  - triggers rescan and returns `{total, new, updated, removed}`
- `PATCH /api/v1/agents/{id}/skills`
  - validates against the effective catalog, not only control-plane records
- `POST /api/v1/skills/{id}/execute`
  - executes the skill with its prompt and tool bindings

`RouteStore.skills` remains useful for control-plane-authored skills and generated built-ins, but the API must operate on an effective merged catalog.

### 2. Generic Workflow Runtime

Change `src/pylon/dsl/parser.py` and `src/pylon/types.py` so agents can declare `skills`.

Then update `src/pylon/runtime/execution.py`:

- before calling `LLMRuntime.chat(...)`, resolve `EffectiveSkillSet`
- augment `static_instruction`
- pass the resolved tool set into the provider call
- record `activated_skills` and `activated_tools` in metrics

This is the main platform path for non-lifecycle workflows.

### 3. Lifecycle Runtime

Lifecycle custom handlers in `src/pylon/lifecycle/orchestrator.py` must use the same resolver.

Add a helper such as:

```python
resolve_lifecycle_skill_context(
    *,
    tenant_id: str,
    agent_id: str,
    explicit_skill_ids: list[str] | None,
)
```

Then update `_lifecycle_llm_json(...)` to accept:

- `tenant_id`
- `agent_id`
- `explicit_skill_ids`

and inject the resolved skill prompt prefix into `static_instruction`.

Skill precedence for lifecycle:

- explicit `selected_skills`
- persisted agent assignment from control-plane
- phase blueprint default skills

### 4. Queued Execution Parity

Queued mode currently diverges from sync runtime semantics.

Extract node execution logic from `src/pylon/runtime/execution.py` into a shared helper, for example:

- `src/pylon/runtime/node_execution.py`

Both:

- sync runtime
- `WorkflowRunService._invoke_project_node_for_queued_mode(...)`

must use the same helper so that skill injection and tool exposure are identical.

This is required for correctness. Without it, skills will work in one execution mode and silently disappear in another.

## Tool Execution Model

### Existing Platform Tools

If a skill references a known tool ID from the platform `ToolRegistry`, the runtime simply exposes that tool when policy permits.

### Local Script Tools

For `kind: local-script` descriptors:

- the descriptor is converted into a runtime `ToolDefinition`
- execution is routed through the existing sandbox model
- script path must remain under the skill package root
- arguments are validated against descriptor schema before execution
- stdout/stderr and timing are recorded as tool events

Recommended execution contract:

- command is derived from the descriptor, not arbitrary user input
- workspace path is the current run workspace
- only relative file paths are allowed in tool arguments unless explicitly marked safe

### Tool Admission Rules

A tool can be activated only if all checks pass:

- descriptor schema is valid
- entrypoint exists
- skill is assigned or explicitly selected
- agent policy allows the effect class
- tenant policy allows the tool class
- sandbox tier can host the tool

If not admitted:

- the skill stays available as prompt guidance
- the tool is excluded
- the exclusion reason is surfaced in skill detail and run metadata

## Public API Additions

Add fields to skill responses:

- `version`
- `digest`
- `dependencies`
- `toolsets`
- `unavailable_tools`
- `loaded_at`
- `source_kind` with values `filesystem`, `control_plane`, `generated`

Add fields to run and event payloads:

- `activated_skills`
- `activated_tools`
- `skill_resolution`
- `skill_digests`

## Observability

Each LLM execution should emit:

- activated skill IDs
- activated tool IDs
- prompt prefix byte count
- prompt truncation flag
- excluded tools with reasons

Each tool execution should emit:

- originating skill ID
- descriptor ID
- sandbox tier
- execution time
- output size
- approval path if any

## Compatibility Strategy

Legacy behavior remains valid:

- a skill folder with only `SKILL.md` loads and works as prompt-only
- UI compatibility pages keep functioning
- lifecycle built-in skill catalog can coexist with filesystem skills

The existing UI development backend logic in `ui/scripts/start_backend.py` should eventually be deleted or reduced to a thin wrapper over the new core modules.

## Security Model

### Prompt Safety

- skill bodies are treated as trusted operator-authored instructions
- untrusted external content is never injected into skill bodies automatically
- prompt composition is deterministic and traceable

### Tool Safety

- local script tools execute in the same sandbox discipline as platform tools
- skill packages cannot bypass approval by declaring `approval_class: auto` if the agent or tenant requires review
- no implicit network access; descriptors must declare tool requirements explicitly

### Supply Chain Safety

Store and expose a content digest for:

- `SKILL.md`
- each tool descriptor
- each local entrypoint

This allows later signing or attestation without redesigning the package format.

## Concrete File Diff Plan

Add:

- `src/pylon/skills/__init__.py`
- `src/pylon/skills/models.py`
- `src/pylon/skills/catalog.py`
- `src/pylon/skills/prompting.py`
- `src/pylon/skills/runtime.py`
- `tests/unit/test_skill_catalog.py`
- `tests/unit/test_skill_runtime.py`

Modify:

- `src/pylon/api/factory.py`
- `src/pylon/api/routes.py`
- `src/pylon/runtime/execution.py`
- `src/pylon/control_plane/workflow_service.py`
- `src/pylon/lifecycle/orchestrator.py`
- `src/pylon/dsl/parser.py`
- `src/pylon/types.py`
- `docs/api-reference.md`
- `docs/SPECIFICATION.md`

Optional later:

- `src/pylon/control_plane/registry/skills.py`
  - rename if desired to reduce confusion with filesystem skill catalog

## Rollout

### Phase 1

- file-backed prompt-only skills
- effective catalog API
- agent skill assignment validation
- generic runtime prompt injection
- lifecycle prompt injection
- queued mode parity

### Phase 2

- descriptor-backed local script tools
- run metadata for activated tools
- control-plane and UI surfacing of unavailable tool reasons

### Phase 3

- signed skill packages
- optional filesystem watch backend
- remote package source support

## Acceptance Criteria

- creating or editing a filesystem skill changes agent behavior without restarting pylon
- an agent with assigned skills receives those instructions in every execution mode
- a skill-declared executable tool is available only when descriptor, policy, and sandbox checks pass
- queued and sync runs produce the same effective skill resolution
- run telemetry clearly shows which skills and tools were activated

## Recommendation

Implement Phase 1 and Phase 2 in one branch, but keep the internal architecture split:

- catalog loading
- prompt composition
- tool binding resolution
- execution integration

That separation gives pylon a skill system that is composable, observable, and safe, without collapsing prompt engineering, package loading, and tool execution into one untestable module.
