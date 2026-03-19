import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import { defaultResearchConfig, defaultStatuses } from "@/lifecycle/store";
import { LifecycleContext, type LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { PhaseStatus } from "@/types/lifecycle";
import { ResearchPhase } from "../lifecycle/ResearchPhase";

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

const workflowState: {
  status: "idle" | "starting" | "running" | "completed" | "failed";
  runId: string | null;
  agentProgress: unknown[];
  state: Record<string, unknown>;
  error: string | null;
  elapsedMs: number;
  liveTelemetry: unknown;
  start: ReturnType<typeof vi.fn>;
  reset: ReturnType<typeof vi.fn>;
} = {
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

let lifecycleState: LifecycleWorkspaceView;

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => ({ projectSlug: "demo-project" }),
  };
});

vi.mock("@/hooks/useWorkflowRun", () => ({
  useWorkflowRun: () => workflowState,
}));

function makeLifecycleState(): LifecycleWorkspaceView {
  const phaseStatuses: PhaseStatus[] = defaultStatuses().map((item) => (
    item.phase === "research"
      ? { ...item, status: "completed", completedAt: "2026-03-14T14:40:11Z" }
      : item.phase === "planning"
        ? { ...item, status: "available" }
        : item
  ));

  return {
    spec: "AI エージェントが市場調査から品質保証まで自律実行する開発プラットフォーム",
    orchestrationMode: "workflow",
    governanceMode: "governed",
    autonomyLevel: "A3",
    productIdentity: {
      ...defaultProductIdentity(),
      companyName: "Pylon Labs",
      productName: "Pylon",
      officialWebsite: "https://pylon.example.com",
      officialDomains: ["pylon.example.com"],
      excludedEntityNames: ["Basler pylon"],
    },
    researchConfig: {
      ...defaultResearchConfig(),
      competitorUrls: ["https://example.com/autonomous-dev-platform"],
    },
    research: {
      competitors: [
        {
          name: "【要約】競合調査記事",
          url: "https://note.com/example/n/demo",
          strengths: ["記事の要約テキスト"],
          weaknesses: ["プロダクトではない"],
          pricing: "非公開",
          target: "B2C",
        },
      ],
      market_size: "76%,#000 99",
      trends: ["チュートリアル：Basler AG: @charset ..."],
      opportunities: ["https://docs.baslerweb.com/tutorial"],
      threats: [],
      tech_feasibility: { score: 0.81, notes: "実装可能" },
      user_research: {
        signals: ["https://docs.baslerweb.com/tutorial"],
        pain_points: ["https://note.com/example/n/demo"],
        segment: "B2B",
      },
      claims: [
        {
          id: "claim-bad",
          statement: "【要約】競合調査記事",
          owner: "research-judge",
          category: "market",
          evidence_ids: ["ev-1"],
          counterevidence_ids: [],
          confidence: 0.96,
          status: "accepted",
        },
        {
          id: "claim-good",
          statement: "運用品質の可視化が導入判断の主要論点になる",
          owner: "research-judge",
          category: "ux",
          evidence_ids: ["ev-2"],
          counterevidence_ids: [],
          confidence: 0.78,
          status: "accepted",
        },
      ],
      evidence: [
        {
          id: "ev-1",
          source_ref: "https://note.com/example/n/demo",
          source_type: "url",
          snippet: "記事の要約です",
          recency: "current",
          relevance: "medium",
        },
        {
          id: "ev-2",
          source_ref: "https://example.com/autonomous-dev-platform",
          source_type: "url",
          snippet: "Operational quality and governance controls are visible during evaluation.",
          recency: "current",
          relevance: "high",
        },
      ],
      dissent: [
        {
          id: "dissent-bad",
          claim_id: "claim-bad",
          challenger: "judge",
          argument: "Basler AG: pylon Software Suite - コンピュータービジョン向け統合ソフトウェアパッケージ",
          severity: "high",
          resolved: false,
        },
      ],
      open_questions: ["どの導入条件が最初の稟議停止要因になるか", "【要約】競合調査記事"],
      winning_theses: ["運用品質が差別化になる", "【要約】競合調査記事"],
      source_links: [
        "https://note.com/example/n/demo",
        "https://docs.baslerweb.com/tutorial",
        "https://example.com/autonomous-dev-platform",
      ],
      confidence_summary: { average: 0.97, floor: 0.96, accepted: 1 },
      quality_gates: [
        {
          id: "source-grounding",
          title: "source grounding",
          passed: true,
          reason: "grounded",
          blockingNodeIds: [],
        },
      ],
      node_results: [
        {
          nodeId: "research-judge",
          status: "success",
          parseStatus: "strict",
          degradationReasons: [],
          sourceClassesSatisfied: [],
          missingSourceClasses: [],
          artifact: {},
          retryCount: 0,
        },
      ],
    },
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
    phaseStatuses,
    deployChecks: [],
    releases: [],
    feedbackItems: [],
    recommendations: [],
    artifacts: [],
    decisionLog: [],
    skillInvocations: [],
    delegations: [],
    phaseRuns: [],
    nextAction: null,
    autonomyState: null,
    runtimeObservedPhase: "research",
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
  };
}

function makeInitialResearchState(): LifecycleWorkspaceView {
  return {
    ...makeLifecycleState(),
    spec: "営業とCSの情報を一画面でつなぎ、次の打ち手を判断しやすくする運用基盤を作りたい。",
    research: null,
    researchConfig: {
      ...defaultResearchConfig(),
      competitorUrls: [],
      depth: "standard",
    },
    phaseStatuses: defaultStatuses(),
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LifecycleContext.Provider value={{ state: lifecycleState, actions: actionMocks }}>
        <ResearchPhase />
      </LifecycleContext.Provider>
    </MemoryRouter>,
  );
}

describe("ResearchPhase", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    Object.values(actionMocks).forEach((mock) => mock.mockReset());
    workflowState.status = "idle";
    workflowState.runId = null;
    workflowState.agentProgress = [];
    workflowState.state = {};
    workflowState.error = null;
    workflowState.elapsedMs = 0;
    workflowState.liveTelemetry = null;
    workflowState.start.mockReset();
    workflowState.reset.mockReset();
    lifecycleState = makeLifecycleState();
  });

  it("surfaces quarantined research items and reuses an available planning review", () => {
    renderPage();

    expect(screen.getByText("調査結果の見直しが必要です")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "企画レビューへ進む" }));
    expect(navigateMock).toHaveBeenCalledWith("/p/demo-project/lifecycle/planning");
    expect(screen.getByText("ユーザー理解を、企画に渡せるフレームへ変換します")).toBeInTheDocument();
    expect(screen.getByText("ユーザージャーニー仮説")).toBeInTheDocument();
    expect(screen.getByText("KANO 仮説")).toBeInTheDocument();
    expect(screen.getByText("IA 仮説")).toBeInTheDocument();
    expect(screen.getAllByText("隔離した項目").length).toBeGreaterThan(0);
    expect(screen.getByText("運用品質の可視化が導入判断の主要論点になる")).toBeInTheDocument();
    expect(screen.getByText("隔離した主張 1 件")).toBeInTheDocument();
    expect(screen.getByText("どの導入条件が最初の稟議停止要因になるか")).toBeInTheDocument();
    expect(screen.getAllByText("【要約】競合調査記事").length).toBeGreaterThan(0);
    expect(screen.getAllByText("市場規模の値が崩れており、数値根拠として扱えません。").length).toBeGreaterThan(0);
    expect(screen.getByText("競合候補はありましたが、記事や対象外ソースを隔離した結果、比較対象として残せる項目がありませんでした。")).toBeInTheDocument();
  }, 10000);

  it("keeps the initial research form accessible by label", () => {
    lifecycleState = makeInitialResearchState();
    renderPage();

    expect(screen.getByLabelText("会社名・運営主体")).toHaveValue("Pylon Labs");
    expect(screen.getByLabelText("サービス名・構想名")).toHaveValue("Pylon");
    expect(screen.getByLabelText("プロダクト概要")).toHaveValue(
      "営業とCSの情報を一画面でつなぎ、次の打ち手を判断しやすくする運用基盤を作りたい。",
    );

    const advancedToggle = screen.getByRole("button", { name: /補足設定で精度を上げる/i });
    expect(advancedToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(advancedToggle);
    expect(advancedToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("公式サイト")).toHaveValue("https://pylon.example.com");
    expect(screen.getByLabelText("競合 URL")).toBeInTheDocument();
  });

  it("allows starting research from the summary alone when identity is undecided", () => {
    lifecycleState = {
      ...makeInitialResearchState(),
      productIdentity: defaultProductIdentity(),
    };
    renderPage();

    expect(screen.getByLabelText("会社名・運営主体")).toHaveValue("");
    expect(screen.getByLabelText("サービス名・構想名")).toHaveValue("");
    expect(screen.getByRole("button", { name: "この内容で調査を開始" })).toBeEnabled();
    expect(screen.getByText("未定でも可")).toBeInTheDocument();
    expect(screen.getByText("補足: 未設定でも開始できます")).toBeInTheDocument();
  });

  it("falls back to completed runtime research while persisted project sync catches up", () => {
    const runtimeResearch = makeLifecycleState().research;
    lifecycleState = {
      ...makeInitialResearchState(),
      research: null,
    };
    workflowState.status = "completed";
    workflowState.runId = "run-runtime-research";
    workflowState.state = { research: runtimeResearch };

    renderPage();

    expect(screen.queryByText("調査実行は完了しましたが、保存済みの調査結果を読み込めませんでした。再同期または再実行が必要です。")).not.toBeInTheDocument();
    expect(screen.getByText("調査結果")).toBeInTheDocument();
    expect(screen.getAllByText("回復オペレーション").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("プロダクト概要")).not.toBeInTheDocument();
  });
});
