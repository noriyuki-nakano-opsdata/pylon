import type { AgentProgress, WorkflowRunState } from "@/hooks/useWorkflowRun";
import type { LifecycleWorkspaceView } from "@/pages/lifecycle/LifecycleContext";
import type {
  AnalysisResult,
  DeployCheck,
  DesignVariant,
  FeedbackItem,
  LifecycleAgentBlueprint,
  LifecyclePhase,
  LifecyclePhaseRuntimeSummary,
  MarketResearch,
  ReleaseRecord,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";

function toAgentProgressStatus(
  status: "idle" | "running" | "completed" | "failed",
): "pending" | "running" | "completed" | "failed" {
  return status === "idle" ? "pending" : status;
}

export function selectPhaseStatus(
  phaseStatuses: LifecycleWorkspaceView["phaseStatuses"],
  phase: LifecyclePhase,
): string {
  return phaseStatuses.find((item) => item.phase === phase)?.status ?? "available";
}

export function selectResearchRuntimeSummary(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeActivePhaseSummary" | "runtimePhaseSummary"
  >,
): LifecyclePhaseRuntimeSummary | null {
  if (lifecycle.runtimeActivePhase === "research") {
    return lifecycle.runtimeActivePhaseSummary;
  }
  if (lifecycle.runtimePhaseSummary?.phase === "research") {
    return lifecycle.runtimePhaseSummary;
  }
  return null;
}

export function selectResearchRuntimeTelemetry(
  lifecycle: Pick<
    LifecycleWorkspaceView,
    "runtimeActivePhase" | "runtimeLiveTelemetry"
  >,
): WorkflowRunLiveTelemetry | null {
  return (lifecycle.runtimeLiveTelemetry?.phase ?? lifecycle.runtimeActivePhase) === "research"
    ? lifecycle.runtimeLiveTelemetry
    : null;
}

export function selectResearchProgressState(params: {
  workflow: Pick<WorkflowRunState, "status" | "agentProgress">;
  runtimeSummary: LifecyclePhaseRuntimeSummary | null;
  runtimeTelemetry: WorkflowRunLiveTelemetry | null;
  isPreparing: boolean;
  nowMs: number;
}) {
  const runtimeProgress = (params.runtimeSummary?.agents ?? []).map((agent) => ({
    nodeId: agent.agentId,
    agent: agent.label,
    status: toAgentProgressStatus(agent.status),
  }));
  const runtimeStartedAt = params.runtimeTelemetry?.run?.startedAt
    ? new Date(params.runtimeTelemetry.run.startedAt).getTime()
    : null;
  const runtimeElapsedMs = runtimeStartedAt
    ? Math.max(0, params.nowMs - runtimeStartedAt)
    : 0;
  const isRunning =
    params.isPreparing
    || params.workflow.status === "starting"
    || params.workflow.status === "running";
  const isResearchRunLive =
    params.runtimeTelemetry?.run != null
    && params.runtimeTelemetry.run.status !== "completed"
    && params.runtimeTelemetry.run.status !== "failed";
  const visibleProgress: AgentProgress[] = params.workflow.agentProgress.length > 0
    ? params.workflow.agentProgress
    : runtimeProgress;
  const totalSteps = Math.max(
    visibleProgress.length,
    params.runtimeSummary?.agents?.length ?? 0,
    1,
  );
  const completedSteps = params.runtimeTelemetry?.completedNodeCount
    ?? visibleProgress.filter((agent) => agent.status === "completed").length;

  return {
    runtimeProgress,
    runtimeElapsedMs,
    runtimeRunningNodes: params.runtimeTelemetry?.runningNodeIds ?? [],
    runtimeRecentNodes: params.runtimeTelemetry?.recentNodeIds ?? [],
    runtimeRecentEvents: params.runtimeTelemetry?.recentEvents ?? [],
    runtimeRecentActions: params.runtimeSummary?.recentActions ?? [],
    runtimeAgentCards: (params.runtimeSummary?.agents ?? []).slice(0, 6),
    isRunning,
    isResearchRunLive,
    isInitialResearchRun: isRunning || isResearchRunLive,
    visibleProgress,
    totalSteps,
    completedSteps,
    progressPercent: Math.max(
      6,
      Math.min(100, Math.round((completedSteps / totalSteps) * 100)),
    ),
  };
}

export function selectResearchReadinessState(params: {
  research: MarketResearch | null;
  phaseStatus: string;
  nextAction: LifecycleWorkspaceView["nextAction"];
}) {
  const research = params.research;
  const hasExternalSources =
    (research?.source_links?.some((link) => /^https?:\/\//i.test(link)) ?? false)
    || (research?.evidence?.some(
      (item) => item.source_type === "url" && /^https?:\/\//i.test(item.source_ref),
    ) ?? false);
  const hasWinningTheses = (research?.winning_theses?.length ?? 0) > 0;
  const confidenceFloor = research?.confidence_summary?.floor ?? 0;
  const criticalDissentCount =
    research?.critical_dissent_count
    ?? (research?.dissent ?? []).filter(
      (item) => item.severity === "critical" && !item.resolved,
    ).length;
  const autonomousRemediation = research?.autonomous_remediation;
  const nextActionAutoResearch =
    params.nextAction?.phase === "research"
    && params.nextAction?.type === "run_phase"
    && params.nextAction?.canAutorun;
  const researchReady =
    !!research
    && params.phaseStatus === "completed"
    && hasExternalSources
    && hasWinningTheses;
  const gateIssues = !researchReady && research
    ? [
        !hasExternalSources
          ? "外部ソースへの根拠リンクが不足しています。"
          : null,
        !hasWinningTheses
          ? "企画に渡せる有力仮説が不足しています。"
          : null,
        confidenceFloor < 0.6
          ? `信頼度下限が ${(confidenceFloor * 100).toFixed(0)}% で、企画に渡す基準の 60% を下回っています。`
          : null,
        criticalDissentCount > 0
          ? `未解決の重大な反証が ${criticalDissentCount} 件あります。`
          : null,
      ].filter((issue): issue is string => Boolean(issue))
    : [];
  const isAutonomousRecoveryActive = !!research && !researchReady && (
    autonomousRemediation?.status === "queued"
    || autonomousRemediation?.status === "retrying"
    || nextActionAutoResearch
  );

  return {
    researchReady,
    hasExternalSources,
    hasWinningTheses,
    confidenceFloor,
    criticalDissentCount,
    autonomousRemediation,
    nextActionAutoResearch,
    isAutonomousRecoveryActive,
    gateIssues,
    warning: !researchReady && research
      ? gateIssues[0] ?? "品質ゲートを満たしていません。企画へ進む前に追加調査が必要です。"
      : null,
  };
}

export function selectPhaseTeam(
  view: Pick<LifecycleWorkspaceView, "blueprints">,
  phase: LifecyclePhase,
  fallback: LifecycleAgentBlueprint[],
): LifecycleAgentBlueprint[] {
  const team = view.blueprints[phase]?.team ?? [];
  return team.length > 0 ? team : fallback;
}

export function selectSelectedFeatures(
  view: Pick<LifecycleWorkspaceView, "features">,
) {
  return view.features.filter((feature) => feature.selected);
}

export function selectSelectedFeatureCount(
  view: Pick<LifecycleWorkspaceView, "features">,
): number {
  return selectSelectedFeatures(view).length;
}

export function selectSelectedDesign(
  view: Pick<LifecycleWorkspaceView, "selectedDesignId" | "designVariants">,
): DesignVariant | null {
  if (!view.selectedDesignId) return null;
  return view.designVariants.find((variant) => variant.id === view.selectedDesignId) ?? null;
}

export function selectCompletedPhaseCount(
  view: Pick<LifecycleWorkspaceView, "phaseStatuses">,
): number {
  return view.phaseStatuses.filter((phase) => phase.status === "completed").length;
}

export function selectSortedFeedbackItems(
  view: Pick<LifecycleWorkspaceView, "feedbackItems">,
): FeedbackItem[] {
  return [...view.feedbackItems].sort((a, b) => b.votes - a.votes);
}

export function selectDeploySummary(
  view: Pick<LifecycleWorkspaceView, "deployChecks" | "releases">,
): {
  checks: DeployCheck[];
  allPassed: boolean;
  deployed: boolean;
  latestRelease: ReleaseRecord | undefined;
  passedCount: number;
  warningCount: number;
  failedCount: number;
} {
  const checks = view.deployChecks;
  return {
    checks,
    allPassed: checks.length > 0 && checks.every((item) => item.status !== "fail"),
    deployed: view.releases.length > 0,
    latestRelease: view.releases[0],
    passedCount: checks.filter((item) => item.status === "pass").length,
    warningCount: checks.filter((item) => item.status === "warning").length,
    failedCount: checks.filter((item) => item.status === "fail").length,
  };
}

export function selectPlanningAnalysis(
  view: Pick<LifecycleWorkspaceView, "analysis">,
): AnalysisResult {
  return view.analysis ?? {
    personas: [],
    user_stories: [],
    kano_features: [],
    recommendations: [],
  };
}

export type PlanningStep =
  | "analyze"
  | "analyzing"
  | "review"
  | "features"
  | "milestones"
  | "epics"
  | "gantt";

export type PlanningReviewTab =
  | "overview"
  | "persona"
  | "kano"
  | "stories"
  | "journey"
  | "jtbd"
  | "ia"
  | "actors"
  | "usecases"
  | "design-tokens";

export function selectPlanningReviewViewModel(analysis: AnalysisResult) {
  return {
    reviewTabs: [
      { key: "overview" as const, label: "概要", hidden: false },
      { key: "persona" as const, label: "ペルソナ", hidden: false },
      { key: "journey" as const, label: "ジャーニー", hidden: !analysis.user_journeys?.length },
      { key: "jtbd" as const, label: "JTBD", hidden: !analysis.job_stories?.length },
      { key: "kano" as const, label: "KANO", hidden: false },
      { key: "stories" as const, label: "ストーリー", hidden: false },
      { key: "actors" as const, label: "アクター/ロール", hidden: !analysis.actors?.length && !analysis.roles?.length },
      { key: "usecases" as const, label: "ユースケース", hidden: !analysis.use_cases?.length },
      { key: "ia" as const, label: "IA分析", hidden: !analysis.ia_analysis },
      { key: "design-tokens" as const, label: "デザイントークン", hidden: !analysis.design_tokens },
    ],
    heroStats: [
      { label: "ペルソナ", value: analysis.personas.length },
      { label: "ストーリー", value: analysis.user_stories.length },
      { label: "機能候補", value: analysis.kano_features.length },
      { label: "レッドチーム", value: analysis.red_team_findings?.length ?? 0 },
    ],
    overviewStats: [
      { label: "ペルソナ", value: analysis.personas.length },
      { label: "ストーリー", value: analysis.user_stories.length },
      { label: "機能候補", value: analysis.kano_features.length },
      { label: "推奨事項", value: analysis.recommendations.length },
      { label: "却下済み", value: analysis.rejected_features?.length ?? 0 },
      { label: "調査結果", value: analysis.red_team_findings?.length ?? 0 },
    ],
    kanoDistribution: [
      {
        label: "当たり前品質",
        count: analysis.kano_features.filter((feature) => feature.category === "must-be").length,
        color: "bg-destructive/10 text-destructive",
      },
      {
        label: "一元的品質",
        count: analysis.kano_features.filter((feature) => feature.category === "one-dimensional").length,
        color: "bg-primary/10 text-primary",
      },
      {
        label: "魅力品質",
        count: analysis.kano_features.filter((feature) => feature.category === "attractive").length,
        color: "bg-success/10 text-success",
      },
    ],
    focusSummary: analysis.judge_summary ?? analysis.recommendations[0] ?? null,
  };
}

export function selectPlanningViewModel(
  view: Pick<LifecycleWorkspaceView, "analysis" | "spec">,
) {
  const analysis = selectPlanningAnalysis(view);
  return {
    analysis,
    hasAnalysis: view.analysis != null,
    initialStep: (view.analysis ? "review" : "analyze") as Exclude<PlanningStep, "analyzing">,
    canRunAnalysis: !!view.spec.trim(),
    review: selectPlanningReviewViewModel(analysis),
  };
}

const DEFAULT_DEVELOPMENT_TEAM: LifecycleAgentBlueprint[] = [
  { id: "planner", label: "ビルド設計", role: "作業分解", autonomy: "A2", tools: [], skills: [] },
  { id: "frontend-builder", label: "フロントエンド", role: "UI 実装", autonomy: "A2", tools: [], skills: [] },
  { id: "backend-builder", label: "バックエンド", role: "Domain 設計", autonomy: "A2", tools: [], skills: [] },
  { id: "integrator", label: "インテグレーター", role: "統合", autonomy: "A2", tools: [], skills: [] },
  { id: "reviewer", label: "リリースレビュー", role: "品質判定", autonomy: "A2", tools: [], skills: [] },
];

export function selectDevelopmentViewModel(
  view: Pick<
    LifecycleWorkspaceView,
    "approvalStatus" | "blueprints" | "designVariants" | "milestones" | "selectedDesignId" | "features"
  >,
) {
  const buildTeam = selectPhaseTeam(view, "development", DEFAULT_DEVELOPMENT_TEAM);
  const selectedFeatureCount = selectSelectedFeatureCount(view);
  const selectedDesign = selectSelectedDesign(view);
  const milestoneCount = view.milestones.length;

  return {
    buildTeam,
    selectedFeatureCount,
    selectedDesign,
    milestoneCount,
    maxIterations: milestoneCount > 0 ? 5 : 1,
    canStartBuild:
      view.approvalStatus === "approved"
      && selectedFeatureCount > 0
      && selectedDesign != null,
  };
}

export function selectApprovalViewModel(
  view: Pick<
    LifecycleWorkspaceView,
    "analysis" | "approvalStatus" | "features" | "milestones" | "research" | "selectedDesignId" | "designVariants" | "spec"
  >,
) {
  const selectedFeatureCount = selectSelectedFeatureCount(view);
  const selectedDesign = selectSelectedDesign(view);
  const milestoneCount = view.milestones.length;
  const checkItems = [
    { label: "プロダクト仕様が明確", done: !!view.spec.trim(), phase: "research" as const },
    { label: "UX分析が完了", done: !!view.analysis, phase: "planning" as const },
    { label: "機能スコープが確定", done: selectedFeatureCount > 0, phase: "planning" as const },
    { label: "デザインパターンが選択済み", done: !!view.selectedDesignId, phase: "design" as const },
    { label: "マイルストーンが定義済み", done: milestoneCount > 0, phase: "planning" as const },
  ];
  const completedChecklistCount = checkItems.filter((item) => item.done).length;

  return {
    selectedFeatureCount,
    selectedDesign,
    milestoneCount,
    reviewLinks: [
      { label: "調査を確認", phase: "research" as const, ready: !!view.research },
      { label: "企画を修正", phase: "planning" as const, ready: !!view.analysis },
      { label: "デザインを修正", phase: "design" as const, ready: !!view.selectedDesignId },
    ],
    checkItems,
    allChecked: completedChecklistCount === checkItems.length,
    completedChecklistCount,
    checklistProgressPercent: (completedChecklistCount / checkItems.length) * 100,
  };
}
