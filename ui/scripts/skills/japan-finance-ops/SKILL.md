---
name: japan-finance-ops
description: Japanese finance operations skill for J-GAAP aware month-end close, invoice and consumption tax checks, procurement approvals, budget-versus-actual reviews, and finance/legal/compliance decision memos. Use when working on freee, Money Forward, Bakuraku, vendor approvals, or audit-ready back-office workflows.
metadata:
  category: finance
  risk: safe
  tags:
    - japan
    - finance
    - compliance
    - procurement
---

# Japan Finance Ops

Use this skill when the task is not just generic finance analysis but Japanese back-office execution with compliance gates. It is designed for finance controllers, FP&A, procurement, legal, and compliance roles that need auditability, approval discipline, and clear operating recommendations.

## When to Use

- Running a monthly close or pre-close issue review
- Reviewing invoices, tax treatment, and evidence completeness
- Preparing a procurement or vendor renewal approval memo
- Comparing budget, actuals, and scenarios for planning decisions
- Designing or auditing workflows in freee, Money Forward, or Bakuraku
- Writing finance/legal/compliance decision memos with explicit risks

## Reference Routing

- If the task touches Japanese accounting, invoice system rules, or electronic recordkeeping law, read [references/japanese-compliance.md](references/japanese-compliance.md).
- If the task touches system choice, ownership boundaries, month-end workflows, or approval routing, read [references/platform-and-ops.md](references/platform-and-ops.md).

## Workflow

1. Classify the request.
   Decide whether the task is close operations, invoice and tax validation, procurement approval, budget variance analysis, or tool/process design.
2. Confirm the system of record and evidence.
   Identify the source system, owner, period, currency, attachments, and missing evidence before giving advice.
3. Apply hard gates before optimization.
   Compliance, approval authority, tax treatment, and auditability are pass/fail constraints, not weighted preferences.
4. Separate financial judgment from workflow judgment.
   State what is a bookkeeping issue, what is a policy issue, and what is an operating-process issue.
5. Produce an operator-ready output.
   Return a recommendation, key risks, blocked items, and concrete next actions with owners.

## Output Shape

- Decision: approve, reject, escalate, or hold pending evidence
- Financial view: amount, variance, scenario impact, or renewal exposure
- Compliance view: tax, invoice, retention, access, or contract checks
- Evidence gaps: missing attachment, owner, supplier data, or audit trail
- Action plan: owner, due date, next system step

## Heuristics

- Treat missing evidence as a first-class finding.
- Separate J-GAAP bookkeeping from management reporting and from procurement approval.
- Consumption tax and invoice-system checks should be explicit, not implied.
- Optimize for traceable decisions that another operator can audit later.
- Use platform-specific recommendations only after clarifying the current system boundary.

## Anti-Patterns

- Mixing tax treatment, booking logic, and approval policy into one vague recommendation
- Comparing vendors on price alone while ignoring renewal, exit, or evidence obligations
- Assuming a screenshot is an audit trail
- Writing a decision memo without naming the blocking evidence or approver
