export type AdsPlatform = "google" | "meta" | "linkedin" | "tiktok" | "microsoft";
export type AuditGrade = "A" | "B" | "C" | "D" | "F";
export type CheckSeverity = "critical" | "high" | "medium" | "low";
export type CheckResult = "pass" | "warning" | "fail" | "na";
export type IndustryType =
  | "saas" | "ecommerce" | "local-service" | "b2b-enterprise"
  | "info-products" | "mobile-app" | "real-estate" | "healthcare"
  | "finance" | "agency" | "generic";

export interface AuditCheck {
  id: string;
  category: string;
  name: string;
  severity: CheckSeverity;
  result: CheckResult;
  finding: string;
  remediation: string;
  estimated_fix_time_min: number;
  is_quick_win: boolean;
}

export interface PlatformHealthScore {
  platform: AdsPlatform;
  score: number;
  grade: AuditGrade;
  budget_share: number;
  checks: AuditCheck[];
  category_scores: Record<string, number>;
}

export interface AggregateReport {
  id: string;
  created_at: string;
  industry_type: IndustryType;
  aggregate_score: number;
  aggregate_grade: AuditGrade;
  platforms: PlatformHealthScore[];
  quick_wins: AuditCheck[];
  critical_issues: AuditCheck[];
  cross_platform: {
    budget_assessment: string;
    tracking_consistency: string;
    creative_consistency: string;
    attribution_overlap: string;
  };
  total_checks: number;
  passed_checks: number;
  warning_checks: number;
  failed_checks: number;
}

export interface BudgetAllocation {
  proven: number;
  growth: number;
  experiment: number;
  platform_mix: Record<AdsPlatform, number>;
  monthly_budget: number;
  mer_target: number;
}

export interface AdPlan {
  industry_type: IndustryType;
  recommended_platforms: AdsPlatform[];
  campaign_architecture: CampaignGroup[];
  monthly_budget_min: number;
  primary_kpi: string;
  time_to_profit: string;
}

export interface CampaignGroup {
  platform: AdsPlatform;
  campaign_name: string;
  objective: string;
  budget_share: number;
  targeting_summary: string;
  creative_requirements: string[];
}

export interface AuditRunConfig {
  platforms: AdsPlatform[];
  industry_type: IndustryType;
  monthly_budget?: number;
  account_data?: Record<string, string>;
}

export interface IndustryTemplate {
  id: IndustryType;
  name: string;
  platforms: Record<string, number>;
  min_monthly: number;
  primary_kpi: string;
  time_to_profit: string;
  description: string;
}
