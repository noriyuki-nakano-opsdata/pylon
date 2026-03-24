---
name: crm-lead-ops
description: CRM lead operations skill for dedupe rules, lifecycle stage hygiene, routing logic, enrichment policy, speed-to-lead workflows, and SDR handoff quality. Use when working on lead intake, CRM cleanup, or follow-up discipline.
---

# CRM Lead Ops

Use this skill when the task is operational lead management rather than broad marketing strategy or one-off outreach copy. It is optimized for lead intake quality, routing rules, enrichment discipline, and follow-up readiness.

## When to Use

- Defining lead field requirements and validation rules
- Designing dedupe logic for contacts, accounts, and domains
- Auditing lead source capture and attribution completeness
- Creating speed-to-lead or SLA follow-up rules
- Reviewing MQL to SDR or SDR to AE handoff quality
- Designing enrichment and BANT capture expectations

## Workflow

1. Map the lifecycle.
   State the exact stages from raw lead through qualified meeting or disqualification.
2. Validate data trust.
   Check source, owner, timestamp, account mapping, contactability, and duplicate risk before optimizing workflow.
3. Separate intake from routing.
   Keep required field quality rules distinct from assignment rules and from follow-up SLA rules.
4. Make the handoff explicit.
   Define who owns the lead next, what context must be included, and when the lead should recycle.
5. Return an operator-ready plan.
   Include required fields, automation rules, exception handling, and quality checks.

## Output Shape

- Lifecycle map: stage, entry rule, exit rule, owner
- Data quality checks: field, reason, enforcement rule
- Routing rules: condition, destination, fallback
- SLA rules: response window, escalation, recycle path
- Cleanup plan: dedupe, stale lead review, missing source remediation

## Heuristics

- Source attribution and owner assignment should be mandatory, not optional.
- Dedupe logic should use company domain plus contact identity, not name alone.
- Speed-to-lead breaks when routing, enrichment, and ownership disagree.
- Recycle criteria should be as explicit as qualification criteria.

## Anti-Patterns

- Treating CRM cleanup as a one-time migration task
- Letting lifecycle stages drift without written entry rules
- Routing leads before required context is captured
- Measuring lead volume without measuring lead response quality
