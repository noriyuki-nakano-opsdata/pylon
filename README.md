# Pylon

Autonomous AI Agent Orchestration Platform — Sandbox-first, protocol-native, MIT licensed.

## Overview

Pylon is a self-contained AI agent orchestration platform that integrates the best design patterns from 7 major OSS frameworks (LangGraph, CrewAI, OpenHands, Cline, Microsoft Agent Framework, Google ADK, AWS Strands Agents) without depending on any of them.

### Key Features

- **Role-based Agent API** — Declarative agent definitions with role/goal/backstory (CrewAI-inspired)
- **Graph Workflow Engine** — Pregel/Beam-inspired state machine with checkpoints (LangGraph-inspired)
- **Sandbox Code Execution** — gVisor/Firecracker isolated containers (OpenHands-inspired)
- **Human-in-the-Loop** — Plan/Act mode with staged escalation (Cline-inspired)
- **Protocol-Native** — MCP 2025-11-25 + A2A RC v1.0 first-class support
- **Multi-Model** — 100+ LLM providers via unified abstraction
- **Multi-Tenant** — K8s namespace isolation, RLS, Vault secrets
- **Agent Safety** — OWASP Agentic Top 10 compliant, kill switch, Guardian AI

## Architecture



## Tech Stack

| Layer | Technology |
|:---|:---|
| Core Runtime | Python 3.12+, asyncio, pydantic v2 |
| API Gateway | TypeScript, Hono, Zod |
| Message Bus | NATS JetStream |
| Database | PostgreSQL + pgvector (RLS) |
| Cache | Redis |
| Container | gVisor (default), Firecracker (high-sec) |
| Orchestration | Kubernetes (EKS) |
| Secrets | HashiCorp Vault |
| Observability | OpenTelemetry, Prometheus |
| CI/CD | GitHub Actions, ArgoCD |

## Quick Start



## Documentation

- [Architecture](docs/architecture/)
- [ADRs](docs/adr/)
- [API Reference](docs/api/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## License

MIT — See [LICENSE](LICENSE).
