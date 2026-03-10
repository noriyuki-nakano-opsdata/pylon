import { apiFetch } from "./client";

export interface CostSummary {
  period?: string;
  total_usd: number;
  budget_usd: number;
  run_count: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_provider: Record<string, number>;
  by_model: Record<string, number>;
}

export const costsApi = {
  summary: (period: string = "mtd") =>
    apiFetch<CostSummary>(`/v1/costs/summary?period=${period}`),
};
