import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
}));

vi.mock("../client", () => ({
  apiFetch,
}));

import { agentsApi } from "../agents";
import { approvalsApi } from "../approvals";
import { adsApi } from "../ads";
import { costsApi } from "../costs";
import { experimentsApi } from "../experiments";
import { featuresApi } from "../features";
import { gtmApi } from "../gtm";
import { lifecycleApi } from "../lifecycle";
import {
  createContent,
  createEvent,
  createMemory,
  createTask,
  createTeam,
  deleteContent,
  deleteEvent,
  deleteMemory,
  deleteTask,
  deleteTeam,
  getAgentActivity,
  getTask,
  listAgentsActivity,
  listContent,
  listEvents,
  listMemories,
  listTasks,
  listTeams,
  updateContent,
  updateTask,
  updateTeam,
} from "../mission-control";
import { modelsApi } from "../models";
import { skillsApi } from "../skills";
import { workflowsApi } from "../workflows";

async function expectApiCall(
  invocation: Promise<unknown>,
  expectedPath: string,
  expectedInit?: RequestInit,
) {
  await invocation;
  if (expectedInit === undefined) {
    expect(apiFetch).toHaveBeenLastCalledWith(expectedPath);
    return;
  }
  expect(apiFetch).toHaveBeenLastCalledWith(expectedPath, expectedInit);
}

describe("stable API contract", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("keeps workflow routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce({ workflows: [], count: 0 });
    await expectApiCall(workflowsApi.list(), "/v1/workflows");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(workflowsApi.get("wf-1"), "/v1/workflows/wf-1");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      workflowsApi.create({ id: "wf-1" }),
      "/v1/workflows",
      { method: "POST", body: JSON.stringify({ id: "wf-1" }) },
    );

    apiFetch.mockResolvedValueOnce({ runs: [], count: 0 });
    await expectApiCall(workflowsApi.listRuns("wf-1"), "/v1/workflows/wf-1/runs");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      workflowsApi.startRun("wf-1", { task: "ship" }),
      "/v1/workflows/wf-1/runs",
      { method: "POST", body: JSON.stringify({ input: { task: "ship" } }) },
    );
  });

  it("keeps experiment campaign routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce({ campaigns: [], count: 0 });
    await expectApiCall(experimentsApi.list("pylon"), "/v1/experiments?project_slug=pylon");

    apiFetch.mockResolvedValueOnce({ campaign: { id: "exp-1" }, iterations: [], count: 0 });
    await expectApiCall(
      experimentsApi.create({
        objective: "Reduce benchmark latency",
        repo_path: "/tmp/repo",
        benchmark_command: "make bench",
        planner_command: "make optimize",
        metric_name: "latency",
        metric_direction: "minimize",
        max_iterations: 3,
      }),
      "/v1/experiments",
      {
        method: "POST",
        body: JSON.stringify({
          objective: "Reduce benchmark latency",
          repo_path: "/tmp/repo",
          benchmark_command: "make bench",
          planner_command: "make optimize",
          metric_name: "latency",
          metric_direction: "minimize",
          max_iterations: 3,
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({ campaign: { id: "exp-1" }, iterations: [], count: 0 });
    await expectApiCall(experimentsApi.get("exp-1"), "/v1/experiments/exp-1");

    apiFetch.mockResolvedValueOnce({ campaign: { id: "exp-1" }, iterations: [], count: 0 });
    await expectApiCall(
      experimentsApi.start("exp-1"),
      "/v1/experiments/exp-1/start",
      { method: "POST" },
    );

    apiFetch.mockResolvedValueOnce({ campaign: { id: "exp-1" }, iterations: [], count: 0 });
    await expectApiCall(
      experimentsApi.promote("exp-1", "pylon/experiments/promoted/exp-1"),
      "/v1/experiments/exp-1/promote",
      {
        method: "POST",
        body: JSON.stringify({ branch_name: "pylon/experiments/promoted/exp-1" }),
      },
    );
  });

  it("keeps agent and approval routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce({ agents: [], count: 0 });
    await expectApiCall(agentsApi.list(), "/v1/agents");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(agentsApi.get("agent-1"), "/v1/agents/agent-1");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      agentsApi.create({ name: "coder" }),
      "/v1/agents",
      { method: "POST", body: JSON.stringify({ name: "coder" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      agentsApi.update("agent-1", { autonomy: "A3" }),
      "/v1/agents/agent-1",
      { method: "PATCH", body: JSON.stringify({ autonomy: "A3" }) },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(
      agentsApi.delete("agent-1"),
      "/v1/agents/agent-1",
      { method: "DELETE" },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(agentsApi.getSkills("agent-1"), "/v1/agents/agent-1/skills");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      agentsApi.updateSkills("agent-1", ["triage"]),
      "/v1/agents/agent-1/skills",
      { method: "PATCH", body: JSON.stringify({ skills: ["triage"] }) },
    );

    apiFetch.mockResolvedValueOnce({ approvals: [], count: 0 });
    await expectApiCall(approvalsApi.list(), "/v1/approvals");

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(
      approvalsApi.approve("approval-1"),
      "/v1/approvals/approval-1/approve",
      { method: "POST" },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(
      approvalsApi.reject("approval-1", "unsafe"),
      "/v1/approvals/approval-1/reject",
      { method: "POST", body: JSON.stringify({ reason: "unsafe" }) },
    );
  });

  it("keeps skills, models, costs, and features routes aligned with backend contract", async () => {
    apiFetch.mockResolvedValueOnce({
      skills: [],
      total: 0,
      categories: {},
      sources: {},
    });
    await expectApiCall(
      skillsApi.list({ category: "ops", source: "local", search: "triage" }),
      "/v1/skills?category=ops&source=local&search=triage",
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(skillsApi.get("triage"), "/v1/skills/triage");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      skillsApi.execute(
        "triage",
        "Investigate login failures",
        { repo: "pylon" },
        "anthropic",
        "claude-sonnet-4-6",
      ),
      "/v1/skills/triage/execute",
      {
        method: "POST",
        body: JSON.stringify({
          input: "Investigate login failures",
          context: { repo: "pylon" },
          provider: "anthropic",
          model: "claude-sonnet-4-6",
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      skillsApi.scan(),
      "/v1/skills/scan",
      { method: "POST" },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(skillsApi.categories(), "/v1/skills/categories");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(skillsApi.importSummary(), "/v1/skill-import/summary");

    apiFetch.mockResolvedValueOnce({ providers: {}, fallback_chain: [], policies: {} });
    await expectApiCall(modelsApi.list(), "/v1/models");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      modelsApi.updatePolicy("anthropic", "balanced", "claude-sonnet-4-6"),
      "/v1/models/policy",
      {
        method: "POST",
        body: JSON.stringify({
          provider: "anthropic",
          policy: "balanced",
          pin: "claude-sonnet-4-6",
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({ providers: {}, fallback_chain: [], policies: {} });
    await expectApiCall(
      modelsApi.refresh(),
      "/v1/models/refresh",
      { method: "POST" },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(modelsApi.health(), "/v1/models/health");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(costsApi.summary("7d"), "/v1/costs/summary?period=7d");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(featuresApi.get(), "/v1/features");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(gtmApi.getOverview(), "/v1/gtm/overview");
  });

  it("keeps mission-control routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listTasks("review"), "/v1/tasks?status=review");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(getTask("task-1"), "/v1/tasks/task-1");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      createTask({
        title: "Triage regressions",
        description: "Check failing smoke tests",
        status: "backlog",
        priority: "high",
        assignee: "ops-bot",
        assigneeType: "ai",
      }),
      "/v1/tasks",
      {
        method: "POST",
        body: JSON.stringify({
          title: "Triage regressions",
          description: "Check failing smoke tests",
          status: "backlog",
          priority: "high",
          assignee: "ops-bot",
          assigneeType: "ai",
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      updateTask("task-1", { status: "review" }),
      "/v1/tasks/task-1",
      { method: "PATCH", body: JSON.stringify({ status: "review" }) },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(deleteTask("task-1"), "/v1/tasks/task-1", { method: "DELETE" });

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listMemories(), "/v1/memories");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      createMemory({
        title: "Insight",
        content: "Users drop before activation",
        category: "learnings",
        actor: "ops-bot",
        tags: ["activation"],
      }),
      "/v1/memories",
      {
        method: "POST",
        body: JSON.stringify({
          title: "Insight",
          content: "Users drop before activation",
          category: "learnings",
          actor: "ops-bot",
          tags: ["activation"],
        }),
      },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(deleteMemory(7), "/v1/memories/7", { method: "DELETE" });

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listAgentsActivity(), "/v1/agents/activity");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(getAgentActivity("agent-1"), "/v1/agents/agent-1/activity");

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listEvents(), "/v1/events");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      createEvent({
        title: "Review",
        description: "",
        start: "2026-03-11T09:00:00Z",
        end: "2026-03-11T10:00:00Z",
        type: "review",
        agentId: "agent-1",
      }),
      "/v1/events",
      {
        method: "POST",
        body: JSON.stringify({
          title: "Review",
          description: "",
          start: "2026-03-11T09:00:00Z",
          end: "2026-03-11T10:00:00Z",
          type: "review",
          agentId: "agent-1",
        }),
      },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(deleteEvent("evt-1"), "/v1/events/evt-1", { method: "DELETE" });

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listContent(), "/v1/content");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      createContent({
        title: "Launch note",
        description: "Prepare launch note",
        type: "article",
        stage: "draft",
        assignee: "writer",
        assigneeType: "ai",
      }),
      "/v1/content",
      {
        method: "POST",
        body: JSON.stringify({
          title: "Launch note",
          description: "Prepare launch note",
          type: "article",
          stage: "draft",
          assignee: "writer",
          assigneeType: "ai",
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      updateContent("content-1", { stage: "review" }),
      "/v1/content/content-1",
      { method: "PATCH", body: JSON.stringify({ stage: "review" }) },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(deleteContent("content-1"), "/v1/content/content-1", { method: "DELETE" });

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(listTeams(), "/v1/teams");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      createTeam({ name: "Growth", nameJa: "グロース" }),
      "/v1/teams",
      { method: "POST", body: JSON.stringify({ name: "Growth", nameJa: "グロース" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      updateTeam("growth", { color: "text-lime-400" }),
      "/v1/teams/growth",
      { method: "PATCH", body: JSON.stringify({ color: "text-lime-400" }) },
    );

    apiFetch.mockResolvedValueOnce(undefined);
    await expectApiCall(deleteTeam("growth"), "/v1/teams/growth", { method: "DELETE" });
  });

  it("keeps ads routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce({ run_id: "audit-1" });
    await expectApiCall(
      adsApi.runAudit({
        platforms: ["google", "meta"],
        industry_type: "saas",
        monthly_budget: 12000,
      }),
      "/v1/ads/audit",
      {
        method: "POST",
        body: JSON.stringify({
          platforms: ["google", "meta"],
          industry_type: "saas",
          monthly_budget: 12000,
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(adsApi.getAuditStatus("audit-1"), "/v1/ads/audit/audit-1");

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(adsApi.listReports(), "/v1/ads/reports");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(adsApi.getReport("report-1"), "/v1/ads/reports/report-1");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      adsApi.generatePlan("saas", 12000),
      "/v1/ads/plan",
      {
        method: "POST",
        body: JSON.stringify({ industry_type: "saas", monthly_budget: 12000 }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      adsApi.optimizeBudget(
        { google: 5000, meta: 4000, linkedin: 1000, tiktok: 1000, microsoft: 1000 },
        3.2,
        15000,
      ),
      "/v1/ads/budget/optimize",
      {
        method: "POST",
        body: JSON.stringify({
          current_spend: { google: 5000, meta: 4000, linkedin: 1000, tiktok: 1000, microsoft: 1000 },
          target_mer: 3.2,
          monthly_budget: 15000,
        }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(adsApi.getBenchmarks("google"), "/v1/ads/benchmarks/google");

    apiFetch.mockResolvedValueOnce([]);
    await expectApiCall(adsApi.getTemplates(), "/v1/ads/templates");
  });

  it("keeps lifecycle routes on the canonical v1 surface", async () => {
    apiFetch.mockResolvedValueOnce({ projects: [], count: 0 });
    await expectApiCall(lifecycleApi.listProjects(), "/v1/lifecycle/projects");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(lifecycleApi.getProject("orbit"), "/v1/lifecycle/projects/orbit");

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.deleteProject("orbit"),
      "/v1/lifecycle/projects/orbit",
      { method: "DELETE" },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.saveProject("orbit", { spec: "Autonomous lifecycle cockpit" }),
      "/v1/lifecycle/projects/orbit",
      { method: "PATCH", body: JSON.stringify({ spec: "Autonomous lifecycle cockpit" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.advanceProject("orbit", { orchestrationMode: "autonomous", maxSteps: 8 }),
      "/v1/lifecycle/projects/orbit/advance",
      { method: "POST", body: JSON.stringify({ orchestration_mode: "autonomous", max_steps: 8 }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.getBlueprints("orbit"),
      "/v1/lifecycle/projects/orbit/blueprint",
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.preparePhase("research", "orbit"),
      "/v1/lifecycle/projects/orbit/phases/research/prepare",
      { method: "POST" },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.syncPhaseRun("orbit", "research", "run-1"),
      "/v1/lifecycle/projects/orbit/phases/research/sync",
      { method: "POST", body: JSON.stringify({ run_id: "run-1" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.addApprovalComment("orbit", { text: "Ship it", type: "approve" }),
      "/v1/lifecycle/projects/orbit/approval/comments",
      { method: "POST", body: JSON.stringify({ text: "Ship it", type: "approve" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.decideApproval("orbit", "approved", "Ready for build"),
      "/v1/lifecycle/projects/orbit/approval/decision",
      { method: "POST", body: JSON.stringify({ decision: "approved", comment: "Ready for build" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.runDeployChecks("orbit", "<html></html>"),
      "/v1/lifecycle/projects/orbit/deploy/checks",
      { method: "POST", body: JSON.stringify({ buildCode: "<html></html>" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.createRelease("orbit", "release note"),
      "/v1/lifecycle/projects/orbit/releases",
      { method: "POST", body: JSON.stringify({ note: "release note" }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.listFeedback("orbit"),
      "/v1/lifecycle/projects/orbit/feedback",
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.addFeedback("orbit", { text: "Improve mobile nav", type: "improvement", impact: "medium" }),
      "/v1/lifecycle/projects/orbit/feedback",
      {
        method: "POST",
        body: JSON.stringify({ text: "Improve mobile nav", type: "improvement", impact: "medium" }),
      },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.voteFeedback("orbit", "fb-1", 1),
      "/v1/lifecycle/projects/orbit/feedback/fb-1/vote",
      { method: "POST", body: JSON.stringify({ delta: 1 }) },
    );

    apiFetch.mockResolvedValueOnce({});
    await expectApiCall(
      lifecycleApi.getRecommendations("orbit"),
      "/v1/lifecycle/projects/orbit/recommendations",
    );
  });

  it("normalizes native lifecycle artifacts from mixed backend payloads", async () => {
    apiFetch.mockResolvedValueOnce({
      id: "orbit",
      projectId: "orbit",
      spec: "Autonomous lifecycle cockpit",
      orchestrationMode: "workflow",
      autonomyLevel: "A3",
      researchConfig: { competitorUrls: [], depth: "standard", outputLanguage: "ja", recoveryMode: "auto" },
      features: [],
      milestones: [],
      designVariants: [],
      approvalStatus: "pending",
      approvalComments: [],
      buildCost: 0,
      buildIteration: 0,
      milestoneResults: [],
      planEstimates: [],
      selectedPreset: "standard",
      phaseStatuses: [],
      deployChecks: [],
      releases: [],
      feedbackItems: [],
      recommendations: [],
      artifacts: [],
      decisionLog: [],
      skillInvocations: [],
      delegations: [],
      phaseRuns: [],
      createdAt: "2026-03-17T00:00:00Z",
      updatedAt: "2026-03-17T00:00:00Z",
      savedAt: "2026-03-17T00:00:00Z",
      requirements: {
        requirements: [
          {
            id: "REQ-0001",
            pattern: "event-driven",
            statement: "When release approval is requested, the system shall record the decision.",
            confidence: 0.9,
            source_claim_ids: ["claim-1"],
            user_story_ids: ["US-0001"],
            acceptance_criteria: ["AC-0001"],
          },
        ],
        user_stories: [{ id: "US-0001", persona: "operator", action: "record the decision", text: "As operator, I want to record the decision." }],
        acceptance_criteria: [{ id: "AC-0001", requirement_id: "REQ-0001", text: "Given a request, when approved, then the decision is stored." }],
        confidence_distribution: { high: 1, medium: 0, low: 0 },
        completeness_score: 0.9,
        traceability_index: { "claim-1": ["REQ-0001"] },
      },
      taskDecomposition: {
        tasks: [{ id: "TASK-0001", title: "Implement approval log", description: "", phase: "Phase 1", milestone_id: "ms-1", depends_on: [], effort_hours: 8, priority: "must", feature_id: "feat-1", requirement_id: "REQ-0001" }],
        dag_edges: [],
        phase_milestones: [{ phase: "Phase 1", milestone_ids: ["ms-1"], task_count: 1, total_hours: 8, duration_days: 20 }],
        total_effort_hours: 8,
        critical_path: ["TASK-0001"],
        effort_by_phase: { "Phase 1": 8 },
        has_cycles: false,
      },
      dcsAnalysis: {
        rubber_duck_prd: {
          problem_statement: "Approval latency blocks delivery.",
          target_users: ["operator"],
          success_metrics: [],
          scope_boundaries: { in_scope: ["approval"], out_of_scope: ["billing"] },
          key_decisions: [],
        },
        edge_case_analysis: {
          edge_cases: [{ id: "EC-1", scenario: "Double submit", severity: "high", mitigation: "dedupe", feature_id: "feat-1" }],
          risk_matrix: { high: 1 },
          coverage_score: 1,
        },
        impact_analysis: {
          layers: [{ layer: "api", impacts: [{ component: "approval route", description: "changes request handling" }] }],
          blast_radius: 2,
          critical_paths_affected: ["TASK-0001"],
        },
        sequence_diagrams: {
          diagrams: [{ id: "seq-1", title: "Approval", mermaid_code: "sequenceDiagram\nUser->>API: approve", flow_type: "success" }],
        },
        state_transitions: {
          states: [{ id: "pending", name: "pending", description: "" }],
          transitions: [{ from_state: "pending", to_state: "approved", trigger: "approve", guard: "", risk_level: "low" }],
          risk_states: [],
          mermaid_code: "stateDiagram-v2\npending --> approved: approve",
        },
      },
      technicalDesign: {
        architecture: { system_overview: "Approval service", architectural_pattern: "SPA + API" },
        dataflow_mermaid: "flowchart LR\nUser-->API",
        api_specification: [{ method: "POST", path: "/api/v1/approvals", description: "Create approval", auth_required: true }],
        database_schema: [{ name: "approvals", columns: [{ name: "id", type: "uuid", primary_key: true }], indexes: [] }],
        interface_definitions: [{ name: "ApprovalRecord", properties: [{ name: "id", type: "string" }], extends: [] }],
        component_dependency_graph: { UI: ["API"] },
      },
      reverseEngineering: {
        extracted_requirements: [{ id: "REQ-R-0001", statement: "The system shall expose approval endpoints.", source_file: "server/routes/items.ts" }],
        architecture_doc: { endpoint_count: 2 },
        dataflow_mermaid: "graph LR\nClient-->API",
        api_endpoints: [{ method: "GET", path: "/api/items", handler: "listItems", file_path: "server/routes/items.ts" }],
        database_schema: [{ name: "items", columns: [], source: "raw_sql" }],
        interfaces: [{ name: "ItemRecord", kind: "interface", properties: [], file_path: "src/types.ts" }],
        task_structure: [{ id: "TASK-R-0001" }],
        test_specs: [{ id: "SPEC-R-0001" }],
        coverage_score: 0.86,
        languages_detected: ["typescript"],
        source_type: "prototype_app",
      },
    });

    const project = await lifecycleApi.getProject("orbit");

    expect(project.requirements?.requirements[0].sourceClaimIds).toEqual(["claim-1"]);
    expect(project.requirements?.requirements[0].acceptanceCriteria[0]).toContain("Given");
    expect(project.taskDecomposition?.tasks[0].effortHours).toBe(8);
    expect(project.dcsAnalysis?.impactAnalysis?.blastRadius).toBe(2);
    expect(project.technicalDesign?.apiSpecification[0].authRequired).toBe(true);
    expect(project.reverseEngineering?.apiEndpoints[0].filePath).toBe("server/routes/items.ts");
  });
});
