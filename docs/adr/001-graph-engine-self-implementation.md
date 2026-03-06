# ADR-001: Graph Engine Self-Implementation

## Status
Accepted

## Context
LangGraph is MIT licensed but has deep implicit dependency on the LangChain ecosystem. LangGraph Platform (commercial features) are unavailable in the OSS version but required for enterprise operations. We need checkpoint/state management integrated directly with Aurora/DynamoDB.

## Decision
Implement a Pregel/Beam-inspired graph execution engine in Python.

## Consequences
- Full control over checkpoint storage backends
- No transitive dependencies on LangChain
- Higher initial development effort
- Must maintain our own graph execution semantics
