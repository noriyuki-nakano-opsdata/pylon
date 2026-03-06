"""Pylon - Autonomous AI Agent Orchestration Platform."""

__version__ = "0.2.0"

# Core modules
# pylon.types          - Type definitions (AgentState, TrustLevel, AutonomyLevel, etc.)
# pylon.errors         - Error hierarchy (PylonError, ConfigError, etc.)

# Agent runtime
# pylon.agents.runtime    - Agent dataclass with lifecycle FSM
# pylon.agents.lifecycle  - AgentLifecycleManager
# pylon.agents.pool       - AgentPool with auto-scaling
# pylon.agents.supervisor - AgentSupervisor with health checks
# pylon.agents.registry   - AgentRegistry

# DSL & configuration
# pylon.dsl.parser      - pylon.yaml parser

# Safety & policy
# pylon.safety.autonomy   - Autonomy ladder enforcement
# pylon.safety.capability - Capability validation (Rule-of-Two+)

# Providers
# pylon.providers.base      - Base LLM provider interface
# pylon.providers.anthropic - Anthropic Claude provider

# Workflow
# pylon.workflow.graph    - Workflow graph builder
# pylon.workflow.executor - Workflow executor

# Control plane
# pylon.control_plane.registry.tools  - Tool registration & discovery (FR-06)
# pylon.control_plane.registry.skills - Skill composition & dependency resolution
# pylon.control_plane.tenant.manager  - Tenant lifecycle (FR-11)
# pylon.control_plane.tenant.quota    - Resource quota enforcement
# pylon.control_plane.scheduler       - Workflow scheduler

# Task queue
# pylon.taskqueue.queue     - Priority task queue with FSM
# pylon.taskqueue.worker    - Task workers and worker pool
# pylon.taskqueue.scheduler - Cron-based task scheduling
# pylon.taskqueue.retry     - Retry policies and dead letter queue

# Resources
# pylon.resources.limiter  - Rate limiting (TokenBucket, SlidingWindow)
# pylon.resources.quota    - Resource quota management
# pylon.resources.pool     - Generic resource pool
# pylon.resources.monitor  - Resource monitoring and alerting

# Protocols
# pylon.protocols.mcp - MCP JSON-RPC 2.0
# pylon.protocols.a2a - Agent-to-Agent protocol

# Repository
# pylon.repository.audit      - Audit logging
# pylon.repository.base       - Base repository
# pylon.repository.checkpoint - Checkpoint management
# pylon.repository.memory     - In-memory repository
# pylon.repository.workflow   - Workflow repository

# Sandbox
# pylon.sandbox - Execution isolation

# Memory
# pylon.memory - Agent memory

__all__ = [
    "__version__",
    "agents",
    "control_plane",
    "dsl",
    "errors",
    "memory",
    "protocols",
    "providers",
    "repository",
    "resources",
    "safety",
    "sandbox",
    "taskqueue",
    "types",
    "workflow",
]
