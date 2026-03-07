# ADR-006: Sandbox-by-Default (gVisor + Firecracker)

## Status
Accepted

## Context
Docker containers share the host kernel and provide insufficient isolation for untrusted AI-generated code execution. Agent code execution requires strong isolation guarantees, especially in multi-tenant environments.

## Decision
All agent code execution runs in gVisor (runsc) sandboxes by default. Firecracker microVMs are available as a high-isolation tier. Host process execution is available only as an explicit opt-in for trusted internal tools.

| Tier | Runtime | Startup | Use Case |
|------|---------|---------|----------|
| Standard | gVisor | <500ms | Default |
| High | Firecracker | <2s | Untrusted code, multi-tenant |
| None | Host process | 0ms | Trusted tools (opt-in) |

## Consequences
- gVisor required on all execution nodes (Linux only for production)
- Warm sandbox pool needed to meet <500ms startup target
- macOS/Windows development uses Docker as fallback with warning
- Firecracker requires KVM support on host
- Sandbox filesystem uses overlay FS with allowlists

## Implementation Note

The current codebase provides the policy and lifecycle scaffolding for this ADR:

- `pylon.sandbox.policy` defines default tiers, limits, and network rules
- `pylon.sandbox.manager` manages sandbox records in memory
- `pylon.sandbox.executor` and `pylon.sandbox.registry` provide reference execution/lookup helpers

Concrete gVisor and Firecracker runtime integrations are not implemented yet. The current runtime is therefore a reference sandbox layer, not a production backend integration.
