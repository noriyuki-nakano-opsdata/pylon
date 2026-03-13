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

export interface SkillImportSummary {
  tenant_id: string;
  source_id?: string | null;
  worker: {
    owner?: string | null;
    is_leader: boolean;
    lease_expires_at?: string | null;
    record_version: number;
    heartbeat_unix?: number | null;
  };
  queue: {
    counts: Record<string, number>;
    oldest_pending_created_at?: string | null;
    running_task_ids: string[];
    tasks: Array<{
      id: string;
      status: string;
      created_at?: string | null;
      started_at?: string | null;
      completed_at?: string | null;
      source_id?: string | null;
      job_id?: string | null;
      retries: number;
    }>;
  };
  jobs: {
    counts: Record<string, number>;
    recent: Array<{
      id: string;
      source_id: string;
      operation: string;
      status: string;
      queue_task_id: string;
      updated_at?: string | null;
      error?: string | null;
    }>;
  };
  sources: {
    counts: Record<string, number>;
    items: Array<{
      id: string;
      status: string;
      adapter_profile?: string | null;
      source_format?: string | null;
      source_revision?: string | null;
      imported_skill_count: number;
      promoted_tool_count: number;
      updated_at?: string | null;
      last_job?: {
        id: string;
        status: string;
        operation: string;
        updated_at?: string | null;
      } | null;
    }>;
  };
  reviews: {
    states: Record<string, number>;
    candidate_count: number;
    promoted_count: number;
  };
  metrics: {
    queue_depth: Record<string, number | null>;
  };
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
  importSummary: (sourceId?: string) =>
    apiFetch<SkillImportSummary>(`/v1/skill-import/summary${sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : ""}`),
};
