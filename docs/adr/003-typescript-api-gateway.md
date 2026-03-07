# ADR-003: TypeScript + Hono for API Gateway

## Status
Accepted

## Context
Frontend team uses Next.js/React. Need WebSocket/SSE streaming. Edge Runtime compatibility desired for future Cloudflare Workers support. Python SDK users connect directly to backend — Gateway doesn't need Python.

## Decision
Implement API Gateway in TypeScript with Hono framework.

## Consequences
- Shared tech stack with frontend team
- Hono is lightweight and Edge Runtime compatible
- Mature WebSocket/SSE ecosystem in TypeScript
- Dual-language codebase (Python core + TS gateway)
