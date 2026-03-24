export interface GtmTeamSnapshot {
  id: string;
  label: string;
  agent_count: number;
  open_tasks: number;
  upcoming_events: number;
  active_content: number;
  status: "strong" | "watch" | "thin";
  core_skills: string[];
}

export interface GtmMotionSnapshot {
  id: string;
  label: string;
  owner_team: string;
  status: "strong" | "watch" | "thin";
  summary: string;
  signals: {
    label: string;
    value: string;
  }[];
}

export interface GtmCapabilitySnapshot {
  id: string;
  label: string;
  status: "covered" | "partial" | "missing";
  summary: string;
  skill_ids: string[];
}

export interface GtmRecommendation {
  title: string;
  priority: "high" | "medium" | "low";
  owner_team: string;
  rationale: string;
  action: string;
}

export interface GtmOverview {
  generated_at: string;
  summary: {
    total_gtm_agents: number;
    open_tasks: number;
    upcoming_events: number;
    active_content_items: number;
    recent_ads_reports: number;
    coverage_score: number;
  };
  teams: GtmTeamSnapshot[];
  motions: GtmMotionSnapshot[];
  capabilities: GtmCapabilitySnapshot[];
  recommendations: GtmRecommendation[];
}
