# ADR-005: Rule-of-Two Safety Constraint

## Status
Accepted

## Context
AI agents with unrestricted capabilities can cause severe damage. A single compromised agent with access to untrusted input, secrets, and external write capabilities represents a critical attack vector (OWASP Agentic Top 10: Unauthorized Actions, Excessive Agency).

## Decision
Enforce a "Rule-of-Two+" constraint: no single agent may simultaneously possess all three dangerous attributes:
1. Process untrusted input
2. Access secrets/credentials
3. Modify external state

An agent may have at most two of these three capabilities. Attempting to configure an agent with all three results in a runtime validation error.

Additionally, the pair below is forbidden even when the third capability is absent:

- untrusted input + secret access

## Consequences
- Forces architectural separation of concerns
- Requires multi-agent collaboration for complex tasks (e.g., one agent reads untrusted input, passes sanitized data to another that writes)
- Capability model must be enforced at agent creation and tool binding time
- Slightly increases complexity for simple use cases, but dramatically reduces blast radius

## Implementation Note

The current code enforces this in a stronger form than the original ADR text:

- `AgentCapability` rejects the forbidden triple and the forbidden untrusted+secrets pair
- `CapabilityValidator` enforces the rule at agent creation, dynamic tool grant, subgraph inheritance, and A2A delegation validation
- `SafetyEngine` extends the same reasoning to runtime `SafetyContext` and `ToolDescriptor` unions
