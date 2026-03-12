# Agent Skills Production Refactor Plan

## Goal

Refactor the current compatibility-layer implementation into a production-grade architecture that is:

- source-aware
- revision-stable
- adapter-driven
- policy-safe
- operationally observable
- generic enough to support `marketingskills` without becoming `marketingskills`-specific

This document captures a multi-agent design discussion and the resulting implementation plan.

## Design Standard

"Beautiful" in this context means:

- one concept has one owner
- identity is stable and explicit
- inference is separated from admission
- runtime behavior is deterministic for a pinned revision
- operator-facing APIs expose states, not hidden side effects
- compatibility profiles are declarative where possible and pluggable where necessary

## Multi-Agent Discussion

### Round 1: What is fundamentally wrong today?

#### Architect

The current implementation has the right instinct but the wrong primary abstraction.

Today the center of gravity is `SkillRecord`. That is too late in the pipeline. The true domain model is:

1. source
2. snapshot
3. normalized import graph
4. promoted runtime projection

Because the system jumps too early into `SkillRecord`, source provenance, collision handling, promotion state, and review state all become bolted-on metadata.

#### Runtime Engineer

The runtime wants immutable activation inputs:

- exact skill identity
- exact tool descriptors
- exact context contracts
- exact reference index

If the importer can mutate those underneath a logical `skill_id`, the runtime cannot make strong promises.

#### Platform Engineer

The import path is still request-driven and synchronous. In production, clone/fetch/materialize work must be a job with status, retries, and idempotency.

#### Security Reviewer

Inference and execution are still too close together. A repo CLI is discovered and immediately turned into a local tool descriptor. Even if it is marked `manual`, the domain model is still too permissive. Imported capability and admitted capability should be different entities.

### Round 1 Consensus

The system should pivot from "imported skill as decorated `SkillRecord`" to:

- `SkillSource`
- `SourceSnapshot`
- `ImportedCapabilityGraph`
- `PromotionDecision`
- `RuntimeProjection`

---

### Round 2: What should the identity model be?

#### Architect

There are three distinct identities:

- human alias: `analytics-tracking`
- source-scoped identity: `source_id/analytics-tracking`
- immutable revision identity: `source_id/analytics-tracking@revision`

Only the third one is suitable for deterministic runtime activation.

#### API Designer

User-facing APIs should still allow short aliases, but only as selectors. The system must resolve them to immutable identities before execution.

Suggested shape:

- `skill_handle`: stable logical key within a source
- `skill_alias`: optional short name shown in UI
- `skill_version_ref`: immutable execution reference

#### Runtime Engineer

Execution artifacts, traces, and metrics should always record the immutable reference, not just the alias.

### Round 2 Consensus

Introduce:

- `SkillHandle = { source_id, skill_key }`
- `SkillVersionRef = { source_id, skill_key, revision }`

Rules:

- control-plane assignment may store `SkillHandle`
- workflow execution resolves assignments into `SkillVersionRef`
- metrics and audit logs store `SkillVersionRef`
- alias collisions are allowed only across sources, never inside a source

---

### Round 3: How should adapters work?

#### Architect

The current code has profile-specific logic embedded in one module. That does not scale. Profiles should be registrable and layered.

#### Integration Engineer

We need two kinds of extension:

- structural adapters: detect and classify repository layout
- semantic adapters: infer context contracts, references, tool candidates, dependencies, and prompt metadata

#### Product Engineer

Adapters should be mostly declarative so operators can inspect them. But some repositories need code-level inference hooks.

### Round 3 Consensus

Define an adapter stack:

1. `RepositoryClassifier`
2. `SourceAdapter`
3. `SkillNormalizer`
4. `ReferenceAdapter`
5. `ContextContractAdapter`
6. `ToolCandidateAdapter`
7. `PromotionPolicy`

Each profile is a composition of those parts.

Example:

- `agent-skills-basic`: generic classifier + generic normalizer + no special tool mapping
- `marketingskills`: generic classifier + profile overrides for context contracts and repo tool registry semantics

Adapters should emit typed intermediate records, never directly mutate runtime state.

---

### Round 4: What is the right import lifecycle?

#### Platform Engineer

Import should be a transaction with explicit stages:

1. fetch or resolve source
2. pin revision
3. classify
4. normalize
5. validate
6. persist snapshot artifacts
7. compute diff against last promoted snapshot
8. mark candidates for review
9. optionally promote approved runtime projection

#### Reliability Engineer

`sync_source()` should not call checkout twice, and runtime should never see half-written artifacts. Use a staging directory and atomic swap.

#### Architect

This implies a new first-class concept: `ImportSession`.

### Round 4 Consensus

Introduce:

- `ImportSession`
- `ImportSnapshot`
- `PromotionSet`

Required invariants:

- one session resolves exactly one source revision
- one snapshot is immutable once committed
- runtime only reads promoted snapshots
- failed sessions do not mutate promoted state

---

### Round 5: How should tools be admitted?

#### Security Reviewer

Imported tool candidates are not runtime tools. They are proposals.

#### Runtime Engineer

Runtime should only receive promoted descriptors that have passed policy.

#### API Designer

This requires explicit review entities and APIs, not only metadata in manifest files.

### Round 5 Consensus

Split the concepts:

- `ToolCandidate`: inferred from source
- `ToolPromotion`: approved runtime-facing tool binding
- `ExecutableToolBinding`: what runtime actually sees

Admission flow:

1. adapters emit `ToolCandidate`
2. policy engine evaluates trust and execution class
3. operator or automation promotes candidate
4. promotion writes a runtime descriptor

Rules:

- `platform-ref` may auto-promote if mapping is exact and policy allows
- repo CLI defaults to review-gated
- doc-only candidates are never executable

---

### Round 6: How should references and context contracts behave?

#### Runtime Engineer

Context contracts are runtime inputs. References are retrieval assets. They should not be represented the same way.

#### Knowledge Engineer

References should be indexed and lazily loaded by path, tag, or retrieval hint. Copying them into normalized skill folders is acceptable only if relative paths are preserved and digests remain stable.

#### Architect

The system needs a `ReferenceIndex`, not just a list of strings on `SkillRecord`.

### Round 6 Consensus

Separate the models:

- `ContextContract`: runtime-visible, resolved pre-execution
- `ReferenceAsset`: indexed content, loaded on demand
- `ReferenceLoad`: trace event for what was actually injected

Rules:

- context contracts may auto-load
- references never auto-load unless an adapter declares a default reference bundle
- loaded references appear in traces and metrics

---

### Round 7: What should the runtime boundary be?

#### Runtime Engineer

`SkillRuntime` should not know about compatibility internals. It should depend on a resolved execution projection.

#### Architect

So the correct boundary is:

- compatibility subsystem produces `ResolvedSkillProjection`
- runtime consumes `ResolvedSkillProjection`

#### API Designer

This also improves testing. You can test projection separately from execution.

### Round 7 Consensus

Refactor runtime-facing models to:

- `ResolvedSkillProjection`
- `ResolvedToolBinding`
- `ResolvedContextBundle`
- `ResolvedReferenceBundle`

`SkillRuntime` should become primarily a resolver over promoted projections, not an importer.

---

### Round 8: What should operators see?

#### Platform Engineer

Operators need explicit states:

- registered
- fetching
- classifying
- normalizing
- awaiting_review
- promoted
- failed

#### UX Engineer

They also need to see diffs:

- new skills
- removed skills
- changed prompt bodies
- changed references
- changed tool candidates
- changed context contracts

### Round 8 Consensus

Add operational APIs around sources, sessions, and promotions instead of overloading `/skills`.

## Target Architecture

### Subsystems

#### 1. Source Registry

Owns:

- source definitions
- trust policy
- refresh policy
- active promoted snapshot pointer

Suggested module:

- `src/pylon/skills/sources.py`

#### 2. Import Pipeline

Owns:

- fetch/checkout
- revision pinning
- staging
- normalization
- validation
- diff computation

Suggested modules:

- `src/pylon/skills/import_pipeline.py`
- `src/pylon/skills/snapshots.py`

#### 3. Adapter Registry

Owns:

- repository classifier registration
- profile composition
- adapter invocation

Suggested modules:

- `src/pylon/skills/adapters/base.py`
- `src/pylon/skills/adapters/registry.py`
- `src/pylon/skills/adapters/agent_skills_basic.py`
- `src/pylon/skills/adapters/marketingskills.py`

#### 4. Promotion Engine

Owns:

- candidate review state
- policy checks
- descriptor promotion
- runtime projection persistence

Suggested modules:

- `src/pylon/skills/promotion.py`
- `src/pylon/skills/policy.py`

#### 5. Runtime Projection Store

Owns:

- promoted skill projections
- source-scoped lookup
- alias resolution
- revision resolution

Suggested modules:

- `src/pylon/skills/projections.py`
- `src/pylon/skills/runtime.py`

## Core Types

### `SkillSource`

```python
@dataclass(frozen=True)
class SkillSource:
    source_id: str
    tenant_id: str
    kind: str
    location: str
    adapter_profile: str
    trust_class: str
    default_branch: str
    refresh_policy: str
    promoted_snapshot_id: str = ""
```

### `ImportSnapshot`

```python
@dataclass(frozen=True)
class ImportSnapshot:
    snapshot_id: str
    source_id: str
    revision: str
    source_format: str
    adapter_profile: str
    created_at: str
    manifest_path: str
    artifact_root: str
```

### `ImportedSkillNode`

```python
@dataclass(frozen=True)
class ImportedSkillNode:
    handle: SkillHandle
    version_ref: SkillVersionRef
    display_name: str
    content_digest: str
    source_skill_path: str
    prompt_body: str
    references: tuple[ReferenceAsset, ...]
    context_contracts: tuple[ContextContract, ...]
    tool_candidates: tuple[ToolCandidate, ...]
```

### `ResolvedSkillProjection`

```python
@dataclass(frozen=True)
class ResolvedSkillProjection:
    version_ref: SkillVersionRef
    alias: str
    prompt_body: str
    prompt_priority: int
    tools: tuple[ResolvedToolBinding, ...]
    context_bundle: ResolvedContextBundle
    reference_bundle: ResolvedReferenceBundle
```

## API Model

### Keep

- `GET /api/v1/skills`
- `GET /api/v1/skills/{id}`

### Add

- `GET /api/v1/skill-sources`
- `POST /api/v1/skill-sources`
- `GET /api/v1/skill-sources/{source_id}`
- `POST /api/v1/skill-sources/{source_id}/imports`
- `GET /api/v1/skill-import-sessions/{session_id}`
- `POST /api/v1/skill-import-sessions/{session_id}/promote`
- `GET /api/v1/skill-import-sessions/{session_id}/diff`
- `GET /api/v1/skill-tool-candidates`
- `POST /api/v1/skill-tool-candidates/{candidate_id}/approve`
- `POST /api/v1/skill-tool-candidates/{candidate_id}/reject`

### Adjust

`GET /api/v1/skills` should return:

- alias
- source handle
- promoted revision
- provenance summary

Not just a flattened `skill_id`.

## Implementation Plan

### Phase 1: Stable Identity and Snapshot Model

Objective:

- eliminate collision ambiguity
- pin runtime behavior to revisions

Changes:

- add `SkillHandle` and `SkillVersionRef`
- extend manifests to store source-scoped and revision-scoped identities
- update runtime metrics to record `version_ref`
- update API payloads to include alias and provenance

Acceptance:

- two sources may contain `analytics-tracking` without collision
- control-plane assignments resolve deterministically
- traces show exact source and revision

### Phase 2: Import Session and Atomic Promotion

Objective:

- make imports deterministic and operationally safe

Changes:

- introduce `ImportSession`
- stage checkout, normalize, and validate under a temp artifact root
- commit snapshot atomically
- remove duplicate checkout logic
- make runtime read only promoted snapshots

Acceptance:

- failed import leaves current promoted snapshot untouched
- manifest and artifacts always correspond to one revision

### Phase 3: Adapter Registry Extraction

Objective:

- decouple generic compatibility machinery from profile logic

Changes:

- extract `RepositoryClassifier`, `ContextContractAdapter`, `ToolCandidateAdapter`
- move `marketingskills` rules into its own adapter module
- create declarative adapter config for common rules

Acceptance:

- adding a new profile requires a new adapter module, not edits across the importer
- generic agent-skills repos continue to work without profile-specific code

### Phase 4: Promotion and Review Workflow

Objective:

- separate inferred capability from admitted capability

Changes:

- persist `ToolCandidate` records in control-plane
- add approval/rejection state
- generate runtime descriptors only for promoted candidates
- add policy evaluation hooks

Acceptance:

- repo CLI tools are visible before execution but not executable until promoted
- `platform-ref` may auto-promote only when policy allows

### Phase 5: Reference Index and Lazy Loading

Objective:

- make references first-class retrieval assets

Changes:

- add `ReferenceAsset` index with preserved relative paths
- stop flattening reference paths on materialization
- add runtime hook for loading reference bundles
- trace `ReferenceLoad` events

Acceptance:

- nested references preserve path identity
- reference injection is explicit and observable

### Phase 6: Async Import Jobs and Operational APIs

Objective:

- make source import production-safe

Changes:

- move import work out of request thread
- add job state, retries, logs, and diff endpoints
- add lock per `source_id`

Acceptance:

- long-running imports do not block API requests
- concurrent scans for the same source serialize safely

## Test Strategy

### Unit Tests

- source collision resolution
- adapter registry dispatch
- import session atomicity
- reference path preservation
- policy-based tool promotion

### Integration Tests

- import `marketingskills`-like repo and promote a subset of tools
- import two repos with same alias
- refresh git source across revisions
- lifecycle and generic runtime both resolve the same promoted snapshot

### Failure Tests

- malformed registry markdown
- missing context file
- rejected CLI candidate
- interrupted import session

## Recommended Execution Order

1. Phase 1
2. Phase 2
3. Phase 3
4. Phase 4
5. Phase 5
6. Phase 6

This order is important.

If Phase 4 is attempted before Phase 1 and Phase 2, the review system will be built on unstable identities and mutable artifacts.

## Immediate Next Refactors

These are the first concrete code changes worth doing next:

1. Introduce `SkillHandle` and `SkillVersionRef` into `models.py`.
2. Replace `skill_metadata(skill_id)` with source-aware lookup.
3. Refactor `sync_source()` into a single-session pipeline object.
4. Preserve reference relative paths during materialization.
5. Extract `marketingskills` rules from `compat.py` into a profile adapter module.
6. Add `register_routes(..., skill_runtime=..., compatibility_layer=...)` style DI everywhere the skills subsystem is constructed.

## Final Recommendation

The most beautiful version of this system is not "a smarter importer".

It is:

- an explicit import platform
- with declarative profile adapters
- immutable snapshots
- revision-scoped runtime projection
- and policy-gated promotion of executable capability

That is the shape that remains elegant when there are 2 repositories, 20 repositories, and 200 repositories.
