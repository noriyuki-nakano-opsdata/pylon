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
  LifecycleDecisionContext,
  LifecycleDecision,
  LifecycleDevelopmentHandoff,
  LifecycleDeliveryPlan,
  LifecycleDelegation,
  LifecycleGovernanceMode,
  LifecycleNextAction,
  LifecycleOutcomeTelemetryContract,
  LifecycleOrchestrationMode,
  LifecyclePhase,
  LifecyclePhaseRuntimeSummary,
  LifecyclePhaseRun,
  LifecycleProductIdentity,
  LifecycleProject,
  LifecycleResearchConfig,
  LifecycleRecommendation,
  LifecycleSkillInvocation,
  LifecycleValueContract,
  MarketResearch,
  Milestone,
  MilestoneResult,
  PhaseBlueprint,
  RequirementsBundle,
  ReverseEngineeringResult,
  TaskDecomposition,
  DCSAnalysis,
  TechnicalDesignBundle,
  PhaseStatus,
  PlanEstimate,
  PlanPreset,
  ReleaseRecord,
  WorkflowRunLiveTelemetry,
} from "@/types/lifecycle";

export interface LifecycleWorkspaceView {
  spec: string;
  githubRepo?: string | null;
  orchestrationMode: LifecycleOrchestrationMode;
  governanceMode?: LifecycleGovernanceMode;
  autonomyLevel: LifecycleAutonomyLevel;
  decisionContext?: LifecycleDecisionContext | null;
  productIdentity: LifecycleProductIdentity;
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
  deliveryPlan?: LifecycleDeliveryPlan | null;
  valueContract?: LifecycleValueContract | null;
  outcomeTelemetryContract?: LifecycleOutcomeTelemetryContract | null;
  developmentHandoff?: LifecycleDevelopmentHandoff | null;
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
  requirements?: RequirementsBundle | null;
  requirementsConfig?: { earsEnabled: boolean; interactiveClarification: boolean; confidenceFloor: number };
  reverseEngineering?: ReverseEngineeringResult | null;
  taskDecomposition?: TaskDecomposition | null;
  dcsAnalysis?: DCSAnalysis | null;
  technicalDesign?: TechnicalDesignBundle | null;
  isHydrating: boolean;
}

export interface LifecycleActions {
  editSpec: (s: string) => void;
  selectGovernanceMode: (mode: LifecycleGovernanceMode) => void;
  updateProductIdentity: (identity: LifecycleProductIdentity) => void;
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
