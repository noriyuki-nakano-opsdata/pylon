export interface Persona { name: string; role: string; age_range: string; goals: string[]; frustrations: string[]; tech_proficiency: string; context: string; }
export interface JourneyStep { phase: string; action: string; touchpoint: string; emotion: "positive" | "neutral" | "negative"; pain_points: string[]; opportunities: string[]; }
export interface UserStory { role: string; action: string; benefit: string; acceptance_criteria: string[]; priority: string; }
export interface JobStory { situation: string; motivation: string; outcome: string; forces: string[]; }
export interface JTBDJob { job_performer: string; core_job: string; job_steps: string[]; desired_outcomes: string[]; constraints: string[]; emotional_jobs: string[]; social_jobs: string[]; }
export interface KanoFeature { feature: string; category: string; user_delight: number; implementation_cost: string; rationale: string; }
export interface BusinessModel { key_partners: string[]; key_activities: string[]; key_resources: string[]; value_propositions: string[]; customer_relationships: string[]; channels: string[]; customer_segments: string[]; cost_structure: string; revenue_streams: string[]; }
export interface BusinessProcess { process_name: string; trigger: string; steps: { actor: string; action: string; system: string; output: string }[]; exceptions: string[]; kpis: string[]; }
export interface UseCase { name: string; actor: string; preconditions: string[]; main_flow: string[]; alternative_flows: { condition: string; steps: string[] }[]; postconditions: string[]; business_rules: string[]; }

export interface AnalysisResult {
  personas: Persona[];
  user_journeys: JourneyStep[][];
  user_stories: UserStory[];
  job_stories: JobStory[];
  jtbd_jobs: JTBDJob[];
  kano_features: KanoFeature[];
  business_model: BusinessModel | null;
  business_processes: BusinessProcess[];
  use_cases: UseCase[];
  recommendations: string[];
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: string;
  state?: Record<string, unknown>;
  started_at: string;
  completed_at: string | null;
}

export type WizardStep = "input" | "analyzing" | "review" | "select" | "building" | "complete";

export interface Milestone {
  id: string;
  name: string;
  criteria: string;
  status: "pending" | "satisfied" | "not_satisfied";
}

export interface FeatureSelection {
  feature: string;
  category: string;
  selected: boolean;
  priority: "must" | "should" | "could" | "wont";
  user_delight: number;
  implementation_cost: string;
  rationale: string;
  fromStory?: string;
}

export interface MilestoneResult {
  id: string;
  name: string;
  status: string;
  reason?: string;
}
