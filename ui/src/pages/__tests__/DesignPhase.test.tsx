import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defaultProductIdentity } from "@/lifecycle/productIdentity";
import { defaultResearchConfig, defaultStatuses } from "@/lifecycle/store";
import { LifecycleContext, type LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type { PhaseStatus } from "@/types/lifecycle";
import { DesignPhase } from "../lifecycle/DesignPhase";

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

function makeLifecycleState(): LifecycleWorkspaceView {
  const phaseStatuses: PhaseStatus[] = defaultStatuses().map((item) => (
    item.phase === "research" || item.phase === "planning"
      ? { ...item, status: "completed", completedAt: "2026-03-15T10:00:00Z" }
      : item.phase === "design"
        ? { ...item, status: "review" }
        : item
  ));

  return {
    spec: "調査から企画、承認、開発までを一貫して進める operator 向け control plane",
    orchestrationMode: "workflow",
    governanceMode: "governed",
    autonomyLevel: "A3",
    decisionContext: {
      schema_version: 1,
      display_language: "ja",
      fingerprint: "fingerprint-1",
      project_frame: {
        lead_thesis: "公開ソースでは導入判断時の不安が繰り返し現れており、信頼形成が主要な UX 論点になります。",
        summary: "The plan keeps only features that remain traceable to research claims and falsifiable milestones.",
        north_star: "Operator trust: every phase decision should remain explainable, reviewable, and recoverable.",
        core_loop: "Turn grounded evidence into a governed plan, then carry the same decision context into design and build.",
        selected_features: [
          { name: "research workspace" },
          { name: "approval gate" },
        ],
        primary_use_cases: [
          { id: "uc-1", title: "劣化した調査を立て直して判断を前に進める" },
        ],
        milestones: [
          { id: "ms-1", name: "Alpha" },
        ],
        key_risks: [{ id: "risk-1", title: "情報密度が高すぎると判断が鈍る" }],
        key_assumptions: [{ id: "assumption-1", title: "承認前に根拠をその場で読める必要がある" }],
        thesis_snapshot: [],
        primary_personas: [],
      },
      consistency_snapshot: {
        status: "warning",
        issues: [{ id: "issue-1", title: "差し戻し時の判断導線は引き続き要確認" }],
      },
    },
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
      user_journeys: [],
      job_stories: [],
      ia_analysis: undefined,
      actors: [],
      roles: [],
      use_cases: [],
      recommended_milestones: [],
      assumptions: [],
      judge_summary: "Legacy english fallback should not win.",
    },
    features: [
      {
        feature: "research workspace",
        selected: true,
        priority: "must",
        category: "workspace",
        user_delight: 5,
        implementation_cost: "medium",
        rationale: "調査と判断の文脈を同じ画面で保つため。",
      },
      {
        feature: "approval gate",
        selected: true,
        priority: "must",
        category: "governance",
        user_delight: 4,
        implementation_cost: "medium",
        rationale: "承認 handoff を追跡可能にするため。",
      },
    ],
    milestones: [{
      id: "ms-1",
      name: "Alpha",
      criteria: "承認に渡せる判断材料が見える",
      status: "pending",
    }],
    designVariants: [
      {
        id: "gemini-designer",
        model: "Gemini 3 Pro",
        pattern_name: "Ivory Signal Gallery",
        description: "An art-directed operations suite.",
        preview_html: "<!doctype html><html><body>preview</body></html>",
        tokens: { in: 4200, out: 3100 },
        cost_usd: 0.28,
        scores: { ux_quality: 0.94, code_quality: 0.89, performance: 0.88, accessibility: 0.93 },
        display_language: "ja",
        localization_status: "best_effort",
        implementation_brief: {
          architecture_thesis: "判断根拠と承認 handoff を同じ状態遷移に乗せる control plane として構成する。",
          system_shape: ["主要ワークスペース", "approval packet", "artifact lineage"],
          technical_choices: [
            {
              area: "フロントエンド shell",
              decision: "stateful workspace shell にする",
              rationale: "再読込や差し戻しでも判断文脈を失わないため。",
            },
          ],
          agent_lanes: [
            {
              role: "アーキテクチャ設計レーン",
              remit: "phase contract と state 同期を定義する",
              skills: ["solution-architecture", "risk-analysis"],
            },
          ],
          delivery_slices: ["Lifecycle Workspace", "Approval Gate", "Artifact Lineage"],
        },
        prototype: {
          kind: "product-workspace",
          app_shell: { layout: "sidebar", density: "balanced", primary_navigation: [], status_badges: [] },
          screens: [
            {
              id: "workspace",
              title: "Lifecycle Workspace — Active Run View",
              headline: "Run discovery-to-build workflow",
              purpose: "Primary work area for each phase",
              layout: "command-center",
              supporting_text: "",
              primary_actions: ["Approve"],
              modules: [{ name: "Approval Gate", type: "panel", items: ["Evidence", "Decision"] }],
              success_state: "",
            },
          ],
          flows: [{ id: "flow-1", name: "Approval Gate", steps: ["Review", "Approve"], goal: "handoff" }],
          interaction_principles: [],
        },
        scorecard: {
          overall_score: 0.86,
          summary: "1 画面 / 1 フロー / llm preview",
          dimensions: [
            { id: "operator_clarity", label: "運用明快さ", score: 0.94, evidence: "1 画面で主要判断を分離。" },
            { id: "handoff_readiness", label: "handoff 準備度", score: 0.8, evidence: "llm preview / 1 screens / 1 workflows" },
          ],
        },
        selection_rationale: {
          summary: "落ち着いた判断室として、根拠確認と承認判断を静かに進められる案です。",
          reasons: [
            "根拠確認と承認判断の往復が穏やかな密度で行える。",
            "主要フローと handoff 内容が一つのパケットにまとまっている。",
          ],
          tradeoffs: ["余白を優先しているため、同時監視量は制御室型より少ない。"],
          approval_focus: ["承認理由と根拠リンクを同じ面に残す。"],
          confidence: 0.86,
          verdict: "selected",
        },
        approval_packet: {
          operator_promise: "根拠確認と承認判断を落ち着いて進められる。",
          must_keep: ["主要フローと承認理由を同じ文脈で確認できること。"],
          guardrails: ["visible UI に内部用語や英語ラベルを残さないこと。"],
          review_checklist: ["承認または差し戻し理由を、その場で根拠と照合できる。"],
          handoff_summary: "主要 1 画面と 1 フローを承認パケットへ束ねる。",
        },
        primary_workflows: [{ id: "flow-1", name: "Approval Gate", goal: "handoff", steps: ["Review", "Approve"] }],
        screen_specs: [{ id: "workspace", title: "Lifecycle Workspace — Active Run View", purpose: "Primary work area for each phase", layout: "command-center", primary_actions: ["Approve"], module_count: 1, route_path: "/" }],
        prototype_app: {
          artifact_kind: "prototype_app",
          framework: "nextjs",
          router: "app",
          dependencies: { next: "15.2.0", react: "19.0.0" },
          dev_dependencies: { typescript: "5.7.0" },
          install_command: "pnpm install",
          dev_command: "pnpm dev",
          build_command: "pnpm build",
          mock_api: ["/api/approvals"],
          entry_routes: ["/", "/approval"],
          files: [
            { path: "app/page.tsx", kind: "route", content: "export default function Page() { return null; }" },
            { path: "components/approval-packet.tsx", kind: "component", content: "export function ApprovalPacket() { return null; }" },
          ],
          artifact_summary: { screen_count: 1, route_count: 2, file_count: 2 },
        },
        artifact_completeness: { score: 1, status: "complete", present: ["preview_html"], missing: [], screen_count: 1, workflow_count: 1, route_count: 1 },
        freshness: { status: "fresh", can_handoff: true, current_fingerprint: "fingerprint-1", variant_fingerprint: "fingerprint-1", reasons: [] },
        preview_meta: { source: "llm", extraction_ok: true, validation_ok: true, fallback_reason: "", html_size: 1600, screen_count_estimate: 4, interactive_features: ["tabs", "accordion", "hover"], validation_issues: [], copy_quality_score: 0.96, copy_issues: [], copy_issue_examples: [] },
        decision_context_fingerprint: "fingerprint-1",
      },
      {
        id: "claude-designer",
        model: "Claude Sonnet 4.6",
        pattern_name: "Obsidian Control Atelier",
        description: "A denser control-room workspace.",
        preview_html: "<!doctype html><html><body>preview b</body></html>",
        tokens: { in: 3800, out: 2800 },
        cost_usd: 0.04,
        scores: { ux_quality: 0.91, code_quality: 0.9, performance: 0.87, accessibility: 0.9 },
        display_language: "ja",
        localization_status: "best_effort",
        implementation_brief: {
          architecture_thesis: "判断ログ、承認状態、成果物系譜を同じ command surface に圧縮する。",
          system_shape: ["command surface", "checkpoint recovery", "decision ledger"],
          technical_choices: [
            {
              area: "実行同期",
              decision: "checkpoint 付き streaming で復元する",
              rationale: "長時間 run と途中介入でも現在地を失わないため。",
            },
          ],
          agent_lanes: [
            {
              role: "実装計画レーン",
              remit: "画面分割とコンポーネント責務を決める",
              skills: ["frontend-implementation", "accessibility"],
            },
          ],
          delivery_slices: ["コマンドデッキ", "承認ゲート", "ラン台帳"],
        },
        prototype: {
          kind: "control-center",
          app_shell: { layout: "sidebar", density: "high", primary_navigation: [], status_badges: [] },
          screens: [
            {
              id: "deck",
              title: "Command Deck",
              headline: "Trace artifact lineage",
              purpose: "Phase artifacts and lineage",
              layout: "command-center",
              supporting_text: "",
              primary_actions: ["Review planning"],
              modules: [{ name: "Run Monitor", type: "panel", items: ["Approval packet", "Decision log"] }],
              success_state: "",
            },
          ],
          flows: [{ id: "flow-2", name: "Artifact Lineage", steps: ["Trace", "Review"], goal: "lineage" }],
          interaction_principles: [],
        },
        scorecard: {
          overall_score: 0.84,
          summary: "1 画面 / 1 フロー / template preview",
          dimensions: [
            { id: "operator_clarity", label: "運用明快さ", score: 0.91, evidence: "1 画面で主要判断を分離。" },
            { id: "handoff_readiness", label: "handoff 準備度", score: 0.78, evidence: "template preview / 1 screens / 1 workflows" },
          ],
        },
        selection_rationale: {
          summary: "密度の高い制御室として、判断、承認、系譜確認を一枚に集約する案です。",
          reasons: [
            "主要判断、承認、系譜が同じ視野に収まる。",
            "復旧導線を操作盤の中に固定できる。",
          ],
          tradeoffs: ["情報密度が高いため、視線誘導とコントラストを維持する必要がある。"],
          approval_focus: ["主要操作のコントラストを下げない。"],
          confidence: 0.82,
          verdict: "candidate",
        },
        approval_packet: {
          operator_promise: "主要判断を一枚の操作盤で捌ける。",
          must_keep: ["次の一手と blocked 状態を同じ面に置くこと。"],
          guardrails: ["主要操作と状態ラベルのコントラストを下げないこと。"],
          review_checklist: ["成果物の系譜と復旧導線が operator 目線で読める。"],
          handoff_summary: "密度高めの制御室体験を保ったまま承認へ渡す。",
        },
        primary_workflows: [{ id: "flow-2", name: "Artifact Lineage", goal: "lineage", steps: ["Trace", "Review"] }],
        screen_specs: [{ id: "deck", title: "Command Deck", purpose: "Phase artifacts and lineage", layout: "command-center", primary_actions: ["Review planning"], module_count: 1, route_path: "/" }],
        artifact_completeness: { score: 1, status: "complete", present: ["preview_html"], missing: [], screen_count: 1, workflow_count: 1, route_count: 1 },
        freshness: { status: "fresh", can_handoff: true, current_fingerprint: "fingerprint-1", variant_fingerprint: "fingerprint-1", reasons: [] },
        preview_meta: { source: "template", extraction_ok: false, validation_ok: false, fallback_reason: "template_preview_used", html_size: 1400, screen_count_estimate: 3, interactive_features: ["hover"], validation_issues: ["limited_interactivity"], copy_quality_score: 0.58, copy_issues: ["english_ui_drift"], copy_issue_examples: ["Run Monitor"] },
        decision_context_fingerprint: "fingerprint-1",
      },
    ],
    selectedDesignId: "gemini-designer",
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
    runtimeObservedPhase: "design",
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

function renderSubject(state = makeLifecycleState()) {
  return render(
    <MemoryRouter>
      <LifecycleContext.Provider value={{ state, actions: actionMocks }}>
        <DesignPhase />
      </LifecycleContext.Provider>
    </MemoryRouter>,
  );
}

describe("DesignPhase", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    Object.values(actionMocks).forEach((mock) => mock.mockReset());
    workflowState.start.mockReset();
    workflowState.reset.mockReset();
  });

  it("organizes review content into overview, compare, prototype, and handoff sections", () => {
    renderSubject();

    expect(screen.getByText("プロトタイプステージ")).toBeInTheDocument();
    expect(screen.getByText("プレビュー品質")).toBeInTheDocument();
    expect(screen.getByText("文言品質")).toBeInTheDocument();
    expect(screen.getByText("引き継ぎ準備度")).toBeInTheDocument();
    expect(screen.getByText("Next.js")).toBeInTheDocument();
    expect(screen.getByText("App Router")).toBeInTheDocument();
    expect(screen.queryByText("handoff 準備度")).not.toBeInTheDocument();
    expect(screen.queryByText("採用判断サマリー")).not.toBeInTheDocument();
    expect(screen.queryByText("構造差分レビュー")).not.toBeInTheDocument();
    expect(screen.queryByText("アーキテクチャ方針")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "判断概要" }));

    expect(screen.getByText("成果物の系譜と承認根拠が同じ操作面でつながり、各判断を説明できる状態を守る。")).toBeInTheDocument();
    expect(screen.getByText("各フェーズの判断が、説明できて、レビューできて、巻き戻せる状態を守る。")).toBeInTheDocument();
    expect(screen.getByText("調査ワークスペース")).toBeInTheDocument();
    expect(screen.getByText("レビューセクション")).toBeInTheDocument();
    expect(screen.getByText("採用判断サマリー")).toBeInTheDocument();
    expect(screen.queryByText("構造差分レビュー")).not.toBeInTheDocument();
    expect(screen.queryByText("アーキテクチャ方針")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "比較" }));

    expect(screen.getByText("固定軸での比較")).toBeInTheDocument();
    expect(screen.getByText("今回採用する理由")).toBeInTheDocument();
    expect(screen.getByText("今回は見送る理由")).toBeInTheDocument();
    expect(screen.getByText("構造差分レビュー")).toBeInTheDocument();
    expect(screen.getAllByText("Gemini 3 Pro").length).toBeGreaterThan(0);
    expect(screen.queryByText("Claude Sonnet 4.6 / Direction B")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "実装引き継ぎ" }));

    expect(screen.getAllByText("承認パケット").length).toBeGreaterThan(0);
    expect(screen.getByText("アーキテクチャ方針と技術判断")).toBeInTheDocument();
    expect(screen.getByText("承認レビューのチェックリスト")).toBeInTheDocument();
    expect(screen.getByText("実装ガードレール")).toBeInTheDocument();
    expect(screen.getByText("マルチエージェント実装レーン")).toBeInTheDocument();
    expect(screen.getByText("状態保持型 ワークスペース シェル にする")).toBeInTheDocument();
  }, 20000);

  it("keeps prototype handoff content aligned with the currently inspected variant", () => {
    renderSubject();

    fireEvent.click(screen.getByRole("button", { name: "比較" }));
    fireEvent.click(screen.getByRole("button", { name: "見る" }));
    fireEvent.click(screen.getByRole("button", { name: "試作プレビュー" }));

    expect(screen.getByText("この案を承認へ渡すなら")).toBeInTheDocument();
    expect(screen.getByText("密度高めの制御室体験を保ったまま承認へ渡す。")).toBeInTheDocument();
  }, 12000);

  it("renders implementation slices from embedded payload strings without breaking the layout", () => {
    const state = makeLifecycleState();
    state.designVariants[0] = {
      ...state.designVariants[0],
      implementation_brief: {
        ...state.designVariants[0].implementation_brief!,
        delivery_slices: [
          "{'slice': 'S1', 'title': 'フェーズナビゲーションシェルと左レール実装', 'milestone': 'ms-alpha', 'acceptance': '左レールの4フェーズ間をキーボードで遷移できる'}",
          "{'slice': 'S2', 'title': '調査ワークスペースと成果物カードCRUD', 'milestone': 'ms-beta', 'acceptance': '成果物カードのCRUDと信頼スコアが揃う'}",
        ],
      },
    };

    renderSubject(state);
    fireEvent.click(screen.getByRole("button", { name: "実装引き継ぎ" }));

    expect(screen.getByText("フェーズナビゲーションシェルと左レール実装")).toBeInTheDocument();
    expect(screen.getByText("初回検証マイルストーン")).toBeInTheDocument();
    expect(screen.getAllByText("受け入れ条件").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\{'slice': 'S1'/)).not.toBeInTheDocument();
  });

  it("disables approval handoff when the selected baseline is stale", () => {
    const state = makeLifecycleState();
    state.designVariants[0] = {
      ...state.designVariants[0],
      freshness: {
        status: "stale",
        can_handoff: false,
        current_fingerprint: "fingerprint-2",
        variant_fingerprint: "fingerprint-1",
        reasons: ["planning/research decision context changed after this design was generated"],
      },
      artifact_completeness: {
        ...(state.designVariants[0].artifact_completeness ?? { score: 1, status: "complete", present: [], missing: [], screen_count: 1, workflow_count: 1, route_count: 1 }),
        status: "partial",
        missing: ["screen_specs"],
      },
    };
    state.decisionContext = {
      ...(state.decisionContext ?? {}),
      consistency_snapshot: {
        status: "attention",
        issues: [
          {
            id: "stale-selected-design",
            title: "Selected design was generated from an older decision context",
            detail: "Ivory Signal Gallery",
          },
        ],
      },
    };

    renderSubject(state);

    expect(screen.getByRole("button", { name: "この方向で承認へ" })).toBeDisabled();
    expect(screen.getAllByText(/企画または調査の判断文脈が変わったため/).length).toBeGreaterThan(0);
    expect(screen.getByText(/design を再生成し、基準案を選び直してください/)).toBeInTheDocument();
  });

  it("blocks approval when the selected preview is invalid even if artifacts are otherwise complete", () => {
    const state = makeLifecycleState();
    state.designVariants[0] = {
      ...state.designVariants[0],
      preview_meta: {
        ...(state.designVariants[0].preview_meta ?? { source: "llm", extraction_ok: true, validation_ok: true, html_size: 1600, screen_count_estimate: 4, interactive_features: [], validation_issues: [] }),
        source: "repaired",
        validation_ok: false,
        validation_issues: ["missing_navigation_shell", "missing_accessibility_annotations"],
      },
      freshness: {
        status: "fresh",
        can_handoff: false,
        current_fingerprint: "fingerprint-1",
        variant_fingerprint: "fingerprint-1",
        reasons: ["design preview does not satisfy the preview contract"],
      },
    };

    renderSubject(state);

    expect(screen.getByRole("button", { name: "この方向で承認へ" })).toBeDisabled();
    expect(screen.getAllByText("再構成").length).toBeGreaterThan(0);
    expect(screen.getByText(/プレビューがプロダクトワークスペースの要件を満たしていない/)).toBeInTheDocument();
    expect(screen.getByText(/プレビュー要修正: ナビゲーションシェルが不足しています、アクセシビリティ注記が不足しています/)).toBeInTheDocument();
  });

  it("blocks approval when stale selection is detected only from consistency issues", () => {
    const state = makeLifecycleState();
    state.designVariants[0] = {
      ...state.designVariants[0],
      freshness: undefined,
      artifact_completeness: undefined,
    };
    state.decisionContext = {
      ...(state.decisionContext ?? {}),
      consistency_snapshot: {
        status: "attention",
        issues: [
          {
            id: "stale-selected-design",
            title: "Selected design was generated from an older decision context",
            detail: "Ivory Signal Gallery",
          },
        ],
      },
    };

    renderSubject(state);

    expect(screen.getByRole("button", { name: "この方向で承認へ" })).toBeDisabled();
    expect(screen.getAllByText("要再生成").length).toBeGreaterThan(0);
    expect(screen.getByText("再評価待ち")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "判断概要" }));

    expect(screen.getAllByText("要再生成").length).toBeGreaterThan(0);
  });

  it("shows restoring telemetry instead of zero-node warmup copy for completed design runs", () => {
    const state = makeLifecycleState();
    state.phaseRuns = [
      {
        id: "run_async_design",
        runId: "run_async_design",
        projectId: "persist-probe-manual",
        phase: "design",
        workflowId: "lifecycle-design-persist-probe-manual",
        status: "completed",
        startedAt: "2026-03-17T00:00:00Z",
        completedAt: "2026-03-17T00:05:00Z",
        createdAt: "2026-03-17T00:05:00Z",
        artifactCount: 10,
        decisionCount: 1,
        costUsd: 0.42,
        executionSummary: {},
      },
    ];

    renderSubject(state);

    expect(screen.getByText("復元中")).toBeInTheDocument();
    expect(screen.getByText("完了した run の詳細を復元しています。")).toBeInTheDocument();
    expect(screen.queryByText(/Claude Sonnet 4.6 が濃色の制御室案を/)).not.toBeInTheDocument();
  });
});
