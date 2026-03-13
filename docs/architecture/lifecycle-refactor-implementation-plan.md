# Lifecycle Refactor Implementation Plan

## Goals

- Preserve current runtime behavior, streaming semantics, and latency characteristics.
- Increase single responsibility and module boundaries across lifecycle orchestration, runtime projection, and UI state management.
- Reduce duplicated normalization and presentation logic between backend and frontend.
- Enable phase-by-phase migration without a long-lived branch or a flag day rewrite.

## Target Module Boundaries

### 1. Lifecycle Domain

Owns canonical phase state and transition contracts.

Files:

- `src/pylon/lifecycle/state.py`
- `src/pylon/lifecycle/contracts.py`
- `src/pylon/lifecycle/__init__.py`
- `src/pylon/lifecycle/phase_catalog.py` (new)

Responsibilities:

- Canonical lifecycle project record shape
- Phase order and unlock semantics
- Phase input/output contracts
- Shared enums and typed record helpers

Rules:

- No HTTP concerns
- No frontend display formatting
- No SSE serialization

### 2. Lifecycle Application Services

Owns projection, sync, localization, remediation, and source quality logic.

Files:

- `src/pylon/lifecycle/runtime_projection.py`
- `src/pylon/lifecycle/operator_console.py`
- `src/pylon/lifecycle/services/research_sources.py` (new)
- `src/pylon/lifecycle/services/research_quality.py` (new)
- `src/pylon/lifecycle/services/research_localization.py` (new)
- `src/pylon/lifecycle/services/research_view_model.py` (new)
- `src/pylon/lifecycle/services/project_sync.py` (new)

Responsibilities:

- Runtime summaries for APIs and SSE
- Research source collection and evidence classification
- Quality gates and remediation planning
- Canonical to localized transformation
- Canonical to compact input digest transformation
- Project/run synchronization and startup recovery

Rules:

- Pure functions where possible
- Reusable from routes, coordinator, and tests
- Projection payloads must be summary-shaped and avoid heavy phase input bodies

### 3. Lifecycle Phase Runtime

Owns workflow blueprints and node handlers.

Files:

- `src/pylon/lifecycle/phases/__init__.py` (new)
- `src/pylon/lifecycle/phases/research.py` (new)
- `src/pylon/lifecycle/phases/planning.py` (new)
- `src/pylon/lifecycle/phases/design.py` (new)
- `src/pylon/lifecycle/phases/development.py` (new)
- `src/pylon/lifecycle/orchestrator.py`

Responsibilities:

- Phase workflow definitions
- Phase node handlers
- Phase-scoped helper wiring

Rules:

- `orchestrator.py` becomes a composition root, not a monolith
- Shared research helper logic moves to `services/`
- Phase files must not depend on route-specific payload shaping

### 4. API Transport

Owns HTTP registration and streaming transport only.

Files:

- `src/pylon/api/routes.py`
- `src/pylon/api/factory.py`
- `src/pylon/api/http_server.py`
- `src/pylon/api/middleware.py`
- `src/pylon/api/modules/lifecycle_routes.py` (new, optional second step)

Responsibilities:

- Request validation
- Route registration
- SSE framing
- Error translation to HTTP responses

Rules:

- Runtime summaries must come from application services
- Route handlers should orchestrate calls, not build domain projections inline

### 5. Frontend Lifecycle Presentation

Owns one state machine for lifecycle workspace rendering.

Files:

- `ui/src/pages/lifecycle/LifecycleLayout.tsx`
- `ui/src/pages/lifecycle/LifecycleContext.ts`
- `ui/src/hooks/useWorkflowRun.ts`
- `ui/src/hooks/useLifecycleRuntimeStream.ts`
- `ui/src/lifecycle/presentation.ts` (new)
- `ui/src/lifecycle/store.ts` (new)
- `ui/src/lifecycle/researchViewModel.ts` (new)

Responsibilities:

- Workspace event reducer
- Derived selectors for each phase screen
- UI labels and formatting
- Minimal transport adapters for polling/SSE

Rules:

- Phase screens consume selectors and dispatch actions
- Defensive normalization stays out of render paths
- Live runtime updates do not overwrite dirty local fields

## Concrete File Splits

### Slice 1: Runtime Projection Extraction

Status:

- In progress

Files:

- Add `src/pylon/lifecycle/runtime_projection.py`
- Remove projection helpers from `src/pylon/api/routes.py`

Functions to live in `runtime_projection.py`:

- `runtime_active_phase`
- `runtime_safe_next_action`
- `lifecycle_phase_runtime_summary`
- `lifecycle_runtime_payload`
- internal team/run/delegation helpers

Migration steps:

1. Move pure projection helpers unchanged.
2. Import them in `routes.py`.
3. Keep `_workflow_run_live_payload` in routes for now.
4. Validate SSE payload parity with existing API tests.

### Slice 2: Research Services Extraction

Files:

- `src/pylon/lifecycle/services/research_sources.py`
- `src/pylon/lifecycle/services/research_quality.py`
- `src/pylon/lifecycle/services/research_localization.py`

Move out of `orchestrator.py`:

- external source search/fetch/classification
- claim quality and gate evaluation
- localization and translation payload shaping

Migration steps:

1. Extract pure helpers first.
2. Keep orchestration signatures stable.
3. Replace internal calls one group at a time.
4. Preserve test coverage per helper cluster.

### Slice 3: Research View Model Stabilization

Files:

- `src/pylon/lifecycle/services/research_view_model.py`
- `ui/src/lifecycle/researchViewModel.ts`

Target outputs:

- `canonical`
- `localized`
- `inputDigest`
- `viewModel`

Migration steps:

1. Backend emits `viewModel` alongside legacy research payload.
2. UI prefers `viewModel` if present.
3. Remove render-time normalization from `ResearchPhase.tsx`.
4. Delete legacy frontend normalization after parity checks.

### Slice 4: Phase Package Split

Files:

- `src/pylon/lifecycle/phases/research.py`
- `src/pylon/lifecycle/phases/planning.py`
- `src/pylon/lifecycle/phases/design.py`
- `src/pylon/lifecycle/phases/development.py`

Migration steps:

1. Move blueprint builders first.
2. Move handlers next.
3. Keep `orchestrator.py` as import facade during migration.
4. Collapse facade only after tests and imports are stable.

### Slice 5: Frontend Workspace Store

Files:

- `ui/src/lifecycle/store.ts`
- `ui/src/lifecycle/presentation.ts`

Events:

- `hydrate`
- `runtime_patch`
- `run_live`
- `local_edit`
- `autosave_started`
- `autosave_succeeded`
- `autosave_failed`
- `terminal_refresh`

Migration steps:

1. Introduce reducer behind existing context.
2. Move `LifecycleLayout` merging logic into reducer.
3. Point `ResearchPhase` and operator console to selectors.
4. Remove ad hoc merge logic from layout/hooks.

## Performance Constraints

- Projection code remains pure and allocation-light.
- Streaming payloads stay summary-only; heavy phase input bodies are excluded.
- Canonical research is normalized once at save/sync time, not during render.
- SSE connections remain one project stream plus optional active run stream.
- Remediation loops remain bounded and targeted.

## Migration Order

1. Runtime projection extraction
2. Research service extraction
3. Backend research view model
4. Frontend lifecycle store
5. Phase package split
6. Optional route module split

This order keeps API payloads stable while removing the highest-cost coupling first.

## Acceptance Criteria Per Slice

### Slice 1

- `routes.py` no longer owns lifecycle runtime projection logic
- lifecycle SSE tests pass unchanged

### Slice 2

- research source, quality, and localization helpers are unit-testable in isolation
- `orchestrator.py` shrinks without behavior changes

### Slice 3

- `ResearchPhase.tsx` stops doing heavy normalization in render path
- backend returns a stable view model for operator and end-user surfaces

### Slice 4

- each executable phase has its own module
- `orchestrator.py` acts as composition root only

### Slice 5

- one lifecycle reducer owns runtime, local edits, and autosave conflict resolution
- terminal refresh cannot clobber dirty local state

## Immediate Implementation Plan

1. Complete Slice 1 and lock parity with `tests/unit/test_api.py`.
2. Extract research quality and localization helpers next because they currently create the largest backend drift.
3. Introduce backend `ResearchViewModel` before touching more lifecycle UI.
4. Only after backend contracts stabilize, move UI to a single workspace store.
