# ADR-004: Autonomy Ladder (A0-A4)

## Status
Accepted

## Context
Autonomous agents operating without human oversight pose safety risks. Different tasks require different levels of autonomy. We need a graduated model that allows agents to operate efficiently for low-risk tasks while requiring human approval for high-risk actions.

## Decision
Implement a five-level Autonomy Ladder (A0-A4) enforced at the policy engine layer.

| Level | Name | Behavior |
|-------|------|----------|
| A0 | Manual | Agent suggests, human executes |
| A1 | Supervised | Agent executes each step after human approval |
| A2 | Semi-autonomous | Agent executes within policy bounds |
| A3 | Autonomous-guarded | Agent plans autonomously; human approves plan before execution |
| A4 | Fully autonomous | Agent operates independently within safety envelope |

Actions at A3+ require explicit human approval by default. This can be configured per-tenant via policy packs.

## Consequences
- Clear contract between agent capability and human oversight
- Policy engine must intercept all actions and check autonomy level
- Approval workflow must support async human-in-the-loop
- Default level is A2 (semi-autonomous) for new agents
