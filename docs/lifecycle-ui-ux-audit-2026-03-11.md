# Product Lifecycle UI/UX Audit

Date: 2026-03-11
Scope: `http://localhost:5173/p/todo-app-builder/lifecycle/*`
Method: live browser walkthrough across `research -> planning -> design -> approval -> development -> deploy -> iterate`, plus mobile spot check and product/UX framework analysis.

## Executive Summary

The Product Lifecycle experience has a strong concept:

- a deterministic multi-agent lifecycle
- an operator console with artifacts, decisions, skills, and A2A delegations
- a full idea-to-release journey in one surface

The current implementation is promising, but the experience is not yet trustworthy enough for a production-grade operator workflow. The biggest gaps are not visual polish alone. They are:

1. state truth is better than before, but the UI still exposes fragile transitions
2. information density is high without strong prioritization
3. generated outputs often feel generic rather than domain-specific
4. mobile layout is materially broken
5. several interactions reduce confidence even when the backend state is correct

## What Was Observed

### Research

- Research screen is clear on first load and makes the first action understandable.
- Result screen shows market size, feasibility, competitors, opportunities, threats, trends.
- Operator console immediately becomes useful after sync and shows:
  - phase run
  - artifacts
  - decisions
  - skill planner
  - A2A delegations

### Planning

- Planning exposes a rich analysis surface: personas, journey, JTBD, KANO, user stories, actors/roles, use cases.
- On the first UI-triggered run, the page crashed with:
  - `Cannot read properties of null (reading 'kano_features')`
- After syncing the phase through the backend, the page became usable again.
- IA analysis was not surfaced at all in the tested flow.

### Design

- Design comparison is visually promising and the side-by-side concept is strong.
- Scorecards, previews, and selected state are clear enough.
- The previews feel too similar, which weakens the credibility of "multi-model comparison."
- The browser reported sandbox warnings for the embedded previews.

### Approval

- Approval is understandable and the checklist is useful.
- It is still too summary-heavy for a real approver.
- Evidence is flattened into counts and labels, not reviewable proof.

### Development

- Team composition is compelling and explains the specialist swarm well.
- The build result is visually legible.
- The quality story is confusing:
  - build completed
  - quality score is high
  - milestone completion is `0/2`
- That combination creates uncertainty about what "done" actually means.

### Deploy

- Release gate is better than the old mock and now uses backend checks.
- The release flow is understandable.
- The checks read as pass/fail utilities, not as a decision narrative.

### Iterate

- Feedback capture and version history exist.
- AI recommendation is still generic in the tested flow.
- The page does not yet feel like a live learning system with signals, clustering, and closed-loop prioritization.

### Mobile

- Mobile is materially broken on the tested screen.
- The left lifecycle rail dominates the viewport.
- Main content collapses into narrow unreadable columns.
- This is a `P0` product issue, not a polish issue.

## Critical Findings

### P0: Broken lifecycle transition on Planning

- Starting planning from the UI caused a runtime crash before the user could continue.
- This breaks the most important promise of the lifecycle product: safe guided progression.

### P0: Mobile layout failure

- On mobile, the lifecycle rail and main content compete for space and the result cards become vertically compressed and unreadable.
- The product cannot currently be considered responsive.

### P1: Trust gap between UI claims and evidence

- Design variants are presented as distinct model outputs, but in the tested flow they were too close in shape and score to feel meaningfully different.
- Development showed a "good" quality score while milestone completion remained zero.
- Deploy checks all passed, but the rationale was shallow.

### P1: Navigation and hierarchy overload

- The screen simultaneously exposes:
  - global sidebar
  - lifecycle rail
  - phase tabs
  - review subtabs
  - operator console
- This is powerful on paper but cognitively heavy in practice.

### P1: Output specificity is not yet high enough

- Research and planning outputs were structurally correct but often generic.
- The strongest flows in this category feel decisively tailored to the user input; this one still feels template-led in places.

### P2: Empty and pre-run states need stronger guidance

- Several pages show "no artifacts yet" or "no delegations yet" without explaining what will appear, why it matters, or what the operator should expect next.

## Product Evaluation by Framework

### User Journey

Primary operator journey:

1. define product idea
2. review research evidence
3. validate planning outputs
4. compare design candidates
5. approve scope
6. inspect build quality
7. run release gate
8. capture feedback and plan iteration

Observed friction:

- planning can fail at the moment of highest commitment
- phase transitions do not always explain readiness clearly
- there is too much navigation chrome relative to task focus
- operator console is strong, but the main pane often does not coordinate with it tightly enough

### User Stories

Key user stories the product must satisfy:

- As a lifecycle operator, I want to know the single best next action so I can keep momentum.
- As a product lead, I want evidence tied to each decision so I can approve with confidence.
- As a design reviewer, I want meaningful differences between variants so I can choose intentionally.
- As an engineering lead, I want milestone truth and quality truth to align so I can trust release readiness.
- As an executive stakeholder, I want concise summaries before deep detail so I can review quickly.

Current fit:

- partially strong for deep review
- weak for crisp next-step guidance
- weak for trust under failure and edge conditions

### Job Stories / JTBD

Core job:

- When a new product idea enters discovery, I want the system to turn it into a decision-ready, release-ready delivery thread, so I can move from ambiguity to action without losing context.

Related functional jobs:

- compare options
- preserve rationale
- inspect specialist work
- release safely
- close the loop from feedback to next scope

Emotional jobs:

- feel in control even while delegating
- trust the system enough to move quickly
- avoid feeling buried in AI-generated noise

Current fit:

- good functional breadth
- insufficient emotional trust

### KANO Analysis for the Product Itself

Must-be:

- crash-free phase transitions
- reliable persistence and state recovery
- responsive layout on mobile and laptop widths
- clear readiness logic between phases
- trustworthy quality and release signals

One-dimensional:

- faster review flows
- clearer evidence trails
- richer design diffs
- better summary-to-detail information hierarchy

Attractive:

- operator-centric smart briefings
- evidence-backed recommendations
- artifact diff views
- role-based review modes

### IA Analysis

Current IA strengths:

- lifecycle is clearly framed as a process
- operator console gives a durable system spine

Current IA weaknesses:

- too many simultaneous navigation layers
- main content panes mix summary, detail, and action without enough separation
- the system does not always foreground the current decision

Recommended IA direction:

- global nav stays global
- lifecycle rail becomes progress + readiness only
- operator console becomes the evidence layer
- main pane becomes decision workspace

### Persona Analysis

Primary personas:

- Lifecycle Operator / PM
- Design Reviewer
- Engineering Lead
- Approver / Stakeholder

Current bias:

- strongest for an expert solo operator
- weaker for asynchronous reviewer handoff
- weaker for executive skim and decision approval

### Use Case Analysis

Strong use cases:

- seeing the lifecycle as a single controlled system
- reviewing structured artifacts
- comparing design variants visually

Weak use cases:

- recovering after a failed phase start
- understanding what changed between versions
- interpreting whether "good score" really means "ready"
- reviewing IA / architecture depth without opening raw payloads

### Market / Competitive Lens

The product sits across multiple categories at once:

- AI app builders emphasize fast prompt-to-preview loops
- product planning tools emphasize prioritization and stakeholder clarity
- execution tools emphasize project truth and operating cadence

Observed market lessons from current product leaders:

- `Linear` keeps the active decision surface extremely calm and readable while preserving depth in linked detail.
- `Jira Product Discovery` emphasizes idea capture, prioritization, and stakeholder communication before execution detail.
- `v0` and `Lovable` make the "first value moment" almost immediate through preview-first interaction and low-friction iteration.

Pylon's opportunity is not to copy any single one of these. It is to combine:

- Linear's clarity
- Jira Product Discovery's prioritization rigor
- v0 / Lovable's immediacy
- plus Pylon's own differentiator: auditable multi-agent orchestration

## Prioritized Improvement Backlog

### P0

- Fix planning phase crash during first-run transition.
- Redesign lifecycle mobile layout so content remains readable and the phase rail collapses cleanly.
- Remove 404 polling noise for not-yet-prepared lifecycle workflows.
- Align development readiness signals so build quality, milestone progress, and release readiness cannot contradict each other.

### P1

- Rework the main-pane hierarchy so each phase has:
  - summary
  - evidence
  - decision
  - next step
- Make operator console entries clickable and cross-linked to the exact artifact or decision they summarize.
- Increase design variant differentiation and explain the source of each score.
- Add explicit "why you can proceed" messaging at each phase transition.
- Make empty states educational:
  - what will appear
  - why it matters
  - what action triggers it

### P2

- Add role-based review modes:
  - operator
  - approver
  - executive summary
- Add artifact diffs between versions and between design candidates.
- Turn iterate into a true signal system:
  - clustering
  - impact scoring
  - recommendation traceability

## Recommended Direction for the Next Implementation Pass

1. Stabilize the journey.
   Fix transition crashes, remove console noise, and repair mobile layout first.

2. Reduce cognitive load.
   Reframe each phase around the current decision, not around every available datum.

3. Increase trust.
   Every score, gate, and recommendation should explain:
   - what was measured
   - why it matters
   - what blocks progression

4. Differentiate multi-agent value.
   Show disagreement, critique, and rationale, not just multiple outputs.

5. Turn the operator console into the product's signature surface.
   It already points in the right direction. It should become the best reason to use the lifecycle.

## Source Links

- Linear docs: https://linear.app/docs
- Jira Product Discovery: https://www.atlassian.com/software/jira/product-discovery
- v0 by Vercel: https://v0.dev
- Lovable: https://lovable.dev
