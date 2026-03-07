# Getting Started

## Prerequisites

- Python 3.12 or later
- pip or uv package manager

## Installation

```bash
pip install pylon-ai
```

Or for development:

```bash
git clone https://github.com/your-org/pylon.git
cd pylon
pip install -e ".[dev]"
```

## Initialize a Project

```bash
pylon init my-project
cd my-project
```

This creates:

```
my-project/
  pylon.yaml       # Project configuration
  agents/          # Custom agent definitions
  workflows/       # Workflow templates
  .pylon/          # Runtime state (gitignored)
```

## Configuration

Edit `pylon.yaml` to define agents, workflows, and policies:

```yaml
version: "1"
name: my-project

agents:
  researcher:
    model: anthropic/claude-sonnet-4-20250514
    role: "Research topics and gather information"
    autonomy: A2
    tools: [web-search, file-read]
    sandbox: gvisor
    input_trust: untrusted

  writer:
    model: anthropic/claude-sonnet-4-20250514
    role: "Write clear documentation"
    autonomy: A2
    tools: [file-read, file-write]
    sandbox: docker

workflow:
  type: graph
  nodes:
    research:
      agent: researcher
      next: [write]
    write:
      agent: writer
      next: [END]

policy:
  max_cost_usd: 5.0
  max_duration_seconds: 1800
  max_file_changes: 20
  require_approval_above: A3
```

## Run a Workflow

```bash
# Run the default workflow
pylon run

# Run with input
pylon run --input '{"topic": "distributed systems"}'

# Run a specific workflow
pylon run research-pipeline
```

## Agent Autonomy Levels

Choose the right autonomy level for each agent:

| Level | When to Use |
|-------|-------------|
| **A0** | Sensitive operations (production deployments) |
| **A1** | New or untested agents (step-by-step approval) |
| **A2** | Trusted agents within clear policy bounds (default) |
| **A3** | Complex tasks (approve plan, then autonomous) |
| **A4** | Fully trusted agents in controlled environments |

## Safety Features

Pylon enforces safety at multiple levels:

1. **Rule-of-Two+**: Agents cannot simultaneously process untrusted input and access secrets
2. **Prompt Guard**: Automatic detection of prompt injection attempts
3. **Input Sanitization**: HTML/script stripping for untrusted input
4. **Output Validation**: Shell injection and path traversal detection before tool execution
5. **Kill Switch**: Emergency halt at global, tenant, workflow, or agent scope
6. **Sandbox Isolation**: Resource limits and network policies per execution tier

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYLON_DEFAULT_MODEL` | Default LLM model | `anthropic/claude-sonnet-4-20250514` |
| `PYLON_LOG_LEVEL` | Logging level | `info` |
| `PYLON_SANDBOX_TIER` | Default sandbox tier | `gvisor` |
| `PYLON_VAULT_ADDR` | Vault server address | `http://127.0.0.1:8200` |
| `PYLON_VAULT_TOKEN` | Vault authentication token | (none) |

## Next Steps

- Read the [Architecture Overview](architecture.md) to understand Pylon's design
- See the [API Reference](api-reference.md) for HTTP endpoint documentation
- Explore sandbox tiers and resource limits in the architecture docs
