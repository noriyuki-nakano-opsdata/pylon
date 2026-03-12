# Agent Skills Compatibility Layer Design

## Goal

Add a compatibility layer to pylon so external Agent Skills repositories can be imported as first-class pylon skills without forcing those repositories to adopt pylon-specific metadata.

The design must support:

- `marketingskills` as a high-quality compatibility target
- generic import of other Agent Skills spec repositories
- prompt-only skills, reference-heavy skills, and tool-backed skills
- stable runtime behavior across generic execution, lifecycle handlers, and queued runs
- source-aware updates, validation, and reproducibility

This document defines the compatibility layer as an adapter system over the current pylon skill runtime, not a replacement for it.

## Problem

Pylon today expects a richer native skill package than most external Agent Skills repositories provide.

Current pylon native package assumptions:

- `SKILL.md` may include `id`, `dependencies`, `toolsets`, `trust_class`, `approval_class`, `prompt_priority`
- executable tools are declared in `tools/*.yaml`
- filesystem packages are scanned from pylon-owned skill directories

External repositories such as `marketingskills` typically provide:

- `SKILL.md` with `name` and `description`
- optional `references/`, `scripts/`, and shared repo-level `tools/`
- workflow conventions encoded in prose rather than descriptors
- repository-level update metadata such as `VERSIONS.md`

So the compatibility problem is not "read markdown". The real problem is:

1. normalize foreign skill packages into pylon's runtime model
2. preserve source semantics instead of flattening them away
3. expose tool capability safely when the source repo does not ship pylon-native descriptors

## Design Principles

- Native-first runtime, compatibility-first import: external repos are adapted into native runtime structures.
- Lossless normalization: retain source metadata, source paths, and inferred fields separately from native fields.
- Explicit provenance: every imported skill, tool, reference, and context contract records where it came from and how it was inferred.
- Safe by default: prose-only repos import as prompt-only unless a tool adapter explicitly upgrades them.
- Generic import path: `marketingskills` may use a tuned adapter profile, but the architecture must work for arbitrary Agent Skills spec repos.
- Reference-aware, not reference-eager: references remain on disk and are loaded on demand.
- No silent behavior changes on update: imported packages are revision-pinned unless the operator opts into refresh.

## Non-Goals

- Running arbitrary shell code solely because a repository contains `scripts/`
- Treating every external repository as equally trusted
- Inferring perfect skill dependencies from prose with no operator review
- Replacing the current `SkillCatalog` / `SkillRuntime` model

## Compatibility Targets

### Tier 1: Agent Skills Spec Repositories

Characteristics:

- one skill per directory
- required `SKILL.md`
- optional `references/`, `scripts/`, `assets/`
- frontmatter usually includes `name` and `description`

Examples:

- `marketingskills`
- future repos following the same structure

### Tier 2: Pylon-Native Skill Repositories

Characteristics:

- already ship pylon-compatible fields and `tools/*.yaml`

These bypass most inference and use the compatibility layer only for source registration and updates.

### Tier 3: Hybrid Repositories

Characteristics:

- content-oriented skills plus repo-level tool catalogs, integration guides, or helper CLIs

`marketingskills` is the canonical example.

## Core Model

The compatibility layer adds a source-oriented import model above the existing skill runtime.

### New Concepts

#### `SkillSource`

Represents an imported repository.

Fields:

- `source_id`
- `kind`: `git`, `local-dir`, `archive`
- `location`
- `default_branch`
- `pinned_revision`
- `trust_class`
- `adapter_profile`
- `status`

#### `ImportedSkillRecord`

Normalized external skill before final conversion into `SkillRecord`.

Fields:

- `source_id`
- `source_revision`
- `source_skill_path`
- `source_format`: `agent-skills-spec`, `pylon-native`, `custom`
- `source_name`
- `normalized_id`
- `normalized_name`
- `description`
- `content`
- `frontmatter`
- `references`
- `scripts`
- `context_contracts`
- `tool_candidates`
- `inference_log`

#### `ReferenceRecord`

Represents a lazily loadable reference file or asset.

Fields:

- `skill_id`
- `path`
- `kind`: `reference-md`, `asset`, `template`
- `title`
- `tags`
- `digest`

#### `ContextContract`

Represents a non-skill file the skill expects to exist.

Examples:

- `.agents/product-marketing-context.md`
- `.claude/product-marketing-context.md`

Fields:

- `contract_id`
- `skill_id`
- `path_patterns`
- `mode`: `read`, `write`, `read-write`
- `required`
- `description`
- `discovery_hint`

#### `ToolCandidate`

Represents a possible tool import before policy admission.

Kinds:

- `native-descriptor`
- `platform-ref`
- `repo-cli`
- `integration-guide`
- `doc-only`

Fields:

- `candidate_id`
- `skill_id`
- `origin_path`
- `adapter_kind`
- `proposed_tool_id`
- `confidence`
- `descriptor_payload`
- `review_required`

## Architecture

The compatibility layer is composed of five stages.

### 1. Source Registration

Add a new source registry:

- local path registration
- git source registration
- source pinning by commit SHA
- optional auto-refresh policy

Storage:

- source metadata in control-plane
- working copy under `.pylon/imports/{source_id}/checkout`
- generated normalized artifacts under `.pylon/imports/{source_id}/normalized`

### 2. Repository Classification

Each source is classified before import.

Classifier outputs:

- repository format
- skill root paths
- repo-level manifests
- tool catalogs
- update metadata files

Classifier rules:

- `skills/*/SKILL.md` strongly indicates Agent Skills spec
- `tools/*.yaml` strongly indicates pylon-native or hybrid
- shared `tools/REGISTRY.md` indicates hybrid tool catalog

For `marketingskills`, the classifier should detect:

- skill root: `skills/`
- shared tool catalog: `tools/REGISTRY.md`
- tool docs root: `tools/integrations/`
- repo CLI root: `tools/clis/`
- update metadata: `VERSIONS.md`

### 3. Normalization

Normalization transforms external packages into `ImportedSkillRecord`.

#### Frontmatter Mapping

Map external Agent Skills fields into pylon-compatible fields.

Example mapping:

| External field | Native target | Rule |
|---|---|---|
| `name` | `normalized_id`, `normalized_name` | use as slug/id if no explicit id |
| `description` | `description` | direct |
| `metadata.version` | `version` | optional |
| missing `prompt_priority` | `prompt_priority` | adapter default |
| missing `trust_class` | `trust_class` | source policy default |
| missing `approval_class` | `approval_class` | source policy default |

#### Content Normalization

Normalize markdown without rewriting meaning:

- preserve body
- preserve relative links
- compute preview
- store source digest

#### Skill ID Normalization

Rules:

- prefer explicit native `id`
- otherwise use external `name`
- otherwise use directory name
- prepend source namespace only on collision

Default collision rule:

- `marketingskills::page-cro` internal canonical key
- display alias remains `page-cro` when unambiguous

### 4. Adapter Enrichment

This is where compatibility becomes high quality rather than "best effort".

#### Reference Adapter

Detect and register:

- `references/*.md`
- templates under `assets/`
- repo-linked docs referenced from `SKILL.md`

Behavior:

- references are not injected into the prompt by default
- runtime can request reference snippets by path or tag
- traces record which references were loaded

#### Context Contract Adapter

Extract context file expectations from skill text and adapter profiles.

For `marketingskills`, infer:

- `product-marketing-context` owns `.agents/product-marketing-context.md`
- most other skills consume that file if present

Generic rule:

- regex and profile-driven detection for phrases like:
  - "If `.agents/...` exists"
  - "create `<path>`"
  - "read `<path>` first"

The compatibility layer should not depend on regex alone. It must support profile overrides.

#### Tool Adapter

Tool import is split into safe tiers.

##### Tier A: Native Tool Descriptor Adapter

If repo ships `tools/*.yaml`, import directly as native `SkillToolSpec`.

##### Tier B: Repo CLI Adapter

If repo ships stable CLIs under a recognized directory such as `tools/clis/`, generate `local-script` descriptors only when:

- the adapter profile explicitly enables that directory
- the command has a known invocation contract
- the file passes validation for the runtime
- operator policy allows execution

For `marketingskills`, this means:

- `tools/clis/*.js` are eligible tool candidates
- generated descriptors use `node <script> ...`
- default state is `review_required=true`
- tools are not auto-attached to skills unless mapping exists

##### Tier C: Registry Adapter

If repo ships a registry file such as `tools/REGISTRY.md`, parse it into a structured repo tool index.

The registry parser should extract:

- tool name
- category
- API/MCP/CLI/SDK flags
- integration guide path

This produces `ToolCandidate` records, not necessarily executable tools.

##### Tier D: Integration Guide Adapter

Integration guides become `doc-only` or `platform-ref` candidates.

Examples:

- if pylon already has a native MCP/provider tool named `ga4`, map the external guide to a `platform-ref`
- otherwise keep the guide as `doc-only`

This is critical for generic compatibility: external repos often describe tools they do not implement.

### 5. Runtime Projection

After normalization and enrichment, the compatibility layer projects imported skills into the current pylon runtime.

Projection outputs:

- `SkillRecord`
- `SkillToolSpec`
- `ReferenceRecord`
- `ContextContract`

The existing `SkillCatalog` remains the execution-facing registry, but now accepts imported skills from compatibility sources.

## Import Modes

### Mode 1: Linked

Source stays in place; pylon indexes it.

Pros:

- no copy
- easiest for local development

Cons:

- source can mutate underfoot

Use for:

- local directories such as `/Users/.../marketingskills`

### Mode 2: Mirrored

Pylon clones or copies the source into `.pylon/imports/{source_id}/checkout`.

Pros:

- stable runtime view
- source revision is explicit

Cons:

- more storage

Use for:

- git imports
- production

### Mode 3: Materialized Native Cache

Pylon writes normalized native artifacts into `.pylon/imports/{source_id}/normalized`.

Use for:

- fast rescan
- deterministic diffs
- offline reproducibility

## Runtime Semantics

### Prompt Semantics

Imported skills are still prompt-first.

Rules:

- imported prompt bodies are injected via the same `build_skill_prompt_prefix(...)`
- source metadata may influence ordering
- compatibility layer may append small provenance hints for debugging, but not by default in production prompts

### Reference Semantics

References are loaded lazily.

New runtime behavior:

- a skill activation may advertise available references
- an execution path may request `reference_snippets` before or during a run
- loaded references are appended in a separate prompt section, not merged into the core skill body

Selection strategies:

- explicit path
- explicit tag
- adapter profile default set
- heuristic retrieval from skill-relative links found in the prompt body

### Context Contract Semantics

Context contracts are runtime-visible.

Examples:

- if a skill expects `.agents/product-marketing-context.md`, runtime checks existence
- if found, it may be loaded as a contextual artifact
- if missing and contract is required, the skill activation records a missing-context warning

This solves a major compatibility gap for repositories like `marketingskills` without hardcoding product-specific logic.

### Tool Semantics

Imported tools are admitted only if:

- a tool adapter created a descriptor
- policy allowed execution
- runtime dependencies exist

Otherwise they remain visible as unavailable or doc-only capability hints.

This means a skill can still be useful even if its tools are not executable.

## API Additions

Add source-oriented endpoints:

- `GET /api/v1/skill-sources`
- `POST /api/v1/skill-sources`
- `GET /api/v1/skill-sources/{id}`
- `POST /api/v1/skill-sources/{id}/scan`
- `POST /api/v1/skill-sources/{id}/refresh`
- `GET /api/v1/skill-sources/{id}/skills`
- `GET /api/v1/skills/{id}/references`
- `GET /api/v1/skills/{id}/context-contracts`

Add import review endpoints:

- `GET /api/v1/skill-imports/review`
- `POST /api/v1/skill-imports/review/{candidate_id}/approve`
- `POST /api/v1/skill-imports/review/{candidate_id}/reject`

These are necessary for repo CLI and tool registry imports.

## Adapter Profiles

An adapter profile customizes inference for a repository family without forking runtime logic.

### Example: `agent-skills-basic`

Defaults:

- import `SKILL.md`
- import `references/`
- ignore `scripts/` unless explicitly enabled
- no repo-level tool mapping

### Example: `marketingskills`

Rules:

- skill root: `skills/*`
- version source: `frontmatter.metadata.version`
- shared tool registry: `tools/REGISTRY.md`
- shared CLI directory: `tools/clis/`
- shared integration docs: `tools/integrations/`
- context contract:
  - producer: `product-marketing-context`
  - consumer hint for all skills mentioning `.agents/product-marketing-context.md`
- repo update source: `VERSIONS.md`

This profile is not special because of custom code. It is special because the adapter configuration is explicit.

## Marketingskills Mapping

### What Imports Cleanly Today

- each `skills/*/SKILL.md` as prompt skill
- `references/*.md` as reference records
- `metadata.version` as `version`

### What Needs the Compatibility Layer

- `.agents/product-marketing-context.md` as context contract
- `tools/REGISTRY.md` as shared repo tool index
- `tools/clis/*.js` as review-gated CLI tool candidates
- `tools/integrations/*.md` as doc-only or `platform-ref` tool guides
- `VERSIONS.md` as update metadata source

### Skill-to-Tool Mapping Strategy

The compatibility layer must not guess skill/tool bindings purely from filenames.

Use this order:

1. explicit adapter profile mapping
2. explicit frontmatter extension if the source repo adds one later
3. section parsing from `SKILL.md` phrases such as "use X, Y, Z"
4. operator review

For `marketingskills`, high-quality import should begin with a maintained profile mapping such as:

- `analytics-tracking` -> `ga4`, `mixpanel`, `segment`, `google-search-console`
- `paid-ads` -> `google-ads`, `meta-ads`, `linkedin-ads`, `tiktok-ads`
- `email-sequence` -> `customer-io`, `mailchimp`, `resend`, `sendgrid`

This is the right tradeoff. Tool binding quality matters more than zero-config guessing.

## Generic Import Algorithm

1. register source
2. classify repository
3. select adapter profile
4. scan skill packages
5. normalize frontmatter and markdown
6. register references and scripts
7. run repo-level adapters
8. generate tool candidates
9. apply review and policy
10. project normalized artifacts into runtime catalog
11. emit import report

Import report must include:

- source revision
- imported skill count
- references count
- executable tool count
- doc-only tool count
- unresolved tool candidates
- missing context contracts
- collision warnings

## Policy Model

Compatibility sources need policy in addition to runtime policy.

### Source Trust

Each source has a trust class:

- `internal`
- `reviewed-third-party`
- `unreviewed-third-party`

Default effects:

- only `internal` and `reviewed-third-party` may generate executable tool candidates
- `unreviewed-third-party` imports as prompt/reference only by default

### Tool Admission

Repo CLI candidates require:

- source trust >= `reviewed-third-party`
- explicit operator approval
- runtime dependency check
- path confinement to source checkout

## Update Model

External sources need explicit update control.

### Source Revision Pinning

Each import stores:

- repository URL or path
- pinned revision or content digest
- adapter profile version
- import timestamp

### Update Detection

Update detection is source-specific:

- git source: compare commit SHA
- local-dir source: compare snapshot digest
- `marketingskills`: optionally parse `VERSIONS.md` for operator-friendly summaries

### Safe Refresh

Refresh does not silently replace running semantics.

Instead:

1. scan new source revision
2. produce diff
3. require approval for:
   - tool candidate changes
   - context contract changes
   - skill ID collisions
4. activate new revision

## Data Placement

New filesystem layout:

```text
.pylon/
  imports/
    marketingskills/
      source.json
      checkout/
      normalized/
        skills.json
        references.json
        tool-candidates.json
        context-contracts.json
        import-report.json
```

This keeps imported sources inspectable and debuggable.

## Integration With Existing Pylon Components

### `SkillCatalog`

Extend to accept additional providers:

- native filesystem provider
- imported source provider

### `SkillRuntime`

Extend to understand:

- `context_contracts`
- `reference manifests`
- imported `control_plane_skills`

No special-case runtime for `marketingskills`.

### Lifecycle

Lifecycle continues to consume normalized `SkillRecord` and `SkillToolSpec`.

Compatibility-specific behaviors such as context contracts and references are resolved before execution.

### API

Skills API becomes source-aware but remains backward compatible for existing callers.

## Open Questions

- Should reference retrieval happen automatically from markdown links, or only through explicit manifests?
- Should repo CLI adapters support Node, Python, and shell equally, or gate by runtime availability?
- Do we want tenant-local overrides on imported skills, and if so should they patch normalized artifacts or wrap them?

## Recommended Delivery Plan

### Phase 1: Prompt/Reference Compatibility

- source registry
- Agent Skills spec classifier
- imported prompt skills
- reference records
- context contracts

This is enough for high-value import of `marketingskills`.

### Phase 2: Repo Tool Compatibility

- registry parser
- repo CLI candidates
- operator review flow
- `platform-ref` guide mapping

### Phase 3: Update and Governance

- source pinning
- revision diff
- activation workflow
- tenant-local overlays

## Bottom Line

The right design is not "teach pylon to read `marketingskills`". The right design is:

- treat external skill repositories as sources
- classify and normalize them into imported skills
- enrich them through adapter profiles
- project them into the existing pylon runtime

`marketingskills` then becomes the first high-quality compatibility profile, not a one-off exception.
