# Value Contract / Outcome Telemetry PRD

## Problem

Pylon already generates user journeys, job stories, JTBD, KANO, and IA analysis, but those outputs are still too decorative. Development and deploy can complete without proving that the selected release candidate remains tied to the intended user value and the metrics required for learning.

## Goal

Convert planning analysis into two enforceable downstream contracts:

- `Value Contract`
  - Captures personas, JTBD/job stories, required use cases, IA key paths, success metrics, and kill criteria.
- `Outcome Telemetry Contract`
  - Captures success metrics, telemetry events, release checks, workspace artifacts, and experiment questions.

## Target Users

- Product operator
  - Needs every selected feature to stay tied to a persona, job story, key journey, and release decision.
- Engineering / platform lead
  - Needs autonomous development to optimize for user outcome, not only code completion.
- Approver / release owner
  - Needs deploy decisions to show value-readiness and observability-readiness, not only implementation quality.

## User Stories

- As a product operator, I want planning analysis to compile into explicit downstream contracts, so that autonomous delivery cannot drift away from the intended user value.
- As an engineering lead, I want every work unit to carry value targets and telemetry events, so that implementation remains tied to measurable outcomes.
- As a release approver, I want deploy gates to include value and telemetry readiness, so that I can decide based on impact and learning readiness.
- As an iteration owner, I want telemetry and kill criteria to survive into deploy and iterate, so that every cycle improves organizational learning.

## Scope

- Compile project-level `valueContract` and `outcomeTelemetryContract` after planning.
- Persist both contracts in the lifecycle project record.
- Inject both contracts into development goal spec, work-unit contracts, and workspace artifacts.
- Add deploy checks for value readiness, telemetry readiness, and instrumentation coverage.
- Surface the contracts in compact development/deploy UI panels.

## Non-goals

- Full product analytics SDK implementation.
- Real runtime event shipping to third-party observability backends.
- Replacing human release/governance decisions.

## Success Criteria

- Planning phase cannot be considered ready unless both contracts are compiled.
- Development phase cannot be considered ready unless both contracts are present in workspace artifacts and work-unit contracts.
- Deploy phase cannot be considered ready unless both contracts pass release checks.
- Operators can see compact value/telemetry readiness without opening raw JSON artifacts.

## Risks

- Heuristic metric/event generation may be too generic for some domains.
- Added quality gates can increase strictness and surface latent project-data gaps.
- UI can become noisy if contract summaries are not kept compact.

## Rollout

1. Compile and persist the contracts at planning sync time.
2. Enforce them in development workspace generation and spec audit.
3. Enforce them again in deploy checks and release contracts.
4. Surface them in compact development and deploy panels.
