# ADR-008: Safety Context and Delegation Boundaries

## Status
Accepted

## Implementation Status
Implemented in the current codebase:

- `SafetyContext` and `SafetyEngine` for dynamic tool use and delegation checks
- structured `ToolDescriptor` resolution for local policy-based tool metadata
- approval binding via `plan_hash` and `effect_hash`
- secret scrubbing before workflow checkpoint persistence
- A2A and MCP runtime boundary checks that keep remote declarations advisory-only

## Context
Static agent capability flags are not enough to secure an agentic system.

They fail to answer questions like:

- Is the current execution frame holding untrusted or model-generated data?
- Is a tool request asking for a new external side effect that was not approved in the original plan?
- Is an A2A child receiving a laundered combination of parent taint and child capabilities?
- Is an approval still valid after the plan or effect scope changes?
- Can a peer's claimed capability be trusted as an authorization source?

Without a dynamic safety boundary, the platform can pass unit tests while still permitting capability laundering or unsafe delegation patterns.

## Decision
Pylon evaluates all sensitive actions with a `SafetyContext` and a centralized `SafetyEngine`.

### SafetyContext

Each execution frame carries:

- agent identity
- workflow/run identity
- static capability envelope
- current data taint
- secret scopes
- external effect scopes
- delegation ancestry (`call_chain`)
- approval token, if any
- sandbox envelope

### Hard safety rules

1. `untrusted` or `model_generated` taint may not coexist with secret-read access in the same execution frame.
2. `untrusted + secrets + external write` is forbidden across the full call chain, not only inside one agent object.
3. Approval may relax soft gates, but never bypass hard denials.
4. Secret-bearing values must be scrubbed before persistence, logs, checkpoints, memory writes, or cross-agent transfer.
5. Remote declarations such as A2A agent cards are advisory metadata only. Local policy is authoritative.
6. Child agents and tools receive a narrowed context; they never expand the parent's authorized envelope.

### Delegation evaluation

All delegation and tool binding decisions use:

`effective_context = union(parent_context, child_declared_capability, requested_effects, incoming_taint)`

The `SafetyEngine` returns one of:

- `allow`
- `require_approval`
- `deny`

`deny` is final.

### Structured tool metadata

Tool registration must declare structured safety metadata, including:

- trust ingestion
- secret read/write scope
- external write scope
- network egress class
- memory write class
- determinism
- required sandbox tier

Tool name matching is not a valid authorization mechanism.

### Approval token binding

Approval tokens are bound to:

- plan hash
- effect envelope
- tenant scope
- actor
- expiry

If node set, tool set, secret scope, or external effect scope expands after approval, the token is invalid and approval must be reacquired.

## Consequences

- Safety decisions become compositional and auditable
- Capability laundering through delegation is blocked by construction
- A2A and MCP integrations become safer because local policy remains the source of truth
- Approval becomes robust against plan drift
- The implementation is more involved than boolean checks, but it matches the real threat model of multi-agent orchestration
