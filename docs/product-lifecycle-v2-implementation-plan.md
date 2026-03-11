# Product Lifecycle V2 Implementation Plan

## Goal

Transform Product Lifecycle from a local UI wizard into a backend-owned, durable, skill-aware, true multi-agent operating surface.

## Design Principles

- Backend is the source of truth for lifecycle state, approvals, releases, feedback, and quality gates.
- Lifecycle phases are modeled as explicit multi-agent teams with artifact contracts, not ad hoc role prompts.
- Workflow definitions are generated server-side so the public contract, safety policy, and execution graph stay aligned.
- Skills are first-class planning inputs. Each phase advertises the skills, tools, and quality gates required to deliver value.
- Deterministic DAG execution remains the backbone. A2A-style delegation and specialist collaboration are layered on top through explicit task and artifact handoff.

## Problems To Fix

1. Lifecycle state is stored in browser `localStorage`, so there is no durable product history or operator-grade audit trail.
2. Workflow definitions are assembled in the UI, which causes drift between product surface and control-plane behavior.
3. Approval, deploy, and iterate phases are simulated instead of backed by durable domain state.
4. "Multi-agent" is mostly cosmetic because the lifecycle surface does not expose artifact handoff, skill usage, or quality gates.
5. The development phase promises iterative specialist collaboration but the workflow graph does not model it.

## Target Architecture

### 1. Lifecycle Domain Model

Persist a tenant-scoped `LifecycleProjectRecord` with:

- canonical project state
- phase status
- design/build artifacts
- approval thread
- deploy quality checks
- release history
- feedback backlog
- AI recommendations
- multi-agent phase blueprints

### 2. Phase Blueprint Contract

Each phase exposes a durable blueprint:

- `team`: agents, roles, tools, skills, autonomy, outputs
- `artifacts`: required inputs and produced outputs
- `quality_gates`: machine-evaluable checks for that phase
- `delegation_rules`: where specialist execution is expected

### 3. Server-Side Workflow Preparation

Move lifecycle workflow authoring into Python:

- Research: parallel scouting + synthesis + critique
- Planning: product analysis + architecture + prioritization
- Design: parallel concept generation + accessibility/performance critique + judge
- Development: architect + specialist builders + QA/security/perf review + integrator

The UI only asks the backend to prepare the phase workflow and then starts a run.

### 4. Product-Grade Review and Release

Implement durable:

- approval comments and approval status
- deploy checks derived from build output
- release records
- feedback backlog and prioritization
- AI improvement suggestions based on real project state

## Implementation Steps

### Step 1. Lifecycle Backend Foundation

- Add lifecycle orchestration module with:
  - phase order
  - default project state
  - phase blueprints
  - server-side workflow builders
  - deploy check and improvement recommendation helpers
- Add lifecycle routes under `/api/v1/lifecycle/...`
- Persist lifecycle records via control-plane surface records

### Step 2. UI Source-of-Truth Migration

- Replace `localStorage` lifecycle persistence with backend fetch/save
- Keep the existing phase UI structure, but bind it to a remote lifecycle record
- Expose lifecycle blueprint data to the UI

### Step 3. Workflow Preparation Migration

- Replace client-built workflow definitions with `preparePhase(...)`
- Keep current output parsers, but make workflow registration server-owned
- Upgrade development to a real specialist graph

### Step 4. Approval / Deploy / Iterate Hardening

- Replace local approval comments with backend approval thread
- Replace fake deploy checks with backend-generated quality gates
- Replace fake iteration backlog with backend feedback records and recommendations

### Step 5. Verification

- Add API tests for lifecycle routes
- Add contract tests for UI lifecycle API
- Run targeted Python tests and frontend `typecheck` / `lint`

## Success Criteria

- Reloading the browser does not lose lifecycle state.
- The UI no longer generates workflow DSL for lifecycle phases.
- Approval, deploy, and iterate are backed by durable backend records.
- Lifecycle surfaces show real multi-agent team definitions, skill usage, and quality gates.
- Development no longer claims an architecture the backend does not encode.
