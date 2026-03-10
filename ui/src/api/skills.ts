import { apiFetch } from "./client";

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  risk: "safe" | "unknown" | "critical";
  source: "builtin" | "local" | "community";
  tags: string[];
  path?: string;
  has_scripts?: boolean;
  content_preview?: string;
  installed_at?: string;
}

export interface SkillsResponse {
  skills: SkillInfo[];
  total: number;
  categories: Record<string, number>;
  sources: Record<string, number>;
}

export interface SkillDetailResponse extends SkillInfo {
  content: string;
}

export interface SkillExecuteResponse {
  skill_id: string;
  result: string;
  tokens_in: number;
  tokens_out: number;
  model: string;
  provider: string;
}

export const skillsApi = {
  list: (params?: { category?: string; source?: string; search?: string }) => {
    const q = new URLSearchParams();
    if (params?.category) q.set("category", params.category);
    if (params?.source) q.set("source", params.source);
    if (params?.search) q.set("search", params.search);
    const qs = q.toString();
    return apiFetch<SkillsResponse>(`/v1/skills${qs ? `?${qs}` : ""}`);
  },
  get: (id: string) => apiFetch<SkillDetailResponse>(`/v1/skills/${id}`),
  execute: (
    id: string,
    input: string,
    context?: Record<string, string>,
    provider?: string,
    model?: string,
  ) =>
    apiFetch<SkillExecuteResponse>(`/v1/skills/${id}/execute`, {
      method: "POST",
      body: JSON.stringify({ input, context, provider, model }),
    }),
  scan: () =>
    apiFetch<{ total: number; new: number; removed: number }>("/v1/skills/scan", {
      method: "POST",
    }),
  categories: () => apiFetch<Record<string, number>>("/v1/skills/categories"),
};
