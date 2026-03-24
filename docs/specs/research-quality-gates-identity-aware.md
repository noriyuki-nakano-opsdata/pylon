# Research Quality Gate Spec: Identity-Aware

## Purpose
Define the quality gate contract for research that must reason about the correct target entity, not just evidence quantity.

## Inputs
- `spec`
- `researchConfig`
- `identity_profile`
  - required:
    - `companyName`
    - `productName`
  - optional:
    - `officialWebsite`
    - `officialDomains`
    - `aliases`
    - `excludedEntityNames`
- normalized research outputs

If optional identity fields are missing, evaluation still proceeds using:
- company + product name anchoring
- derived alias candidates
- same-name collision heuristics

## Gate Model
Each gate returns:
- `id`
- `title`
- `passed`
- `reason`
- `blockingNodeIds`
- `severity`

## Required Gates
### `target-identity-locked`
- Pass when `companyName` and `productName` are both present.
- Fail when either is missing.
- Severity: `critical`

### `homonym-risk-cleared`
- Pass when no accepted competitor, source, or evidence matches excluded entities or same-name off-target candidates.
- Fail when same-name contamination is detected.
- Severity: `critical`

### `accepted-claims-entity-linked`
- Pass when accepted claims are supported by trusted evidence not quarantined for identity mismatch.
- Fail when accepted claims rely only on quarantined evidence.
- Severity: `critical`

### `competitors-organization-distinct`
- Pass when competitor URLs are not on official target domains and do not resolve to the target company.
- Fail when same-company pages are presented as competitors.
- Severity: `high`

### `source-grounding`
- Existing structural gate.
- Pass when accepted claims have grounded external evidence.
- Severity: `high`

### `counterclaim-coverage`
- Existing structural gate.
- Severity: `medium`

### `critical-dissent-resolved`
- Existing structural gate.
- Severity: `critical`

### `confidence-floor`
- Existing structural gate, but only evaluated after identity gates pass.
- Severity: `high`

### `critical-node-health`
- Existing structural gate.
- Severity: `medium`

## Evaluation Order
1. `target-identity-locked`
2. `homonym-risk-cleared`
3. `competitors-organization-distinct`
4. `accepted-claims-entity-linked`
5. existing structural gates

If any gate in steps `1-4` fails, research readiness is `rework` regardless of structural confidence.

## Readiness Rule
`researchReady = true` only when:
- all critical identity gates pass
- trusted external evidence exists
- at least one trusted winning thesis exists
- confidence floor meets threshold
- no unresolved critical dissent remains
- no degraded critical nodes remain

## Quarantine Rules
- Quarantine any source/evidence/competitor that matches `excludedEntityNames`.
- Quarantine any non-official-domain source that mentions the registered product name but not the registered company.
- Quarantine any competitor hosted on official target domains.
- Quarantine any claim whose evidence chain is fully quarantined.

## Operator UX Contract
- Show `調査対象のロック` in review UI.
- Show quarantined same-name items as explicit identity conflicts.
- Disable research start when identity lock is missing.
- When identity gates fail, surface the failure before confidence metrics.

## Test Dataset Requirements
- Include same-name collision fixtures:
  - `Pylon`
  - `Atlas`
  - `Mercury`
  - `Pilot`
- For each fixture, verify:
  - off-target accepted claims = `0`
  - official-domain competitors = `0`
  - readiness = `false` without locked identity
  - readiness = `true` only after trusted entity-linked evidence exists
