/* ── Product Lifecycle Types ── */

export type LifecyclePhase =
  | "research"
  | "planning"
  | "design"
  | "approval"
  | "development"
  | "deploy"
  | "iterate";

export interface PhaseStatus {
  phase: LifecyclePhase;
  status: "locked" | "available" | "in_progress" | "review" | "completed";
  completedAt?: string;
  version: number;
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

export interface MarketResearch {
  competitors: Competitor[];
  market_size: string;
  trends: string[];
  opportunities: string[];
  threats: string[];
  tech_feasibility: { score: number; notes: string };
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
export interface DesignVariant {
  id: string;
  model: string;
  pattern_name: string;
  description: string;
  preview_html: string;
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

/* ── Project Data (persisted per lifecycle) ── */
export interface LifecycleProject {
  id: string;
  spec: string;
  research?: MarketResearch;
  analysis?: AnalysisResult;
  features: FeatureSelection[];
  milestones: Milestone[];
  designVariants: DesignVariant[];
  selectedDesignId?: string;
  approvalStatus: "pending" | "approved" | "rejected" | "revision_requested";
  approvalComments: string[];
  buildCode?: string;
  buildCost: number;
  buildIteration: number;
  phaseStatuses: PhaseStatus[];
  createdAt: string;
  updatedAt: string;
}
