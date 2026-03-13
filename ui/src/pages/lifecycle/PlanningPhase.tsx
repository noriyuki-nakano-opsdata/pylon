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
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLifecycleActions, useLifecycleState } from "./LifecycleContext";
import { useWorkflowRun } from "@/hooks/useWorkflowRun";
import { lifecycleApi } from "@/api/lifecycle";
import { AgentProgressView } from "@/components/lifecycle/AgentProgressView";
import { buildPlanningWorkflowInput } from "@/lifecycle/inputs";
import {
  EpicsWbsContent,
  FeaturesContent,
  GanttContent,
  MilestonesContent,
} from "@/pages/lifecycle/planning/PlanningEditors";
import { ReviewContent } from "@/pages/lifecycle/planning/PlanningReview";
import {
  selectPhaseTeam,
  selectPlanningViewModel,
  type PlanningStep,
} from "@/lifecycle/selectors";

const PLANNING_AGENTS = [
  { id: "persona-builder", label: "ペルソナ分析", role: "ユーザー理解", autonomy: "A2", tools: [], skills: [] },
  { id: "story-architect", label: "ユースケース設計", role: "行動設計", autonomy: "A2", tools: [], skills: [] },
  { id: "feature-analyst", label: "KANO分析", role: "価値評価", autonomy: "A2", tools: [], skills: [] },
  { id: "solution-architect", label: "実装設計", role: "構造設計", autonomy: "A2", tools: [], skills: [] },
  { id: "planning-synthesizer", label: "企画統合", role: "統合判断", autonomy: "A2", tools: [], skills: [] },
];

export function PlanningPhase() {
  const navigate = useNavigate();
  const { projectSlug } = useParams();
  const lc = useLifecycleState();
  const actions = useLifecycleActions();
  const workflow = useWorkflowRun("planning", projectSlug ?? "");
  const planningAgents = selectPhaseTeam(lc, "planning", PLANNING_AGENTS);
  const planningVm = selectPlanningViewModel(lc);
  const [subStep, setSubStep] = useState<PlanningStep>(planningVm.initialStep);
  const syncedRunRef = useRef<string | null>(null);

  useEffect(() => {
    if (planningVm.hasAnalysis && subStep === "analyze") setSubStep("review");
  }, [planningVm.hasAnalysis, subStep]);

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

  const goNext = () => {
    actions.completePhase("planning");
    navigate(`/p/${projectSlug}/lifecycle/design`);
  };

  const goBack = () => {
    navigate(`/p/${projectSlug}/lifecycle/research`);
  };

  // Analyze input
  if (subStep === "analyze") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-xl w-full space-y-6 text-center">
          <Lightbulb className="h-12 w-12 text-primary mx-auto" />
          <h2 className="text-xl font-bold text-foreground">UX / ビジネス分析</h2>
          <p className="text-sm text-muted-foreground">
            調査結果を基にペルソナ、ユーザーストーリー、KANO分析を実施します
          </p>
          {lc.spec && (
            <div className="rounded-lg border border-border bg-card p-4 text-left">
              <p className="text-xs font-medium text-muted-foreground mb-1">分析対象</p>
              <p className="text-sm text-foreground line-clamp-3">{lc.spec}</p>
            </div>
          )}
          <button onClick={runAnalysis} disabled={!planningVm.canRunAnalysis} className={cn(
            "w-full flex items-center justify-center gap-2 rounded-lg py-3 text-sm font-medium transition-colors",
            planningVm.canRunAnalysis ? "bg-primary text-primary-foreground hover:bg-primary/90" : "bg-muted text-muted-foreground cursor-not-allowed",
          )}>
            <Zap className="h-4 w-4" /> 分析を開始
          </button>
        </div>
      </div>
    );
  }

  // Analyzing
  if (subStep === "analyzing") {
    if (workflow.status === "failed") {
      return (
        <div className="flex h-full items-center justify-center p-6">
          <div className="max-w-md w-full space-y-4 text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
            <h2 className="text-lg font-bold text-foreground">分析エラー</h2>
            <p className="text-sm text-muted-foreground">{workflow.error ?? "ワークフローの実行に失敗しました"}</p>
            <button onClick={() => { workflow.reset(); setSubStep("analyze"); }} className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
              やり直す
            </button>
          </div>
        </div>
      );
    }
    return (
      <AgentProgressView
        agents={planningAgents}
        progress={workflow.agentProgress}
        elapsedMs={workflow.elapsedMs}
        title="AIが徹底分析中..."
        subtitle="企画評議会がペルソナ、ユースケース、優先度、デリバリープランを統合しています"
      />
    );
  }

  // Review / Features / Milestones
  const a = planningVm.analysis;
  return (
    <div className="flex h-full flex-col">
      {/* Sub-nav */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 sm:px-6">
        <button onClick={goBack} className="mr-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
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
            <button key={tab.key} onClick={() => setSubStep(tab.key)} className={cn(
              "shrink-0 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              subStep === tab.key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
            )}>
              <tab.icon className="h-3.5 w-3.5" />{tab.label}
            </button>
          ))}
        </div>
        <button onClick={goNext} className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 sm:w-auto">
          デザイン比較へ <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {subStep === "review" && <ReviewContent analysis={a} />}
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
        {subStep === "milestones" && <MilestonesContent milestones={lc.milestones} setMilestones={actions.replaceMilestones} recommended={lc.analysis?.recommended_milestones} />}
      </div>
    </div>
  );
}
