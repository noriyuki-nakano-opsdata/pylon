# Improvement Roadmap

This roadmap turns the current improvement points into an execution order based
on user impact and architectural leverage.

## P0: Surface Contract Breakage

- Status: implemented
- Goal: remove mismatches that break the current UI or example workflows
- Implemented:
  - Added `/api/v1/agents` compatibility routes alongside the existing
    versionless agent routes
  - Added `PATCH /agents/{id}` and `PATCH /api/v1/agents/{id}` support
  - Added agent skill assignment routes:
    `GET/PATCH /api/v1/agents/{id}/skills`
  - Added minimal `/api/v1/skills` and `/api/v1/models` compatibility endpoints
  - Completed the `mission-control` and `ads` backend surfaces expected by the
    current UI contract
  - Moved API-only product state onto the shared control-plane store so the
    enabled surfaces survive restarts when `json_file` or `sqlite` backends are
    configured
  - Added `GET /api/v1/contract` so SDKs, tests, and generated clients can bind
    to a machine-readable canonical contract
  - Added deprecation and sunset headers on compatibility aliases so migration
    off legacy routes is explicit instead of indefinite
- Remaining:
  - publish the compatibility-layer removal date in release notes once a stable
    release train exists

## P1: CLI and Docs Drift

- Status: implemented in this pass
- Goal: make the documented CLI flows match the shipped command behavior
- Implemented:
  - `pylon run` now accepts a project path or directory, not just the current
    directory
  - `pylon run --input` now accepts JSON and `KEY=VALUE` syntax
  - added `pylon validate [path]`
  - updated getting-started and quick-start docs to include validation
  - documented canonical local `workflow_id` behavior
  - added deprecated `--project` / `--file` migration flags for `run` and
    `validate`
  - audited and updated the shipped example READMEs to use canonical CLI syntax
- Remaining:
  - keep legacy CLI aliases on a removal schedule instead of leaving them
    permanently ambiguous

## P2: UI and Backend Parity

- Status: implemented for the currently enabled surfaces
- Goal: stop shipping screens that imply unsupported backend capabilities
- Scope:
  - `ads`
  - `mission-control`
  - richer `skills` execution flows
  - provider/model management beyond the current minimal compatibility payloads
- Implemented:
  - added backend feature manifest plus UI feature gating for unsupported
    product surfaces
  - aligned stable UI APIs with canonical `/api/v1` routes
  - added `POST /api/v1/skills/{id}/execute` with provider-backed execution when
    configured and a deterministic local preview fallback otherwise
  - added tenant-scoped backend CRUD for tasks, memories, events, content,
    teams, and agent activity
  - added deterministic ads audit, reporting, planning, benchmark, and budget
    optimization endpoints
  - enabled the corresponding project feature flags once the backend contract
    existed end to end
- Remaining:
  - keep `studio`, `issues`, and `pulls` disabled until they have the same
    contract completeness

## P3: Frontend Quality Gates

- Status: partially implemented in this pass
- Goal: raise confidence on the Vite/React surface
- Scope:
  - add a real lint tool and CI target
  - expand page-level tests beyond the current small utility-focused set
  - add a route-to-endpoint contract test so UI API clients cannot drift from
    the backend unnoticed
- Implemented:
  - added ESLint configuration and a stable-surface `lint` target
  - added `test:contract` for UI API route contract coverage
- Recommendation:
  - expand contract coverage to lifecycle and other surfaces when they move
    from future-facing to supported
  - add page-level interaction tests for the enabled admin surfaces
