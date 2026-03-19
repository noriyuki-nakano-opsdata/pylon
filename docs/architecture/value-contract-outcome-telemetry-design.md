# Value Contract / Outcome Telemetry Design

## Architecture

New shared service:

- `src/pylon/lifecycle/services/value_contracts.py`
  - `build_value_contract(project_record)`
  - `build_outcome_telemetry_contract(project_record, value_contract=...)`
  - readiness helpers and shared contract IDs

This service is intentionally pure and does not depend on orchestrator/runtime modules, so it can be reused by planning sync, contracts, development workspace generation, and deploy checks without circular imports.

## Data Model

### `valueContract`

- `summary`
- `primary_personas`
- `selected_features`
- `required_use_cases`
- `job_stories`
- `user_journeys`
- `kano_focus`
- `information_architecture`
- `success_metrics`
- `kill_criteria`
- `release_readiness_signals`
- `decision_context_fingerprint`

### `outcomeTelemetryContract`

- `summary`
- `success_metrics`
- `kill_criteria`
- `telemetry_events`
- `workspace_artifacts`
- `release_checks`
- `instrumentation_requirements`
- `experiment_questions`
- `decision_context_fingerprint`

## Phase-by-Phase Changes

### Planning

- `backfill_planning_artifacts()` now compiles both contracts.
- `operator_console._phase_output_patch()` persists both contracts when planning runs are synced.
- Planning phase contract now requires both contracts to be ready.

### Development

- Goal spec now injects:
  - `design-system-contract`
  - `access-control-contract`
  - `operability-contract`
  - `development-standards`
  - `value-contract`
  - `outcome-telemetry-contract`
- Each work unit now carries:
  - `value_targets`
  - `telemetry_events`
  - expanded `required_contracts`
- Workspace generation now materializes:
  - `app/lib/value-contract.ts`
  - `docs/spec/value-contract.md`
  - `server/contracts/outcome-telemetry.ts`
  - `docs/spec/outcome-telemetry.md`
- Development spec audit blocks if either contract or artifact set is missing.

### Deploy

- Deploy checks now include:
  - `value-contract`
  - `outcome-telemetry-contract`
  - `instrumentation-coverage`
- Deploy phase contract requires value and telemetry readiness to pass, not only generic release checks.

### Iterate

- The outcome telemetry contract is preserved so iterate can map feedback and experiment questions back to planning intent.

## Runtime / Freshness

- Delivery topology now includes value and telemetry contracts in the topology frame.
- Topology fingerprints therefore change when downstream-enforced value assumptions change, improving rerun accuracy.

## UI

### Development

- Pre-build surface shows a compact `Value Contract / Telemetry Contract` disclosure.
- Build-complete summary rail now shows compact value and telemetry readiness cards.

### Deploy

- Deploy surface now shows a `Value Readiness` card with contract summary counts and telemetry readiness counts.

## Testing

- Backend:
  - planning backfill / sync
  - development workspace artifacts
  - development spec audit blockers
  - deploy checks and release contract gates
- Frontend:
  - lifecycle project normalization
  - development/deploy compact contract panels
