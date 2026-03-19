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
export type LifecycleGovernanceMode = "governed" | "complete_autonomy";
export type LifecycleAutonomyLevel = "A3" | "A4";
export type LifecycleResearchDepth = "quick" | "standard" | "deep";
export type LifecycleResearchRecoveryMode = "auto" | "deepen_evidence" | "reframe_research";

export interface LifecycleProductIdentity {
  companyName: string;
  productName: string;
  officialWebsite?: string;
  officialDomains: string[];
  aliases: string[];
  excludedEntityNames: string[];
}

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
  recoveryMode?: LifecycleResearchRecoveryMode;
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

export interface LifecycleValueMetric {
  id: string;
  name: string;
  signal: string;
  target: string;
  source: string;
  leading_indicator?: string;
}

export interface LifecycleValueContract {
  id: string;
  schema_version: number;
  summary: string;
  primary_personas: Array<{
    name: string;
    role?: string;
    context?: string;
    goals?: string[];
    frustrations?: string[];
  }>;
  selected_features: Array<{
    id: string;
    name: string;
    priority?: string;
    category?: string;
    rationale?: string;
  }>;
  required_use_cases: Array<{
    id: string;
    title: string;
    priority?: string;
    actor?: string;
    summary?: string;
    feature_names?: string[];
    milestone_names?: string[];
  }>;
  job_stories: Array<{
    id: string;
    title: string;
    situation?: string;
    motivation?: string;
    outcome?: string;
    priority?: string;
    related_features?: string[];
  }>;
  user_journeys: Array<{
    id: string;
    persona_name: string;
    critical_touchpoints: Array<{
      phase?: string;
      action?: string;
      touchpoint?: string;
      emotion?: string;
      pain_point?: string;
      opportunity?: string;
    }>;
    failure_moments?: string[];
  }>;
  kano_focus?: {
    must_be?: string[];
    performance?: string[];
    attractive?: string[];
  };
  information_architecture?: {
    navigation_model?: string;
    top_level_nodes?: Array<{
      id: string;
      label: string;
      priority?: string;
      description?: string;
    }>;
    key_paths?: Array<{ name: string; steps: string[] }>;
    top_tasks?: string[];
  };
  success_metrics: LifecycleValueMetric[];
  kill_criteria?: string[];
  release_readiness_signals?: string[];
  decision_context_fingerprint?: string;
}

export interface LifecycleOutcomeTelemetryContract {
  id: string;
  schema_version: number;
  summary: string;
  success_metrics: LifecycleValueMetric[];
  kill_criteria: string[];
  telemetry_events: Array<{
    id: string;
    name: string;
    purpose?: string;
    properties?: string[];
    success_metric_ids?: string[];
  }>;
  workspace_artifacts?: string[];
  release_checks?: Array<{
    id: string;
    title: string;
    detail?: string;
  }>;
  instrumentation_requirements?: string[];
  experiment_questions?: string[];
  decision_context_fingerprint?: string;
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
  governanceMode?: LifecycleGovernanceMode;
  requiresHumanDecision?: boolean;
  payload: Record<string, unknown>;
}

export interface LifecycleHumanDecision {
  phase: LifecyclePhase;
  decisionId: string;
  title: string;
  reason: string;
  availableDecisions: string[];
  required: boolean;
  blockingIssues?: string[];
  reviewTriggers?: string[];
}

export interface LifecyclePhaseGovernancePolicy {
  phase: LifecyclePhase;
  executionPolicy: string;
  humanDecisionGates: string[];
  optionalHumanDecisions: string[];
  humanReviewTriggers: string[];
  allowHumanEdits: boolean;
  allowHumanOverride: boolean;
  allowReentry: boolean;
  continuousDeliveryMode: string;
  summary: string;
}

export interface LifecycleAutonomyState {
  orchestrationMode: LifecycleOrchestrationMode;
  governanceMode?: LifecycleGovernanceMode;
  completedExecutablePhases: LifecyclePhase[];
  blockedPhases: Partial<Record<LifecyclePhase, string[]>>;
  approvalRequired: boolean;
  humanDecisionRequired?: boolean;
  requiredHumanDecisions?: LifecycleHumanDecision[];
  phasePolicies?: Partial<Record<LifecyclePhase, LifecyclePhaseGovernancePolicy>>;
  humanOverrideAlwaysAllowed?: boolean;
  continuousDeliveryMode?: string;
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
  recoveryMode?: LifecycleResearchRecoveryMode;
  recommendedOperatorAction?: "wait_for_autonomous_recovery" | "deepen_evidence" | "reframe_research" | "conditional_handoff" | "clarify_scope" | "advance_to_planning";
  conditionalHandoffAllowed?: boolean;
  strategySummary?: string;
  strategyChecklist?: string[];
  planningGuardrails?: string[];
  followUpQuestion?: string;
  stalledSignature?: boolean;
  confidenceFloor?: number;
  targetConfidenceFloor?: number;
  stopReason?: string;
}

export interface ResearchOperatorDecision {
  mode: "conditional_handoff";
  selectedAt: string;
  rationale?: string;
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

export interface PlanningCoveragePresetBreakdown {
  preset: PlanPreset;
  epic_count: number;
  wbs_count: number;
  total_effort_hours: number;
}

export interface PlanningCoverageSummary {
  selected_feature_count: number;
  job_story_count: number;
  use_case_count: number;
  actor_count: number;
  role_count: number;
  traceability_count: number;
  milestone_count: number;
  uncovered_features: string[];
  use_cases_without_milestone: string[];
  use_cases_without_traceability: string[];
  preset_breakdown: PlanningCoveragePresetBreakdown[];
}

export interface PlanningOperatorCopyCouncilCard {
  id: string;
  agent: string;
  lens: string;
  title: string;
  summary: string;
  action_label: string;
  target_tab?: string;
  target_section?: "risk" | "recommendation";
  tone?: string;
}

export interface PlanningOperatorCopyHandoffBrief {
  headline: string;
  summary: string;
  bullets: string[];
}

export interface PlanningOperatorCopy {
  council_cards?: PlanningOperatorCopyCouncilCard[];
  handoff_brief?: PlanningOperatorCopyHandoffBrief;
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
  coverage_summary?: PlanningCoverageSummary;
  confidence_summary?: ConfidenceSummary;
  judge_summary?: string;
  operator_copy?: PlanningOperatorCopy;
  model_assignments?: Record<string, string>;
  low_diversity_mode?: boolean;
  canonical?: Record<string, unknown>;
  localized?: Record<string, unknown>;
  display_language?: string;
  localization_status?: string;
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

export interface PrototypeSpecRoute {
  id: string;
  screen_id: string;
  path: string;
  segment: string;
  title: string;
  headline: string;
  layout: string;
  primary_actions: string[];
  states: string[];
}

export interface PrototypeSpecComponent {
  id: string;
  screen_id: string;
  kind: string;
  title: string;
  purpose: string;
  data_keys: string[];
}

export interface PrototypeSpecState {
  state: string;
  trigger: string;
  summary: string;
}

export interface PrototypeSpec {
  schema_version: string;
  framework_target: string;
  title: string;
  subtitle: string;
  shell: {
    kind: string;
    layout: string;
    density: string;
    status_badges: string[];
    primary_navigation: Array<{
      id: string;
      label: string;
      priority: string;
    }>;
  };
  theme: {
    primary: string;
    accent: string;
    background: string;
    surface: string;
    text: string;
    heading_font: string;
    body_font: string;
  };
  selected_features: string[];
  screens: PrototypeScreen[];
  routes: PrototypeSpecRoute[];
  components: PrototypeSpecComponent[];
  mock_data: Record<string, unknown>;
  state_matrix: Record<string, PrototypeSpecState[]>;
  interaction_map: Array<{
    screen_id: string;
    action: string;
    result: string;
  }>;
  acceptance_flows: PrototypeFlow[];
  quality_targets: string[];
  decision_scope?: DesignDecisionScope;
}

export interface PrototypeAppFile {
  path: string;
  kind: string;
  content: string;
}

export interface PrototypeAppArtifact {
  artifact_kind: string;
  framework: string;
  router: string;
  entry_routes: string[];
  dependencies: Record<string, string>;
  dev_dependencies: Record<string, string>;
  install_command: string;
  dev_command: string;
  build_command: string;
  mock_api: string[];
  files: PrototypeAppFile[];
  artifact_summary?: {
    screen_count: number;
    route_count: number;
    file_count: number;
  };
}

export interface DesignDecisionScope {
  phase?: string;
  fingerprint?: string;
  lead_thesis?: string;
  thesis_ids?: string[];
  risk_ids?: string[];
  primary_use_case_ids?: string[];
  selected_features?: string[];
  milestone_ids?: string[];
  selected_design_id?: string;
  selected_design_name?: string;
}

export interface DesignNarrative {
  experience_thesis: string;
  operational_bet: string;
  signature_moments: string[];
  handoff_note: string;
}

export interface DesignTechnicalChoice {
  area: string;
  decision: string;
  rationale: string;
}

export interface DesignAgentLane {
  role: string;
  remit: string;
  skills: string[];
}

export interface DesignImplementationBrief {
  architecture_thesis: string;
  system_shape: string[];
  technical_choices: DesignTechnicalChoice[];
  agent_lanes: DesignAgentLane[];
  delivery_slices: string[];
}

export interface DesignScorecardDimension {
  id: string;
  label: string;
  score: number;
  evidence: string;
}

export interface DesignScorecard {
  overall_score: number;
  summary: string;
  dimensions: DesignScorecardDimension[];
}

export interface DesignSelectionRationale {
  summary: string;
  reasons: string[];
  tradeoffs: string[];
  approval_focus: string[];
  confidence: number;
  verdict: "selected" | "candidate";
}

export interface DesignApprovalPacket {
  operator_promise: string;
  must_keep: string[];
  guardrails: string[];
  review_checklist: string[];
  handoff_summary: string;
}

export interface DesignWorkflowSummary {
  id: string;
  name: string;
  goal: string;
  steps: string[];
}

export interface DesignScreenSpec {
  id: string;
  title: string;
  purpose: string;
  layout: string;
  primary_actions: string[];
  module_count: number;
  route_path?: string;
}

export interface DesignArtifactCompleteness {
  score: number;
  status: "complete" | "partial" | "incomplete";
  present: string[];
  missing: string[];
  screen_count: number;
  workflow_count: number;
  route_count: number;
}

export interface DesignFreshness {
  status: "fresh" | "stale" | "unknown";
  can_handoff: boolean;
  current_fingerprint?: string;
  variant_fingerprint?: string;
  reasons: string[];
}

export interface DesignPreviewMeta {
  source: string;
  extraction_ok: boolean;
  validation_ok: boolean;
  fallback_reason?: string;
  html_size: number;
  screen_count_estimate: number;
  interactive_features: string[];
  validation_issues: string[];
  copy_issues?: string[];
  copy_issue_examples?: string[];
  copy_quality_score?: number;
}

export interface DesignVariant {
  id: string;
  model: string;
  pattern_name: string;
  description: string;
  preview_html: string;
  primary_color?: string;
  accent_color?: string;
  prototype_spec?: PrototypeSpec;
  prototype_app?: PrototypeAppArtifact;
  quality_focus?: string[];
  prototype?: PrototypeBlueprint;
  rationale?: string;
  provider_note?: string;
  decision_scope?: DesignDecisionScope;
  narrative?: DesignNarrative;
  implementation_brief?: DesignImplementationBrief;
  scorecard?: DesignScorecard;
  selection_rationale?: DesignSelectionRationale;
  approval_packet?: DesignApprovalPacket;
  primary_workflows?: DesignWorkflowSummary[];
  screen_specs?: DesignScreenSpec[];
  artifact_completeness?: DesignArtifactCompleteness;
  freshness?: DesignFreshness;
  preview_meta?: DesignPreviewMeta;
  decision_context_fingerprint?: string;
  canonical?: Record<string, unknown>;
  localized?: Record<string, unknown>;
  display_language?: string;
  localization_status?: string;
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

export interface DevelopmentWorkPackage {
  id: string;
  title: string;
  lane: string;
  summary: string;
  depends_on: string[];
  start_day: number;
  duration_days: number;
  deliverables: string[];
  acceptance_criteria: string[];
  owned_surfaces: string[];
  source_epic?: string | null;
  status: "planned" | "in_progress" | "completed" | "blocked";
  is_critical?: boolean;
}

export interface DevelopmentLanePlan {
  agent: string;
  label: string;
  remit: string;
  skills: string[];
  owned_surfaces: string[];
  conflict_guards: string[];
  merge_order: number;
}

export interface DevelopmentWavePlan {
  wave_index: number;
  work_unit_ids: string[];
  lane_ids: string[];
  entry_criteria?: string[];
  exit_criteria?: string[];
}

export interface DevelopmentWorkUnitContract {
  id: string;
  work_package_id: string;
  title: string;
  lane: string;
  wave_index: number;
  depends_on: string[];
  acceptance_criteria: string[];
  qa_checks: string[];
  security_checks: string[];
  required_contracts?: string[];
  value_targets?: string[];
  telemetry_events?: string[];
  repair_policy?: Record<string, string>;
}

export interface DevelopmentGanttSegment {
  work_package_id: string;
  lane: string;
  start_day: number;
  duration_days: number;
  depends_on: string[];
  is_critical: boolean;
}

export interface DevelopmentMergeStrategy {
  integration_order: string[];
  conflict_prevention: string[];
  shared_touchpoints: string[];
}

export interface DevelopmentSpecGap {
  id: string;
  title: string;
  severity: string;
  detail: string;
  closing_action: string;
}

export interface DevelopmentFeatureCoverage {
  feature: string;
  requirement_covered: boolean;
  task_covered: boolean;
  api_covered: boolean;
  route_covered: boolean;
}

export interface DevelopmentSpecAudit {
  status: string;
  completeness_score: number;
  requirements_count: number;
  task_count: number;
  api_surface_count: number;
  database_table_count: number;
  interface_count: number;
  route_binding_count: number;
  workspace_file_count: number;
  behavior_gate_count: number;
  feature_coverage: DevelopmentFeatureCoverage[];
  unresolved_gaps: DevelopmentSpecGap[];
  closing_actions: string[];
}

export interface DevelopmentWorkspacePackage {
  id: string;
  label: string;
  path: string;
  lane: string;
  kind: string;
  file_count: number;
}

export interface DevelopmentWorkspaceFile {
  path: string;
  kind: string;
  package_id: string;
  package_label: string;
  package_path: string;
  lane: string;
  route_paths: string[];
  entrypoint: boolean;
  generated_from: string;
  line_count: number;
  content_preview: string;
  content: string;
}

export interface DevelopmentWorkspaceRouteBinding {
  route_path: string;
  screen_id?: string | null;
  file_paths: string[];
}

export interface DevelopmentCodeWorkspace {
  framework: string;
  router: string;
  preview_entry: string;
  entrypoints: string[];
  install_command: string;
  dev_command: string;
  build_command: string;
  package_tree: DevelopmentWorkspacePackage[];
  files: DevelopmentWorkspaceFile[];
  package_graph: Array<{ source: string; target: string; reason: string }>;
  route_bindings: DevelopmentWorkspaceRouteBinding[];
  artifact_summary?: {
    package_count: number;
    file_count: number;
    route_binding_count: number;
    entrypoint_count: number;
  };
}

export interface DevelopmentRepoCommandResult {
  status: string;
  command: string;
  exit_code: number | null;
  duration_ms: number;
  stdout_tail: string;
  stderr_tail: string;
}

export interface DevelopmentRepoExecution {
  mode: string;
  workspace_path: string;
  worktree_path?: string | null;
  repo_root?: string | null;
  materialized_file_count: number;
  install: DevelopmentRepoCommandResult;
  build: DevelopmentRepoCommandResult;
  test: DevelopmentRepoCommandResult;
  ready: boolean;
  errors: string[];
}

export interface LifecycleDeliveryPlan {
  execution_mode: string;
  topology_mode?: string;
  summary: string;
  selected_preset?: string;
  source_plan_preset?: string;
  success_definition?: string;
  work_packages: DevelopmentWorkPackage[];
  lanes: DevelopmentLanePlan[];
  waves?: DevelopmentWavePlan[];
  wave_count?: number;
  work_unit_contracts?: DevelopmentWorkUnitContract[];
  critical_path: string[];
  gantt: DevelopmentGanttSegment[];
  merge_strategy: DevelopmentMergeStrategy;
  shift_left_plan?: Record<string, unknown>;
  runtime_graph?: Record<string, unknown>;
  goal_spec?: Record<string, unknown>;
  dependency_analysis?: Record<string, unknown>;
  spec_audit?: DevelopmentSpecAudit;
  code_workspace?: DevelopmentCodeWorkspace;
  repo_execution?: DevelopmentRepoExecution;
  decision_context_fingerprint?: string;
  topology_fingerprint?: string;
  runtime_graph_fingerprint?: string;
  value_contract?: LifecycleValueContract | null;
  outcome_telemetry_contract?: LifecycleOutcomeTelemetryContract | null;
}

export interface EvidenceItem {
  category: string;
  label: string;
  value: string | number;
  unit: string;
}

export interface ChecklistItem {
  id: string;
  label: string;
  category: string;
  required: boolean;
}

export interface BlockingIssue {
  id: string;
  severity: "critical" | "major";
  description: string;
  source_phase: string;
}

export interface ReviewFocusItem {
  area: string;
  description: string;
  priority: "high" | "medium" | "low";
}

export interface LifecycleDevelopmentHandoff {
  readiness_status: string;
  release_candidate: string;
  operator_summary: string;
  deploy_checklist: ChecklistItem[];
  evidence: EvidenceItem[];
  blocking_issues: BlockingIssue[];
  review_focus: ReviewFocusItem[];
  topology_fingerprint?: string;
  runtime_graph_fingerprint?: string;
  wave_exit_ready?: boolean;
  ready_wave_count?: number;
  non_final_wave_count?: number;
  blocked_work_unit_ids?: string[];
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
  waveCount?: number;
  workUnitCount?: number;
  currentWaveIndex?: number | null;
  retryNodeIds?: string[];
  focusWorkUnitIds?: string[];
  executionWaves?: LifecycleDevelopmentExecutionWave[];
  workUnits?: LifecycleDevelopmentExecutionWorkUnit[];
  topologyFingerprint?: string | null;
  runtimeGraphFingerprint?: string | null;
  topologyFresh?: boolean;
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

export interface LifecycleDevelopmentExecutionWave {
  waveIndex: number;
  workUnitIds: string[];
  laneIds: string[];
  status: string;
  ready?: boolean;
  blockedWorkUnitIds: string[];
  activeNodeIds: string[];
  completedWorkUnitCount: number;
  workUnitCount: number;
}

export interface LifecycleDevelopmentExecutionWorkUnit {
  id: string;
  title: string;
  lane: string;
  waveIndex: number;
  status: string;
  builderStatus?: string | null;
  qaStatus?: string | null;
  securityStatus?: string | null;
  blockedBy?: string[];
  nodeId?: string | null;
}

export interface LifecycleDevelopmentExecutionSummary {
  decisionContextFingerprint?: string | null;
  topologyFingerprint?: string | null;
  runtimeGraphFingerprint?: string | null;
  topologyFresh?: boolean;
  topologyIssues?: string[];
  waveCount: number;
  workUnitCount: number;
  currentWaveIndex?: number | null;
  retryNodeIds?: string[];
  focusWorkUnitIds?: string[];
  blockedWorkUnitIds?: string[];
  waves: LifecycleDevelopmentExecutionWave[];
  workUnits: LifecycleDevelopmentExecutionWorkUnit[];
}

// --- Tsumiki Integration Types ---

export interface EARSRequirement {
  id: string;
  pattern: "ubiquitous" | "event-driven" | "unwanted" | "state-driven" | "optional" | "complex";
  statement: string;
  confidence: number;
  sourceClaimIds: string[];
  userStoryIds: string[];
  acceptanceCriteria: string[];
}

export interface RequirementsBundle {
  requirements: EARSRequirement[];
  userStories: { id: string; title: string; description: string }[];
  acceptanceCriteria: { id: string; requirementId: string; criterion: string }[];
  confidenceDistribution: { high: number; medium: number; low: number };
  completenessScore: number;
  traceabilityIndex: Record<string, string[]>;
}

export interface TaskItem {
  id: string;
  title: string;
  description: string;
  phase: string;
  milestoneId: string | null;
  dependsOn: string[];
  effortHours: number;
  priority: "must" | "should" | "could";
  featureId: string | null;
  requirementId: string | null;
}

export interface TaskDecomposition {
  tasks: TaskItem[];
  dagEdges: [string, string][];
  phaseMilestones: { phase: string; milestoneIds: string[]; taskCount: number; totalHours: number; durationDays: number }[];
  totalEffortHours: number;
  criticalPath: string[];
  effortByPhase: Record<string, number>;
  hasCycles: boolean;
}

export interface EdgeCase {
  id: string;
  scenario: string;
  severity: "critical" | "high" | "medium" | "low";
  mitigation: string;
  featureId: string;
}

export interface DCSAnalysis {
  rubberDuckPrd: {
    problemStatement: string;
    targetUsers: string[];
    successMetrics: Record<string, unknown>[];
    scopeBoundaries: { inScope: string[]; outOfScope: string[] };
    keyDecisions: Record<string, unknown>[];
  } | null;
  edgeCases: {
    edgeCases: EdgeCase[];
    riskMatrix: Record<string, number>;
    coverageScore: number;
  } | null;
  impactAnalysis?: {
    layers: { layer: string; impacts: Record<string, unknown>[] }[];
    blastRadius: number;
    criticalPathsAffected: string[];
  } | null;
  sequenceDiagrams: {
    diagrams: { id: string; title: string; mermaidCode: string; flowType: string }[];
  } | null;
  stateTransitions: {
    states: { id: string; name: string; description: string }[];
    transitions: { fromState: string; toState: string; trigger: string; guard: string; riskLevel: string }[];
    riskStates: Record<string, unknown>[];
    mermaidCode: string;
  } | null;
}

export interface TechnicalDesignBundle {
  architecture: Record<string, unknown>;
  dataflowMermaid: string;
  apiSpecification: { method: string; path: string; description: string; authRequired: boolean }[];
  databaseSchema: { name: string; columns: { name: string; type: string; nullable?: boolean; primaryKey?: boolean }[]; indexes: string[] }[];
  interfaceDefinitions: { name: string; properties: { name: string; type: string; optional?: boolean }[]; extends: string[] }[];
  componentDependencyGraph: Record<string, string[]>;
}

export interface ReverseEngineeringResult {
  extractedRequirements: Record<string, unknown>[];
  architectureDoc: Record<string, unknown>;
  dataflowMermaid: string;
  apiEndpoints: { method: string; path: string; handler: string; filePath: string }[];
  databaseSchema: { name: string; columns: Record<string, unknown>[]; source: string }[];
  interfaces: { name: string; kind: string; properties: Record<string, unknown>[]; filePath: string }[];
  taskStructure: Record<string, unknown>[];
  testSpecs: Record<string, unknown>[];
  coverageScore: number;
  languagesDetected: string[];
  sourceType?: string;
}

/* ── Project Data (persisted per lifecycle) ── */
export interface LifecycleProject {
  id: string;
  projectId: string;
  tenant_id?: string;
  name?: string;
  description?: string;
  githubRepo?: string | null;
  productIdentity?: LifecycleProductIdentity;
  spec: string;
  orchestrationMode: LifecycleOrchestrationMode;
  governanceMode?: LifecycleGovernanceMode;
  autonomyLevel: LifecycleAutonomyLevel;
  researchConfig: LifecycleResearchConfig;
  researchOperatorDecision?: ResearchOperatorDecision | null;
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
  deliveryPlan?: LifecycleDeliveryPlan | null;
  developmentExecution?: LifecycleDevelopmentExecutionSummary | null;
  developmentHandoff?: LifecycleDevelopmentHandoff | null;
  valueContract?: LifecycleValueContract | null;
  outcomeTelemetryContract?: LifecycleOutcomeTelemetryContract | null;
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
  decisionContext?: LifecycleDecisionContext;
  decision_context?: LifecycleDecisionContext;
  requirements?: RequirementsBundle | null;
  requirementsConfig?: { earsEnabled: boolean; interactiveClarification: boolean; confidenceFloor: number };
  reverseEngineering?: ReverseEngineeringResult | null;
  taskDecomposition?: TaskDecomposition | null;
  dcsAnalysis?: DCSAnalysis | null;
  technicalDesign?: TechnicalDesignBundle | null;
  createdAt: string;
  updatedAt: string;
  savedAt: string;
}

export interface LifecycleDecisionFrameSignal {
  id: string;
  title: string;
  severity?: string;
  summary?: string;
}

export interface LifecycleDecisionFrameFeature {
  name: string;
  priority?: string;
  category?: string;
}

export interface LifecycleDecisionFrameUseCase {
  id: string;
  title: string;
  priority?: string;
}

export interface LifecycleDecisionFrameMilestone {
  id: string;
  name: string;
  phase?: string;
}

export interface LifecycleDecisionFramePersona {
  name: string;
  role?: string;
}

export interface LifecycleDecisionFrame {
  north_star?: string;
  core_loop?: string;
  lead_thesis?: string;
  thesis_snapshot?: string[];
  key_risks?: LifecycleDecisionFrameSignal[];
  key_assumptions?: LifecycleDecisionFrameSignal[];
  selected_features?: LifecycleDecisionFrameFeature[];
  primary_use_cases?: LifecycleDecisionFrameUseCase[];
  milestones?: LifecycleDecisionFrameMilestone[];
  primary_personas?: LifecycleDecisionFramePersona[];
  summary?: string;
  selected_design?: {
    id?: string;
    name?: string;
    description?: string;
  };
}

export interface LifecycleDecisionContextIssue {
  id: string;
  severity?: string;
  title: string;
  detail?: string;
}

export interface LifecycleDecisionContext {
  schema_version?: number;
  display_language?: string;
  fingerprint?: string;
  project_frame?: LifecycleDecisionFrame;
  consistency_snapshot?: {
    status?: string;
    issues?: LifecycleDecisionContextIssue[];
    stats?: Record<string, unknown>;
  };
  decision_graph?: Record<string, unknown>;
}
