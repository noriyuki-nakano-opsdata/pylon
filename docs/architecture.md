# Architecture Overview

## 5-Layer Architecture

```
+------------------------------------------------------------------+
|                        Layer 5: API                               |
|  server.py | routes.py | middleware.py | schemas.py               |
|  HTTP endpoints, auth, tenant isolation, rate limiting            |
+------------------------------------------------------------------+
|                      Layer 4: Safety                              |
|  capability.py | autonomy.py | prompt_guard.py | kill_switch.py  |
|  input_sanitizer.py | output_validator.py | policy.py            |
|  Rule-of-Two+, Autonomy Ladder, Prompt Guard, Kill Switch        |
+------------------------------------------------------------------+
|                   Layer 3: Orchestration                          |
|  agents/   | workflow/  | dsl/                                   |
|  runtime, lifecycle, pool, supervisor | graph, executor | parser |
|  Agent management, DAG workflows, config parsing                 |
+------------------------------------------------------------------+
|                    Layer 2: Protocols                             |
|  protocols/mcp/  | protocols/a2a/  | providers/                  |
|  MCP JSON-RPC    | Agent-to-Agent  | LLM providers               |
+------------------------------------------------------------------+
|                  Layer 1: Infrastructure                          |
|  sandbox/  | secrets/  | repository/                             |
|  Isolation tiers, resource limits | Vault, rotation, audit       |
|  Event sourcing, checkpoints, persistence                        |
+------------------------------------------------------------------+
```

## Data Flow

```
                     External Request
                           |
                           v
                    +------+------+
                    |  API Server |  (Layer 5)
                    |  Auth + Rate|
                    +------+------+
                           |
                           v
                    +------+------+
                    | Safety Layer|  (Layer 4)
                    | Prompt Guard|
                    | Policy Check|
                    +------+------+
                           |
                           v
              +------------+------------+
              |                         |
              v                         v
      +-------+-------+       +--------+--------+
      | Agent Runtime  |       | Workflow Engine |  (Layer 3)
      | Lifecycle Mgmt |       | DAG Execution  |
      +-------+-------+       +--------+--------+
              |                         |
              v                         v
      +-------+-------+       +--------+--------+
      | MCP / A2A     |       | LLM Providers   |  (Layer 2)
      | Tool Calls    |       | Anthropic, etc. |
      +-------+-------+       +--------+--------+
              |                         |
              v                         v
      +-------+--------+      +--------+--------+
      | Sandbox        |      | Secrets / Repo  |  (Layer 1)
      | gVisor/Docker  |      | Vault, Events   |
      +----------------+      +-----------------+
```

## Core Design Principles

### Rule-of-Two+ (Section 2.3)

No single agent may simultaneously hold all three capabilities:

| Capability | Description |
|------------|-------------|
| `can_read_untrusted` | Process input from external sources (MCP, A2A, GitHub) |
| `can_access_secrets` | Read from Vault, env vars, or secret stores |
| `can_write_external` | Push to GitHub, write to DB, call external APIs |

Additionally, the pair `can_read_untrusted + can_access_secrets` is forbidden
(prompt injection exfiltration risk).

Validation occurs at 4 checkpoints:
1. Agent creation (static, from pylon.yaml)
2. Dynamic tool grant (every MCP tool discovery)
3. Subgraph inheritance (child subset of parent)
4. A2A delegation (peer agent-card verification)

### Autonomy Ladder (ADR-004)

| Level | Name | Behavior |
|-------|------|----------|
| A0 | Manual | Agent suggests, human executes |
| A1 | Supervised | Human approves each step |
| A2 | Semi-autonomous | Within policy bounds, no approval |
| A3 | Autonomous-guarded | Human approves plan, then autonomous |
| A4 | Fully autonomous | Within safety envelope only |

### Prompt Guard Pipeline (Section 2.4)

```
Input --> [Trust Level Check]
            |
            +--> TRUSTED: pass through
            |
            +--> INTERNAL: Pattern Matcher --> pass/reject
            |
            +--> UNTRUSTED: Pattern Matcher --> Classifier LLM --> pass/reject
```

18 built-in regex patterns detect:
- Instruction override ("ignore previous instructions")
- System prompt extraction ("reveal your system prompt")
- Role hijacking ("you are now", "pretend you are")
- Format injection (XML tags, INST markers)
- Jailbreak attempts ("DAN mode")

### Multi-path Kill Switch (FR-10)

| Path | Mechanism | Target Latency |
|------|-----------|---------------|
| Primary | NATS publish | < 1s |
| Fallback | ConfigMap poll | < 5s |
| Emergency | Namespace delete | < 10s |

Scopes: `global`, `tenant:{id}`, `workflow:{id}`, `agent:{id}`
Global activation blocks all sub-scopes automatically.

### Sandbox Isolation (FR-06)

| Tier | Isolation | Startup | Platform |
|------|-----------|---------|----------|
| Firecracker | microVM | < 2s | Linux KVM |
| gVisor | User-space kernel | < 500ms | Linux |
| Docker | Container | < 1s | All |
| None | Host process | 0 | SuperAdmin only |

Each tier has default resource limits (CPU, memory, network, execution time)
and network policies (host allowlist, port blocking, internet access).

## Event Sourcing

All state changes are captured as `EventLogEntry` records. Checkpoints are
event logs, not state snapshots. This enables deterministic replay for
debugging and audit.

```
EventLogEntry:
  node_id: str
  input_data: Any
  llm_response: Any
  tool_results: list[Any]
  output_data: Any
  state_ref: str  # URI for large state (>1MB) in S3/MinIO
```
