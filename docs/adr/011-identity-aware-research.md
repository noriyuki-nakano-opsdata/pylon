# ADR 011: Identity-Aware Research

## Status
Accepted

## Context
Research quality failures showed that the system could treat same-name third-party products as valid competitors or evidence. The prior architecture used spec text and vendor-like URLs as the primary grounding mechanism. That is insufficient when entity ambiguity exists.

## Decision
Adopt a project-level `productIdentity` record and make it a first-class research input.

`productIdentity` contains:
- `companyName`
- `productName`
- `officialWebsite`
- `officialDomains`
- `aliases`
- `excludedEntityNames`

This identity is:
- captured in UI before or at research start
- persisted on `LifecycleProject`
- passed into research workflow input as `identity_profile`
- used in query anchor generation
- used in frontend audit and readiness logic
- treated as a research lineage input, so changes invalidate downstream artifacts

The UI contract distinguishes:
- required fields: `companyName`, `productName`
- optional fields: `officialWebsite`, `aliases`, `excludedEntityNames`

Optional fields are not treated as hard blockers. When omitted, the system still attempts lightweight enrichment using company + product anchoring, alias candidate derivation, and homonym quarantine heuristics.

## Rationale
- Entity ambiguity is an input problem before it is a ranking problem.
- The lowest-risk place to enforce identity is the project model, not post-hoc review only.
- Query anchoring plus quarantine is a pragmatic step that raises precision without requiring a full entity-resolution service yet.
- Keeping identity at the project level makes it reusable across research reruns and later phases.

## Alternatives Considered
### Keep current spec-only anchoring
Rejected. It does not solve same-name contamination.

### Build a separate company registry service first
Rejected for now. Higher implementation cost and slower product delivery.

### Only quarantine in UI after research
Rejected. Too late in the flow and wastes runtime budget.

## Consequences
### Positive
- Better research precision for ambiguous names.
- Clearer operator mental model.
- Deterministic lifecycle invalidation when identity changes.

### Negative
- Research start now has an additional required data dependency.
- Existing projects without identity lock will require operator input before rerun.
- Full backend factual verification still remains a follow-up step.

## Implementation Notes
- UI stores normalized identity via autosave.
- Backend includes `productIdentity` in mutable lifecycle fields.
- `productIdentity` is included in lineage reset logic for research.
- Research query anchor prefers `productName + companyName + officialDomain`.
- Frontend audit quarantines:
  - excluded same-name entities
  - same-product-name links on non-official domains without company match
  - same-company pages incorrectly presented as competitors

## Follow-Up
- Introduce backend `target-identity-locked` and `homonym-risk-cleared` quality gates.
- Add entity-linked claim and evidence contracts.
- Add golden datasets for `Pylon`, `Atlas`, `Mercury`, `Pilot` class collisions.
