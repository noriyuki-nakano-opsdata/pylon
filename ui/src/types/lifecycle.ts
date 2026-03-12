/* ── Product Lifecycle Types ── */

export type LifecyclePhase =
  | "research"
  | "planning"
  | "design"
  | "approval"
  | "development"
  | "deploy"
  | "iterate";

export type LifecycleOrchestrationMode = "workflow" | "guided" | "autonomous";
export type LifecycleAutonomyLevel = "A3" | "A4";
export type LifecycleResearchDepth = "quick" | "standard" | "deep";

export interface PhaseStatus {
  phase: LifecyclePhase;
  status: "locked" | "available" | "in_progress" | "review" | "completed";
  completedAt?: string;
  version: number;
}

export interface LifecycleAgentBlueprint {
  id: string;
  label: string;
  role: string;
  autonomy: string;
  tools: string[];
  skills: string[];
}

export interface LifecycleArtifactDescriptor {
  id: string;
  phase: LifecyclePhase;
  title: string;
}

export interface LifecycleQualityGate {
  id: string;
  title: string;
}

export interface PhaseBlueprint {
  phase: LifecyclePhase;
  title: string;
  summary: string;
  team: LifecycleAgentBlueprint[];
  artifacts: LifecycleArtifactDescriptor[];
  quality_gates: LifecycleQualityGate[];
}

export interface LifecycleResearchConfig {
  competitorUrls: string[];
  depth: LifecycleResearchDepth;
  outputLanguage?: string;
}

export interface ApprovalComment {
  id: string;
  text: string;
  type: "comment" | "approve" | "reject";
  time: string;
}

export interface DeployCheck {
  id: string;
  label: string;
  status: "pass" | "warning" | "fail";
  detail: string;
}

export interface ReleaseRecord {
  id: string;
  createdAt: string;
  version: string;
  note: string;
  selectedDesignId?: string;
  artifactBytes: number;
  qualitySummary: {
    overallScore: number;
    releaseReady: boolean;
    passed: number;
    warnings: number;
    failed: number;
  };
}

export interface FeedbackItem {
  id: string;
  type: "bug" | "feature" | "improvement" | "praise";
  text: string;
  impact: "low" | "medium" | "high";
  votes: number;
  createdAt?: string;
}

export interface LifecycleRecommendation {
  id: string;
  title: string;
  reason: string;
  priority: "medium" | "high" | "critical";
}

export interface LifecycleArtifact {
  id: string;
  phase: LifecyclePhase;
  kind: string;
  title: string;
  summary: string;
  createdAt: string;
  runId?: string;
  nodeId?: string;
  producer?: string;
  skillIds: string[];
  payload: Record<string, unknown>;
}

export interface LifecycleDecision {
  id: string;
  phase: LifecyclePhase;
  kind: string;
  title: string;
  rationale: string;
  status: string;
  createdAt: string;
  runId?: string;
  details: Record<string, unknown>;
}

export interface LifecycleSkillInvocation {
  id: string;
  phase: LifecyclePhase;
  agentId: string;
  agentLabel: string;
  skill: string;
  status: string;
  mode: "local" | "a2a";
  provider: string;
  toolIds: string[];
  outputArtifactIds: string[];
  delegatedTo?: string;
  createdAt: string;
  summary: string;
}

export interface LifecycleDelegation {
  id: string;
  phase: LifecyclePhase;
  agentId: string;
  peer: string;
  peerCard: Record<string, unknown>;
  skill: string;
  status: string;
  runId: string;
  createdAt: string;
  task: Record<string, unknown>;
}

export interface LifecyclePhaseRun {
  id: string;
  runId: string;
  projectId: string;
  phase: LifecyclePhase;
  workflowId: string;
  status: string;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  artifactCount: number;
  decisionCount: number;
  costUsd: number;
  costMeasured?: boolean;
  totalTokens?: number;
  meteredTokens?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  reasoningTokens?: number;
  executionSummary: Record<string, unknown>;
}

export interface LifecycleNextAction {
  type: string;
  phase: LifecyclePhase | null;
  title: string;
  reason: string;
  canAutorun: boolean;
  requiresTrigger?: boolean;
  orchestrationMode?: LifecycleOrchestrationMode;
  payload: Record<string, unknown>;
}

export interface LifecycleAutonomyState {
  orchestrationMode: LifecycleOrchestrationMode;
  completedExecutablePhases: LifecyclePhase[];
  blockedPhases: Partial<Record<LifecyclePhase, string[]>>;
  approvalRequired: boolean;
  canAdvanceAutonomously: boolean;
}

/* ── Research ── */
export interface Competitor {
  name: string;
  url?: string;
  strengths: string[];
  weaknesses: string[];
  pricing: string;
  target: string;
}

export interface ResearchClaim {
  id: string;
  statement: string;
  owner: string;
  category: string;
  evidence_ids: string[];
  counterevidence_ids: string[];
  confidence: number;
  status: string;
}

export interface ResearchEvidence {
  id: string;
  source_ref: string;
  source_type: string;
  snippet: string;
  recency: string;
  relevance: string;
}

export interface ResearchDissent {
  id: string;
  claim_id: string;
  challenger: string;
  argument: string;
  severity: string;
  resolved: boolean;
  recommended_test?: string;
  resolution?: string;
}

export interface ConfidenceSummary {
  average: number;
  floor: number;
  accepted?: number;
  critical_findings?: number;
}

export interface ResearchNodeResult {
  nodeId: string;
  status: "success" | "degraded" | "failed";
  parseStatus: "strict" | "repaired" | "fallback" | "failed";
  degradationReasons: string[];
  sourceClassesSatisfied: string[];
  missingSourceClasses: string[];
  artifact: Record<string, unknown>;
  rawPreview?: string;
  llmModel?: string;
  llmProvider?: string;
  retryCount: number;
}

export interface ResearchQualityGateResult {
  id: string;
  title: string;
  passed: boolean;
  reason: string;
  blockingNodeIds: string[];
}

export interface ResearchRemediationPlan {
  objective: string;
  retryNodeIds: string[];
  maxIterations: number;
}

export interface ResearchAutonomousRemediation {
  status: "not_needed" | "queued" | "retrying" | "resolved" | "blocked";
  attemptCount: number;
  maxAttempts: number;
  remainingAttempts: number;
  autoRunnable?: boolean;
  objective: string;
  retryNodeIds: string[];
  blockingGateIds: string[];
  blockingNodeIds?: string[];
  missingSourceClasses?: string[];
  blockingSummary?: string[];
  stopReason?: string;
}

export interface MarketResearch {
  competitors: Competitor[];
  market_size: string;
  trends: string[];
  opportunities: string[];
  threats: string[];
  tech_feasibility: { score: number; notes: string };
  user_research?: {
    signals: string[];
    pain_points: string[];
    segment: string;
  };
  claims?: ResearchClaim[];
  evidence?: ResearchEvidence[];
  dissent?: ResearchDissent[];
  open_questions?: string[];
  winning_theses?: string[];
  source_links?: string[];
  confidence_summary?: ConfidenceSummary;
  judge_summary?: string;
  model_assignments?: Record<string, string>;
  low_diversity_mode?: boolean;
  critical_dissent_count?: number;
  resolved_dissent_count?: number;
  node_results?: ResearchNodeResult[];
  quality_gates?: ResearchQualityGateResult[];
  readiness?: "ready" | "rework" | "failed";
  remediation_plan?: ResearchRemediationPlan;
  autonomous_remediation?: ResearchAutonomousRemediation;
  execution_trace?: Array<Record<string, unknown>>;
  canonical?: Record<string, unknown>;
  localized?: Record<string, unknown>;
  display_language?: string;
  localization_status?: string;
}

/* ── Planning (Analysis) ── */
export interface Persona {
  name: string;
  role: string;
  age_range: string;
  goals: string[];
  frustrations: string[];
  tech_proficiency: string;
  context: string;
}

export interface UserStory {
  role: string;
  action: string;
  benefit: string;
  acceptance_criteria: string[];
  priority: "must" | "should" | "could" | "wont";
}

export interface KanoFeature {
  feature: string;
  category: "must-be" | "one-dimensional" | "attractive" | "indifferent" | "reverse";
  user_delight: number;
  implementation_cost: "low" | "medium" | "high";
  rationale: string;
}

/* ── User Journey ── */
export type JourneyPhase = "awareness" | "consideration" | "acquisition" | "usage" | "advocacy";
export interface JourneyTouchpoint {
  phase: JourneyPhase;
  persona: string;
  action: string;
  touchpoint: string;
  emotion: "positive" | "neutral" | "negative";
  pain_point?: string;
  opportunity?: string;
}
export interface UserJourneyMap {
  persona_name: string;
  touchpoints: JourneyTouchpoint[];
}

/* ── JTBD / Job Stories ── */
export interface JobStory {
  situation: string;   // "When..."
  motivation: string;  // "I want to..."
  outcome: string;     // "So I can..."
  priority: "core" | "supporting" | "aspirational";
  related_features: string[];
}

/* ── IA (Information Architecture) ── */
export interface IANode {
  id: string;
  label: string;
  description?: string;
  children?: IANode[];
  priority: "primary" | "secondary" | "utility";
}
export interface IAAnalysis {
  site_map: IANode[];
  navigation_model: "hierarchical" | "flat" | "hub-and-spoke" | "matrix";
  key_paths: { name: string; steps: string[] }[];
}

/* ── Actor & Role Analysis ── */
export interface Actor {
  name: string;
  type: "primary" | "secondary" | "external_system";
  description: string;
  goals: string[];
  interactions: string[];
}

export interface Role {
  name: string;
  responsibilities: string[];
  permissions: string[];
  related_actors: string[];
}

/* ── Use Cases ── */
export interface UseCase {
  id: string;
  title: string;
  actor: string;
  category: string;
  sub_category: string;
  preconditions: string[];
  main_flow: string[];
  alternative_flows?: { condition: string; steps: string[] }[];
  postconditions: string[];
  priority: "must" | "should" | "could";
  related_stories?: string[];
}

/* ── Recommended Milestones ── */
export interface RecommendedMilestone {
  id: string;
  name: string;
  criteria: string;
  rationale: string;
  phase: "alpha" | "beta" | "release";
  depends_on_use_cases?: string[];
}

export interface FeatureDecision {
  feature: string;
  selected: boolean;
  supporting_claim_ids: string[];
  counterarguments: string[];
  rejection_reason: string;
  uncertainty: number;
}

export interface RejectedFeature {
  feature: string;
  reason: string;
  counterarguments: string[];
}

export interface PlanningAssumption {
  id: string;
  statement: string;
  severity: string;
}

export interface RedTeamFinding {
  id: string;
  title: string;
  challenger: string;
  severity: string;
  impact: string;
  recommendation: string;
  related_feature?: string;
}

export interface NegativePersona {
  id: string;
  name: string;
  scenario: string;
  risk: string;
  mitigation: string;
}

export interface TraceabilityLink {
  claim_id: string;
  claim: string;
  use_case_id: string;
  use_case: string;
  feature: string;
  milestone_id: string;
  milestone: string;
  confidence: number;
}

export interface KillCriterion {
  id: string;
  milestone_id: string;
  condition: string;
  rationale: string;
}

export interface AnalysisResult {
  personas: Persona[];
  user_stories: UserStory[];
  kano_features: KanoFeature[];
  recommendations: string[];
  business_model?: {
    value_propositions: string[];
    customer_segments: string[];
    channels: string[];
    revenue_streams: string[];
  };
  user_journeys?: UserJourneyMap[];
  job_stories?: JobStory[];
  ia_analysis?: IAAnalysis;
  actors?: Actor[];
  roles?: Role[];
  use_cases?: UseCase[];
  recommended_milestones?: RecommendedMilestone[];
  design_tokens?: DesignTokenAnalysis;
  feature_decisions?: FeatureDecision[];
  rejected_features?: RejectedFeature[];
  assumptions?: PlanningAssumption[];
  red_team_findings?: RedTeamFinding[];
  negative_personas?: NegativePersona[];
  traceability?: TraceabilityLink[];
  kill_criteria?: KillCriterion[];
  confidence_summary?: ConfidenceSummary;
  judge_summary?: string;
  model_assignments?: Record<string, string>;
  low_diversity_mode?: boolean;
}

/* ── Design Tokens (generated from persona/KANO analysis) ── */
export interface DesignTokenAnalysis {
  style: {
    name: string;
    keywords: string[];
    best_for: string;
    performance: string;
    accessibility: string;
  };
  colors: {
    primary: string;
    secondary: string;
    cta: string;
    background: string;
    text: string;
    notes: string;
  };
  typography: {
    heading: string;
    body: string;
    mood: string[];
    google_fonts_url?: string;
  };
  effects: string[];
  anti_patterns: string[];
  rationale: string;
}

/* ── Design ── */
export interface PrototypeModule {
  name: string;
  type: string;
  items: string[];
}

export interface PrototypeScreen {
  id: string;
  title: string;
  purpose: string;
  layout: string;
  headline: string;
  supporting_text: string;
  primary_actions: string[];
  modules: PrototypeModule[];
  success_state: string;
}

export interface PrototypeFlow {
  id: string;
  name: string;
  steps: string[];
  goal: string;
}

export interface PrototypeAppShell {
  layout: string;
  density: string;
  primary_navigation: Array<{
    id: string;
    label: string;
    priority: string;
  }>;
  status_badges: string[];
}

export interface PrototypeBlueprint {
  kind: string;
  app_shell: PrototypeAppShell;
  screens: PrototypeScreen[];
  flows: PrototypeFlow[];
  interaction_principles: string[];
  design_anchor?: {
    pattern_name?: string;
    description?: string;
    style_name?: string;
  };
}

export interface DesignVariant {
  id: string;
  model: string;
  pattern_name: string;
  description: string;
  preview_html: string;
  primary_color?: string;
  accent_color?: string;
  quality_focus?: string[];
  prototype?: PrototypeBlueprint;
  tokens: { in: number; out: number };
  cost_usd: number;
  scores: {
    ux_quality: number;
    code_quality: number;
    performance: number;
    accessibility: number;
  };
}

/* ── Epic / WBS / Gantt ── */
export type PlanPreset = "minimal" | "standard" | "full";

export interface Epic {
  id: string;
  name: string;
  description: string;
  use_cases: string[];
  priority: "must" | "should" | "could";
  stories: string[];              // UserStory references by index
}

export interface WbsItem {
  id: string;
  epic_id: string;
  title: string;
  description: string;
  assignee_type: "agent" | "human";
  assignee: string;               // agent name or role
  skills: string[];               // skill IDs used
  depends_on: string[];           // other WbsItem ids
  effort_hours: number;
  start_day: number;              // relative day offset from project start
  duration_days: number;
  status: "pending" | "in_progress" | "done";
}

export interface PlanEstimate {
  preset: PlanPreset;
  label: string;
  description: string;
  total_effort_hours: number;
  total_cost_usd: number;
  duration_weeks: number;
  epics: Epic[];
  wbs: WbsItem[];
  agents_used: string[];
  skills_used: string[];
}

/* ── Feature Selection ── */
export interface FeatureSelection {
  feature: string;
  category: string;
  selected: boolean;
  priority: "must" | "should" | "could" | "wont";
  user_delight: number;
  implementation_cost: string;
  rationale: string;
}

/* ── Milestones ── */
export interface Milestone {
  id: string;
  name: string;
  criteria: string;
  status: "pending" | "satisfied" | "not_satisfied";
  reason?: string;
}

/* ── Build Progress ── */
export interface MilestoneResult {
  id: string;
  name: string;
  status: "satisfied" | "not_satisfied";
  reason?: string;
}

export interface BuildProgress {
  iteration: number;
  maxIterations: number;
  milestoneResults: MilestoneResult[];
  qualityScore: number;
  costUsd: number;
  agentActivity: { agent: string; status: "idle" | "working" | "done" }[];
}

export interface WorkflowRunLiveSnapshot {
  id: string;
  status: string;
  startedAt: string;
  completedAt: string | null;
  error?: string;
}

export interface WorkflowRunLiveEvent {
  seq: number | null;
  timestamp?: string;
  nodeId: string;
  agent?: string;
  status: "running" | "completed" | "failed" | "pending";
  summary: string;
}

export interface WorkflowRunLiveTelemetry {
  run: WorkflowRunLiveSnapshot | null;
  phase?: LifecyclePhase | null;
  eventCount: number;
  completedNodeCount: number;
  runningNodeIds: string[];
  failedNodeIds: string[];
  lastEventSeq: number | null;
  activeFocusNodeId?: string;
  lastNodeId?: string;
  lastAgent?: string;
  recentNodeIds: string[];
  recentEvents: WorkflowRunLiveEvent[];
}

export interface LifecyclePhaseRuntimeSummary {
  phase: LifecyclePhase;
  status: string;
  objective?: string;
  blockingSummary: string[];
  readiness?: "ready" | "rework" | "failed";
  failedGateCount?: number;
  degradedNodeCount?: number;
  attemptCount?: number;
  maxAttempts?: number;
  canAutorun?: boolean;
  nextAutomaticAction?: string;
  agents?: LifecyclePhaseRuntimeAgent[];
  recentActions?: LifecyclePhaseRuntimeAction[];
}

export interface LifecyclePhaseRuntimeAgent {
  agentId: string;
  label: string;
  role: string;
  status: "idle" | "running" | "completed" | "failed";
  currentTask: string;
  delegatedTo?: string;
  lastArtifactTitle?: string;
}

export interface LifecyclePhaseRuntimeAction {
  nodeId: string;
  label: string;
  status: string;
  summary: string;
  agent?: string;
  agentLabel?: string;
  nodeLabel?: string;
}

/* ── Project Data (persisted per lifecycle) ── */
export interface LifecycleProject {
  id: string;
  projectId: string;
  tenant_id?: string;
  name?: string;
  description?: string;
  githubRepo?: string | null;
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  research?: MarketResearch;
  analysis?: AnalysisResult;
  features: FeatureSelection[];
  milestones: Milestone[];
  designVariants: DesignVariant[];
  selectedDesignId?: string;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  approvalComments: ApprovalComment[];
  buildCode?: string;
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
  blueprints?: Record<LifecyclePhase, PhaseBlueprint>;
  nextAction?: LifecycleNextAction;
  autonomyState?: LifecycleAutonomyState;
  createdAt: string;
  updatedAt: string;
  savedAt: string;
}
