# Module Map

This is a compact map of the major packages in `src/pylon` and what each one owns.

## Core Runtime

| Package | Key modules | Responsibility |
|---------|-------------|----------------|
| `pylon.types` | `types.py` | shared enums and dataclasses |
| `pylon.errors` | `errors.py` | common error hierarchy |
| `pylon.agents` | `runtime`, `lifecycle`, `registry`, `pool`, `supervisor` | agent lifecycle and management |
| `pylon.workflow` | `graph`, `compiled`, `conditions`, `executor`, `result`, `state`, `commit`, `replay` | compiled DAG execution and replay |
| `pylon.safety` | `capability`, `context`, `engine`, `tools`, `autonomy`, `prompt_guard`, `input_sanitizer`, `output_validator`, `scrubber`, `policy`, `kill_switch` | static and dynamic safety enforcement |
| `pylon.approval` | `types`, `store`, `manager` | approval workflow and binding validation |

## Developer Surfaces

| Package | Key modules | Responsibility |
|---------|-------------|----------------|
| `pylon.cli` | `main`, `state`, `commands/*` | local CLI commands and persisted local state |
| `pylon.api` | `server`, `routes`, `middleware`, `schemas` | lightweight embedded API contract |
| `pylon.sdk` | `client`, `builder`, `decorators`, `config` | in-memory SDK client plus decorator/builder helpers |
| `pylon.dsl` | `parser` | `pylon.yaml` parsing and validation |

## Protocol Boundaries

| Package | Key modules | Responsibility |
|---------|-------------|----------------|
| `pylon.protocols.mcp` | `server`, `client`, `router`, `types`, `dto`, `auth`, `session` | MCP JSON-RPC server/client/auth surface |
| `pylon.protocols.a2a` | `server`, `client`, `types`, `dto`, `card` | A2A task routing, peer cards, streaming |
| `pylon.providers` | `base`, `anthropic` | LLM provider protocol and Anthropic implementation |

## State, Persistence, and Infra

| Package | Key modules | Responsibility |
|---------|-------------|----------------|
| `pylon.repository` | `workflow`, `checkpoint`, `memory`, `audit`, `base` | run/checkpoint/memory persistence interfaces and in-memory stores |
| `pylon.state` | `store`, `machine`, `snapshot`, `diff` | generic state utilities |
| `pylon.events` | `bus`, `types`, `handlers`, `store` | event bus and event helpers |
| `pylon.sandbox` | `manager`, `policy`, `executor`, `registry` | sandbox policy and lifecycle reference layer |
| `pylon.secrets` | `manager`, `vault`, `rotation`, `audit` | secret storage and secret backend abstractions |
| `pylon.tenancy` | `context`, `config`, `quota`, `isolation`, `lifecycle`, `middleware` | tenant isolation and context propagation |

## Support Systems

| Package | Key modules | Responsibility |
|---------|-------------|----------------|
| `pylon.taskqueue` | `queue`, `worker`, `scheduler`, `retry` | queueing and task execution helpers |
| `pylon.plugins` | `types`, `loader`, `registry`, `sdk`, `hooks`, `lifecycle` | plugin manifests, lifecycle, hooks |
| `pylon.control_plane` | `registry`, `scheduler`, `tenant` | registries and higher-level tenant/scheduler helpers |
| `pylon.resources` | `limiter`, `quota`, `pool`, `monitor` | resource limiting and pooling utilities |
| `pylon.resilience` | `retry`, `fallback`, `circuit_breaker`, `bulkhead` | resilience primitives |
| `pylon.observability` | `metrics`, `tracing`, `logging`, `exporters` | metrics, tracing, logging |
| `pylon.config` | `loader`, `resolver`, `validator`, `registry` | generic configuration helpers |
| `pylon.coding` | `loop`, `planner`, `reviewer`, `committer` | coding loop and code-quality helpers |

## Maturity Guide

### Most mature

- `pylon.workflow`
- `pylon.safety`
- `pylon.protocols.mcp`
- `pylon.protocols.a2a`
- `pylon.approval`

### Reference-quality but simpler

- `pylon.api`
- `pylon.cli`
- `pylon.sdk`
- `pylon.sandbox`
- `pylon.secrets`
- `pylon.tenancy`
- `pylon.repository`

### Utility/support layers

- `pylon.events`
- `pylon.state`
- `pylon.resources`
- `pylon.resilience`
- `pylon.observability`
- `pylon.taskqueue`
- `pylon.plugins`
- `pylon.control_plane`
- `pylon.config`
- `pylon.coding`
