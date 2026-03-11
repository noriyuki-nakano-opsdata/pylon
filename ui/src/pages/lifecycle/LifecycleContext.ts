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
} from "@/types/lifecycle";

export interface LifecycleState {
  spec: string;
  setSpec: (s: string) => void;
  orchestrationMode: LifecycleOrchestrationMode;
  setOrchestrationMode: (mode: LifecycleOrchestrationMode) => void;
  autonomyLevel: LifecycleAutonomyLevel;
  setAutonomyLevel: (level: LifecycleAutonomyLevel) => void;
  researchConfig: LifecycleResearchConfig;
  setResearchConfig: (config: LifecycleResearchConfig) => void;
  research: MarketResearch | null;
  setResearch: (r: MarketResearch | null) => void;
  analysis: AnalysisResult | null;
  setAnalysis: (a: AnalysisResult | null) => void;
  features: FeatureSelection[];
  setFeatures: (f: FeatureSelection[]) => void;
  milestones: Milestone[];
  setMilestones: (m: Milestone[]) => void;
  designVariants: DesignVariant[];
  setDesignVariants: (v: DesignVariant[]) => void;
  selectedDesignId: string | null;
  setSelectedDesignId: (id: string | null) => void;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  setApprovalStatus: (s: "pending" | "approved" | "rejected" | "revision_requested") => void;
  approvalComments: ApprovalComment[];
  setApprovalComments: (c: ApprovalComment[]) => void;
  buildCode: string | null;
  setBuildCode: (c: string | null) => void;
  buildCost: number;
  setBuildCost: (c: number) => void;
  buildIteration: number;
  setBuildIteration: (i: number) => void;
  milestoneResults: MilestoneResult[];
  setMilestoneResults: (r: MilestoneResult[]) => void;
  planEstimates: PlanEstimate[];
  setPlanEstimates: (e: PlanEstimate[]) => void;
  selectedPreset: PlanPreset;
  setSelectedPreset: (p: PlanPreset) => void;
  phaseStatuses: PhaseStatus[];
  setPhaseStatuses: (s: PhaseStatus[]) => void;
  deployChecks: DeployCheck[];
  setDeployChecks: (c: DeployCheck[]) => void;
  releases: ReleaseRecord[];
  setReleases: (r: ReleaseRecord[]) => void;
  feedbackItems: FeedbackItem[];
  setFeedbackItems: (f: FeedbackItem[]) => void;
  recommendations: LifecycleRecommendation[];
  setRecommendations: (r: LifecycleRecommendation[]) => void;
  artifacts: LifecycleArtifact[];
  decisionLog: LifecycleDecision[];
  skillInvocations: LifecycleSkillInvocation[];
  delegations: LifecycleDelegation[];
  phaseRuns: LifecyclePhaseRun[];
  nextAction: LifecycleNextAction | null;
  autonomyState: LifecycleAutonomyState | null;
  blueprints: Record<LifecyclePhase, PhaseBlueprint>;
  isHydrating: boolean;
  applyProject: (project: LifecycleProject) => void;
  advancePhase: (phase: LifecyclePhase) => void;
  completePhase: (phase: LifecyclePhase) => void;
}

export const LifecycleContext = createContext<LifecycleState | null>(null);

export function useLifecycle() {
  const ctx = useContext(LifecycleContext);
  if (!ctx) throw new Error("useLifecycle must be used within LifecycleLayout");
  return ctx;
}
