"""Pylon SDK -- Autonomous Workflow Example

Demonstrates five approaches to defining and running autonomous agent workflows
using Pylon's Python SDK:

1. Decorator-based workflow definition
2. Programmatic project definition via DSL models
3. Direct in-process execution
4. Remote execution via the HTTP client
5. Autonomy primitives: goals, termination, and model routing
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Section 1: Decorator-based workflow definition
# ---------------------------------------------------------------------------

def section_decorator_workflow() -> None:
    """Define agents, tools, and a workflow using Pylon's decorator API.

    Decorated functions are automatically registered in global registries
    (AgentRegistry, ToolRegistry, WorkflowRegistry) and can later be
    resolved by name when a project is materialized for execution.
    """
    from pylon.sdk.decorators import agent, tool, workflow

    # -- Custom tools -------------------------------------------------------

    @tool(name="static_analysis", description="Run static analysis on source code")
    def run_static_analysis(source: str) -> dict[str, Any]:
        """Simulate a static-analysis pass and return findings."""
        issues: list[str] = []
        if "eval(" in source:
            issues.append("Unsafe eval() usage detected")
        if len(source.splitlines()) > 500:
            issues.append("File exceeds 500-line limit")
        return {"issues": issues, "lines_analyzed": len(source.splitlines())}

    @tool(name="test_runner", description="Execute test suite and report results")
    def run_tests(test_dir: str) -> dict[str, Any]:
        """Simulate running a test suite."""
        return {
            "passed": 42,
            "failed": 0,
            "skipped": 1,
            "coverage_pct": 87.3,
            "test_dir": test_dir,
        }

    # -- Agent handlers -----------------------------------------------------
    # Each handler receives the current workflow state dict and returns a
    # state-patch dict that is merged into the shared state.

    @agent(name="analyzer", role="code_analysis", tools=["static_analysis"])
    def handle_analyzer(state: dict[str, Any]) -> dict[str, Any]:
        """Analyze the input source code and produce findings."""
        source = state.get("source_code", "")
        findings = run_static_analysis(source)
        return {
            "analysis_complete": True,
            "findings": findings,
        }

    @agent(name="implementer", role="code_generation", tools=[])
    def handle_implementer(state: dict[str, Any]) -> dict[str, Any]:
        """Generate an implementation based on analysis findings."""
        findings = state.get("findings", {})
        issues = findings.get("issues", [])
        patches = [f"fix: {issue}" for issue in issues]
        return {
            "implementation_complete": True,
            "patches": patches,
        }

    @agent(name="validator", role="quality_assurance", tools=["test_runner"])
    def handle_validator(state: dict[str, Any]) -> dict[str, Any]:
        """Validate the implementation by running tests."""
        test_results = run_tests("tests/")
        passed = test_results["failed"] == 0
        return {
            "validation_complete": True,
            "test_results": test_results,
            "all_tests_passed": passed,
        }

    # -- Workflow definition ------------------------------------------------

    @workflow(name="code-review-pipeline")
    def review_pipeline() -> None:
        """Declarative workflow composed from registered agents.

        The workflow runtime resolves the agent names registered above and
        wires them into a sequential graph: analyzer -> implementer -> validator.
        """

    # Verify registrations
    from pylon.sdk.decorators import AgentRegistry, ToolRegistry, WorkflowRegistry

    print("=== Section 1: Decorator-based workflow ===")
    print(f"Registered agents:    {list(AgentRegistry.get_agents().keys())}")
    print(f"Registered tools:     {list(ToolRegistry.get_tools().keys())}")
    print(f"Registered workflows: {list(WorkflowRegistry.get_workflows().keys())}")

    # Demonstrate calling a handler directly
    sample_state = {"source_code": "x = eval(input())"}
    result = handle_analyzer(sample_state)
    print(f"Analyzer output:      {result}")
    print()


# ---------------------------------------------------------------------------
# Section 2: Programmatic project definition
# ---------------------------------------------------------------------------

def section_programmatic_project() -> dict[str, Any]:
    """Build a PylonProject entirely in Python using the DSL models.

    This is the declarative equivalent of writing a pylon.yaml file, but
    constructed programmatically for dynamic or generated workflows.
    """
    from pylon.dsl.parser import (
        AgentDef,
        GoalConstraintsDef,
        GoalCriterionDef,
        GoalDef,
        PolicyDef,
        PylonProject,
        SafetyDef,
        WorkflowDef,
        WorkflowNodeDef,
    )

    project = PylonProject(
        version="1",
        name="autonomous-review",
        description="Three-stage code review with bounded autonomy",
        agents={
            "analyzer": AgentDef(
                model="anthropic/claude-sonnet-4-20250514",
                role="code_analysis",
                autonomy="A2",
                tools=["static_analysis"],
                sandbox="gvisor",
                input_trust="untrusted",
            ),
            "implementer": AgentDef(
                model="anthropic/claude-sonnet-4-20250514",
                role="code_generation",
                autonomy="A2",
                tools=[],
                sandbox="gvisor",
            ),
            "validator": AgentDef(
                model="anthropic/claude-haiku-3-5-20241022",
                role="quality_assurance",
                autonomy="A1",
                tools=["test_runner"],
                sandbox="gvisor",
            ),
        },
        workflow=WorkflowDef(
            type="graph",
            nodes={
                "analyze": WorkflowNodeDef(agent="analyzer", next="implement"),
                "implement": WorkflowNodeDef(agent="implementer", next="validate"),
                "validate": WorkflowNodeDef(agent="validator", next="END"),
            },
        ),
        policy=PolicyDef(
            max_cost_usd=5.0,
            max_duration="30m",
            require_approval_above="A3",
            safety=SafetyDef(
                blocked_actions=["shell_exec", "network_write"],
                max_file_changes=20,
            ),
        ),
        goal=GoalDef(
            objective="Review source code, fix issues, and validate all tests pass",
            success_criteria=[
                GoalCriterionDef(
                    type="test_pass_rate",
                    threshold=1.0,
                    rubric="All tests must pass with zero failures",
                ),
                GoalCriterionDef(
                    type="static_analysis_clean",
                    threshold=0.95,
                    rubric="At most 5% of findings may remain unresolved",
                ),
            ],
            constraints=GoalConstraintsDef(
                max_iterations=10,
                max_tokens=100_000,
                max_cost_usd=5.0,
                timeout="30m",
            ),
        ),
    )

    # Serialize to JSON-compatible dict for storage or transport
    serialized = project.model_dump(mode="json")

    print("=== Section 2: Programmatic project definition ===")
    print(f"Project name:       {project.name}")
    print(f"Agents:             {list(project.agents.keys())}")
    print(f"Workflow nodes:     {list(project.workflow.nodes.keys())}")
    print(f"Goal objective:     {project.goal.objective}")  # type: ignore[union-attr]
    print(f"Serialized keys:    {list(serialized.keys())}")
    print()

    return serialized


# ---------------------------------------------------------------------------
# Section 3: Direct in-process execution
# ---------------------------------------------------------------------------

def section_direct_execution() -> None:
    """Compile and execute a project using the in-process runtime.

    ``compile_project_graph`` converts a PylonProject into the internal
    WorkflowGraph representation.  ``execute_project_sync`` runs it through
    the full runtime including checkpoints, approvals, and goal evaluation.
    """
    from pylon.dsl.parser import (
        AgentDef,
        GoalConstraintsDef,
        GoalCriterionDef,
        GoalDef,
        PolicyDef,
        PylonProject,
        WorkflowDef,
        WorkflowNodeDef,
    )
    from pylon.runtime.execution import compile_project_graph, execute_project_sync

    # Build a minimal project for local execution
    project = PylonProject(
        name="local-pipeline",
        agents={
            "analyzer": AgentDef(role="analysis", autonomy="A1"),
            "validator": AgentDef(role="validation", autonomy="A1"),
        },
        workflow=WorkflowDef(
            nodes={
                "analyze": WorkflowNodeDef(agent="analyzer", next="validate"),
                "validate": WorkflowNodeDef(agent="validator", next="END"),
            },
        ),
        policy=PolicyDef(max_cost_usd=1.0, max_duration="5m"),
        goal=GoalDef(
            objective="Analyze and validate input data",
            success_criteria=[
                GoalCriterionDef(type="completeness", threshold=1.0),
            ],
            constraints=GoalConstraintsDef(max_iterations=5, timeout="5m"),
        ),
    )

    # Inspect the compiled graph
    graph = compile_project_graph(project)
    print("=== Section 3: Direct execution ===")
    print(f"Graph name:         {graph.name}")
    print(f"Graph nodes:        {list(graph.nodes.keys())}")

    # Provide custom node handlers so the example runs without an LLM provider.
    # In production you would omit these and let the runtime call the model.
    def analyzer_handler(state: dict[str, Any]) -> dict[str, Any]:
        return {"analysis": "ok", "score": 0.95}

    def validator_handler(state: dict[str, Any]) -> dict[str, Any]:
        return {"validated": True}

    artifacts = execute_project_sync(
        project,
        input_data={"source": "def hello(): pass"},
        workflow_id="local-pipeline",
        node_handlers={
            "analyze": analyzer_handler,
            "validate": validator_handler,
        },
    )

    print(f"Run ID:             {artifacts.run.id}")
    print(f"Run status:         {artifacts.run.status.value}")
    print(f"Checkpoints:        {len(artifacts.checkpoints)}")
    print(f"Approvals:          {len(artifacts.approvals)}")
    print(f"Final state keys:   {list(artifacts.run.state.keys())}")
    print()


# ---------------------------------------------------------------------------
# Section 4: HTTP client usage
# ---------------------------------------------------------------------------

def section_http_client() -> None:
    """Interact with a remote Pylon server using PylonHTTPClient.

    The HTTP client targets the canonical workflow control-plane API exposed
    by ``pylon.server``.  It supports project registration, run management,
    approval workflows, and checkpoint replay.

    NOTE: This section is illustrative.  It will raise a connection error
    unless a Pylon server is running at the configured URL.
    """
    print("=== Section 4: HTTP client (illustrative) ===")

    try:
        from pylon.sdk.http_client import PylonHTTPClient
    except ImportError:
        # The full HTTP client import chain pulls in heavy modules
        # (config, api, control_plane) that may not be available in all
        # environments.  Show the API surface documentation instead.
        print("  (PylonHTTPClient import unavailable in this environment)")
        print("  Install the full pylon[server] extras to use the HTTP client.")
        _print_http_client_api_surface()
        return

    # Connect to a remote Pylon server
    client = PylonHTTPClient(
        base_url="http://localhost:8080",
        api_key="my-api-key",
        timeout=30,
        tenant_id="default",
        correlation_id="example-session-001",
    )

    print(f"Base URL:           {client.config.base_url}")
    print(f"Tenant ID:          {client.tenant_id}")
    print(f"Correlation ID:     {client.correlation_id}")
    print()

    _print_http_client_api_surface()


def _print_http_client_api_surface() -> None:
    """Print the HTTP client API surface documentation."""
    # The calls below demonstrate the API surface.  Each would require a
    # running server, so they are shown as documentation rather than executed.
    print("Available operations (require a running server):")
    print("  client.register_project('my-project', project)")
    print("  client.list_workflows()")
    print("  client.get_workflow('my-project')")
    print("  result = client.run_workflow('my-project', input_data={...})")
    print("  run    = client.get_run(result.run_id)")
    print("  client.approve_request(run.approval_request_id, reason='LGTM')")
    print("  client.list_checkpoints(run_id=result.run_id)")
    print("  client.replay_checkpoint(checkpoint_id)")
    print()
    print("After each call, inspect observability headers:")
    print("  client.last_trace_id       -- distributed trace ID")
    print("  client.last_request_id     -- unique request ID")
    print("  client.last_response_headers")
    print()


# ---------------------------------------------------------------------------
# Section 5: Autonomy and termination primitives
# ---------------------------------------------------------------------------

def section_autonomy() -> None:
    """Compose goal specifications, termination conditions, and model routing.

    These primitives form the foundation of Pylon's bounded autonomy system.
    They can be used independently of the workflow runtime for custom control
    loops or evaluation harnesses.
    """
    from pylon.autonomy import (
        CostBudget,
        GoalConstraints,
        GoalSpec,
        MaxIterations,
        ModelProfile,
        ModelRouter,
        ModelRouteRequest,
        ModelTier,
        QualityThreshold,
        SuccessCriterion,
        Timeout,
    )

    print("=== Section 5: Autonomy primitives ===")

    # -- Goal specification -------------------------------------------------

    goal = GoalSpec(
        objective="Produce a production-ready code review",
        success_criteria=(
            SuccessCriterion(
                type="test_pass_rate",
                threshold=1.0,
                rubric="All tests must pass",
            ),
            SuccessCriterion(
                type="review_coverage",
                threshold=0.9,
                rubric="At least 90% of changed files reviewed",
            ),
        ),
        constraints=GoalConstraints(
            max_iterations=20,
            max_tokens=200_000,
            max_cost_usd=10.0,
            timeout_seconds=1800,
        ),
    )

    print(f"Goal objective:     {goal.objective}")
    print(f"Success criteria:   {len(goal.success_criteria)}")
    print(f"Constraints:        {goal.constraints.to_dict()}")

    # -- Composable termination conditions ----------------------------------
    # The | operator creates AnyTermination (match if ANY child matches).
    # The & operator creates AllTermination (match only if ALL children match).

    budget_guard = MaxIterations(20) | Timeout(1800) | CostBudget(10.0)
    print(f"Budget guard type:  {type(budget_guard).__name__}")

    # Quality gate: stop early when quality is sufficient
    quality_gate = QualityThreshold(min_score=0.95)

    # Combined: stop on quality OR on any budget limit
    combined = quality_gate | budget_guard
    print(f"Combined type:      {type(combined).__name__}")

    # GoalConstraints can also produce a termination condition directly
    auto_termination = goal.constraints.to_termination_condition()
    print(f"Auto termination:   {type(auto_termination).__name__}")

    # -- Model routing ------------------------------------------------------

    custom_profiles = (
        ModelProfile(
            provider_name="anthropic",
            model_id="claude-haiku-3-5-20241022",
            tier=ModelTier.LIGHTWEIGHT,
            supports_tools=True,
            prompt_caching=True,
            batch_api=True,
        ),
        ModelProfile(
            provider_name="anthropic",
            model_id="claude-sonnet-4-20250514",
            tier=ModelTier.STANDARD,
            supports_tools=True,
            prompt_caching=True,
            batch_api=True,
        ),
        ModelProfile(
            provider_name="anthropic",
            model_id="claude-opus-4-20250514",
            tier=ModelTier.PREMIUM,
            supports_tools=True,
            prompt_caching=True,
            batch_api=True,
        ),
    )

    router = ModelRouter(profiles=custom_profiles)

    # Route a lightweight, latency-sensitive request
    fast_route = router.route(
        ModelRouteRequest(
            purpose="quick-lint",
            input_tokens_estimate=500,
            requires_tools=False,
            latency_sensitive=True,
        ),
    )
    print(f"Fast route:         {fast_route.provider_name}/{fast_route.model_id} "
          f"({fast_route.tier.value})")

    # Route a quality-sensitive, tool-using request with a budget constraint
    quality_route = router.route(
        ModelRouteRequest(
            purpose="deep-review",
            input_tokens_estimate=15_000,
            requires_tools=True,
            quality_sensitive=True,
            remaining_budget_usd=2.50,
        ),
    )
    print(f"Quality route:      {quality_route.provider_name}/{quality_route.model_id} "
          f"({quality_route.tier.value})")
    print(f"Route reasoning:    {quality_route.reasoning}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_decorator_workflow()
    section_programmatic_project()
    section_direct_execution()
    section_http_client()
    section_autonomy()
