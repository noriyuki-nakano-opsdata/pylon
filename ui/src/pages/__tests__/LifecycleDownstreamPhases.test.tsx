import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import { defaultResearchConfig, defaultStatuses } from "@/lifecycle/store";
import { LifecycleContext, type LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { DesignVariant, LifecycleAgentBlueprint } from "@/types/lifecycle";
import { lifecycleApi } from "@/api/lifecycle";
import { ApprovalPhase } from "../lifecycle/ApprovalPhase";
import { DevelopmentPhase } from "../lifecycle/DevelopmentPhase";
import { DeployPhase } from "../lifecycle/DeployPhase";
import { IteratePhase } from "../lifecycle/IteratePhase";

const navigateMock = vi.fn();
const actionMocks = {
  editSpec: vi.fn(),
  selectGovernanceMode: vi.fn(),
  updateProductIdentity: vi.fn(),
  updateResearchConfig: vi.fn(),
  replaceFeatures: vi.fn(),
  replaceMilestones: vi.fn(),
  selectDesign: vi.fn(),
  recordBuildIteration: vi.fn(),
  recordMilestoneResults: vi.fn(),
  selectPreset: vi.fn(),
  applyProject: vi.fn(),
  advancePhase: vi.fn(),
  completePhase: vi.fn(),
};

const workflowState = {
  status: "idle",
  runId: null,
  agentProgress: [],
  state: {},
  error: null,
  elapsedMs: 0,
  liveTelemetry: null,
  start: vi.fn(),
  reset: vi.fn(),
};

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => ({ projectSlug: "opp-smoke" }),
  };
});

vi.mock("@/api/lifecycle", async () => {
  const actual = await vi.importActual<typeof import("@/api/lifecycle")>("@/api/lifecycle");
  return {
    ...actual,
    lifecycleApi: {
      ...actual.lifecycleApi,
      addApprovalComment: vi.fn(),
      decideApproval: vi.fn(),
    },
  };
});

vi.mock("@/hooks/useWorkflowRun", () => ({
  useWorkflowRun: () => workflowState,
}));

function makeDesignVariant(): DesignVariant {
  return {
    id: "claude-designer",
    model: "Claude Sonnet 4.6",
    pattern_name: "Obsidian Control Atelier",
    description: "Operator-led multi-agent lifecycle workspace for approval and release review.",
    preview_html: "<!doctype html><html><body>preview</body></html>",
    tokens: { in: 1200, out: 980 },
    cost_usd: 0.24,
    scores: { ux_quality: 0.92, code_quality: 0.89, performance: 0.87, accessibility: 0.9 },
    scorecard: {
      overall_score: 0.89,
      summary: "Structured approval packet",
      dimensions: [
        { id: "clarity", label: "運用明快さ", score: 0.94, evidence: "承認理由と根拠を一つの面で確認できる。" },
      ],
    },
    approval_packet: {
      operator_promise: "根拠確認と承認判断を同じ画面で進められる。",
      must_keep: ["承認理由と根拠リンクを同じ文脈で読む。"],
      guardrails: ["英語の内部ラベルを visible UI に残さない。"],
      review_checklist: ["差し戻し理由をその場で根拠に結び付けられる。"],
      handoff_summary: "承認パケット、主要画面、主要フローをそのまま開発へ渡す。",
    },
    primary_workflows: [
      { id: "wf-1", name: "Approval Gate", goal: "handoff", steps: ["Review", "Approve"] },
    ],
    screen_specs: [
      { id: "screen-1", title: "Approval Gate", purpose: "Review approval packet", layout: "command-center", primary_actions: ["Approve"], module_count: 3, route_path: "/approval" },
    ],
    implementation_brief: {
      architecture_thesis: "承認状態と成果物系譜を一体で持つ。",
      system_shape: ["approval gate", "artifact lineage"],
      technical_choices: [
        { area: "State同期", decision: "phase run を project state に同期する", rationale: "リロード後も判断文脈を復元するため。" },
      ],
      agent_lanes: [
        { role: "実装統合レーン", remit: "承認パケットを build へ束ねる", skills: ["integration", "release-review"] },
      ],
      delivery_slices: [
        "{'slice': 'S1', 'title': 'フェーズナビゲーションシェルと左レール実装', 'milestone': '初回検証マイルストーン', 'acceptance': '承認と差し戻しが同じ画面から実行できる'}",
      ],
    },
    artifact_completeness: {
      score: 1,
      status: "complete",
      present: ["preview_html", "scorecard", "approval_packet", "primary_workflows", "screen_specs"],
      missing: [],
      screen_count: 1,
      workflow_count: 1,
      route_count: 1,
    },
    freshness: {
      status: "fresh",
      can_handoff: true,
      current_fingerprint: "fp-1",
      variant_fingerprint: "fp-1",
      reasons: [],
    },
    preview_meta: {
      source: "repaired",
      extraction_ok: true,
      validation_ok: true,
      html_size: 18000,
      screen_count_estimate: 4,
      interactive_features: ["tabs", "navigation"],
      validation_issues: [],
    },
  };
}

function makeTeam(): Record<string, { phase: string; title: string; summary: string; team: LifecycleAgentBlueprint[]; artifacts: []; quality_gates: [] }> {
  return {
    research: { phase: "research", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    planning: { phase: "planning", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    design: { phase: "design", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    approval: { phase: "approval", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    development: {
      phase: "development",
      title: "",
      summary: "",
      team: [
        { id: "integrator", label: "インテグレーター", role: "統合", autonomy: "A2", tools: [], skills: [] },
      ],
      artifacts: [],
      quality_gates: [],
    },
    deploy: { phase: "deploy", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    iterate: { phase: "iterate", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
  };
}

function makeLifecycleState(overrides: Partial<LifecycleWorkspaceView> = {}): LifecycleWorkspaceView {
  const variant = makeDesignVariant();
  return {
    spec: "Operator-led multi-agent lifecycle workspace that keeps approval, development, deploy, and iteration traceable.",
    orchestrationMode: "workflow",
    governanceMode: "governed",
    autonomyLevel: "A3",
    decisionContext: null,
    productIdentity: {
      ...defaultProductIdentity(),
      companyName: "Pylon Labs",
      productName: "Pylon",
    },
    researchConfig: defaultResearchConfig(),
    research: null,
    analysis: {
      personas: [],
      user_stories: [],
      kano_features: [],
      recommendations: [],
      roles: [
        {
          name: "Operator",
          responsibilities: ["review approval packets"],
          permissions: ["approve_delivery"],
          related_actors: ["Lifecycle Operator"],
        },
      ],
      design_tokens: {
        style: {
          name: "Operator Studio",
          keywords: ["structured", "high-contrast"],
          best_for: "workflow-heavy operator consoles",
          performance: "lightweight transitions",
          accessibility: "strong contrast and focus rings",
        },
        colors: {
          primary: "#2563eb",
          secondary: "#0f172a",
          cta: "#f97316",
          background: "#f8fafc",
          text: "#0f172a",
          notes: "approval actions stay warm and visible",
        },
        typography: {
          heading: "IBM Plex Sans",
          body: "Noto Sans JP",
          mood: ["governed", "precise"],
        },
        effects: ["approval actions use restrained hover elevation", "state changes fade with explicit focus retention"],
        anti_patterns: ["avoid decorative motion"],
        rationale: "Keep approval work visible and calm.",
      },
    },
    features: [
      {
        feature: "research workspace",
        selected: true,
        priority: "must",
        category: "must-be",
        user_delight: 5,
        implementation_cost: "medium",
        rationale: "traceability",
      },
    ],
    milestones: [
      { id: "ms-1", name: "Operator-ready release", criteria: "承認と差し戻しが一つの操作面で完結する", status: "pending" },
    ],
    designVariants: [variant],
    selectedDesignId: variant.id,
    approvalStatus: "pending",
    approvalComments: [],
    buildCode: null,
    buildCost: 0.42,
    buildIteration: 1,
    milestoneResults: [{ id: "ms-1", name: "Operator-ready release", status: "satisfied", reason: "met" }],
    planEstimates: [],
    selectedPreset: "standard",
    requirements: {
      requirements: [
        {
          id: "REQ-1",
          pattern: "ubiquitous",
          statement: "The system shall let authorized operators review approval packets and trigger development safely.",
          confidence: 0.9,
          sourceClaimIds: ["claim-1"],
          userStoryIds: ["story-1"],
          acceptanceCriteria: ["Authorized operators can review packet details before approving delivery."],
        },
      ],
      userStories: [{ id: "story-1", title: "Operator approval", description: "Approve delivery safely within an explicit authorization boundary." }],
      acceptanceCriteria: [{ id: "ac-1", requirementId: "REQ-1", criterion: "Approval packet is visible." }],
      confidenceDistribution: { high: 1, medium: 0, low: 0 },
      completenessScore: 0.9,
      traceabilityIndex: { "REQ-1": ["claim-1"] },
    },
    requirementsConfig: { earsEnabled: true, interactiveClarification: true, confidenceFloor: 0.6 },
    taskDecomposition: {
      tasks: [
        {
          id: "TASK-1",
          title: "Implement approval delivery workspace",
          description: "Build the access-controlled delivery workspace for operator approval.",
          phase: "development",
          milestoneId: "ms-1",
          dependsOn: [],
          effortHours: 8,
          priority: "must",
          featureId: "feature-1",
          requirementId: "REQ-1",
        },
      ],
      dagEdges: [],
      phaseMilestones: [{ phase: "development", milestoneIds: ["ms-1"], taskCount: 1, totalHours: 8, durationDays: 2 }],
      totalEffortHours: 8,
      criticalPath: ["TASK-1"],
      effortByPhase: { development: 8 },
      hasCycles: false,
    },
    dcsAnalysis: {
      rubberDuckPrd: null,
      edgeCases: { edgeCases: [], riskMatrix: {}, coverageScore: 0.8 },
      impactAnalysis: { layers: [], blastRadius: 1, criticalPathsAffected: ["approval"] },
      sequenceDiagrams: { diagrams: [{ id: "seq-1", title: "Approval flow", mermaidCode: "sequenceDiagram\nA->>B: ok", flowType: "core" }] },
      stateTransitions: { states: [{ id: "s1", name: "Ready", description: "ready" }], transitions: [], riskStates: [], mermaidCode: "stateDiagram-v2\n[*] --> Ready" },
    },
    technicalDesign: {
      architecture: { style: "nextjs + typed contracts" },
      dataflowMermaid: "flowchart LR\nUI-->API",
      apiSpecification: [{ method: "POST", path: "/api/approval/decision", description: "Approve delivery", authRequired: true }],
      databaseSchema: [{ name: "approval_decisions", columns: [{ name: "id", type: "uuid", primaryKey: true }], indexes: ["approval_decisions_pkey"] }],
      interfaceDefinitions: [{ name: "ApprovalDecision", properties: [{ name: "id", type: "string" }], extends: [] }],
      componentDependencyGraph: { shell: ["approval-panel"] },
    },
    reverseEngineering: {
      extractedRequirements: [],
      architectureDoc: {},
      dataflowMermaid: "flowchart LR\nUI-->API",
      apiEndpoints: [{ method: "POST", path: "/api/approval/decision", handler: "approveDecision", filePath: "server/api/approval.ts" }],
      databaseSchema: [{ name: "approval_decisions", columns: [], source: "schema.sql" }],
      interfaces: [{ name: "ApprovalDecision", kind: "interface", properties: [], filePath: "server/contracts/api-contract.ts" }],
      taskStructure: [],
      testSpecs: [],
      coverageScore: 0.82,
      languagesDetected: ["typescript"],
      sourceType: "prototype_app",
    },
    phaseStatuses: defaultStatuses(),
    deployChecks: [],
    releases: [],
    feedbackItems: [],
    recommendations: [
      { id: "rec-1", title: "Protect first-release scope", reason: "Keep this out of the first release unless a research claim explicitly requires it.", priority: "high" },
    ],
    artifacts: [],
    decisionLog: [],
    skillInvocations: [],
    delegations: [],
    phaseRuns: [],
    nextAction: null,
    autonomyState: null,
    runtimeObservedPhase: null,
    runtimeActivePhase: null,
    runtimePhaseSummary: null,
    runtimeActivePhaseSummary: null,
    runtimeLiveTelemetry: null,
    runtimeConnectionState: "inactive",
    blueprints: makeTeam() as LifecycleWorkspaceView["blueprints"],
    isHydrating: false,
    ...overrides,
  };
}

function renderWithState(ui: React.ReactNode, state: LifecycleWorkspaceView) {
  return render(
    <MemoryRouter>
      <LifecycleContext.Provider value={{ state, actions: actionMocks }}>
        {ui}
      </LifecycleContext.Provider>
    </MemoryRouter>,
  );
}

describe("Lifecycle downstream phases", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    Object.values(actionMocks).forEach((mock) => mock.mockReset());
    vi.mocked(lifecycleApi.addApprovalComment).mockResolvedValue({
      ...makeLifecycleState(),
      project: makeLifecycleState(),
      actions: [],
      nextAction: null,
    } as unknown as Awaited<ReturnType<typeof lifecycleApi.addApprovalComment>>);
    vi.mocked(lifecycleApi.decideApproval).mockResolvedValue({
      ...makeLifecycleState({ approvalStatus: "approved" }),
      project: makeLifecycleState({ approvalStatus: "approved" }),
      actions: [],
      nextAction: null,
    } as unknown as Awaited<ReturnType<typeof lifecycleApi.decideApproval>>);
  });

  it("renders approval with localized handoff artifacts", () => {
    renderWithState(<ApprovalPhase />, makeLifecycleState());

    expect(screen.getByText("承認レビュー")).toBeInTheDocument();
    expect(screen.getByText("調査ワークスペース")).toBeInTheDocument();
    expect(screen.getByText("フェーズナビゲーションシェルと左レール実装")).toBeInTheDocument();
    expect(screen.queryByText(/\{'slice': 'S1'/)).not.toBeInTheDocument();
    expect(screen.getByText("承認する")).toBeEnabled();
  });

  it("submits approval through the decision API and applies the returned project", async () => {
    renderWithState(<ApprovalPhase />, makeLifecycleState());

    fireEvent.click(screen.getByRole("button", { name: "承認する" }));

    await waitFor(() => {
      expect(lifecycleApi.decideApproval).toHaveBeenCalledWith("opp-smoke", "approved", "承認しました");
    });
    expect(lifecycleApi.addApprovalComment).not.toHaveBeenCalled();
    expect(actionMocks.applyProject).toHaveBeenCalledWith(
      expect.objectContaining({ approvalStatus: "approved" }),
    );
  }, 10000);

  it("submits revision requests through the decision API", async () => {
    renderWithState(<ApprovalPhase />, makeLifecycleState());

    fireEvent.click(screen.getByRole("button", { name: "差し戻す" }));

    await waitFor(() => {
      expect(lifecycleApi.decideApproval).toHaveBeenCalledWith("opp-smoke", "revision_requested", "差し戻しました");
    });
  });

  it("renders development handoff and enables build start after approval", () => {
    renderWithState(<DevelopmentPhase />, makeLifecycleState({ approvalStatus: "approved" }));

    expect(screen.getByText("承認済みの判断を自律デリバリーへ変換する準備")).toBeInTheDocument();
    expect(screen.getByText("SPEC とコードワークスペース")).toBeInTheDocument();
    expect(screen.getByText("フェーズナビゲーションシェルと左レール実装")).toBeInTheDocument();
    expect(screen.getByText("State同期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /開発を開始/ })).toBeEnabled();
  });

  it("shows repo execution truth in the completed development workspace", async () => {
    renderWithState(
      <DevelopmentPhase />,
      makeLifecycleState({
        approvalStatus: "approved",
        buildCode: "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /></head><body><main>release</main></body></html>",
        deliveryPlan: {
          execution_mode: "autonomous_repo_delivery",
          summary: "delivery graph",
          selected_preset: "standard",
          source_plan_preset: "standard",
          success_definition: "ship",
          work_packages: [],
          lanes: [],
          critical_path: [],
          gantt: [],
          merge_strategy: { integration_order: [], conflict_prevention: [], shared_touchpoints: [] },
          spec_audit: {
            status: "ready_for_autonomous_build",
            completeness_score: 0.95,
            requirements_count: 1,
            task_count: 1,
            api_surface_count: 1,
            database_table_count: 1,
            interface_count: 1,
            route_binding_count: 1,
            workspace_file_count: 1,
            behavior_gate_count: 1,
            feature_coverage: [],
            unresolved_gaps: [],
            closing_actions: [],
          },
          code_workspace: {
            framework: "nextjs",
            router: "app",
            preview_entry: "/",
            entrypoints: ["app/page.tsx"],
            install_command: "npm install",
            dev_command: "npm run dev",
            build_command: "npm run build",
            package_tree: [{ id: "app-routes", label: "App Routes", path: "app", lane: "frontend-builder", kind: "generated", file_count: 1 }],
            files: [{ path: "app/page.tsx", kind: "tsx", package_id: "app-routes", package_label: "App Routes", package_path: "app", lane: "frontend-builder", route_paths: ["/"], entrypoint: true, generated_from: "prototype_app", line_count: 3, content_preview: "export default", content: "export default function Page() { return <main>release</main>; }" }],
            package_graph: [],
            route_bindings: [{ route_path: "/", screen_id: "screen-1", file_paths: ["app/page.tsx"] }],
            artifact_summary: { package_count: 1, file_count: 1, route_binding_count: 1, entrypoint_count: 1 },
          },
          repo_execution: {
            mode: "git_worktree",
            workspace_path: "/tmp/pylon/worktree",
            worktree_path: "/tmp/pylon/worktree",
            repo_root: "/tmp/local-repo",
            materialized_file_count: 1,
            install: { status: "passed", command: "npm install", exit_code: 0, duration_ms: 1000, stdout_tail: "", stderr_tail: "" },
            build: { status: "passed", command: "npm run build", exit_code: 0, duration_ms: 2000, stdout_tail: "", stderr_tail: "" },
            test: { status: "passed", command: "npm test", exit_code: 0, duration_ms: 1200, stdout_tail: "", stderr_tail: "" },
            ready: true,
            errors: [],
          },
        },
        developmentHandoff: {
          readiness_status: "ready_for_deploy",
          release_candidate: "candidate",
          operator_summary: "deploy ready",
          deploy_checklist: [{ id: "repo-execution-passed", label: "materialized repo/worktree で install / build / test が成功している", category: "readiness", required: true }],
          evidence: [{ category: "execution", label: "repo execution", value: "git_worktree", unit: "id" }],
          blocking_issues: [],
          review_focus: [],
        },
      }),
    );

    expect(screen.queryByText("repo execution passed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "サマリーを表示" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "サマリーを表示" }));

    await waitFor(() => {
      expect(screen.getByText("repo execution passed")).toBeInTheDocument();
    });
    expect(screen.getByText("Workspace materialized successfully")).toBeInTheDocument();
    expect(screen.getByText(/workspace: \/tmp\/pylon\/worktree/)).toBeInTheDocument();
  });

  it("renders an editor-like workspace view for generated code", () => {
    renderWithState(
      <DevelopmentPhase />,
      makeLifecycleState({
        approvalStatus: "approved",
        buildCode: "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /></head><body><main>release</main></body></html>",
        deliveryPlan: {
          execution_mode: "autonomous_repo_delivery",
          summary: "delivery graph",
          selected_preset: "standard",
          source_plan_preset: "standard",
          success_definition: "ship",
          work_packages: [],
          lanes: [],
          critical_path: [],
          gantt: [],
          merge_strategy: { integration_order: [], conflict_prevention: [], shared_touchpoints: [] },
          spec_audit: {
            status: "ready_for_autonomous_build",
            completeness_score: 0.95,
            requirements_count: 1,
            task_count: 1,
            api_surface_count: 1,
            database_table_count: 1,
            interface_count: 1,
            route_binding_count: 1,
            workspace_file_count: 2,
            behavior_gate_count: 1,
            feature_coverage: [],
            unresolved_gaps: [],
            closing_actions: [],
          },
          code_workspace: {
            framework: "nextjs",
            router: "app",
            preview_entry: "/",
            entrypoints: ["app/page.tsx"],
            install_command: "npm install",
            dev_command: "npm run dev",
            build_command: "npm run build",
            package_tree: [
              { id: "app-routes", label: "App Routes", path: "app", lane: "frontend-builder", kind: "generated", file_count: 1 },
              { id: "server-contracts", label: "Server Contracts", path: "server/contracts", lane: "backend-builder", kind: "generated", file_count: 1 },
            ],
            files: [
              { path: "app/page.tsx", kind: "tsx", package_id: "app-routes", package_label: "App Routes", package_path: "app", lane: "frontend-builder", route_paths: ["/"], entrypoint: true, generated_from: "prototype_app", line_count: 3, content_preview: "Page component", content: "export default function Page() {\n  return <main>release</main>;\n}" },
              { path: "server/contracts/api.ts", kind: "ts", package_id: "server-contracts", package_label: "Server Contracts", package_path: "server/contracts", lane: "backend-builder", route_paths: [], entrypoint: false, generated_from: "technical_design", line_count: 2, content_preview: "API contract", content: "export interface ApiContract {\n  releaseReady: boolean;\n}" },
            ],
            package_graph: [
              { source: "app-routes", target: "server-contracts", reason: "Route consumes release gate contract" },
            ],
            route_bindings: [{ route_path: "/", screen_id: "screen-1", file_paths: ["app/page.tsx"] }],
            artifact_summary: { package_count: 2, file_count: 2, route_binding_count: 1, entrypoint_count: 1 },
          },
          repo_execution: {
            mode: "git_worktree",
            workspace_path: "/tmp/pylon/worktree",
            worktree_path: "/tmp/pylon/worktree",
            repo_root: "/tmp/local-repo",
            materialized_file_count: 2,
            install: { status: "passed", command: "npm install", exit_code: 0, duration_ms: 1000, stdout_tail: "", stderr_tail: "" },
            build: { status: "passed", command: "npm run build", exit_code: 0, duration_ms: 2000, stdout_tail: "", stderr_tail: "" },
            test: { status: "passed", command: "npm test", exit_code: 0, duration_ms: 1200, stdout_tail: "", stderr_tail: "" },
            ready: true,
            errors: [],
          },
        },
        developmentHandoff: {
          readiness_status: "ready_for_deploy",
          release_candidate: "candidate",
          operator_summary: "deploy ready",
          deploy_checklist: [{ id: "repo-execution-passed", label: "materialized repo/worktree で install / build / test が成功している", category: "readiness", required: true }],
          evidence: [{ category: "execution", label: "repo execution", value: "git_worktree", unit: "id" }],
          blocking_issues: [],
          review_focus: [],
        },
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Code" }));

    expect(screen.getByPlaceholderText("path / route / lane を検索")).toBeInTheDocument();
    expect(screen.getByText("workspace explorer")).toBeInTheDocument();
    expect(screen.queryByText("inspector")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inspector を表示" }));

    expect(screen.getByText("inspector")).toBeInTheDocument();
    expect(screen.getByText("Route consumes release gate contract")).toBeInTheDocument();
    expect(screen.getByText("app/page.tsx")).toBeInTheDocument();
  });

  it("renders deploy release gate summary with localized status labels", () => {
    renderWithState(
      <DeployPhase />,
      makeLifecycleState({
        buildCode: "<!doctype html><html><body><h1>release</h1></body></html>",
        deployChecks: [
          { id: "check-pass", label: "release gate", status: "pass", detail: "All checks passed" },
          { id: "check-warning", label: "mobile density", status: "warning", detail: "Minor warning" },
        ],
      }),
    );

    expect(screen.getByRole("heading", { name: "リリースゲート" })).toBeInTheDocument();
    expect(screen.getAllByText("合格").length).toBeGreaterThan(0);
    expect(screen.getAllByText("注意").length).toBeGreaterThan(0);
    expect(screen.getByText("Obsidian Control Atelier")).toBeInTheDocument();
  });

  it("surfaces the governed release gate before creating a release record", () => {
    renderWithState(
      <DeployPhase />,
      makeLifecycleState({
        buildCode: "<!doctype html><html><body><h1>release</h1></body></html>",
        deployChecks: [
          { id: "check-pass", label: "release gate", status: "pass", detail: "All checks passed" },
        ],
        nextAction: {
          type: "request_release_decision",
          phase: "deploy",
          title: "Human release approval required",
          reason: "warning の運用判断と公開可否は人が最終確認します。",
          canAutorun: false,
          requiresTrigger: true,
          orchestrationMode: "workflow",
          governanceMode: "governed",
          requiresHumanDecision: true,
          payload: {
            availableDecisions: ["approve_release", "return_to_development"],
          },
        },
      }),
    );

    expect(screen.getByText("HUMAN RELEASE GATE")).toBeInTheDocument();
    expect(screen.getByText("warning の運用判断と公開可否は人が最終確認します。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認してリリース記録を作成" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "修正のため development へ戻る" })).toBeInTheDocument();
  });

  it("renders iterate summary with localized feedback and recommendations", () => {
    renderWithState(
      <IteratePhase />,
      makeLifecycleState({
        buildCode: "<!doctype html><html><body><h1>preview</h1></body></html>",
        feedbackItems: [
          { id: "fb-1", type: "improvement", text: "Improve approval gate contrast", impact: "medium", votes: 4, createdAt: "2026-03-17T02:00:00Z" },
        ],
        releases: [
          {
            id: "rel-1",
            createdAt: "2026-03-17T01:00:00Z",
            version: "v0.1.0",
            note: "Initial release",
            artifactBytes: 1200,
            qualitySummary: { overallScore: 88, releaseReady: true, passed: 2, warnings: 0, failed: 0 },
          },
        ],
      }),
    );

    expect(screen.getByText("次に着手する提案")).toBeInTheDocument();
    expect(screen.getByText("調査ワークスペース")).toBeInTheDocument();
    expect(screen.getAllByText("改善案").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/承認ゲート|Improve/).length).toBeGreaterThan(1);
  });

  it("surfaces iteration triage when governed mode requires a human decision", () => {
    renderWithState(
      <IteratePhase />,
      makeLifecycleState({
        buildCode: "<!doctype html><html><body><h1>preview</h1></body></html>",
        nextAction: {
          type: "request_iteration_triage",
          phase: "iterate",
          title: "Human iteration triage required",
          reason: "次の改善 wave に入る前に、must / should の優先順位を人が調整します。",
          canAutorun: false,
          requiresTrigger: true,
          orchestrationMode: "workflow",
          governanceMode: "governed",
          requiresHumanDecision: true,
          payload: {
            availableDecisions: ["return_to_planning", "collect_more_feedback"],
          },
        },
      }),
    );

    expect(screen.getByText("HUMAN ITERATION GATE")).toBeInTheDocument();
    expect(screen.getByText("次の改善 wave に入る前に、must / should の優先順位を人が調整します。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "優先順位を確定して planning へ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "planning に戻って scope を決める" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "追加フィードバックを集める" })).toBeInTheDocument();
  });
});
