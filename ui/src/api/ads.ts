import { apiFetch } from "./client";
import type {
  AuditRunConfig,
  AggregateReport,
  AdPlan,
  BudgetAllocation,
  IndustryType,
  AdsPlatform,
  IndustryTemplate,
} from "@/types/ads";

export const adsApi = {
  runAudit: (config: AuditRunConfig) =>
    apiFetch<{ run_id: string }>("/v1/ads/audit", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  getAuditStatus: (runId: string) =>
    apiFetch<{ status: string; progress: Record<string, string>; report?: AggregateReport }>(
      `/v1/ads/audit/${runId}`
    ),

  listReports: () =>
    apiFetch<AggregateReport[]>("/v1/ads/reports"),

  getReport: (reportId: string) =>
    apiFetch<AggregateReport>(`/v1/ads/reports/${reportId}`),

  generatePlan: (industryType: IndustryType, monthlyBudget: number) =>
    apiFetch<AdPlan>("/v1/ads/plan", {
      method: "POST",
      body: JSON.stringify({ industry_type: industryType, monthly_budget: monthlyBudget }),
    }),

  optimizeBudget: (
    currentSpend: Record<AdsPlatform, number>,
    targetMer: number,
    monthlyBudget?: number,
  ) =>
    apiFetch<BudgetAllocation>("/v1/ads/budget/optimize", {
      method: "POST",
      body: JSON.stringify({
        current_spend: currentSpend,
        target_mer: targetMer,
        monthly_budget: monthlyBudget,
      }),
    }),

  getBenchmarks: (platform: AdsPlatform) =>
    apiFetch<Record<string, unknown>>(`/v1/ads/benchmarks/${platform}`),

  getTemplates: () =>
    apiFetch<IndustryTemplate[]>("/v1/ads/templates"),
};
