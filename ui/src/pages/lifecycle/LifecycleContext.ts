import { createContext, useContext } from "react";
import type {
  ApprovalComment,
  AnalysisResult,
  DeployCheck,
  DesignVariant,
  FeatureSelection,
  FeedbackItem,
  LifecycleArtifact,
  LifecycleAutonomyLevel,
  LifecycleAutonomyState,
  LifecycleDecision,
  LifecycleDelegation,
  LifecycleNextAction,
  LifecycleOrchestrationMode,
  LifecyclePhase,
  LifecyclePhaseRuntimeSummary,
  LifecyclePhaseRun,
  LifecycleProject,
  LifecycleResearchConfig,
  LifecycleRecommendation,
  LifecycleSkillInvocation,
  MarketResearch,
  Milestone,
  MilestoneResult,
  PhaseBlueprint,
  PhaseStatus,
  PlanEstimate,
  PlanPreset,
  ReleaseRecord,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";

export interface LifecycleWorkspaceView {
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  research: MarketResearch | null;
  analysis: AnalysisResult | null;
  features: FeatureSelection[];
  milestones: Milestone[];
  designVariants: DesignVariant[];
  selectedDesignId: string | null;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  approvalComments: ApprovalComment[];
  buildCode: string | null;
  buildCost: number;
  buildIteration: number;
  milestoneResults: MilestoneResult[];
  planEstimates: PlanEstimate[];
  selectedPreset: PlanPreset;
  phaseStatuses: PhaseStatus[];
  deployChecks: DeployCheck[];
  releases: ReleaseRecord[];
  feedbackItems: FeedbackItem[];
  recommendations: LifecycleRecommendation[];
  artifacts: LifecycleArtifact[];
  decisionLog: LifecycleDecision[];
  skillInvocations: LifecycleSkillInvocation[];
  delegations: LifecycleDelegation[];
  phaseRuns: LifecyclePhaseRun[];
  nextAction: LifecycleNextAction | null;
  autonomyState: LifecycleAutonomyState | null;
  runtimeObservedPhase: LifecyclePhase | null;
  runtimeActivePhase: LifecyclePhase | null;
  runtimePhaseSummary: LifecyclePhaseRuntimeSummary | null;
  runtimeActivePhaseSummary: LifecyclePhaseRuntimeSummary | null;
  runtimeLiveTelemetry: WorkflowRunLiveTelemetry | null;
  runtimeConnectionState: "inactive" | "connecting" | "live" | "reconnecting";
  blueprints: Record<LifecyclePhase, PhaseBlueprint>;
  isHydrating: boolean;
}

export interface LifecycleActions {
  editSpec: (s: string) => void;
  updateResearchConfig: (config: LifecycleResearchConfig) => void;
  replaceFeatures: (f: FeatureSelection[]) => void;
  replaceMilestones: (m: Milestone[]) => void;
  selectDesign: (id: string | null) => void;
  recordBuildIteration: (i: number) => void;
  recordMilestoneResults: (r: MilestoneResult[]) => void;
  selectPreset: (p: PlanPreset) => void;
  applyProject: (project: LifecycleProject) => void;
  advancePhase: (phase: LifecyclePhase) => void;
  completePhase: (phase: LifecyclePhase) => void;
}

export interface LifecycleContextValue {
  state: LifecycleWorkspaceView;
  actions: LifecycleActions;
}

export const LifecycleContext = createContext<LifecycleContextValue | null>(null);

export function useLifecycleState() {
  const ctx = useContext(LifecycleContext);
  if (!ctx) throw new Error("useLifecycleState must be used within LifecycleLayout");
  return ctx.state;
}

export function useLifecycleActions() {
  const ctx = useContext(LifecycleContext);
  if (!ctx) throw new Error("useLifecycleActions must be used within LifecycleLayout");
  return ctx.actions;
}
