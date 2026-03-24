# Pylon LP Brief

Date: 2026-03-13

## Agent-Led Synthesis

- `market-researcher`: validated that multi-agent orchestration is now a mainstream category across major vendors and frameworks.
- `competitive-analyst`: compared Pylon against LangGraph, CrewAI, OpenAI Agents SDK, and Microsoft Copilot Studio.
- `product-manager`: defined the core wedge and conversion path for the landing page.
- `content-marketer`: translated the wedge into buyer-facing messaging and section flow.
- `ui-designer`: framed the page as an enterprise B2B SaaS LP with strong hierarchy and proof-first structure.

## Market Read

The market signal is no longer "agents are interesting." The signal is that every major platform now offers some version of multi-agent workflows, orchestration, tools, or handoffs.

- OpenAI positions the Agents SDK around tools, handoffs, streaming, and tracing.
- LangGraph positions around expressive orchestration for complex company-specific tasks.
- CrewAI positions around orchestration, triggers, tools, observability, and enterprise rollout.
- Microsoft Copilot Studio now documents multi-agent orchestration patterns explicitly.

Implication:

The category is moving from experimentation to operationalization. Buyers will not only ask "can it orchestrate agents?" They will ask:

- Can we govern it?
- Can we replay and audit it?
- Can we constrain unsafe behavior?
- Can we plug it into MCP/A2A ecosystems?
- Can we run it as a real system rather than a demo loop?

## Competitive Read

### Where competitors are strong

- `OpenAI Agents SDK`: strong default for model-native handoffs, tracing, and agent app development.
- `LangGraph`: strong developer flexibility and expressive orchestration for complex workflows.
- `CrewAI`: strong business-facing platform story with tools, triggers, enterprise rollout, and observability.
- `Copilot Studio`: strong Microsoft ecosystem fit and maker-friendly orchestration patterns.

### Where Pylon can win

Pylon should not lead with "we also orchestrate agents." That is table stakes now.

Pylon's credible wedge is:

1. Deterministic execution model
   - compiled DAGs
   - replayability
   - checkpointed state
2. Governance and safety as first-class runtime behavior
   - Rule-of-Two+
   - approval gates
   - autonomy levels
   - capability checks
3. Protocol-native interoperability
   - MCP
   - A2A
4. Infrastructure-minded architecture
   - tenancy
   - secrets
   - sandboxing
   - observability
   - resilience

## ICP

Primary:

- platform teams
- AI engineering teams
- infra/security-conscious product teams
- enterprises moving from prototype agents to governed production workflows

Secondary:

- startups building agentic products that need stronger runtime control before enterprise rollout

## Buyer Pains To Lead With

- Agent demos break when they hit real approvals, secrets, tenants, or external writes.
- Multi-agent workflows become black boxes without replay, traceability, and deterministic state.
- Teams stitch together framework code, tool calls, and permissions without a runtime control plane.
- Governance is bolted on after the fact instead of enforced inside execution.

## Core Positioning

Pylon is the control plane for governed multi-agent systems.

Alternative headline frames:

- Govern every agent workflow from one control plane
- Deterministic orchestration for multi-agent systems
- Ship multi-agent workflows with runtime safety built in

## Recommended LP Structure

### 1. Hero

Goal:
- establish category
- differentiate immediately on governance and deterministic execution

Message:
- Pylon helps teams build and run multi-agent workflows with approvals, replayability, safety boundaries, and protocol-native integration.

Primary CTA:
- Build a governed agent workflow

Secondary CTA:
- View architecture

### 2. Problem Section

Title:
- Multi-agent demos are easy. Governed production systems are not.

Bullets:
- tool sprawl
- opaque execution
- unsafe writes
- missing approvals
- brittle workflow state

### 3. Why Now

Title:
- Every major platform now supports multi-agent orchestration. Control is the new differentiator.

This section exists to anchor the market shift and explain why orchestration alone is no longer enough.

### 4. Differentiation Grid

Columns:
- Pylon
- framework-first alternatives
- workflow/platform alternatives

Rows:
- deterministic DAG execution
- replay and checkpoints
- runtime safety enforcement
- approval system
- MCP + A2A boundaries
- multi-tenant and sandbox-aware architecture

### 5. Capability Pillars

- Orchestrate
- Govern
- Integrate
- Observe

### 6. How It Works

3-step flow:
- define agents and workflow
- enforce autonomy, approvals, and safety at runtime
- inspect runs, replay state, and evolve safely

### 7. Technical Proof

Use concrete implementation signals from the repo:

- Python-first framework
- compiled workflow DAG engine
- Rule-of-Two+ safety model
- autonomy ladder A0-A4
- approval binding with drift detection
- MCP and A2A protocol support

### 8. Conversion Section

CTA:
- Start with a governed workflow, not another agent demo

Secondary trust text:
- designed for teams that care about control, auditability, and production boundaries

## Stitch Prompt Payload

Use this when generating the LP in Stitch:

Create a modern B2B SaaS landing page for "Pylon", a Python-first autonomous AI agent orchestration platform.

Audience:
- AI platform teams
- enterprise engineering teams
- infra and security-conscious builders

Positioning:
- Pylon is the control plane for governed multi-agent systems.
- It is not just another agent framework.
- It helps teams move from agent demos to deterministic, replayable, safety-enforced production workflows.

Key differentiators to emphasize:
- deterministic DAG workflow execution
- Rule-of-Two+ runtime safety
- approval gates and autonomy levels
- MCP and A2A interoperability
- sandboxing, secrets, tenancy, observability, and resilience

Sections to include:
1. Hero with headline, subheadline, primary and secondary CTA
2. Problem section about why multi-agent demos fail in production
3. Why now section about the rise of multi-agent orchestration across major vendors
4. Differentiation comparison grid
5. Four capability pillars: Orchestrate, Govern, Integrate, Observe
6. How it works 3-step workflow
7. Technical proof / architecture credibility section
8. Final CTA

Visual direction:
- enterprise-grade
- clean, structured, high-contrast
- not playful
- strong diagrammatic sections
- premium infrastructure/product aesthetic

Tone:
- precise
- technical
- confident
- proof-oriented
