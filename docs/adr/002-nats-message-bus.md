# ADR-002: NATS JetStream as Message Bus

## Status
Accepted

## Context
Redis Streams is already used for cache/pubsub — adding message bus responsibility overloads it. SQS/SNS locks us into AWS. We need a lightweight, K8s-native message bus with persistence.

## Decision
Adopt NATS JetStream for workflow events and task queues.

## Consequences
- Apache 2.0 license (MIT compatible)
- Lightweight, K8s-native
- JetStream provides persistence
- Additional infrastructure component to operate
