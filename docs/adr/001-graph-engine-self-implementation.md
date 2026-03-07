# ADR-001: Graph Engine Self-Implementation

## Status
Accepted

## Context
LangGraph is MIT licensed but has deep implicit dependency on the LangChain ecosystem. LangGraph Platform (commercial features) are unavailable in the OSS version but required for enterprise operations. We need checkpoint/state management integrated directly with Aurora/DynamoDB.

## Decision
Implement an in-house workflow engine in Python rather than depending on LangGraph/LangChain runtime semantics.

## Consequences
- Full control over checkpoint storage backends
- No transitive dependencies on LangChain
- Higher initial development effort
- Must maintain our own graph execution semantics

## Implementation Note

The current implementation has settled on a compiled deterministic DAG executor in `pylon.workflow`, not a Pregel-style distributed graph runtime.

Implemented pieces now include:

- `WorkflowGraph` validation and compilation
- explicit join policies: `ALL_RESOLVED`, `ANY`, `FIRST`
- restricted condition compilation
- structured `NodeResult`
- patch-based commit semantics
- node-scoped checkpoints and replay with `state_hash` verification
