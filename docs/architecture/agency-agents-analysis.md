# agency-agents Analysis

## Summary

`agency-agents` is not just a prompt library. Its strongest value is the combination of:

- broad specialist coverage across engineering, design, testing, product, marketing, and operations
- explicit operating doctrine through NEXUS playbooks
- structured handoffs between roles
- evidence-first QA posture through `Evidence Collector`

Those traits map well to pylon's external skill source model. The right integration point is the compatibility layer, not manual prompt copying.

## Notable Strengths

### 1. Division-based information architecture

The repository groups agents by functional division. That taxonomy is useful at runtime because it helps operators filter skills by delivery phase and team role.

### 2. NEXUS orchestration doctrine

The `strategy/` materials define reusable coordination rules:

- phase-based execution
- quality gates
- retry limits
- standardized handoffs

This is more valuable than any single persona file because it makes multi-agent execution coherent.

### 3. Evidence-based QA

`testing/testing-evidence-collector.md` is opinionated in a productive way:

- require artifacts before approval
- bias toward finding defects rather than rubber-stamping
- separate observed evidence from unsupported claims

That posture is a strong fit for pylon's lifecycle and runtime observability model.

## What Was Integrated Into pylon

### Native bundled integration

Pylon now ships a bundled `agency-agents` skill pack under its own repository so the runtime can load those skills without any external skill-source registration.

### Adapter support for agency-agents repositories

Pylon also recognizes `agency-agents` as an external compatibility profile when import is still useful for comparison or refresh workflows.

### Category preservation

Imported skills retain their top-level division as `category` so the catalog can distinguish engineering, testing, specialized, and other groups.

### Strategy references

Relevant NEXUS documents are attached as lazily loadable references for imported skills. Examples:

- `agents-orchestrator` gets quick-start and handoff references by default
- testing skills get hardening and handoff references
- engineering skills get build/foundation references

### QA artifact context loading

Evidence-oriented skills now declare a context contract for `public/qa-screenshots/test-results.json` so QA evidence can be injected automatically when present.

## Why This Approach

This keeps pylon native-first:

- pylon runs from its own bundled native skill artifacts
- the external repo is only needed when intentionally refreshing the bundle
- NEXUS knowledge becomes executable runtime context
- no prompt copy/paste drift is introduced

## Follow-up Candidates

- map more agency roles to pylon lifecycle phases
- infer richer dependencies between orchestrator, developer, and QA skills
- expose agency-specific filters in the UI skills catalog
