# ADR-002: NATS JetStream as Message Bus

## Status
Accepted (deferred — not yet implemented)

## Context
Redis Streams is already used for cache/pubsub — adding message bus responsibility overloads it. SQS/SNS locks us into AWS. We need a lightweight, K8s-native message bus with persistence.

## Decision
Adopt NATS JetStream for workflow events and task queues.

## Consequences
- Apache 2.0 license (MIT compatible)
- Lightweight, K8s-native
- JetStream provides persistence
- Additional infrastructure component to operate

## Implementation Note

This ADR is not implemented in the current codebase.

Current state:

- `pylon.events` is an in-memory pub/sub event bus
- `pylon.taskqueue` is an in-memory priority queue plus scheduler/worker model
- no NATS JetStream transport or persistence integration exists in `src/pylon`

Treat this ADR as a future infrastructure direction, not a description of current runtime behavior.
