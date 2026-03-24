# Platform And Ops Guidance

Use this reference when the task is operational design, system ownership, or platform choice across Japanese back-office tools.

## Platform Fit

- `freee`: Good system-of-record choice for accounting-led workflows, invoice handling, payroll adjacency, and journal-centric operations.
- `Money Forward`: Strong for accounting and finance workflow coverage where broader cloud-suite alignment or OCR-driven intake matters.
- `Bakuraku`: Strong for expense, invoice, and evidence-heavy intake flows that need operator efficiency and retention discipline.
- `Sansan`: Use for counterparty context, sales-side master enrichment, and relationship verification when the process crosses finance and GTM.

## Operating Patterns

- `Month-end close`: confirm source systems, open issues, missing attachments, owner, and close impact before escalation.
- `Procurement approval`: separate business need, finance approval, legal review, and security/compliance gates.
- `Budget variance review`: separate one-time variance, run-rate variance, and forecast change.
- `Renewal review`: require owner confirmation, usage evidence, spend trend, and negotiation posture before approval.

## Decision Rule

If the user asks for an action recommendation, return:

1. system of record
2. owner and approver
3. hard gates
4. financial impact
5. next action
