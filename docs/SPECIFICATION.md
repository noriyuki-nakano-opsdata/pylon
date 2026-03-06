# Pylon Platform Specification v1.0

## 1. Vision

Pylon is an autonomous AI agent orchestration platform. It provides a framework-independent, protocol-native runtime for building, deploying, and governing multi-agent systems at enterprise scale.

**Design Principles:**
1. **Framework Independence** — No transitive dependency on LangChain, AutoGen, or any specific AI framework
2. **Protocol-Native** — MCP 2025-11-25 and A2A RC v1.0 as first-class citizens, not adapters
3. **Sandbox-by-Default** — gVisor default, Firecracker microVM for high-isolation; Docker-only is rejected
4. **Human-Governed Autonomy** — Autonomy Ladder (A0-A4) with approval gates at A3+
5. **Replayable State Machine** — Every workflow is deterministically replayable from any checkpoint

**License:** MIT

---

## 2. Architecture Overview

### 2.1 Five-Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│ L1: Developer Surfaces                              │
│   CLI (pylon) │ Web Console │ SDK (Python/TS) │ IDE │
├─────────────────────────────────────────────────────┤
│ L2: Control Plane                                   │
│   API Gateway (Hono/TS) │ Policy Engine │ Registry  │
│   Scheduler │ Approval Manager │ Tenant Controller  │
├─────────────────────────────────────────────────────┤
│ L3: Execution Plane                                 │
│   Graph Engine │ Agent Runtime │ Sandbox Pool        │
│   Tool Executor │ Coding Loop │ Memory Manager      │
├─────────────────────────────────────────────────────┤
│ L4: State & Data Plane                              │
│   PostgreSQL+pgvector │ NATS JetStream │ Redis      │
│   Object Store (S3/MinIO) │ Checkpoint Store        │
├─────────────────────────────────────────────────────┤
│ L5: External Ecosystem                              │
│   LLM Providers │ MCP Servers │ A2A Peers           │
│   Git Repos │ Container Registries │ IdP (OIDC)     │
└─────────────────────────────────────────────────────┘
```

### 2.2 Standard Execution Lifecycle

```
Request → Policy Classify → Plan → Approval Gate (A3+)
       → Execute → Validate → Checkpoint → Publish Result
       ↻ Replay from any Checkpoint
```

### 2.3 Rule-of-Two Safety Constraint

No single agent may simultaneously possess all three:
1. Process untrusted input
2. Access secrets/credentials
3. Modify external state (write to DB, push to git, call APIs)

Violation → runtime error. Architecture enforces separation via capability tags on agent definitions.

---

## 3. Repository Structure

```
pylon/
├── core/
│   ├── runtime/          # Agent runtime, lifecycle, capability model
│   ├── engine/           # Pregel/Beam-inspired graph execution engine
│   ├── sandbox/          # gVisor/Firecracker sandbox manager
│   ├── memory/           # 4-layer memory (working/episodic/semantic/procedural)
│   ├── safety/           # Policy engine, Rule-of-Two enforcer, kill switch
│   └── coding/           # Plan-Code-Execute-Observe-Refine loop
├── control-plane/
│   ├── gateway/          # Hono TypeScript API gateway (WebSocket/SSE)
│   ├── scheduler/        # Workflow scheduler, priority queues
│   ├── registry/         # Agent/tool/skill registry
│   ├── approval/         # Human approval gate manager
│   └── tenant/           # Multi-tenant isolation controller
├── protocols/
│   ├── mcp/              # MCP 2025-11-25 (Streamable HTTP + OAuth 2.1 PKCE)
│   └── a2a/              # A2A RC v1.0 (/.well-known/agent-card.json)
├── providers/
│   ├── llm/              # Provider-agnostic LLM interface
│   ├── embedding/        # Embedding provider abstraction
│   └── storage/          # Storage backend abstraction (Aurora/DynamoDB/S3)
├── sdk/
│   ├── python/           # Python SDK (pylon-sdk)
│   └── typescript/       # TypeScript SDK (@pylon/sdk)
├── cli/                  # pylon CLI (init/dev/run/replay/inspect/approve/publish/doctor/eval)
├── ui/
│   └── web/              # Web console (React/Next.js)
├── charts/
│   └── pylon/            # Helm chart
├── evals/                # SWE-bench, HumanEval, custom eval suites
├── examples/             # Quick-start examples and tutorials
├── docs/
│   ├── adr/              # Architecture Decision Records
│   ├── rfc/              # Request for Comments
│   ├── api/              # API reference (OpenAPI)
│   └── runbooks/         # Operational runbooks
├── governance/           # CODEOWNERS, release process, DCO
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── pyproject.toml
├── Makefile
└── pylon.yaml            # Project definition entry point
```

---

## 4. Functional Requirements

### FR-01: Project DSL (`pylon.yaml`)

Single-file project definition. 30 lines for Hello World, scales to enterprise.

```yaml
# pylon.yaml
version: "1"
name: my-project
description: Code review automation

agents:
  planner:
    model: anthropic/claude-sonnet-4-20250514
    role: >
      Analyze PR diffs, create review plan.
    autonomy: A2  # Semi-autonomous, no approval needed
    tools: [github-pr-read, file-read]

  reviewer:
    model: anthropic/claude-sonnet-4-20250514
    role: >
      Review code changes per plan.
    autonomy: A2
    tools: [github-pr-comment]
    sandbox: gvisor  # default

workflow:
  type: graph
  nodes:
    analyze: { agent: planner, next: review }
    review: { agent: reviewer, next: END }

policy:
  max_cost_usd: 5.0
  max_duration: 30m
  require_approval_above: A3
```

**Implementation:**

- **Parser**: Pydantic v2 model with strict validation
- **Schema**: JSON Schema published for IDE autocomplete
- **Loader**: Support YAML, JSON, and Python DSL (`pylon.py`) via `PylonConfig` class
- **TypeScript DSL**: `@pylon/sdk` provides `definePylon()` builder

### FR-02: Agent Runtime

**Agent Lifecycle:** `INIT → READY → RUNNING → PAUSED → COMPLETED | FAILED | KILLED`

**Capability Model:**
```python
@dataclass
class AgentCapability:
    can_read_untrusted: bool = False
    can_access_secrets: bool = False
    can_write_external: bool = False
    # Rule-of-Two: at most 2 of 3 can be True
```

**Provider Abstraction:**
```python
class LLMProvider(Protocol):
    async def chat(self, messages: list[Message], **kwargs) -> Response: ...
    async def stream(self, messages: list[Message], **kwargs) -> AsyncIterator[Chunk]: ...

# Built-in providers: Anthropic, OpenAI, Ollama, AWS Bedrock, Google Vertex
```

**Key modules:**
- `core/runtime/agent.py` — Agent base class, lifecycle state machine
- `core/runtime/capability.py` — Capability model, Rule-of-Two enforcement
- `core/runtime/pool.py` — Agent pool manager (warm pool, scaling)
- `core/runtime/supervisor.py` — Parent-child agent supervision tree

### FR-03: Workflow / Graph Engine

Pregel/Beam-inspired graph execution engine (ADR-001).

**Graph Primitives:**
- **Node**: Stateful computation unit bound to an agent
- **Edge**: Conditional transition (predicate function or LLM router)
- **Subgraph**: Composable nested graph
- **Checkpoint**: Serializable snapshot of full graph state

```python
from pylon.engine import Graph, Node, Edge

graph = Graph("code-review")
graph.add_node("plan", agent="planner")
graph.add_node("review", agent="reviewer")
graph.add_node("approve", agent="approver", autonomy="A3")
graph.add_edge("plan", "review")
graph.add_edge("review", "approve", condition=lambda state: state.has_issues)
graph.add_edge("review", END, condition=lambda state: not state.has_issues)
```

**Execution Model:**
- Async-first, supports parallel node execution (fan-out/fan-in)
- Deterministic replay from checkpoint
- State serialized to PostgreSQL (JSONB) with version vectors
- NATS JetStream for event sourcing (ADR-002)
- Configurable retry policies (exponential backoff, circuit breaker)

**Key modules:**
- `core/engine/graph.py` — Graph definition, DAG validation
- `core/engine/executor.py` — Pregel-style superstep execution
- `core/engine/checkpoint.py` — Checkpoint serialization/restoration
- `core/engine/state.py` — Immutable state container with version vectors

### FR-04: Coding Loop

**Plan → Code → Execute → Observe → Refine** cycle.

```
┌──────┐     ┌──────┐     ┌─────────┐     ┌─────────┐     ┌────────┐
│ Plan │────→│ Code │────→│ Execute │────→│ Observe │────→│ Refine │
└──────┘     └──────┘     └────┬────┘     └─────────┘     └───┬────┘
                               │                               │
                               └──── Sandbox (gVisor) ─────────┘
```

**Key modules:**
- `core/coding/planner.py` — Break task into subtasks with file targets
- `core/coding/coder.py` — Generate code diffs (unified diff format)
- `core/coding/executor.py` — Run in sandbox, capture stdout/stderr/exit code
- `core/coding/observer.py` — Analyze test results, lint output, runtime errors
- `core/coding/refiner.py` — Iterate on failures with context from observer

**Constraints:**
- Max iterations configurable (default: 5)
- Each iteration creates a checkpoint
- Sandbox timeout: 60s default, 300s max
- File writes validated against allowlist (no `/etc`, no `~/.ssh`)

### FR-05: Sandbox

**Isolation tiers:**

| Tier | Runtime | Startup | Use Case |
|------|---------|---------|----------|
| Standard | gVisor (runsc) | <500ms | Default for all agent code execution |
| High | Firecracker microVM | <2s | Untrusted code, multi-tenant production |
| None | Host process | 0ms | Trusted internal tools only (opt-in) |

**Sandbox Manager:**
```python
class SandboxManager:
    async def create(self, config: SandboxConfig) -> Sandbox: ...
    async def execute(self, sandbox_id: str, command: Command) -> Result: ...
    async def destroy(self, sandbox_id: str) -> None: ...
    async def snapshot(self, sandbox_id: str) -> Snapshot: ...
```

**Key modules:**
- `core/sandbox/manager.py` — Pool management, warm pool pre-allocation
- `core/sandbox/gvisor.py` — gVisor runtime integration
- `core/sandbox/firecracker.py` — Firecracker microVM integration
- `core/sandbox/filesystem.py` — Overlay FS, allowlist enforcement
- `core/sandbox/network.py` — Network namespace, egress filtering

**Non-functional targets:**
- Warm sandbox startup: <500ms (gVisor), <2s (Firecracker)
- Concurrent sandboxes: 5,000+
- Memory per sandbox: 256MB default, configurable to 4GB

### FR-06: Tools & Skills

**Tool Registry:**
```python
@tool(name="github-pr-read", description="Read PR details")
async def read_pr(owner: str, repo: str, number: int) -> PullRequest:
    ...

# Tools are registered in the control-plane registry
# Agents request tools by name; capability checks applied before granting
```

**Skill System:**
- Skills = composable tool chains with state
- Defined as Python packages or YAML descriptors
- Hot-reloadable at runtime

**Key modules:**
- `control-plane/registry/tools.py` — Tool registration, discovery, versioning
- `control-plane/registry/skills.py` — Skill composition, dependency resolution

### FR-07: Memory Architecture

Four-layer memory model:

| Layer | Storage | TTL | Scope |
|-------|---------|-----|-------|
| Working | In-process dict | Session | Single agent invocation |
| Episodic | PostgreSQL + pgvector | 30d default | Per-agent, per-tenant |
| Semantic | PostgreSQL + pgvector (HNSW) | Permanent | Shared knowledge base |
| Procedural | PostgreSQL | Permanent | Learned action patterns |

```python
class MemoryManager:
    async def store(self, layer: Layer, key: str, value: Any, embedding: Vector | None = None) -> None: ...
    async def recall(self, layer: Layer, query: str, limit: int = 10) -> list[Memory]: ...
    async def distill(self, source: Layer, target: Layer) -> DistillResult: ...
    async def forget(self, layer: Layer, key: str) -> None: ...
```

**Key modules:**
- `core/memory/manager.py` — Unified memory interface
- `core/memory/working.py` — In-process working memory
- `core/memory/episodic.py` — Episode storage with vector search
- `core/memory/semantic.py` — Semantic knowledge with HNSW index
- `core/memory/procedural.py` — Action pattern storage and retrieval
- `core/memory/distiller.py` — Cross-layer memory distillation (CronJob)

### FR-08: MCP Integration

**Protocol version:** MCP 2025-11-25

**Transport:** Streamable HTTP (primary), stdio (local dev)

**Authentication:** OAuth 2.1 + PKCE

**Modes:**
- **MCP Client**: Pylon connects to external MCP servers as a client
- **MCP Server**: Pylon exposes its tools/skills as MCP-compatible endpoints

```python
# As MCP Client
async with MCPClient("https://mcp.example.com", auth=oauth_config) as client:
    tools = await client.list_tools()
    result = await client.call_tool("search", query="pylon docs")

# As MCP Server (auto-generated from tool registry)
app = create_mcp_server(tool_registry)
# Exposes: /mcp/v1/tools, /mcp/v1/resources, /mcp/v1/prompts
```

**Key modules:**
- `protocols/mcp/client.py` — MCP client with Streamable HTTP transport
- `protocols/mcp/server.py` — MCP server exposing Pylon tools
- `protocols/mcp/auth.py` — OAuth 2.1 + PKCE handler
- `protocols/mcp/types.py` — MCP protocol type definitions

### FR-09: A2A Integration

**Protocol version:** A2A RC v1.0

**Discovery:** `/.well-known/agent-card.json` (NOT `agent.json`)

```json
// GET /.well-known/agent-card.json
{
  "name": "pylon-reviewer",
  "description": "Code review agent",
  "url": "https://agents.example.com/reviewer",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": true
  },
  "skills": [
    { "id": "code-review", "name": "Code Review" }
  ],
  "authentication": {
    "schemes": ["oauth2"]
  }
}
```

**Key modules:**
- `protocols/a2a/server.py` — A2A task endpoint handler
- `protocols/a2a/client.py` — A2A task delegation client
- `protocols/a2a/card.py` — Agent card generation and discovery
- `protocols/a2a/types.py` — A2A protocol type definitions

### FR-10: Policy & Safety

**Autonomy Ladder:**

| Level | Name | Behavior |
|-------|------|----------|
| A0 | Manual | Agent suggests, human executes |
| A1 | Supervised | Agent executes each step after human approval |
| A2 | Semi-autonomous | Agent executes within policy bounds, reports results |
| A3 | Autonomous-guarded | Agent plans and executes; human approves plan |
| A4 | Fully autonomous | Agent operates independently within safety envelope |

**Policy Engine:**
```python
class PolicyEngine:
    async def classify(self, request: Request) -> PolicyDecision: ...
    async def check_approval(self, action: Action, autonomy: AutonomyLevel) -> ApprovalResult: ...
    async def enforce_budget(self, tenant_id: str, cost: Decimal) -> bool: ...
    async def kill_switch(self, scope: str) -> None: ...  # Immediate halt

# Policy Pack (YAML)
policies:
  cost:
    max_per_workflow: 10.0
    max_per_tenant_daily: 100.0
    currency: USD
  safety:
    blocked_actions: [rm -rf, DROP TABLE, force push to main]
    require_approval:
      - pattern: "*.production.*"
        level: A3
  compliance:
    data_residency: [us-east-1, ap-northeast-1]
    audit_log: required
```

**Key modules:**
- `core/safety/policy.py` — Policy engine, rule evaluation
- `core/safety/autonomy.py` — Autonomy ladder enforcement
- `core/safety/rule_of_two.py` — Rule-of-Two runtime enforcer
- `core/safety/kill_switch.py` — Emergency halt (tenant/global scope)
- `core/safety/audit.py` — Immutable audit log writer

### FR-11: Multi-Tenancy

**Isolation model:**
- Tenant → Namespace (K8s) + Schema (PostgreSQL) + VHost (NATS)
- Per-tenant resource quotas (CPU, memory, sandbox count, LLM budget)
- Network policies: deny-all default, explicit allow to control plane
- SPIFFE/SPIRE workload identity per tenant

**Key modules:**
- `control-plane/tenant/manager.py` — Tenant lifecycle (create/update/delete)
- `control-plane/tenant/quota.py` — Resource quota enforcement
- `control-plane/tenant/isolation.py` — Namespace/schema/network setup

### FR-12: Observability

**Stack:** OpenTelemetry GenAI Semantic Conventions v1.40

**Signals:**
- Traces: Full workflow execution trace with LLM spans (model, tokens, latency)
- Metrics: Agent count, sandbox utilization, LLM cost, workflow latency
- Logs: Structured JSON, correlated with trace IDs
- Events: NATS JetStream for real-time event streaming

**Key modules:**
- `core/runtime/telemetry.py` — OTel instrumentation, GenAI span attributes
- `control-plane/gateway/middleware/tracing.ts` — Gateway trace propagation

**Dashboards (Grafana):**
- Workflow execution overview
- LLM cost and token usage per tenant
- Sandbox pool utilization
- Agent health and lifecycle

### FR-13: Product Surfaces

**CLI (`pylon`):**
```bash
pylon init                    # Scaffold new project
pylon dev                     # Local development server with hot-reload
pylon run [workflow]          # Execute workflow
pylon replay <checkpoint-id>  # Replay from checkpoint
pylon inspect <run-id>        # Inspect execution state
pylon approve <approval-id>   # Approve pending action
pylon publish                 # Publish agent/skill to registry
pylon doctor                  # Health check and diagnostics
pylon eval <suite>            # Run eval suite
```

**Web Console:**
- Workflow builder (visual graph editor)
- Real-time execution monitor
- Approval inbox
- Cost and usage dashboard
- Tenant management (enterprise)

**SDK:**
- Python: `pip install pylon-sdk`
- TypeScript: `npm install @pylon/sdk`

### FR-14: OSS Governance

- **License**: MIT for all core components
- **DCO**: Developer Certificate of Origin required for contributions
- **CODEOWNERS**: Per-directory ownership
- **Release Process**: Semantic versioning, changelog generation, signed releases
- **SLSA Build Level 3**: Signed provenance, hermetic builds
- **SBOM**: CycloneDX + SPDX dual format
- **VEX**: Vulnerability Exploitability Statements for known CVEs

---

## 5. Non-Functional Requirements

### 5.1 Performance Targets

| Metric | Target |
|--------|--------|
| Hello World (pylon init → first run) | <10 minutes |
| Warm sandbox startup (gVisor) | <500ms |
| Workflow start latency | <200ms |
| Concurrent workflows | 10,000+ |
| Active sandboxes | 5,000+ |
| Checkpoint save/restore | <1s for 10MB state |
| MCP tool call round-trip | <100ms (local) |

### 5.2 Availability

| Tier | SLA |
|------|-----|
| Standard | 99.9% |
| Enterprise | 99.95% |

### 5.3 Security Compliance

- OWASP Agentic Top 10 (2026)
- OWASP LLM Top 10 (2025)
- CIS Kubernetes Benchmark Level 2
- Zero Trust architecture (mTLS, SPIFFE/SPIRE)
- SOC 2 Type II readiness
- ISO 27001/27017/27018 alignment
- ISO 42001 AI Management System
- GDPR / APPI data residency controls
- EU AI Act compliance enablement

---

## 6. Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Core Engine | Python 3.12+ | Async-first, ML ecosystem, type hints |
| API Gateway | TypeScript + Hono | Edge-ready, WebSocket/SSE, shared with frontend (ADR-003) |
| Graph Engine | Custom (Pregel/Beam) | No LangChain dependency (ADR-001) |
| Message Bus | NATS JetStream | Lightweight, K8s-native, persistent (ADR-002) |
| Primary DB | PostgreSQL 16 + pgvector | JSONB checkpoints, vector search, schemas per tenant |
| Cache | Redis 7 | Session cache, pub/sub, rate limiting |
| Object Store | S3 / MinIO | Sandbox images, artifacts, recordings |
| Sandbox (default) | gVisor (runsc) | <500ms startup, syscall filtering |
| Sandbox (high) | Firecracker | microVM isolation, <2s startup |
| Identity | SPIFFE/SPIRE | Workload identity, mTLS |
| Observability | OpenTelemetry + Prometheus + Grafana | GenAI semantic conventions |
| Container | Kubernetes 1.29+ | Orchestration, namespace isolation |
| CI/CD | GitHub Actions | SLSA Level 3, signed provenance |

---

## 7. Milestones

### M0: Foundation (4-6 weeks)
- [ ] Repository structure migration (from stacks/ to core/ layout)
- [ ] Core runtime: Agent lifecycle, capability model
- [ ] Graph engine: Basic DAG execution with checkpoints
- [ ] pylon.yaml parser and validator
- [ ] gVisor sandbox integration (create/execute/destroy)
- [ ] PostgreSQL schema: tenants, workflows, checkpoints, agents
- [ ] CLI: `pylon init`, `pylon run`, `pylon doctor`
- [ ] Unit test framework (pytest + pytest-asyncio)
- [ ] CI pipeline (GitHub Actions)

### M1: Developer Beta (6-8 weeks)
- [ ] Full graph engine: conditional edges, fan-out/fan-in, subgraphs
- [ ] Coding loop: Plan-Code-Execute-Observe-Refine
- [ ] Memory: working + episodic layers
- [ ] MCP client integration (Streamable HTTP)
- [ ] LLM provider abstraction (Anthropic, OpenAI, Ollama)
- [ ] Policy engine: autonomy ladder, cost limits
- [ ] CLI: `pylon dev`, `pylon replay`, `pylon inspect`
- [ ] Python SDK: `pylon-sdk` package
- [ ] Integration test suite
- [ ] Documentation: getting started, API reference

### M2: Team Beta (8 weeks)
- [ ] A2A server + client
- [ ] MCP server (expose Pylon tools)
- [ ] Memory: semantic + procedural layers with HNSW
- [ ] Multi-tenancy: namespace isolation, per-tenant quotas
- [ ] API gateway (Hono): REST + WebSocket + SSE
- [ ] Approval workflow (human-in-the-loop)
- [ ] Web console: workflow monitor, approval inbox
- [ ] TypeScript SDK: `@pylon/sdk`
- [ ] Helm chart v1
- [ ] SWE-bench eval integration

### M3: Enterprise RC (8-12 weeks)
- [ ] Firecracker sandbox tier
- [ ] SPIFFE/SPIRE workload identity
- [ ] Rule-of-Two runtime enforcement
- [ ] Kill switch (tenant + global scope)
- [ ] Full observability: OTel GenAI, dashboards
- [ ] Memory distillation CronJob
- [ ] Policy packs (YAML-based enterprise guardrails)
- [ ] SLSA Level 3 builds, SBOM, VEX
- [ ] SOC 2 / ISO alignment documentation
- [ ] Performance benchmarks (all NFR targets met)

### M4: OSS GA (2-4 weeks)
- [ ] All acceptance tests passing (AT-01 through AT-10)
- [ ] Documentation complete
- [ ] Governance: CODEOWNERS, DCO, release process
- [ ] Launch: blog post, demo video, community channels

---

## 8. Acceptance Tests

| ID | Test | Criteria |
|----|------|----------|
| AT-01 | Hello World | `pylon init` → first successful run in <10 minutes |
| AT-02 | Checkpoint Resume | Kill mid-workflow, `pylon replay` completes successfully |
| AT-03 | Approval Gate | A3 action blocks until human approves via CLI/Web |
| AT-04 | MCP Export | Pylon tools accessible via standard MCP client |
| AT-05 | A2A Delegation | Agent delegates task to external A2A peer, receives result |
| AT-06 | Tenant Isolation | Tenant A cannot access Tenant B's data, agents, or sandboxes |
| AT-07 | Kill Switch | `pylon kill --scope=tenant` halts all agents within 5s |
| AT-08 | Supply Chain | SLSA provenance verified, SBOM accurate, VEX published |
| AT-09 | Eval Regression | SWE-bench score regression blocks CI merge |
| AT-10 | DR Drill | Full state restore from backup in <30 minutes |

---

## 9. Domain Model

```
Tenant ─────────────┐
  │                  │
  ├── Agent ─────────┤
  │     ├── Capability
  │     ├── Memory
  │     └── Tool[]
  │                  │
  ├── Workflow ──────┤
  │     ├── Graph
  │     │    ├── Node[]
  │     │    └── Edge[]
  │     ├── Checkpoint[]
  │     ├── Run[]
  │     └── Policy
  │                  │
  ├── Sandbox ───────┤
  │     ├── Filesystem
  │     └── Network
  │                  │
  └── ApprovalQueue
        └── Approval[]
```

---

## 10. API Design

### 10.1 REST API (Hono Gateway)

```
POST   /api/v1/workflows              # Create workflow
GET    /api/v1/workflows/:id           # Get workflow status
POST   /api/v1/workflows/:id/run       # Execute workflow
POST   /api/v1/workflows/:id/replay    # Replay from checkpoint
DELETE /api/v1/workflows/:id           # Cancel workflow

GET    /api/v1/agents                  # List agents
POST   /api/v1/agents                  # Register agent
GET    /api/v1/agents/:id/status       # Agent status

POST   /api/v1/approvals/:id/approve   # Approve action
POST   /api/v1/approvals/:id/reject    # Reject action
GET    /api/v1/approvals/pending       # List pending approvals

GET    /api/v1/checkpoints/:workflow_id # List checkpoints
GET    /api/v1/checkpoints/:id          # Get checkpoint detail

WS     /api/v1/stream/:workflow_id     # Real-time execution stream
SSE    /api/v1/events/:workflow_id     # Server-sent events
```

### 10.2 MCP Endpoints

```
POST   /mcp/v1/tools/list             # List available tools
POST   /mcp/v1/tools/call             # Call a tool
POST   /mcp/v1/resources/list         # List resources
POST   /mcp/v1/resources/read         # Read a resource
POST   /mcp/v1/prompts/list           # List prompts
POST   /mcp/v1/prompts/get            # Get a prompt
```

### 10.3 A2A Endpoints

```
GET    /.well-known/agent-card.json    # Agent discovery
POST   /a2a/v1/tasks                  # Send task
GET    /a2a/v1/tasks/:id              # Get task status
POST   /a2a/v1/tasks/:id/cancel       # Cancel task
```

---

## 11. Database Schema (PostgreSQL)

```sql
-- Core tables (public schema)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    quotas JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id),
    name TEXT NOT NULL,
    config JSONB NOT NULL,
    capabilities JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'INIT',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, name)
);

CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id),
    name TEXT NOT NULL,
    graph JSONB NOT NULL,
    policy JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES workflows(id),
    status TEXT NOT NULL DEFAULT 'RUNNING',
    state JSONB,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES workflow_runs(id),
    node_id TEXT NOT NULL,
    state JSONB NOT NULL,
    version_vector JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES workflow_runs(id),
    action JSONB NOT NULL,
    autonomy_level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Per-tenant memory schema (tenant_<name>)
CREATE TABLE episodic_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    embedding vector(1536),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_episodic_embedding ON episodic_memory
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE semantic_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    embedding vector(1536) NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_semantic_embedding ON semantic_memory
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE procedural_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_name TEXT NOT NULL,
    trigger JSONB NOT NULL,
    action_sequence JSONB NOT NULL,
    success_rate FLOAT DEFAULT 0.0,
    invocation_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 12. NATS JetStream Subjects

```
pylon.workflow.{tenant_id}.created
pylon.workflow.{tenant_id}.{workflow_id}.started
pylon.workflow.{tenant_id}.{workflow_id}.node.{node_id}.started
pylon.workflow.{tenant_id}.{workflow_id}.node.{node_id}.completed
pylon.workflow.{tenant_id}.{workflow_id}.completed
pylon.workflow.{tenant_id}.{workflow_id}.failed
pylon.workflow.{tenant_id}.{workflow_id}.checkpoint
pylon.agent.{tenant_id}.{agent_id}.status
pylon.approval.{tenant_id}.requested
pylon.approval.{tenant_id}.decided
pylon.sandbox.{tenant_id}.created
pylon.sandbox.{tenant_id}.destroyed
pylon.system.kill_switch
```

---

## 13. Configuration

### Environment Variables

```bash
# Required
PYLON_DATABASE_URL=postgresql://user:pass@host:5432/pylon
PYLON_NATS_URL=nats://host:4222
PYLON_REDIS_URL=redis://host:6379

# Optional
PYLON_S3_ENDPOINT=http://minio:9000
PYLON_S3_BUCKET=pylon-artifacts
PYLON_SANDBOX_RUNTIME=gvisor          # gvisor | firecracker | none
PYLON_LOG_LEVEL=info                  # debug | info | warn | error
PYLON_LOG_FORMAT=json                 # json | text
PYLON_OTEL_ENDPOINT=http://otel:4317  # OpenTelemetry collector
PYLON_MAX_CONCURRENT_WORKFLOWS=1000
PYLON_MAX_SANDBOX_POOL_SIZE=100

# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OLLAMA_URL=http://localhost:11434

# Auth
PYLON_OIDC_ISSUER=https://auth.example.com
PYLON_OIDC_CLIENT_ID=pylon
```

---

## 14. Migration Plan (stacks/ → core/ layout)

The current repository uses a `stacks/` structure. Migration to the recommended `core/` layout:

1. Create new directory structure under `core/`, `control-plane/`, `protocols/`, `providers/`
2. Move `src/core/agents/` → `core/runtime/`
3. Move `src/core/workflow/` → `core/engine/`
4. Move `src/core/sandbox/` → `core/sandbox/`
5. Move `src/core/memory/` → `core/memory/`
6. Move `src/core/safety/` → `core/safety/`
7. Move `src/protocols/mcp/` → `protocols/mcp/`
8. Move `src/protocols/a2a/` → `protocols/a2a/`
9. Move `src/gateway/` → `control-plane/gateway/`
10. Move `src/providers/` → `providers/`
11. Remove `stacks/` directory (functionality absorbed into core modules)
12. Update all import paths
13. Update pyproject.toml package discovery

**This migration should be done as a single commit in M0.**

---

## Appendix A: Competitive Differentiation

| Feature | LangGraph | CrewAI | OpenHands | Google ADK | Pylon |
|---------|-----------|--------|-----------|------------|-------|
| Framework-independent | No (LangChain) | No | N/A | No (Google) | Yes |
| MCP native | No | No | Partial | Partial | Yes |
| A2A native | No | No | No | Yes | Yes |
| Sandbox-by-default | No | No | Docker | No | gVisor/Firecracker |
| Checkpoint replay | Yes | No | No | No | Yes |
| Autonomy ladder | No | No | Partial | No | Yes (A0-A4) |
| Multi-tenant | Commercial | No | No | No | Yes (OSS) |
| Rule-of-Two safety | No | No | No | No | Yes |
| MIT license | Yes* | No | MIT | Apache 2.0 | MIT |

*LangGraph OSS is MIT but enterprise features require commercial license.

---

## Appendix B: File Naming Conventions

- Python modules: `snake_case.py`
- TypeScript modules: `kebab-case.ts`
- Config files: `kebab-case.yaml`
- ADRs: `NNN-short-title.md` (sequential numbering)
- Tests mirror source: `core/runtime/agent.py` → `tests/unit/core/runtime/test_agent.py`
