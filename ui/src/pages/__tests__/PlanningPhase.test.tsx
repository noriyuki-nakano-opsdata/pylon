import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import { defaultResearchConfig, defaultStatuses } from "@/lifecycle/store";
import { LifecycleContext, type LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import { PlanningPhase } from "../lifecycle/PlanningPhase";

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
    useParams: () => ({ projectSlug: "persist-probe-manual" }),
  };
});

vi.mock("@/hooks/useWorkflowRun", () => ({
  useWorkflowRun: () => workflowState,
}));

function makeLifecycleState(overrides: Partial<LifecycleWorkspaceView> = {}): LifecycleWorkspaceView {
  return {
    spec: "",
    orchestrationMode: "workflow",
    governanceMode: "governed",
    autonomyLevel: "A3",
    decisionContext: null,
    productIdentity: defaultProductIdentity(),
    researchConfig: defaultResearchConfig(),
    research: null,
    analysis: null,
    features: [],
    milestones: [],
    designVariants: [],
    selectedDesignId: null,
    approvalStatus: "pending",
    approvalComments: [],
    buildCode: null,
    buildCost: 0,
    buildIteration: 0,
    milestoneResults: [],
    planEstimates: [],
    selectedPreset: "standard",
    phaseStatuses: defaultStatuses(),
    deployChecks: [],
    releases: [],
    feedbackItems: [],
    recommendations: [],
    artifacts: [],
    decisionLog: [],
    skillInvocations: [],
    delegations: [],
    phaseRuns: [],
    nextAction: {
      type: "collect_input",
      phase: "research",
      title: "Project spec is required",
      reason: "Lifecycle autonomy cannot start until the project spec is defined.",
      canAutorun: false,
      payload: {},
      orchestrationMode: "workflow",
      requiresTrigger: false,
    },
    autonomyState: null,
    runtimeObservedPhase: "planning",
    runtimeActivePhase: null,
    runtimePhaseSummary: null,
    runtimeActivePhaseSummary: null,
    runtimeLiveTelemetry: null,
    runtimeConnectionState: "inactive",
    blueprints: {
      research: { phase: "research", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      planning: { phase: "planning", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      design: { phase: "design", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      approval: { phase: "approval", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      development: { phase: "development", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      deploy: { phase: "deploy", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
      iterate: { phase: "iterate", title: "", summary: "", team: [], artifacts: [], quality_gates: [] },
    },
    isHydrating: false,
    ...overrides,
  };
}

function renderSubject(overrides: Partial<LifecycleWorkspaceView> = {}) {
  return render(
    <MemoryRouter>
      <LifecycleContext.Provider value={{ state: makeLifecycleState(overrides), actions: actionMocks }}>
        <PlanningPhase />
      </LifecycleContext.Provider>
    </MemoryRouter>,
  );
}

describe("PlanningPhase", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    Object.values(actionMocks).forEach((mock) => mock.mockReset());
    workflowState.start.mockReset();
    workflowState.reset.mockReset();
  });

  it("renders a safe bootstrap state for empty and locked projects", () => {
    renderSubject();

    expect(screen.getByText("企画分析")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "分析を開始" })).toBeDisabled();
    expect(screen.getByText("調査結果をもとに、誰に何を届けるかと最初のスコープを落ち着いて固めます。")).toBeInTheDocument();
  });

  it("shows compact downstream value and telemetry contracts once planning is compiled", () => {
    renderSubject({
      spec: "authenticated analytics workspace",
      analysis: {
        personas: [],
        user_stories: [],
        kano_features: [],
        recommendations: [],
      },
      valueContract: {
        id: "value-contract",
        schema_version: 1,
        summary: "PM が主要導線と成功条件を固定できる状態にする",
        primary_personas: [{ name: "PM", goals: ["進捗判断"], frustrations: ["実装と価値が切れる"] }],
        selected_features: [],
        required_use_cases: [],
        job_stories: [],
        user_journeys: [],
        kano_focus: { must_be: ["auth"], performance: ["speed"], attractive: ["automation"] },
        information_architecture: {
          navigation_model: "hierarchical",
          top_level_nodes: [],
          key_paths: [{ name: "handoff to development", steps: ["planning", "design", "development"] }],
          top_tasks: ["ship with evidence"],
        },
        success_metrics: [{ id: "metric-1", name: "lead time", signal: "time", target: "<7d", source: "analytics" }],
        kill_criteria: ["handoff stagnates"],
        release_readiness_signals: ["metric coverage"],
      },
      outcomeTelemetryContract: {
        id: "outcome-telemetry-contract",
        schema_version: 1,
        summary: "release 前に instrumentation と kill criteria を満たす",
        success_metrics: [{ id: "metric-1", name: "lead time", signal: "time", target: "<7d", source: "analytics" }],
        kill_criteria: ["metric gap"],
        telemetry_events: [{ id: "event-1", name: "handoff_completed", properties: ["project_id"], success_metric_ids: ["metric-1"] }],
        workspace_artifacts: ["server/contracts/outcome-telemetry.ts"],
        release_checks: [{ id: "check-1", title: "Instrumentation coverage" }],
        instrumentation_requirements: ["emit handoff_completed"],
        experiment_questions: ["does the lead time drop?"],
      },
    });

    expect(screen.getByText("分析を実装契約へ昇格")).toBeInTheDocument();
    expect(screen.getByText("VALUE CONTRACT")).toBeInTheDocument();
    expect(screen.getByText("OUTCOME TELEMETRY")).toBeInTheDocument();
    expect(screen.getByText("PM が主要導線と成功条件を固定できる状態にする")).toBeInTheDocument();
    expect(screen.getByText("release 前に instrumentation と kill criteria を満たす")).toBeInTheDocument();
  });
});
