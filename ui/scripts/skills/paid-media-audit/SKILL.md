---
name: paid-media-audit
description: Paid media audit skill for Google Ads, Meta Ads, creative fatigue checks, tracking validation, budget diagnostics, and ad policy triage. Use when reviewing campaign structure, spend efficiency, attribution health, or compliance risk.
---

# Paid Media Audit

Use this skill when the work concerns operational ad quality and attribution health rather than general brand strategy. It is optimized for search, paid social, creative review, tracking QA, budget allocation, and ad policy risk.

## When to Use

- Auditing Google Ads or Meta Ads account structure
- Checking tracking, conversion API, pixel, or event mapping health
- Diagnosing budget pacing, bidding, or spend concentration problems
- Reviewing creative fatigue, message match, or landing-page alignment
- Preparing compliance findings for privacy or ad-policy review
- Summarizing priority fixes with estimated impact and risk

## Workflow

1. Validate measurement first.
   Check pixels, conversion actions, naming consistency, consent dependencies, offline conversion handling, and duplication risk.
2. Inspect account structure.
   Review campaign segmentation, budget fragmentation, geo/device splits, audience overlap, and experiment hygiene.
3. Diagnose efficiency.
   Compare spend concentration, impression share, CPA or ROAS dispersion, learning resets, and bid strategy fit.
4. Review creative and destination.
   Check fatigue, message match, offer clarity, landing speed, and CTA continuity.
5. Summarize action stack.
   Separate critical fixes, near-term optimizations, and longer-term experiments.

## Output Shape

- Audit summary: platform, objective, core finding
- Tracking findings: issue, impact, required fix
- Spend findings: issue, evidence, likely cause
- Creative findings: fatigue, mismatch, missing asset, test idea
- Priority plan: owner, expected effect, urgency

## Heuristics

- Never optimize budget before trusting measurement.
- Creative fatigue and tracking loss often appear as bidding problems.
- Separate account-structure issues from landing-page issues.
- Budget recommendations should state the tradeoff between efficiency and volume.

## Anti-Patterns

- Calling policy issues a performance issue
- Reallocating budget without explaining the measurement caveat
- Treating platform recommendations as universal across objective types
- Ignoring landing-page constraints while judging creative in isolation
