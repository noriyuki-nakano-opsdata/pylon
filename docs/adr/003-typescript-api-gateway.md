# ADR-003: TypeScript + Hono for API Gateway

## Status
Accepted (deferred — not yet implemented)

## Context
Frontend team uses Next.js/React. Need WebSocket/SSE streaming. Edge Runtime compatibility desired for future Cloudflare Workers support. Python SDK users connect directly to backend — Gateway doesn't need Python.

## Decision
Implement API Gateway in TypeScript with Hono framework.

## Consequences
- Shared tech stack with frontend team
- Hono is lightweight and Edge Runtime compatible
- Mature WebSocket/SSE ecosystem in TypeScript
- Dual-language codebase (Python core + TS gateway)

## Implementation Note

This ADR is not implemented in the current repository.

Current state:

- the API surface is implemented in Python under `pylon.api`
- the SDK surface in this repository is Python-only (`pylon.sdk`)
- no TypeScript gateway, TypeScript SDK, or web console package exists in the repository

Treat this ADR as a design direction for a future split deployment, not as a description of the current code layout.
