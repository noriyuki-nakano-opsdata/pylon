# GTM Multi-Agent Implementation Plan

## Objective

Turn the current generic mission-control environment into a practical revenue operating system for sales, marketing, customer success, partnerships, and advertising.

## Target Operating Model

The environment should support five layers:

1. Specialist agents
   Seed domain-specific GTM agents with clear roles and skill bundles.
2. Reusable playbooks
   Store repeatable operating knowledge as local skills under `ui/scripts/skills/`.
3. Operating control tower
   Provide one project-scoped surface that summarizes GTM health across agents, tasks, content, events, and ads.
4. Actionable recommendations
   Convert missing coverage or stale operating signals into concrete next actions.
5. Progressive expansion
   Start with insight and coordination. Add direct SaaS integrations later for CRM, MA, BI, webinar, and contract tooling.

## Phase Plan

### Phase 1: GTM Control Plane Foundation

- Add a `gtm` project surface to the feature manifest
- Add `GET /api/v1/gtm/overview`
- Create a GTM Control Tower page in the UI
- Derive health, coverage, and recommendations from existing control-plane records

### Phase 2: Playbook Coverage Expansion

Add repo-local skills for the highest-value gaps:

- CRM lead operations
- Lifecycle campaign operations
- Webinar and field marketing operations
- GTM reporting and analytics
- Deal desk and commercial review

### Phase 3: Specialist Agent Expansion

Seed dedicated GTM operators:

- CRM Ops Manager
- Campaign Manager
- Field Marketer
- GTM Analyst
- Deal Desk Manager

Each agent should carry domain-appropriate local skills plus broader analyst or writer skills where needed.

### Phase 4: System Integrations

Add direct integrations for:

- Salesforce or HubSpot
- Marketo, HubSpot MA, or Customer.io
- GA4 and Looker or Tableau
- Zoom or Teams webinar attendance
- DocuSign or CloudSign workflow metadata

This phase should prioritize read-only synchronization first, then controlled write actions behind approvals.

### Phase 5: Closed-Loop Automation

Add automations and workflows for:

- Daily lead queue triage
- Weekly pipeline hygiene review
- Campaign launch readiness review
- Webinar follow-up and handoff
- Monthly GTM performance brief

## Design Principles

- Keep workflows explicit and operator-auditable
- Prefer derived recommendations over static dashboards
- Separate strategic analysis from operational execution
- Use skills for reusable judgment and scripts for deterministic tasks
- Treat CRM, attribution, and stage hygiene as hard prerequisites for forecast quality

## Success Criteria

- GTM teams can see current operating health in one page
- Missing playbook coverage is visible from the catalog and team skill assignments
- Sales and marketing specialists are seeded by default in the demo environment
- The environment produces concrete next actions, not only metrics
- Future SaaS integrations can plug into the same control-tower surface without redesign
