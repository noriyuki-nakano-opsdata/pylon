import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckSquare,
  Eye,
  Flag,
  GanttChart,
  Layers,
  Lightbulb,
  Loader2,
  Route,
  Target,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { MultiAgentCollaborationPulse, type CollaborationTimelineStep } from "@/components/lifecycle/MultiAgentCollaborationPulse";
import { buildPhasePulseSnapshot } from "@/components/lifecycle/pulseUtils";
import {
  buildPlanningRecommendedMilestoneDisplay,
  planningPresetLabel,
} from "@/lifecycle/planningDisplay";
import { buildPlanningWorkflowInput } from "@/lifecycle/inputs";
import { hasRestorablePhaseRun } from "@/lifecycle/phaseStatus";
import {
  EpicsWbsContent,
  FeaturesContent,
  GanttContent,
  MilestonesContent,
} from "@/pages/lifecycle/planning/PlanningEditors";
import { ReviewContent } from "@/pages/lifecycle/planning/PlanningReview";
import { TaskDecompositionPanel } from "./TaskDecompositionPanel";
import { BehaviorModelPanel } from "./BehaviorModelPanel";
import {
  selectPhaseStatus,
  selectPhaseTeam,
  selectPlanningViewModel,
  selectSelectedFeatureCount,
  type PlanningStep,
} from "@/lifecycle/selectors";
import {
  planningActionVariants,
  planningChipVariants,
  planningDetailCardVariants,
  planningEyebrowClassName,
  planningMetricTileVariants,
  planningMutedCopyClassName,
  planningSurfaceVariants,
  planningTabVariants,
  planningTopbarClassName,
  planningWorkspaceClassName,
} from "@/lifecycle/planningTheme";
import { persistCompletedPhase } from "@/lifecycle/phasePersistence";

const PLANNING_AGENTS = [
  { id: "persona-builder", label: "ペルソナ分析", role: "ユーザー理解", autonomy: "A2", tools: [], skills: [] },
  { id: "story-architect", label: "ユースケース設計", role: "行動設計", autonomy: "A2", tools: [], skills: [] },
  { id: "feature-analyst", label: "KANO分析", role: "価値評価", autonomy: "A2", tools: [], skills: [] },
  { id: "solution-architect", label: "実装設計", role: "構造設計", autonomy: "A2", tools: [], skills: [] },
  { id: "planning-synthesizer", label: "企画統合", role: "統合判断", autonomy: "A2", tools: [], skills: [] },
];

function buildPlanningTimeline(agents: ReturnType<typeof buildPhasePulseSnapshot>["agents"]): CollaborationTimelineStep[] {
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const lead = agents.find((agent) => agent.status === "running") ?? agents[0];
  const synth = agents.find((agent) => agent.id === "planning-synthesizer");

  return [
    {
      id: "parallel-analysis",
      label: "並列分析",
      detail: runningCount > 0
        ? `${runningCount} 本のレーンで、ペルソナ・ストーリー・価値評価・構造設計を同時に進めています。`
        : "企画チームを各分析レーンへ配置しています。",
      status: runningCount > 0 || completedCount > 0 ? "completed" : "pending",
      owner: lead?.label,
      artifact: "分析素材",
    },
    {
      id: "tradeoff-synthesis",
      label: "論点の統合",
      detail: "競合する要件とスコープを突き合わせ、企画として通すべき優先順位に圧縮します。",
      status: runningCount > 0 ? "running" : completedCount >= 3 ? "completed" : "pending",
      owner: lead?.label,
      artifact: "優先順位案",
    },
    {
      id: "planning-packet",
      label: "企画パケット",
      detail: synth?.status === "running"
        ? synth.currentTask ?? "統合担当がロードマップパケットを組み立てています。"
        : "統合担当がデザインに渡す企画パケットを作成します。",
      status: synth?.status === "completed" ? "completed" : synth?.status === "running" ? "running" : "pending",
      owner: synth?.label,
      artifact: "企画パケット",
    },
    {
      id: "design-handoff",
      label: "デザインへ引き継ぎ",
      detail: "機能・エピック・マイルストーンを揃え、デザイン比較にそのまま渡します。",
      status: agents.every((agent) => agent.status === "completed") ? "completed" : "pending",
      owner: synth?.label,
      artifact: "デザイン入力",
    },
  ];
}

export function PlanningPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const planningPhaseStatus = selectPhaseStatus(lc.phaseStatuses, "planning");
  const hasKnownPlanningRun = hasRestorablePhaseRun(
    lc.phaseStatuses,
    lc.phaseRuns,
    lc.runtimeActivePhase,
    "planning",
  );
  const workflow = useWorkflowRun("planning", projectSlug ?? "", { knownRunExists: hasKnownPlanningRun });
  const planningAgents = selectPhaseTeam(lc, "planning", PLANNING_AGENTS);
  const planningVm = selectPlanningViewModel(lc);
  const handoffGuidance = lc.nextAction?.phase === "planning"
    && lc.nextAction?.payload?.operatorGuidance
    && typeof lc.nextAction.payload.operatorGuidance === "object"
      ? lc.nextAction.payload.operatorGuidance as Record<string, unknown>
      : null;
  const planningGuardrails = Array.isArray(handoffGuidance?.planningGuardrails)
    ? handoffGuidance.planningGuardrails.filter((item): item is string => typeof item === "string")
    : [];
  const handoffNotice = typeof handoffGuidance?.strategySummary === "string"
    ? handoffGuidance.strategySummary
    : null;
  const planningPulse = buildPhasePulseSnapshot({
    lifecycle: lc,
    phase: "planning",
    team: planningAgents,
    workflow,
    warmupTasks: [
      "ペルソナ分析が最初の顧客像を組み立てています。",
      "ユースケース設計が主要フローの分解を開始しています。",
      "KANO分析が価値の強弱を見積もっています。",
      "実装設計がスコープ境界を確認しています。",
      "企画統合が引き継ぎパケットの骨子を準備しています。",
    ],
  });
  const [subStep, setSubStep] = useState<PlanningStep>(planningVm.initialStep);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const syncedRunRef = useRef<string | null>(null);
  const hasPriorityRisks = planningVm.review.riskHighlights.length > 0;
  const selectedFeatureCount = selectSelectedFeatureCount(lc);
  const totalFeatureCount = lc.features.length;
  const recommendedMilestones = buildPlanningRecommendedMilestoneDisplay(planningVm.analysis);
  const requiresDecisionConfirmation = hasPriorityRisks || planningGuardrails.length > 0;
  const valueContract = lc.valueContract ?? null;
  const outcomeTelemetryContract = lc.outcomeTelemetryContract ?? null;
  const [decisionConfirmed, setDecisionConfirmed] = useState(!requiresDecisionConfirmation);
  const decisionConfirmationKey = [
    planningVm.review.decisionSummary?.title ?? "",
    planningGuardrails.join("|"),
  ].join("::");
  const continueBlocked = requiresDecisionConfirmation && !decisionConfirmed;
  const continueLabel = isHandingOff
    ? "保存して移動中..."
    : continueBlocked
      ? "主要リスクを確認"
      : hasPriorityRisks
        ? "前提を残してデザイン比較へ"
        : "デザイン比較へ";
  const topRisk = planningVm.review.riskHighlights[0] ?? null;
  const topRecommendation = planningVm.review.structuredRecommendations[0] ?? null;

  const workspaceIntro = subStep === "features"
    ? {
        eyebrow: "スコープ整理",
        title: "M1 に残す機能だけを切り出す",
        description: "必須品質と差別化機能を切り分け、最初のリリースで検証したい価値だけを残します。",
        stats: [
          { label: "選択中", value: `${selectedFeatureCount}/${totalFeatureCount || 0}` },
          { label: "最優先リスク", value: topRisk?.title ?? "大きな阻害要因なし" },
          { label: "次の判断", value: topRecommendation?.action ?? "魅力機能は後ろに置く" },
        ],
      }
    : subStep === "epics"
      ? {
          eyebrow: "実行プラン",
          title: "どの構成で進めるかを決める",
          description: "工数、期間、スキルの釣り合いを見ながら、いまの仮説に対して無理のない実行プランを選びます。",
          stats: [
            { label: "現在の構成", value: planningPresetLabel(lc.selectedPreset) },
            { label: "最優先リスク", value: topRisk?.title ?? "大きな阻害要因なし" },
            { label: "見るべき点", value: "工数より停止条件を先に満たせるか" },
          ],
        }
      : subStep === "gantt"
        ? {
            eyebrow: "工程確認",
            title: "工程の流れと依存を確認する",
            description: "どの順序で進めると早く学習できるかを見て、デリバリーが仮説検証を遅らせない構造にします。",
            stats: [
              { label: "現在の構成", value: planningPresetLabel(lc.selectedPreset) },
              { label: "見るべき点", value: "先に証跡が出る作業が前にあるか" },
              { label: "持ち込む前提", value: planningGuardrails[0] ?? "主要導線を先に成立させる" },
            ],
          }
        : subStep === "milestones"
          ? {
              eyebrow: "停止条件",
              title: "止める条件まで含めて定義する",
              description: "成功条件だけではなく、中止条件と責任者を決めて、進んでいるように見えるだけの状態を防ぎます。",
              stats: [
                { label: "推奨数", value: `${recommendedMilestones.length}` },
                { label: "最優先リスク", value: topRisk?.title ?? "大きな阻害要因なし" },
                { label: "次の判断", value: "証跡が出ない時点で止められるか" },
              ],
            }
          : null;

  useEffect(() => {
    setDecisionConfirmed(!requiresDecisionConfirmation);
  }, [decisionConfirmationKey, requiresDecisionConfirmation]);

  useEffect(() => {
    if (planningVm.hasAnalysis && subStep === "analyze") setSubStep("review");
  }, [planningVm.hasAnalysis, subStep]);

  useEffect(() => {
    if (planningPhaseStatus === "in_progress" && !planningVm.hasAnalysis && subStep === "analyze") {
      setSubStep("analyzing");
    }
  }, [planningPhaseStatus, planningVm.hasAnalysis, subStep]);

  // Sync terminal workflow runs back into the lifecycle project.
  useEffect(() => {
    if ((workflow.status !== "completed" && workflow.status !== "failed") || !workflow.runId || !projectSlug) {
      return;
    }
    if (syncedRunRef.current === workflow.runId) return;
    syncedRunRef.current = workflow.runId;
    void lifecycleApi.syncPhaseRun(projectSlug, "planning", workflow.runId).then(({ project }) => {
      actions.applyProject(project);
    });
    if (workflow.status === "completed") {
      setSubStep("review");
    }
  }, [actions, workflow.runId, workflow.status, projectSlug]);

  // Handle workflow failure
  useEffect(() => {
    if (workflow.status === "failed") {
      setSubStep("analyze");
    }
  }, [workflow.status]);

  const runAnalysis = () => {
    setSubStep("analyzing");
    actions.advancePhase("planning");
    workflow.start(buildPlanningWorkflowInput(lc));
  };

  const goNext = async () => {
    if (continueBlocked) {
      setSubStep("review");
      return;
    }
    if (!projectSlug) return;
    setTransitionError(null);
    setIsHandingOff(true);
    try {
      const response = await persistCompletedPhase(projectSlug, "planning", lc.phaseStatuses);
      actions.applyProject(response.project);
      navigate(`/p/${projectSlug}/lifecycle/design`);
    } catch (err) {
      setTransitionError(err instanceof Error ? err.message : "デザインへの引き継ぎに失敗しました");
    } finally {
      setIsHandingOff(false);
    }
  };

  const goBack = () => {
    navigate(`/p/${projectSlug}/lifecycle/research`);
  };

  // Analyze input
  const isAnalyzing = subStep === "analyzing"
    || (planningPhaseStatus === "in_progress" && !planningVm.hasAnalysis);

  if (subStep === "analyze" && !isAnalyzing) {
    return (
      <div className={cn(planningWorkspaceClassName, "flex h-full items-center justify-center p-6")}>
        <div className="max-w-xl w-full space-y-6 text-center">
          <Lightbulb className="h-12 w-12 text-primary mx-auto" />
          <h2 className="text-xl font-bold text-foreground">企画分析</h2>
          <p className={planningMutedCopyClassName}>
            調査結果をもとに、誰に何を届けるかと最初のスコープを落ち着いて固めます。
          </p>
          {lc.spec && (
            <div className={cn(planningSurfaceVariants({ tone: "default", padding: "md" }), "text-left")}>
              <p className={cn(planningEyebrowClassName, "mb-1")}>分析対象</p>
              <p className="text-sm text-foreground line-clamp-3">{lc.spec}</p>
            </div>
          )}
          {handoffNotice && (
            <div className={cn(planningSurfaceVariants({ tone: "accent", padding: "md" }), "text-left")}>
              <p className={cn(planningEyebrowClassName, "text-[color:var(--planning-accent-strong)]")}>調査からの引き継ぎメモ</p>
              <p className="mt-1 text-sm leading-6 text-foreground">{handoffNotice}</p>
              {!!planningGuardrails.length && (
                <div className="mt-2 space-y-1">
                  {planningGuardrails.map((item) => (
                    <p key={item} className="text-xs text-[color:var(--planning-text-soft)]">• {item}</p>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            onClick={runAnalysis}
            disabled={!planningVm.canRunAnalysis}
            className={cn("w-full py-3 text-sm", planningActionVariants({ tone: planningVm.canRunAnalysis ? "primary" : "muted" }))}
          >
            <Zap className="h-4 w-4" /> 分析を開始
          </button>
        </div>
      </div>
    );
  }

  // Analyzing
  if (isAnalyzing) {
    if (workflow.status === "failed") {
      return (
        <div className={cn(planningWorkspaceClassName, "flex h-full items-center justify-center p-6")}>
          <div className="max-w-md w-full space-y-4 text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
            <h2 className="text-lg font-bold text-foreground">分析エラー</h2>
            <p className={planningMutedCopyClassName}>{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
            <button onClick={() => { workflow.reset(); setSubStep("analyze"); }} className={planningActionVariants({ tone: "primary" })}>
              やり直す
            </button>
          </div>
        </div>
      );
    }
    return (
      <MultiAgentCollaborationPulse
        title="AIが徹底分析中..."
        subtitle="企画評議会がペルソナ、ユースケース、優先度、デリバリープランを統合しています"
        elapsedLabel={planningPulse.elapsedLabel}
        agents={planningPulse.agents}
        actions={planningPulse.actions}
        events={planningPulse.events}
        timeline={buildPlanningTimeline(planningPulse.agents)}
      />
    );
  }

  // Review / Features / Milestones
  const a = planningVm.analysis;
  return (
    <div className={cn(planningWorkspaceClassName, "flex h-full flex-col")}>
      {/* Sub-nav */}
      <div className={cn(planningTopbarClassName, "flex flex-wrap items-center gap-2 px-4 py-3 sm:px-6")}>
        <button onClick={goBack} className="mr-1 flex items-center gap-1 text-xs text-[color:var(--planning-text-soft)] hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <div className="-mx-1 flex min-w-0 flex-1 gap-1 overflow-x-auto px-1 pb-1">
          {([
            { key: "review" as const, label: "分析結果", icon: Eye },
            { key: "features" as const, label: "機能選択", icon: CheckSquare },
            { key: "epics" as const, label: "エピック/WBS", icon: Layers },
            { key: "gantt" as const, label: "ガントチャート", icon: GanttChart },
            { key: "milestones" as const, label: "マイルストーン", icon: Flag },
          ]).map((tab) => (
            <button key={tab.key} onClick={() => setSubStep(tab.key)} className={planningTabVariants({ active: subStep === tab.key })}>
              <tab.icon className="h-3.5 w-3.5" />{tab.label}
            </button>
          ))}
        </div>
        <button
          onClick={goNext}
          disabled={isHandingOff}
          className={cn(
            "w-full sm:w-auto",
            planningActionVariants({
              tone: continueBlocked || (subStep === "review" && hasPriorityRisks) ? "tonal" : "primary",
            }),
          )}
        >
          {isHandingOff && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {continueLabel}
          {!isHandingOff && <ArrowRight className="h-3.5 w-3.5" />}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {transitionError && (
          <div className="mx-auto mb-4 max-w-5xl rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {transitionError}
          </div>
        )}
        {workspaceIntro && (
          <div className={cn(planningSurfaceVariants({ tone: "strong", padding: "md" }), "mx-auto mb-6 max-w-5xl")}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-2">
                <div className={planningChipVariants({ tone: "accent" })}>
                  <Zap className="h-3.5 w-3.5" />
                  {workspaceIntro.eyebrow}
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-foreground">{workspaceIntro.title}</h2>
                  <p className={cn("mt-1", planningMutedCopyClassName)}>{workspaceIntro.description}</p>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-3 lg:w-[34rem]">
                {workspaceIntro.stats.map((item) => (
                  <div key={item.label} className={planningMetricTileVariants({ tone: item.label === "最優先リスク" ? "warning" : item.label === "次の判断" ? "accent" : "default" })}>
                    <p className={planningEyebrowClassName}>{item.label}</p>
                    <p className="mt-2 text-sm font-medium text-foreground">{item.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
        {(valueContract || outcomeTelemetryContract) && (
          <div className={cn(planningSurfaceVariants({ tone: "default", padding: "md" }), "mx-auto mb-6 max-w-5xl")}>
            <div className="flex flex-col gap-3 border-b border-[color:var(--planning-border)] pb-4 md:flex-row md:items-end md:justify-between">
              <div>
                <p className={planningEyebrowClassName}>downstream contracts</p>
                <h2 className="text-lg font-semibold text-foreground">分析を実装契約へ昇格</h2>
                <p className={cn("mt-1 max-w-3xl", planningMutedCopyClassName)}>
                  planning で定義したユーザー価値と計測設計を、design / development / deploy の必須契約として固定します。
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-[color:var(--planning-text-soft)]">
                <span className={planningChipVariants({ tone: "accent" })}>design gate</span>
                <span className={planningChipVariants({ tone: "warning" })}>development gate</span>
                <span className={planningChipVariants({ tone: "default" })}>deploy gate</span>
              </div>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className={cn(planningDetailCardVariants({ tone: "accent", padding: "md" }), "space-y-3")}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className={planningEyebrowClassName}>VALUE CONTRACT</p>
                    <p className="mt-1 text-sm font-semibold text-foreground">{valueContract?.summary ?? "planning 完了時に生成されます"}</p>
                  </div>
                  <Target className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--planning-accent-strong)]" />
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className={planningMetricTileVariants({ tone: "accent" })}>
                    <p className={planningEyebrowClassName}>persona</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{valueContract?.primary_personas?.length ?? 0}</p>
                  </div>
                  <div className={planningMetricTileVariants({ tone: "default" })}>
                    <p className={planningEyebrowClassName}>journey path</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{valueContract?.information_architecture?.key_paths?.length ?? 0}</p>
                  </div>
                  <div className={planningMetricTileVariants({ tone: "warning" })}>
                    <p className={planningEyebrowClassName}>success metric</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{valueContract?.success_metrics?.length ?? 0}</p>
                  </div>
                </div>
              </div>
              <div className={cn(planningDetailCardVariants({ tone: "default", padding: "md" }), "space-y-3")}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className={planningEyebrowClassName}>OUTCOME TELEMETRY</p>
                    <p className="mt-1 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.summary ?? "計測・停止条件を planning で固定します"}</p>
                  </div>
                  <Route className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className={planningMetricTileVariants({ tone: "accent" })}>
                    <p className={planningEyebrowClassName}>event</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.telemetry_events?.length ?? 0}</p>
                  </div>
                  <div className={planningMetricTileVariants({ tone: "warning" })}>
                    <p className={planningEyebrowClassName}>kill criteria</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.kill_criteria?.length ?? 0}</p>
                  </div>
                  <div className={planningMetricTileVariants({ tone: "default" })}>
                    <p className={planningEyebrowClassName}>release check</p>
                    <p className="mt-2 text-sm font-semibold text-foreground">{outcomeTelemetryContract?.release_checks?.length ?? 0}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
        {subStep === "review" && (
          <ReviewContent
            analysis={a}
            handoffNotice={handoffNotice}
            planningGuardrails={planningGuardrails}
            onContinue={goNext}
            continueLabel={continueLabel}
            requiresDecisionConfirmation={requiresDecisionConfirmation}
            decisionConfirmed={decisionConfirmed}
            onDecisionConfirmedChange={setDecisionConfirmed}
          />
        )}
        {subStep === "features" && <FeaturesContent features={lc.features} setFeatures={actions.replaceFeatures} />}
        {subStep === "epics" && (
          <EpicsWbsContent
            planEstimates={lc.planEstimates}
            selectedPreset={lc.selectedPreset}
            onSelectPreset={actions.selectPreset}
          />
        )}
        {subStep === "gantt" && (
          <GanttContent
            planEstimates={lc.planEstimates}
            selectedPreset={lc.selectedPreset}
            onSelectPreset={actions.selectPreset}
          />
        )}
        {subStep === "milestones" && (
          <MilestonesContent
            milestones={lc.milestones}
            setMilestones={actions.replaceMilestones}
            recommended={recommendedMilestones}
          />
        )}
        <TaskDecompositionPanel decomposition={lc.taskDecomposition ?? null} />
        <BehaviorModelPanel analysis={lc.dcsAnalysis ?? null} />
      </div>
    </div>
  );
}
